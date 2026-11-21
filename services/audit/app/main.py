"""audit-service: historial firmado de todos los cambios del sistema.

- Consume TODOS los eventos de RabbitMQ (cola "auditoria.historial").
- Cada evento se encadena por hash y se firma con Ed25519.
- Es el único servicio que escribe en audit_log; la base además impide
  UPDATE y DELETE sobre esa tabla.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from comun import contexto
from comun.app import crear_app
from comun.config import configuracion
from comun.db import fabrica_sesiones, get_db
from comun.modelos import RegistroAuditoria
from comun.seguridad import LECTORES_INTERNOS, SOLO_ADMIN, UsuarioToken, requiere_rol

from .cadena import (
    CAMPOS, HASH_INICIAL, calcular_hash, diferencias, firma_valida, firmar, normalizar_fecha,
)
from .llaves import llave_id, llave_privada, llave_publica, llave_publica_pem

log = structlog.get_logger()

CANDADO_CADENA = 7_314_159   # número arbitrario para pg_advisory_xact_lock
RECURSOS = {"CAMPUS", "EDIFICIO", "AREA", "INVENTARIO", "TIPO_ELEMENTO", "SERVICIO", "CONSUMO", "ARCHIVO", "USUARIO", "SESION",
            "AUDITORIA"}


# ------------------------------------------------------- agregar a la cadena
async def anexar(db: AsyncSession, evento: dict[str, Any]) -> RegistroAuditoria:
    """Agrega un evento al final de la cadena. Debe ejecutarse dentro de una transacción.

    El candado asegura que, aunque haya varias réplicas, solo una agregue
    a la vez y la cadena no se bifurque.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CANDADO_CADENA})
    ultimo = (await db.execute(
        select(RegistroAuditoria.hash).order_by(RegistroAuditoria.id.desc()).limit(1)
    )).scalar_one_or_none()
    hash_anterior = ultimo or HASH_INICIAL

    registro = {campo: evento.get(campo) for campo in CAMPOS}
    registro["fecha"] = normalizar_fecha(evento["fecha"])
    hash_actual = calcular_hash(hash_anterior, registro)

    fila = RegistroAuditoria(
        evento_id=uuid.UUID(str(registro["evento_id"])),
        fecha=datetime.fromisoformat(registro["fecha"]),
        registrado_en=datetime.now(timezone.utc),
        usuario_id=registro["usuario_id"],
        usuario_nombre=registro["usuario_nombre"],
        rol=registro["rol"],
        ip=registro["ip"],
        accion=registro["accion"],
        recurso=registro["recurso"],
        recurso_id=registro["recurso_id"],
        antes=registro["antes"],
        despues=registro["despues"],
        motivo=registro["motivo"],
        correlation_id=registro["correlation_id"],
        trace_id=registro["trace_id"],
        hash_anterior=hash_anterior,
        hash=hash_actual,
        firma=firmar(llave_privada(), hash_actual),
        llave_id=llave_id(),
    )
    db.add(fila)
    await db.flush()
    return fila


async def al_recibir_evento(evento: dict[str, Any]) -> None:
    """Manejador del consumidor de RabbitMQ."""
    from comun.idempotencia import marcar_procesado

    async with fabrica_sesiones()() as db:
        async with db.begin():
            if not await marcar_procesado(db, "audit", evento["evento_id"]):
                return   # ya estaba en el historial
            fila = await anexar(db, evento)
    log.info("evento_auditado", id=fila.id, tipo=evento.get("tipo"), recurso=evento.get("recurso"))


# --------------------------------------------------------------- respuestas
def _a_dict(fila: RegistroAuditoria, *, con_cadena: bool) -> dict[str, Any]:
    datos = {
        "id": fila.id,
        "evento_id": str(fila.evento_id),
        "fecha": fila.fecha,
        "usuario_id": fila.usuario_id,
        "usuario_nombre": fila.usuario_nombre,
        "rol": fila.rol,
        "accion": fila.accion,
        "recurso": fila.recurso,
        "recurso_id": fila.recurso_id,
        "motivo": fila.motivo,
        "cambios": diferencias(fila.antes, fila.despues),
        "antes": fila.antes,
        "despues": fila.despues,
        "correlation_id": fila.correlation_id,
        "trace_id": fila.trace_id,
    }
    if con_cadena:
        datos |= {"ip": fila.ip, "hash_anterior": fila.hash_anterior, "hash": fila.hash,
                  "firma": fila.firma, "llave_id": fila.llave_id}
    return datos


# --------------------------------------------------------------------- rutas
router_historial = APIRouter(prefix="/historial", tags=["Historial"])
router_auditoria = APIRouter(prefix="/auditoria", tags=["Auditoría (Administrador)"])


@router_historial.get("/{recurso}/{recurso_id}", summary="Línea de tiempo de un recurso (todos menos el Observador)")
async def historial_recurso(
    recurso: str,
    recurso_id: int,
    _: UsuarioToken = Depends(requiere_rol(*LECTORES_INTERNOS)),
    db: AsyncSession = Depends(get_db),
):
    recurso = recurso.upper()
    if recurso not in RECURSOS - {"SESION", "USUARIO", "AUDITORIA"}:
        raise HTTPException(404, "Recurso desconocido")
    filas = (await db.execute(
        select(RegistroAuditoria)
        .where(RegistroAuditoria.recurso == recurso, RegistroAuditoria.recurso_id == recurso_id)
        .order_by(RegistroAuditoria.id)
    )).scalars().all()
    return [_a_dict(f, con_cadena=False) for f in filas]


