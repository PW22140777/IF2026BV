"""mantenimiento-service: plantillas y órdenes de mantenimiento de los recursos.

- Plantilla: a qué recursos aplica, cuándo se abre una orden (por ESTADO, PERIODICO o MANUAL),
  qué lista de verificación se llena y en qué estado queda el recurso según el resultado.
- Orden: Programada -> En curso -> Terminada (o Cancelada). Se asigna a uno o más técnicos;
  solo ellos (o el Administrador) la inician y la terminan.
- Este servicio NO escribe las tablas de los recursos: al iniciar o terminar publica el evento
  orden_mantenimiento.iniciada/terminada.v1 con `estado_recurso_nuevo`, e inmuebles-service o
  servicios-service aplican el estado (el mismo patrón que desactiva servicios al eliminar un área).
"""
import asyncio
from datetime import date, datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from comun.adjuntos import crear_router_adjuntos
from comun.app import crear_app
from comun.config import configuracion
from comun.db import fabrica_sesiones, get_db
from comun.historial import registrar_evento
from comun.modelos import (
    Area, Edificio, ElementoInventario, OrdenMantenimiento, OrdenTecnico, PlantillaMantenimiento, ServicioBasico,
    TipoElemento, Usuario,
)
from comun.propiedades import revisar_valores
from comun.recursos import crear_router_recurso
from comun.seguridad import (
    ADMINISTRADOR, EDITORES, LECTORES_INTERNOS, SISTEMA, SOLO_ADMIN, TECNICO, UsuarioToken, requiere_rol,
)

from .esquemas import (
    Asignacion, Cancelacion, OrdenCrear, OrdenDetalle, OrdenSalida, Persona, PlantillaActualizar, PlantillaCrear,
    PlantillaSalida, Terminacion,
)

log = structlog.get_logger()

# Tabla de cada recurso: solo se lee, para saber si existe y a qué plantillas aplica
MODELOS = {"EDIFICIO": Edificio, "AREA": Area, "INVENTARIO": ElementoInventario, "SERVICIO": ServicioBasico}
ABIERTAS = ("PROGRAMADA", "EN_CURSO")


# ----------------------------------------------------------------- utilidades
async def _tecnicos_vigentes(db: AsyncSession, orden_id: int) -> list[int]:
    filas = await db.execute(select(OrdenTecnico.usuario_id).where(
        OrdenTecnico.orden_id == orden_id, OrdenTecnico.quitado_en.is_(None)).order_by(OrdenTecnico.id))
    return list(filas.scalars())


async def foto(db: AsyncSession, orden: OrdenMantenimiento) -> dict:
    """Estado completo de la orden para el historial, con sus técnicos asignados."""
    salida = OrdenSalida.model_validate(orden)
    salida.tecnicos = await _tecnicos_vigentes(db, orden.id)
    return salida.model_dump(mode="json")


async def _validar_tecnicos(db: AsyncSession, ids: list[int]) -> list[int]:
    """Solo cuentas activas de Técnico o Administrador (columnas que este servicio puede leer)."""
    ids = list(dict.fromkeys(ids))   # sin repetidos, en el mismo orden
    filas = (await db.execute(select(Usuario.id, Usuario.rol, Usuario.activo).where(Usuario.id.in_(ids)))).all()
    validos = {i for i, rol, activo in filas if activo and rol in (TECNICO, ADMINISTRADOR)}
    invalidos = [i for i in ids if i not in validos]
    if invalidos:
        raise HTTPException(422, f"Estos usuarios no son técnicos activos y no se les puede asignar: {invalidos}")
    return ids


def _aplica(plantilla: PlantillaMantenimiento, objeto) -> bool:
    """Una plantilla de inventario con tipo solo aplica a elementos de ese tipo."""
    return not (plantilla.recurso == "INVENTARIO" and plantilla.tipo_elemento and objeto.tipo != plantilla.tipo_elemento)


