"""servicios-service: servicios básicos (agua, luz, internet, alcantarillado), su estado y sus consumos."""
from datetime import date, datetime, timezone
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from comun.app import crear_app
from comun.config import configuracion
from comun.db import fabrica_sesiones, get_db
from comun.historial import registrar_evento
from comun.modelos import Area, Campus, Consumo, Edificio, ServicioBasico
from comun.recursos import SalidaBase, crear_router_recurso
from comun.seguridad import SISTEMA, TODOS, requiere_rol

log = structlog.get_logger()
UNIDADES = {"AGUA": "m3", "LUZ": "kWh"}
# Catálogo de tipos de servicio básico (coincide con el CHECK de servicios_basicos).
# Solo AGUA y LUZ se miden por consumo mensual (ver UNIDADES e IF-56).
TipoServicio = Literal["AGUA", "LUZ", "INTERNET", "ALCANTARILLADO"]
# Catálogo de estados de un servicio (coincide con el CHECK de servicios_basicos).
EstadoServicio = Literal["OPERANDO", "CON_FALLA", "SUSPENDIDO", "EN_MANTENIMIENTO"]


# ------------------------------------------------------------------ esquemas
class ServicioCrear(BaseModel):
    tipo: TipoServicio
    nombre: str = Field(min_length=1, max_length=120, examples=["Medidor general edificio A"])
    numero_medidor: str | None = Field(default=None, max_length=60)
    proveedor: str | None = Field(default=None, max_length=120, examples=["CFE"])
    # A quién abastece: exactamente uno de los tres
    campus_id: int | None = Field(default=None, description="Toma o medidor general del campus")
    edificio_id: int | None = None
    area_id: int | None = None
    activo: bool = True
    estado: EstadoServicio = "OPERANDO"
    descripcion: str | None = Field(default=None, max_length=2000, description="Notas sobre el servicio")
    propiedades: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def un_solo_destino(self):
        if sum(x is not None for x in (self.campus_id, self.edificio_id, self.area_id)) != 1:
            raise ValueError("Indica exactamente uno: campus_id, edificio_id o area_id")
        return self


class ServicioActualizar(BaseModel):
    nombre: str = Field(default=None, min_length=1, max_length=120)
    numero_medidor: str | None = Field(default=None, max_length=60)
    proveedor: str | None = Field(default=None, max_length=120)
    campus_id: int | None = None
    edificio_id: int | None = None
    area_id: int | None = None
    activo: bool = Field(default=None)
    estado: EstadoServicio = Field(default=None)
    descripcion: str | None = Field(default=None, max_length=2000)
    propiedades: dict[str, Any] = Field(default=None)


class ServicioSalida(SalidaBase):
    tipo: str
    nombre: str
    numero_medidor: str | None
    proveedor: str | None
    campus_id: int | None
    edificio_id: int | None
    area_id: int | None
    activo: bool
    estado: str
    descripcion: str | None


class ConsumoCrear(BaseModel):
    servicio_id: int
    periodo: date = Field(description="Cualquier día del mes; se guarda como el día 1")
    cantidad: float = Field(ge=0, description="m³ para agua, kWh para luz")
    costo: float | None = Field(default=None, ge=0)
    propiedades: dict[str, Any] = Field(default_factory=dict)

    @field_validator("periodo")
    @classmethod
    def primer_dia(cls, valor: date) -> date:
        return valor.replace(day=1)


class ConsumoActualizar(BaseModel):
    cantidad: float = Field(default=None, ge=0)
    costo: float | None = Field(default=None, ge=0)
    propiedades: dict[str, Any] = Field(default=None)


class ConsumoSalida(SalidaBase):
    servicio_id: int
    periodo: date
    cantidad: float
    unidad: str
    costo: float | None


# --------------------------------------------------------- reglas de negocio
async def _destino_activo(db: AsyncSession, modelo, id_: int, nombre: str) -> None:
    obj = await db.get(modelo, id_)
    if obj is None or obj.eliminado_en is not None:
        raise HTTPException(422, f"{nombre} {id_} no existe o está eliminado")


DESTINOS = {"campus_id": (Campus, "El campus"), "edificio_id": (Edificio, "El edificio"), "area_id": (Area, "El área")}