@router_auditoria.get("", summary="Bitácora completa con filtros")
async def bitacora(
    usuario_id: int | None = None,
    recurso: str | None = None,
    accion: str | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    limite: int = Query(50, ge=1, le=500),
    desplazamiento: int = Query(0, ge=0),
    _: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    condiciones = []
    if usuario_id is not None:
        condiciones.append(RegistroAuditoria.usuario_id == usuario_id)
    if recurso:
        condiciones.append(RegistroAuditoria.recurso == recurso.upper())
    if accion:
        condiciones.append(RegistroAuditoria.accion == accion.upper())
    if desde:
        condiciones.append(RegistroAuditoria.fecha >= desde)
    if hasta:
        condiciones.append(RegistroAuditoria.fecha <= hasta)
    total = (await db.execute(select(func.count()).select_from(RegistroAuditoria).where(*condiciones))).scalar_one()
    filas = (await db.execute(
        select(RegistroAuditoria).where(*condiciones)
        .order_by(RegistroAuditoria.id.desc()).limit(limite).offset(desplazamiento)
    )).scalars().all()
    return {"total": total, "registros": [_a_dict(f, con_cadena=True) for f in filas]}


@router_auditoria.get("/usuarios", summary="Actividad de cada usuario (responsabilidad)")
async def actividad_por_usuario(
    _: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    filas = await db.execute(
        select(
            RegistroAuditoria.usuario_id,
            func.max(RegistroAuditoria.usuario_nombre),
            func.max(RegistroAuditoria.rol),
            RegistroAuditoria.accion,
            func.count(),
            func.max(RegistroAuditoria.fecha),
        )
        .where(RegistroAuditoria.usuario_id.is_not(None))
        .group_by(RegistroAuditoria.usuario_id, RegistroAuditoria.accion)
    )
    usuarios: dict[int, dict[str, Any]] = {}
    for usuario_id, nombre, rol, accion, total, ultima in filas.all():
        u = usuarios.setdefault(usuario_id, {"usuario_id": usuario_id, "nombre": nombre, "rol": rol,
                                             "acciones": {}, "total": 0, "ultima_actividad": ultima})
        u["acciones"][accion] = total
        u["total"] += total
        u["ultima_actividad"] = max(u["ultima_actividad"], ultima)
    return sorted(usuarios.values(), key=lambda u: u["total"], reverse=True)


@router_auditoria.get("/verificar", summary="Verificar la integridad de toda la cadena")
async def verificar(
    usuario: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    publica = llave_publica()
    id_llave = llave_id()
    hash_esperado = HASH_INICIAL
    revisados = 0
    error: dict[str, Any] | None = None
    ultimo_id = 0

    while error is None:
        lote = (await db.execute(
            select(RegistroAuditoria).where(RegistroAuditoria.id > ultimo_id)
            .order_by(RegistroAuditoria.id).limit(1000)
        )).scalars().all()
        if not lote:
            break
        for fila in lote:
            registro = {campo: getattr(fila, campo) for campo in CAMPOS}
            if fila.hash_anterior != hash_esperado:
                error = {"id": fila.id, "problema": "La cadena está rota: falta o se reordenó un registro anterior"}
            elif calcular_hash(fila.hash_anterior, registro) != fila.hash:
                error = {"id": fila.id, "problema": "El contenido del registro fue modificado"}
            elif fila.llave_id != id_llave:
                error = {"id": fila.id, "problema": f"Firmado con una llave desconocida ({fila.llave_id})"}
            elif not firma_valida(publica, fila.hash, fila.firma):
                error = {"id": fila.id, "problema": "La firma digital no es válida"}
            if error:
                break
            hash_esperado = fila.hash
            ultimo_id = fila.id
            revisados += 1

    resultado = {
        "integra": error is None,
        "registros_revisados": revisados,
        "ultimo_hash": hash_esperado,
        "error": error,
        "verificado_en": datetime.now(timezone.utc),
    }

    # La propia verificación queda en el historial: quién la hizo y qué resultó
    await anexar(db, {
        "evento_id": str(uuid.uuid4()),
        "fecha": datetime.now(timezone.utc).isoformat(),
        "usuario_id": usuario.id, "usuario_nombre": usuario.nombre, "rol": usuario.rol,
        "ip": contexto.ip_cliente.get(), "accion": "VERIFICAR", "recurso": "AUDITORIA",
        "recurso_id": None, "antes": None,
        "despues": {"integra": resultado["integra"], "registros_revisados": revisados, "error": error},
        "motivo": None, "correlation_id": contexto.correlation_id.get(),
        "trace_id": contexto.trace_id_actual(),
    })
    await db.commit()
    return resultado


@router_auditoria.get("/llave-publica", summary="Llave pública para verificación externa")
async def obtener_llave_publica(_: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN))):
    return {"llave_id": llave_id(), "algoritmo": "Ed25519", "pem": llave_publica_pem()}


def _consumidores():
    from comun.mensajeria import consumidor

    return [consumidor("auditoria.historial", ["#"], al_recibir_evento)]


async def _preparar_llave() -> None:
    llave_privada()   # la genera si no existe
    log.info("llave_de_firma_lista", llave_id=llave_id())


app = crear_app(
    nombre="audit",
    titulo="audit-service",
    descripcion="Historial de cambios encadenado por hash y firmado (Ed25519), y su verificación.",
    routers=[router_historial, router_auditoria],
    publica_eventos=False,
    consumidores=_consumidores() if configuracion().rabbitmq_url else (),
    al_iniciar=_preparar_llave,
)