async def _abrir_orden(db: AsyncSession, plantilla: PlantillaMantenimiento, recurso_id: int, origen: str,
                       usuario: UsuarioToken, tecnicos: list[int], fecha: date | None = None) -> OrdenMantenimiento | None:
    """Crea una orden si no hay otra abierta de la misma plantilla para ese recurso. El llamador hace commit."""
    abierta = (await db.execute(select(OrdenMantenimiento.id).where(
        OrdenMantenimiento.plantilla_id == plantilla.id, OrdenMantenimiento.recurso_id == recurso_id,
        OrdenMantenimiento.recurso == plantilla.recurso, OrdenMantenimiento.estado.in_(ABIERTAS),
        OrdenMantenimiento.eliminado_en.is_(None)))).first()
    if abierta:
        return None
    try:
        # Punto de guardado: si otra réplica la creó al mismo tiempo, el índice único lo impide sin romper lo demás
        async with db.begin_nested():
            orden = OrdenMantenimiento(plantilla_id=plantilla.id, recurso=plantilla.recurso, recurso_id=recurso_id,
                                       origen=origen, estado="PROGRAMADA", fecha_programada=fecha or date.today(),
                                       creado_por=usuario.id, creado_en=datetime.now(timezone.utc))
            db.add(orden)
            await db.flush()
            for tecnico in tecnicos:
                db.add(OrdenTecnico(orden_id=orden.id, usuario_id=tecnico, asignado_por=usuario.id,
                                    asignado_en=datetime.now(timezone.utc)))
            await db.flush()
    except IntegrityError:
        return None
    await db.refresh(orden)
    await registrar_evento(db, accion="CREAR", recurso="ORDEN_MANTENIMIENTO", recurso_id=orden.id, usuario=usuario,
                           despues=await foto(db, orden),
                           motivo=None if origen == "MANUAL" else f"Abierta por {origen.lower()}: {plantilla.nombre}")
    return orden


async def _cancelar(db: AsyncSession, orden: OrdenMantenimiento, usuario: UsuarioToken, motivo: str) -> None:
    antes = await foto(db, orden)
    orden.estado = "CANCELADA"
    orden.motivo_cancelacion = motivo
    orden.modificado_en = datetime.now(timezone.utc)
    orden.modificado_por = usuario.id
    await db.flush()
    await registrar_evento(db, accion="CANCELAR", recurso="ORDEN_MANTENIMIENTO", recurso_id=orden.id,
                           usuario=usuario, antes=antes, despues=await foto(db, orden), motivo=motivo)


async def _orden_abierta(db: AsyncSession, id_: int) -> OrdenMantenimiento:
    orden = await db.get(OrdenMantenimiento, id_)
    if orden is None or orden.eliminado_en is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe la orden de mantenimiento {id_}")
    return orden


async def _exige_asignado(db: AsyncSession, orden: OrdenMantenimiento, usuario: UsuarioToken) -> None:
    """Inician y terminan los técnicos asignados; el Administrador siempre puede."""
    if usuario.rol == ADMINISTRADOR:
        return
    asignados = await _tecnicos_vigentes(db, orden.id)
    if not asignados:
        raise HTTPException(403, "La orden todavía no tiene técnicos asignados; pide al Administrador que la asigne")
    if usuario.id not in asignados:
        raise HTTPException(403, "Esta orden está asignada a otros técnicos; solo ellos o el Administrador la atienden")


async def _nombres_recursos(db: AsyncSession, ordenes: list[OrdenMantenimiento]) -> dict[tuple[str, int], str]:
    """Nombre legible de cada recurso, p. ej. «Aire acondicionado en Aula 3»."""
    nombres: dict[tuple[str, int], str] = {}
    por_tipo: dict[str, set[int]] = {}
    for o in ordenes:
        por_tipo.setdefault(o.recurso, set()).add(o.recurso_id)
    for recurso, ids in por_tipo.items():
        if recurso == "INVENTARIO":
            filas = await db.execute(
                select(ElementoInventario.id, func.coalesce(TipoElemento.nombre, ElementoInventario.tipo), Area.nombre)
                .join(Area, Area.id == ElementoInventario.area_id)
                .outerjoin(TipoElemento, (TipoElemento.clave == ElementoInventario.tipo) & TipoElemento.eliminado_en.is_(None))
                .where(ElementoInventario.id.in_(ids)))
            nombres.update({(recurso, i): f"{tipo} en {area}" for i, tipo, area in filas.all()})
        else:
            modelo = MODELOS[recurso]
            filas = await db.execute(select(modelo.id, modelo.nombre).where(modelo.id.in_(ids)))
            nombres.update({(recurso, i): nombre for i, nombre in filas.all()})
    return nombres


