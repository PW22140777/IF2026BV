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
    ADMINISTRADOR, EDITORES, SISTEMA, SOLO_ADMIN, TECNICO, TODOS, UsuarioToken, requiere_rol,
)

from . import evidencias
from .esquemas import (
    Asignacion, Cancelacion, OrdenCrear, OrdenDetalle, OrdenSalida, Persona, PlantillaActualizar, PlantillaCrear,
    PlantillaSalida, Terminacion,
)

log = structlog.get_logger()

# Tabla de cada recurso: solo se lee, para saber si existe y a qué plantillas aplica
MODELOS = {"EDIFICIO": Edificio, "AREA": Area, "INVENTARIO": ElementoInventario, "SERVICIO": ServicioBasico}
ABIERTAS = ("PROGRAMADA", "EN_CURSO")
CANDADO_PROGRAMADOR = 8_008      # pg_advisory_xact_lock: una sola réplica programa a la vez
INTERVALO_PROGRAMADOR_S = 3600   # revisa las plantillas periódicas cada hora


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
    orden.estado_recurso_nuevo = None    # cancelar no cambia el estado del recurso
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
    filtros=filtros_plantillas, validar=validar_plantilla, roles_edicion=SOLO_ADMIN,
    antes_de_eliminar=plantilla_antes_de_eliminar,
)


# -------------------------------------------------------------------- órdenes
router_ordenes = APIRouter(prefix="/mantenimientos/ordenes", tags=["Órdenes de mantenimiento"])


@router_ordenes.get("", response_model=list[OrdenDetalle], summary="Órdenes de mantenimiento con filtros")
async def listar_ordenes(
    estado: str | None = Query(None, description="Uno o varios separados por coma: PROGRAMADA,EN_CURSO"),
    recurso: str | None = None,
    recurso_id: int | None = None,
    mias: bool = Query(False, description="Solo las asignadas a quien consulta"),
    limite: int = Query(200, ge=1, le=1000),
    usuario: UsuarioToken = Depends(requiere_rol(*TODOS)),
    db: AsyncSession = Depends(get_db),
):
    consulta = select(OrdenMantenimiento).where(OrdenMantenimiento.eliminado_en.is_(None))
    if estado:
        consulta = consulta.where(OrdenMantenimiento.estado.in_([e.strip() for e in estado.split(",")]))
    if recurso:
        consulta = consulta.where(OrdenMantenimiento.recurso == recurso)
    if recurso_id is not None:
        consulta = consulta.where(OrdenMantenimiento.recurso_id == recurso_id)
    if mias:
        consulta = consulta.where(OrdenMantenimiento.id.in_(select(OrdenTecnico.orden_id).where(
            OrdenTecnico.usuario_id == usuario.id, OrdenTecnico.quitado_en.is_(None))))
    # Primero lo que hay que atender (en curso, luego programadas por fecha), al final lo cerrado
    prioridad = case({"EN_CURSO": 0, "PROGRAMADA": 1}, value=OrdenMantenimiento.estado, else_=2)
    consulta = consulta.order_by(prioridad, OrdenMantenimiento.fecha_programada, OrdenMantenimiento.id.desc()).limit(limite)
    return await _detalles(db, list((await db.execute(consulta)).scalars()))


@router_ordenes.get("/{id}", response_model=OrdenDetalle, summary="Una orden de mantenimiento")
async def ver_orden(id: int, _: UsuarioToken = Depends(requiere_rol(*TODOS)), db: AsyncSession = Depends(get_db)):
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
    orden.estado_recurso_nuevo = plantilla.estado_al_iniciar     # None = el recurso no cambia al iniciar
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
    # En qué estado queda el recurso según el resultado (lo aplica el servicio dueño del recurso)
    orden.estado_recurso_nuevo = {"RESUELTO": plantilla.estado_resuelto, "PARCIAL": plantilla.estado_parcial,
                                  "NO_RESUELTO": plantilla.estado_no_resuelto}[datos.resultado]
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


# Evidencias: esqueleto. Responden 501 hasta que se defina dónde se guardan los archivos (evidencias.py)
@router_ordenes.get("/{id}/evidencias", summary="Evidencias de la orden (todavía no disponible)")
async def listar_evidencias(id: int, _: UsuarioToken = Depends(requiere_rol(*TODOS)), db: AsyncSession = Depends(get_db)):
    await _orden_abierta(db, id)
    return {"disponible": evidencias.almacen() is not None, "evidencias": [], "mensaje": evidencias.MENSAJE_NO_DISPONIBLE}