async def validar_servicio(db: AsyncSession, datos: dict, existente: ServicioBasico | None) -> None:
    """Un servicio abastece exactamente a uno: el campus completo, un edificio o un área.

    Al modificar, si se envía un destino nuevo, los otros dos se limpian.
    """
    nuevos = {campo: datos[campo] for campo in DESTINOS if datos.get(campo) is not None}
    if existente is not None and not nuevos:
        if any(campo in datos for campo in DESTINOS):
            raise HTTPException(422, "El servicio debe abastecer a un campus, un edificio o un área")
        return
    if len(nuevos) != 1:
        raise HTTPException(422, "Indica exactamente uno: campus_id, edificio_id o area_id")
    (campo, valor), = nuevos.items()
    modelo, nombre = DESTINOS[campo]
    await _destino_activo(db, modelo, valor, nombre)
    for otro in DESTINOS:
        if otro != campo:
            datos[otro] = None


def condicion_campus_servicio(campus_id: int):
    """Servicios que pertenecen a un campus: directos, de sus edificios o de sus áreas."""
    return or_(
        ServicioBasico.campus_id == campus_id,
        ServicioBasico.edificio_id.in_(select(Edificio.id).where(Edificio.campus_id == campus_id)),
        ServicioBasico.area_id.in_(select(Area.id).where(Area.campus_id == campus_id)),
    )


def filtros_servicios(
    campus_id: int | None = Query(None, description="Incluye los servicios de sus edificios y áreas"),
    tipo: TipoServicio | None = None,
    edificio_id: int | None = None,
    area_id: int | None = None,
    activo: bool | None = None,
    estado: EstadoServicio | None = None,
):
    condiciones = []
    if campus_id is not None:
        condiciones.append(condicion_campus_servicio(campus_id))
    if tipo:
        condiciones.append(ServicioBasico.tipo == tipo)
    if edificio_id is not None:
        condiciones.append(ServicioBasico.edificio_id == edificio_id)
    if area_id is not None:
        condiciones.append(ServicioBasico.area_id == area_id)
    if activo is not None:
        condiciones.append(ServicioBasico.activo == activo)
    if estado:
        condiciones.append(ServicioBasico.estado == estado)
    return condiciones


async def servicio_antes_de_restaurar(db: AsyncSession, servicio: ServicioBasico) -> None:
    for campo, (modelo, nombre) in DESTINOS.items():
        id_ = getattr(servicio, campo)
        if id_ is not None:
            destino = await db.get(modelo, id_)
            if destino is None or destino.eliminado_en is not None:
                raise HTTPException(409, f"{nombre} al que abastece está eliminado; restáuralo primero")


async def validar_consumo(db: AsyncSession, datos: dict, existente: Consumo | None) -> dict:
    if existente is None:
        servicio = await db.get(ServicioBasico, datos["servicio_id"])
        if servicio is None or servicio.eliminado_en is not None:
            raise HTTPException(422, f"El servicio {datos['servicio_id']} no existe o está eliminado")
        if servicio.tipo not in UNIDADES:
            raise HTTPException(422, f"Los servicios de tipo {servicio.tipo} no registran consumo mensual; solo AGUA y LUZ")
        datos["unidad"] = UNIDADES[servicio.tipo]
    return datos


def filtros_consumos(
    campus_id: int | None = None,
    servicio_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
):
    condiciones = []
    if campus_id is not None:
        condiciones.append(Consumo.servicio_id.in_(
            select(ServicioBasico.id).where(condicion_campus_servicio(campus_id))))
    if servicio_id is not None:
        condiciones.append(Consumo.servicio_id == servicio_id)
    if desde:
        condiciones.append(Consumo.periodo >= desde.replace(day=1))
    if hasta:
        condiciones.append(Consumo.periodo <= hasta)
    return condiciones


router_servicios = crear_router_recurso(
    ruta="/servicios", etiqueta="Servicios básicos", recurso="SERVICIO", modelo=ServicioBasico,
    Crear=ServicioCrear, Actualizar=ServicioActualizar, Salida=ServicioSalida,
    filtros=filtros_servicios, validar=validar_servicio, antes_de_restaurar=servicio_antes_de_restaurar,
)

router_consumos = crear_router_recurso(
    ruta="/consumos", etiqueta="Consumos", recurso="CONSUMO", modelo=Consumo,
    Crear=ConsumoCrear, Actualizar=ConsumoActualizar, Salida=ConsumoSalida,
    filtros=filtros_consumos, validar=validar_consumo,
)


# ------------------------------------------------------- resumen para decidir
router_resumen = APIRouter(prefix="/resumen", tags=["Resumen"])