async def _detalles(db: AsyncSession, ordenes: list[OrdenMantenimiento]) -> list[OrdenDetalle]:
    if not ordenes:
        return []
    ids = [o.id for o in ordenes]
    plantillas = {p.id: p for p in (await db.execute(select(PlantillaMantenimiento).where(
        PlantillaMantenimiento.id.in_({o.plantilla_id for o in ordenes})))).scalars()}
    asignaciones = (await db.execute(
        select(OrdenTecnico.orden_id, Usuario.id, Usuario.nombre).join(Usuario, Usuario.id == OrdenTecnico.usuario_id)
        .where(OrdenTecnico.orden_id.in_(ids), OrdenTecnico.quitado_en.is_(None)).order_by(OrdenTecnico.id))).all()
    personas = {o.iniciada_por for o in ordenes} | {o.terminada_por for o in ordenes}
    nombres_usuarios = dict((await db.execute(select(Usuario.id, Usuario.nombre).where(
        Usuario.id.in_([p for p in personas if p is not None])))).all())
    nombres = await _nombres_recursos(db, ordenes)
    resultado = []
    for o in ordenes:
        asignados = [Persona(id=u, nombre=n) for oid, u, n in asignaciones if oid == o.id]
        plantilla = plantillas[o.plantilla_id]
        resultado.append(OrdenDetalle(
            **OrdenSalida.model_validate(o).model_dump(exclude={"tecnicos"}), tecnicos=[a.id for a in asignados],
            plantilla_nombre=plantilla.nombre, lista_verificacion=plantilla.lista_verificacion,
            recurso_nombre=nombres.get((o.recurso, o.recurso_id), f"{o.recurso.lower()} {o.recurso_id}"),
            asignados=asignados, iniciada_por_nombre=nombres_usuarios.get(o.iniciada_por),
            terminada_por_nombre=nombres_usuarios.get(o.terminada_por),
        ))
    return resultado


# ---------------------------------------------------------------- plantillas
def filtros_plantillas(recurso: str | None = None, disparo: str | None = None):
    condiciones = []
    if recurso:
        condiciones.append(PlantillaMantenimiento.recurso == recurso)
    if disparo:
        condiciones.append(PlantillaMantenimiento.disparo == disparo)
    return condiciones


CAMPOS_PLANTILLA = set(PlantillaCrear.model_fields)