@router_ordenes.post("/{id}/evidencias", summary="Adjuntar una evidencia (todavía no disponible)")
async def adjuntar_evidencia(id: int, _: UsuarioToken = Depends(requiere_rol(*EDITORES)), db: AsyncSession = Depends(get_db)):
    await _orden_abierta(db, id)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, evidencias.MENSAJE_NO_DISPONIBLE)


# ------------------------------------------------------------------- resumen
router_resumen = APIRouter(prefix="/resumen", tags=["Resumen"])
DIAS_RESUMEN = 30


def _del_campus(campus_id: int):
    """Órdenes cuyo recurso está en el campus (el inventario por su área; un servicio por su destino)."""
    areas = select(Area.id).where(Area.campus_id == campus_id)
    edificios = select(Edificio.id).where(Edificio.campus_id == campus_id)
    o = OrdenMantenimiento
    return or_(
        and_(o.recurso == "EDIFICIO", o.recurso_id.in_(edificios)),
        and_(o.recurso == "AREA", o.recurso_id.in_(areas)),
        and_(o.recurso == "INVENTARIO", o.recurso_id.in_(
            select(ElementoInventario.id).where(ElementoInventario.area_id.in_(areas)))),
        and_(o.recurso == "SERVICIO", o.recurso_id.in_(select(ServicioBasico.id).where(or_(
            ServicioBasico.campus_id == campus_id, ServicioBasico.edificio_id.in_(edificios),
            ServicioBasico.area_id.in_(areas))))),
    )


@router_resumen.get("/mantenimientos", summary="Indicadores de mantenimiento para el tablero")
async def resumen_mantenimientos(
    campus_id: int | None = Query(None, description="Vacío = todos los campus"),
    _: UsuarioToken = Depends(requiere_rol(*TODOS)),
    db: AsyncSession = Depends(get_db),
):
    o = OrdenMantenimiento
    base = [o.eliminado_en.is_(None)] + ([_del_campus(campus_id)] if campus_id is not None else [])
    hoy = date.today()
    desde = datetime.now(timezone.utc) - timedelta(days=DIAS_RESUMEN)

    async def contar(*condiciones) -> int:
        return (await db.execute(select(func.count()).select_from(o).where(*base, *condiciones))).scalar_one()

    con_tecnico = select(OrdenTecnico.orden_id).where(OrdenTecnico.quitado_en.is_(None))
    terminadas = [o.estado == "TERMINADA", o.terminada_en >= desde]
    por_resultado = dict((await db.execute(
        select(o.resultado, func.count()).where(*base, *terminadas).group_by(o.resultado))).all())
    # Tiempo de atención: de «Iniciar» a «Terminar», en minutos
    segundos = (await db.execute(select(func.avg(func.extract("epoch", o.terminada_en - o.iniciada_en)))
                                 .where(*base, *terminadas))).scalar_one()
    vencidas = list((await db.execute(select(o).where(*base, o.estado == "PROGRAMADA", o.fecha_programada < hoy)
                                      .order_by(o.fecha_programada, o.id).limit(5))).scalars())
    detalles = await _detalles(db, vencidas)
    return {
        "programadas": await contar(o.estado == "PROGRAMADA"),
        "en_curso": await contar(o.estado == "EN_CURSO"),
        "vencidas": await contar(o.estado == "PROGRAMADA", o.fecha_programada < hoy),
        "sin_asignar": await contar(o.estado.in_(ABIERTAS), o.id.not_in(con_tecnico)),
        "dias": DIAS_RESUMEN,
        "terminadas": sum(por_resultado.values()),
        "por_resultado": {r: por_resultado.get(r, 0) for r in ("RESUELTO", "PARCIAL", "NO_RESUELTO")},
        "minutos_promedio": round(float(segundos) / 60) if segundos is not None else None,
        "vencidas_detalle": [
            {"id": d.id, "plantilla_nombre": d.plantilla_nombre, "recurso_nombre": d.recurso_nombre,
             "fecha_programada": d.fecha_programada.isoformat(), "dias_vencida": (hoy - d.fecha_programada).days}
            for d in detalles
        ],
    }