@router_resumen.get("/consumos", summary="Consumo y costo por mes y tipo de servicio")
async def resumen_consumos(
    meses: int = Query(12, ge=1, le=60),
    campus_id: int | None = Query(None, description="Vacío = todos los campus"),
    _=Depends(requiere_rol(*TODOS)),
    db: AsyncSession = Depends(get_db),
):
    hoy = date.today()
    mes_inicio = (hoy.year * 12 + hoy.month - 1) - (meses - 1)
    desde = date(mes_inicio // 12, mes_inicio % 12 + 1, 1)
    condiciones = [Consumo.eliminado_en.is_(None), Consumo.periodo >= desde]
    if campus_id is not None:
        condiciones.append(condicion_campus_servicio(campus_id))
    filas = await db.execute(
        select(Consumo.periodo, ServicioBasico.tipo, func.sum(Consumo.cantidad), func.sum(Consumo.costo))
        .join(ServicioBasico, ServicioBasico.id == Consumo.servicio_id)
        .where(*condiciones)
        .group_by(Consumo.periodo, ServicioBasico.tipo)
        .order_by(Consumo.periodo)
    )
    return [
        {"periodo": periodo.isoformat(), "tipo": tipo, "unidad": UNIDADES[tipo],
         "cantidad": float(cantidad or 0), "costo": float(costo or 0)}
        for periodo, tipo, cantidad, costo in filas.all()
    ]


@router_resumen.get("/servicios", summary="Servicios que no están operando con normalidad en un campus")
async def resumen_servicios(
    campus_id: int | None = Query(None, description="Vacío = todos los campus"),
    _=Depends(requiere_rol(*TODOS)),
    db: AsyncSession = Depends(get_db),
):
    condiciones = [ServicioBasico.eliminado_en.is_(None), ServicioBasico.estado != "OPERANDO"]
    if campus_id is not None:
        condiciones.append(condicion_campus_servicio(campus_id))
    filas = await db.execute(
        select(ServicioBasico, Campus.nombre, Edificio.nombre, Area.nombre)
        .outerjoin(Campus, Campus.id == ServicioBasico.campus_id)
        .outerjoin(Edificio, Edificio.id == ServicioBasico.edificio_id)
        .outerjoin(Area, Area.id == ServicioBasico.area_id)
        .where(*condiciones)
        .order_by(ServicioBasico.estado, ServicioBasico.nombre)
    )
    return [
        {
            "id": s.id, "tipo": s.tipo, "nombre": s.nombre, "estado": s.estado,
            "campus": nombre_campus, "edificio": nombre_edificio, "area": nombre_area,
        }
        for s, nombre_campus, nombre_edificio, nombre_area in filas.all()
    ]


# ------------------------------------------------- reacción a otros servicios
async def al_eliminar_inmueble(evento: dict) -> None:
    """Si se elimina un campus, edificio o área, sus servicios de agua y luz quedan inactivos."""
    from comun.idempotencia import marcar_procesado

    columna = {
        "CAMPUS": ServicioBasico.campus_id,
        "EDIFICIO": ServicioBasico.edificio_id,
        "AREA": ServicioBasico.area_id,
    }[evento["recurso"]]
    async with fabrica_sesiones()() as db:
        async with db.begin():
            if not await marcar_procesado(db, "servicios", evento["evento_id"]):
                return
            servicios = (await db.execute(select(ServicioBasico).where(
                columna == evento["recurso_id"],
                ServicioBasico.activo.is_(True),
                ServicioBasico.eliminado_en.is_(None),
            ))).scalars().all()
            for servicio in servicios:
                antes = ServicioSalida.model_validate(servicio).model_dump(mode="json")
                servicio.activo = False
                servicio.modificado_en = datetime.now(timezone.utc)
                servicio.modificado_por = None   # acción automática del sistema
                await db.flush()
                await registrar_evento(
                    db, accion="MODIFICAR", recurso="SERVICIO", recurso_id=servicio.id, usuario=SISTEMA,
                    antes=antes, despues=ServicioSalida.model_validate(servicio).model_dump(mode="json"),
                    motivo=f"Se eliminó {evento['recurso'].lower()} {evento['recurso_id']}",
                )
            if servicios:
                log.info("servicios_desactivados", total=len(servicios), recurso=evento["recurso"])


def _consumidores():
    from comun.mensajeria import consumidor

    return [consumidor("servicios.inmuebles", ["campus.eliminado.*", "edificio.eliminado.*", "area.eliminado.*"], al_eliminar_inmueble)]


app = crear_app(
    nombre="servicios",
    titulo="servicios-service",
    descripcion="Servicios básicos (agua, luz, internet, alcantarillado), su estado y registro de sus consumos.",
    routers=[router_servicios, router_consumos, router_resumen],
    consumidores=_consumidores() if configuracion().rabbitmq_url else (),
)