async def validar_plantilla(db: AsyncSession, datos: dict, existente: PlantillaMantenimiento | None) -> dict:
    # Al modificar se revisa la plantilla completa: lo nuevo más lo que ya tenía
    completa = datos
    if existente is not None:
        anterior = PlantillaSalida.model_validate(existente).model_dump(include=CAMPOS_PLANTILLA)
        completa = {**anterior, **datos}
    try:
        PlantillaCrear.model_validate(completa)
    except ValidationError as e:
        raise HTTPException(422, "; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors()))
    tipo = completa.get("tipo_elemento")
    if tipo and "tipo_elemento" in datos:
        existe = (await db.execute(select(TipoElemento.id).where(
            TipoElemento.clave == tipo, TipoElemento.eliminado_en.is_(None)))).first()
        if not existe:
            raise HTTPException(422, f"El tipo de elemento {tipo} no está en el catálogo")
    return datos


async def plantilla_antes_de_eliminar(db: AsyncSession, plantilla: PlantillaMantenimiento) -> None:
    abiertas = (await db.execute(select(func.count()).select_from(OrdenMantenimiento).where(
        OrdenMantenimiento.plantilla_id == plantilla.id, OrdenMantenimiento.estado.in_(ABIERTAS)))).scalar_one()
    if abiertas:
        raise HTTPException(409, f"La plantilla tiene {abiertas} orden(es) abierta(s); termínalas o cancélalas primero")


router_plantillas = crear_router_recurso(
    ruta="/mantenimientos/plantillas", etiqueta="Plantillas de mantenimiento", recurso="PLANTILLA_MANTENIMIENTO",
    modelo=PlantillaMantenimiento, Crear=PlantillaCrear, Actualizar=PlantillaActualizar, Salida=PlantillaSalida,
    filtros=filtros_plantillas, validar=validar_plantilla, roles_edicion=SOLO_ADMIN, roles_lectura=LECTORES_INTERNOS,
    antes_de_eliminar=plantilla_antes_de_eliminar,
)


# -------------------------------------------------------------------- órdenes
router_ordenes = APIRouter(prefix="/mantenimientos/ordenes", tags=["Órdenes de mantenimiento"])


@router_ordenes.get("", response_model=list[OrdenDetalle], summary="Órdenes de mantenimiento con filtros")
async def listar_ordenes(
    estado: str | None = Query(None, description="Uno o varios separados por coma: PROGRAMADA,EN_CURSO"),
    recurso: str | None = None,
    recurso_id: int | None = None,
    limite: int = Query(200, ge=1, le=1000),
    usuario: UsuarioToken = Depends(requiere_rol(*LECTORES_INTERNOS)),
    db: AsyncSession = Depends(get_db),
):
    consulta = select(OrdenMantenimiento).where(OrdenMantenimiento.eliminado_en.is_(None))
    if estado:
        consulta = consulta.where(OrdenMantenimiento.estado.in_([e.strip() for e in estado.split(",")]))
    if recurso:
        consulta = consulta.where(OrdenMantenimiento.recurso == recurso)
    if recurso_id is not None:
        consulta = consulta.where(OrdenMantenimiento.recurso_id == recurso_id)
    # Primero lo que hay que atender (en curso, luego programadas por fecha), al final lo cerrado
    prioridad = case({"EN_CURSO": 0, "PROGRAMADA": 1}, value=OrdenMantenimiento.estado, else_=2)
    consulta = consulta.order_by(prioridad, OrdenMantenimiento.fecha_programada, OrdenMantenimiento.id.desc()).limit(limite)
    return await _detalles(db, list((await db.execute(consulta)).scalars()))


@router_ordenes.get("/{id}", response_model=OrdenDetalle, summary="Una orden de mantenimiento")
async def ver_orden(id: int, _: UsuarioToken = Depends(requiere_rol(*LECTORES_INTERNOS)), db: AsyncSession = Depends(get_db)):
    return (await _detalles(db, [await _orden_abierta(db, id)]))[0]


@router_ordenes.post("", response_model=OrdenDetalle, status_code=201, summary="Programar un mantenimiento a mano")
async def crear_orden(datos: OrdenCrear, usuario: UsuarioToken = Depends(requiere_rol(*EDITORES)),
                      db: AsyncSession = Depends(get_db)):
    plantilla = await db.get(PlantillaMantenimiento, datos.plantilla_id)
    if plantilla is None or plantilla.eliminado_en is not None or not plantilla.activa:
        raise HTTPException(422, f"La plantilla {datos.plantilla_id} no existe o no está activa")
    objeto = await db.get(MODELOS[plantilla.recurso], datos.recurso_id)
    if objeto is None or objeto.eliminado_en is not None:
        raise HTTPException(422, f"No existe un registro activo de {plantilla.recurso.lower()} con id {datos.recurso_id}")
    if not _aplica(plantilla, objeto):
        raise HTTPException(422, f"La plantilla «{plantilla.nombre}» es para elementos de tipo {plantilla.tipo_elemento}")
    tecnicos = datos.tecnicos or ([usuario.id] if usuario.rol == TECNICO else [])
    if not tecnicos:
        raise HTTPException(422, "Asigna la orden a uno o más técnicos")
    tecnicos = await _validar_tecnicos(db, tecnicos)
    orden = await _abrir_orden(db, plantilla, datos.recurso_id, "MANUAL", usuario, tecnicos, datos.fecha_programada)
    if orden is None:
        raise HTTPException(409, f"Ya hay una orden abierta de «{plantilla.nombre}» para este recurso; atiende esa")
    await db.commit()
    return (await _detalles(db, [orden]))[0]


@router_ordenes.put("/{id}/tecnicos", response_model=OrdenDetalle, summary="Asignar técnicos (Administrador)")
async def asignar(id: int, datos: Asignacion, usuario: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN)),
                  db: AsyncSession = Depends(get_db)):
    orden = await _orden_abierta(db, id)
    if orden.estado not in ABIERTAS:
        raise HTTPException(409, "Solo se asignan técnicos a órdenes programadas o en curso")
    nuevos = await _validar_tecnicos(db, datos.tecnicos)
    antes = await foto(db, orden)
    vigentes = (await db.execute(select(OrdenTecnico).where(
        OrdenTecnico.orden_id == orden.id, OrdenTecnico.quitado_en.is_(None)))).scalars().all()
    ahora = datetime.now(timezone.utc)
    for asignacion in vigentes:
        if asignacion.usuario_id not in nuevos:      # se quita: queda la fila con la fecha
            asignacion.quitado_en, asignacion.quitado_por = ahora, usuario.id
    ya = {a.usuario_id for a in vigentes}
    for tecnico in nuevos:
        if tecnico not in ya:
            db.add(OrdenTecnico(orden_id=orden.id, usuario_id=tecnico, asignado_por=usuario.id, asignado_en=ahora))
    orden.modificado_en, orden.modificado_por = ahora, usuario.id
    await db.flush()
    await registrar_evento(db, accion="MODIFICAR", recurso="ORDEN_MANTENIMIENTO", recurso_id=orden.id, usuario=usuario,
                           antes=antes, despues=await foto(db, orden), motivo="Técnicos asignados")
    await db.commit()
    return (await _detalles(db, [orden]))[0]