# ---------------------------------------------------- órdenes automáticas
async def generar_periodicas() -> int:
    """Abre las órdenes de las plantillas periódicas que ya tocan. Devuelve cuántas creó."""
    creadas = 0
    async with fabrica_sesiones()() as db:
        async with db.begin():
            # Candado de la transacción (sirve con el pooler): varias réplicas no duplican órdenes
            await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CANDADO_PROGRAMADOR})
            plantillas = (await db.execute(select(PlantillaMantenimiento).where(
                PlantillaMantenimiento.disparo == "PERIODICO", PlantillaMantenimiento.activa.is_(True),
                PlantillaMantenimiento.eliminado_en.is_(None)))).scalars().all()
            for plantilla in plantillas:
                modelo = MODELOS[plantilla.recurso]
                consulta = select(modelo.id).where(modelo.eliminado_en.is_(None))
                if plantilla.recurso == "INVENTARIO" and plantilla.tipo_elemento:
                    consulta = consulta.where(ElementoInventario.tipo == plantilla.tipo_elemento)
                limite = datetime.now(timezone.utc) - timedelta(days=plantilla.cada_dias)
                for recurso_id in (await db.execute(consulta)).scalars():
                    ultima = (await db.execute(select(func.max(OrdenMantenimiento.terminada_en)).where(
                        OrdenMantenimiento.plantilla_id == plantilla.id, OrdenMantenimiento.recurso_id == recurso_id,
                        OrdenMantenimiento.estado == "TERMINADA"))).scalar_one()
                    if ultima is not None and ultima > limite:
                        continue
                    if await _abrir_orden(db, plantilla, recurso_id, "PERIODICO", SISTEMA, []):
                        creadas += 1
    if creadas:
        log.info("ordenes_periodicas_creadas", total=creadas)
    return creadas


async def programador(detener: asyncio.Event) -> None:
    """Tarea de fondo: revisa las plantillas periódicas al arrancar y después cada hora."""
    while not detener.is_set():
        try:
            await generar_periodicas()
        except Exception:   # un error no debe detener la tarea: se reintenta en la siguiente vuelta
            log.exception("programador_fallo")
        try:
            await asyncio.wait_for(detener.wait(), timeout=INTERVALO_PROGRAMADOR_S)
        except asyncio.TimeoutError:
            pass


router_programar = APIRouter(prefix="/mantenimientos", tags=["Órdenes de mantenimiento"])


@router_programar.post("/programar", summary="Abrir ya las órdenes periódicas que tocan (Administrador)")
async def programar_ahora(_: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN))):
    return {"creadas": await generar_periodicas()}


async def al_cambiar_recurso(evento: dict) -> None:
    """Un recurso cambió: abre órdenes por estado o cancela las abiertas si se eliminó."""
    from comun.idempotencia import marcar_procesado

    recurso = evento.get("recurso")
    if recurso not in MODELOS:
        return
    async with fabrica_sesiones()() as db:
        async with db.begin():
            if not await marcar_procesado(db, "mantenimiento", evento["evento_id"]):
                return
            if evento["accion"] == "ELIMINAR":
                abiertas = (await db.execute(select(OrdenMantenimiento).where(
                    OrdenMantenimiento.recurso == recurso, OrdenMantenimiento.recurso_id == evento["recurso_id"],
                    OrdenMantenimiento.estado.in_(ABIERTAS)))).scalars().all()
                for orden in abiertas:
                    await _cancelar(db, orden, SISTEMA, f"Se eliminó {recurso.lower()} {evento['recurso_id']}")
                return
            # Solo cambios hechos por una persona: el estado que deja un mantenimiento (SISTEMA) no abre otra orden
            if evento["accion"] not in ("CREAR", "MODIFICAR") or evento.get("usuario_id") is None:
                return
            antes, despues = evento.get("antes") or {}, evento.get("despues") or {}
            nuevo = despues.get("estado")
            if not nuevo or nuevo == antes.get("estado"):
                return
            plantillas = (await db.execute(select(PlantillaMantenimiento).where(
                PlantillaMantenimiento.recurso == recurso, PlantillaMantenimiento.disparo == "ESTADO",
                PlantillaMantenimiento.activa.is_(True), PlantillaMantenimiento.eliminado_en.is_(None)))).scalars().all()
            for plantilla in plantillas:
                tipo_ok = not plantilla.tipo_elemento or despues.get("tipo") == plantilla.tipo_elemento
                if nuevo in plantilla.estados_disparo and tipo_ok:
                    await _abrir_orden(db, plantilla, evento["recurso_id"], "ESTADO", SISTEMA, [])


def _tareas():
    from comun.mensajeria import consumidor

    return [
        consumidor("mantenimiento.recursos", ["edificio.*.v1", "area.*.v1", "inventario.*.v1", "servicio.*.v1"],
                   al_cambiar_recurso),
        programador,
    ]


app = crear_app(
    nombre="mantenimiento",
    titulo="mantenimiento-service",
    descripcion="Plantillas y órdenes de mantenimiento: por estado, periódicas o manuales, con técnicos asignados.",
    routers=[router_plantillas, router_ordenes, router_programar, router_resumen],
    consumidores=_tareas() if configuracion().rabbitmq_url else (),
)