@router_ordenes.post("/{id}/iniciar", response_model=OrdenDetalle, summary="Iniciar el mantenimiento")
async def iniciar(id: int, usuario: UsuarioToken = Depends(requiere_rol(*EDITORES)), db: AsyncSession = Depends(get_db)):
    orden = await _orden_abierta(db, id)
    if orden.estado != "PROGRAMADA":
        raise HTTPException(409, f"La orden está {orden.estado.lower().replace('_', ' ')}; solo se inicia una programada")
    await _exige_asignado(db, orden, usuario)
    objeto = await db.get(MODELOS[orden.recurso], orden.recurso_id)
    if objeto is None or objeto.eliminado_en is not None:
        raise HTTPException(409, "El recurso de esta orden ya no existe; el Administrador puede cancelarla")
    plantilla = await db.get(PlantillaMantenimiento, orden.plantilla_id)
    antes = await foto(db, orden)
    orden.estado = "EN_CURSO"
    orden.iniciada_en, orden.iniciada_por = datetime.now(timezone.utc), usuario.id
    orden.modificado_en, orden.modificado_por = orden.iniciada_en, usuario.id
    await db.flush()
    await registrar_evento(db, accion="INICIAR", recurso="ORDEN_MANTENIMIENTO", recurso_id=orden.id, usuario=usuario,
                           antes=antes, despues=await foto(db, orden))
    await db.commit()
    return (await _detalles(db, [orden]))[0]


@router_ordenes.post("/{id}/terminar", response_model=OrdenDetalle, summary="Terminar el mantenimiento con su resultado")
async def terminar(id: int, datos: Terminacion, usuario: UsuarioToken = Depends(requiere_rol(*EDITORES)),
                   db: AsyncSession = Depends(get_db)):
    orden = await _orden_abierta(db, id)
    if orden.estado != "EN_CURSO":
        raise HTTPException(409, "Solo se termina una orden en curso; pulsa «Iniciar» primero")
    await _exige_asignado(db, orden, usuario)
    plantilla = await db.get(PlantillaMantenimiento, orden.plantilla_id)
    respuestas, errores = revisar_valores(plantilla.lista_verificacion, datos.respuestas, plantilla.nombre.lower())
    if errores:
        raise HTTPException(422, "Revisa la lista de verificación: " + "; ".join(errores))
    antes = await foto(db, orden)
    orden.estado = "TERMINADA"
    orden.resultado, orden.respuestas, orden.notas = datos.resultado, respuestas, datos.notas
    orden.terminada_en, orden.terminada_por = datetime.now(timezone.utc), usuario.id
    orden.modificado_en, orden.modificado_por = orden.terminada_en, usuario.id
    await db.flush()
    await registrar_evento(db, accion="TERMINAR", recurso="ORDEN_MANTENIMIENTO", recurso_id=orden.id, usuario=usuario,
                           antes=antes, despues=await foto(db, orden),
                           motivo=f"Resultado: {datos.resultado.lower().replace('_', ' ')}")
    await db.commit()
    return (await _detalles(db, [orden]))[0]


@router_ordenes.post("/{id}/cancelar", response_model=OrdenDetalle, summary="Cancelar una orden (Administrador)")
async def cancelar(id: int, datos: Cancelacion, usuario: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN)),
                   db: AsyncSession = Depends(get_db)):
    orden = await _orden_abierta(db, id)
    if orden.estado not in ABIERTAS:
        raise HTTPException(409, "Solo se cancela una orden programada o en curso")
    await _cancelar(db, orden, usuario, datos.motivo)
    await db.commit()
    return (await _detalles(db, [orden]))[0]


# Evidencias (fotos, PDF) de una orden: archivos adjuntos que guarda archivos-service
async def _puede_adjuntar_evidencia(db: AsyncSession, orden: OrdenMantenimiento, usuario: UsuarioToken) -> None:
    if orden.estado == "CANCELADA":
        raise HTTPException(409, "La orden está cancelada; ya no se le adjuntan evidencias")
    await _exige_asignado(db, orden, usuario)   # las suben los técnicos asignados o el Administrador


router_evidencias = crear_router_adjuntos(
    ruta="/mantenimientos/ordenes", recurso="ORDEN_MANTENIMIENTO", modelo=OrdenMantenimiento,
    carpeta="mantenimientos", sufijo="evidencias", etiqueta="Órdenes de mantenimiento: evidencias",
    roles_lectura=LECTORES_INTERNOS, categoria_inicial="EVIDENCIA", antes_de_adjuntar=_puede_adjuntar_evidencia,
)


app = crear_app(
    nombre="mantenimiento",
    titulo="mantenimiento-service",
    descripcion="Plantillas y órdenes de mantenimiento: por estado, periódicas o manuales, con técnicos asignados.",
    routers=[router_plantillas, router_ordenes, router_evidencias],
)
