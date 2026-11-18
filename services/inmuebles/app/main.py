"""inmuebles-service: campus, edificios, áreas (con o sin edificio) e inventario.

Jerarquía:  campus > edificio > área > elemento de inventario
Un área puede no tener edificio (cancha, bancas), pero siempre pertenece a un campus.
"""
from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from comun.app import crear_app
from comun.config import configuracion
from comun.db import fabrica_sesiones, get_db
from comun.historial import registrar_evento
from comun.propiedades import revisar_valores
from comun.modelos import Area, Campus, Edificio, ElementoInventario, TipoElemento
from comun.recursos import crear_router_recurso
from comun.seguridad import SISTEMA, SOLO_ADMIN, TODOS, requiere_rol

from .esquemas import (
    AreaActualizar, AreaCrear, AreaSalida, CampusSalida,
    EdificioActualizar, EdificioCrear, EdificioSalida, ElementoActualizar, ElementoCrear, ElementoSalida,
    TipoElementoActualizar, TipoElementoCrear, TipoElementoSalida,
)

log = structlog.get_logger()

CAMPUS_FIJOS: tuple[tuple[str, str], ...] = (
    ("CENTRO", "Campus Centro"),
    ("NORTE", "Campus Norte"),
)
CLAVES_CAMPUS_FIJOS = tuple(clave for clave, _ in CAMPUS_FIJOS)


async def _exige_activo(db: AsyncSession, modelo, id_: int, nombre: str):
    obj = await db.get(modelo, id_)
    if obj is None or obj.eliminado_en is not None:
        raise HTTPException(422, f"{nombre} {id_} no existe o está eliminado")
    return obj


async def _exige_campus_fijo(db: AsyncSession, id_: int) -> Campus:
    campus = await _exige_activo(db, Campus, id_, "El campus")
    if campus.clave not in CLAVES_CAMPUS_FIJOS:
        raise HTTPException(422, f"El campus {id_} no es uno de los campus fijos permitidos")
    return campus


async def _contar_activos(db: AsyncSession, modelo, columna, valor) -> int:
    consulta = select(func.count()).select_from(modelo).where(columna == valor, modelo.eliminado_en.is_(None))
    return (await db.execute(consulta)).scalar_one()


async def _padre_activo(db: AsyncSession, modelo, id_: int | None, mensaje: str) -> None:
    """Para restaurar: el padre (campus, edificio o área) debe estar activo."""
    if id_ is None:
        return
    padre = await db.get(modelo, id_)
    if padre is None or padre.eliminado_en is not None:
        raise HTTPException(409, mensaje)


router_campus = APIRouter(prefix="/campus", tags=["Campus"])


@router_campus.get("", response_model=list[CampusSalida], summary="Listar campus (solo lectura)")
async def listar_campus(
    estado: str | None = None,
    buscar: str | None = Query(None, description="Clave o nombre"),
    _=Depends(requiere_rol(*TODOS)),
    db: AsyncSession = Depends(get_db),
):
    condiciones = [
        Campus.eliminado_en.is_(None),
        Campus.clave.in_(CLAVES_CAMPUS_FIJOS),
    ]
    if estado:
        condiciones.append(Campus.estado == estado)
    if buscar:
        patron = f"%{buscar}%"
        condiciones.append(Campus.nombre.ilike(patron) | Campus.clave.ilike(patron))
    consulta = select(Campus).where(*condiciones).order_by(Campus.id)
    return (await db.execute(consulta)).scalars().all()


@router_campus.get("/{id}", response_model=CampusSalida, summary="Ver un campus (solo lectura)")
async def ver_campus(
    id: int,
    _=Depends(requiere_rol(*TODOS)),
    db: AsyncSession = Depends(get_db),
):
    campus = await db.get(Campus, id)
    if campus is None or campus.eliminado_en is not None or campus.clave not in CLAVES_CAMPUS_FIJOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Campus: no existe el registro {id}")
    return campus


# ----------------------------------------------------------------- edificios
def filtros_edificios(
    campus_id: int | None = None,
    estado: str | None = None,
    buscar: str | None = Query(None, description="Clave o nombre"),
):
    condiciones = []
    if campus_id is not None:
        condiciones.append(Edificio.campus_id == campus_id)
    if estado:
        condiciones.append(Edificio.estado == estado)
    if buscar:
        patron = f"%{buscar}%"
        condiciones.append(Edificio.nombre.ilike(patron) | Edificio.clave.ilike(patron))
    return condiciones


def _texto_pisos(niveles: int) -> str:
    return "solo la planta baja (piso 0)" if niveles == 1 else f"los pisos 0 (planta baja) a {niveles - 1}"


async def validar_edificio(db: AsyncSession, datos: dict, existente: Edificio | None) -> None:
    if "campus_id" in datos:   # solo al crear: el campus de un edificio no cambia
        await _exige_campus_fijo(db, datos["campus_id"])
    # Si se reducen los niveles, ninguna área activa puede quedar en un piso que ya no existe
    if existente is not None and datos.get("niveles") is not None:
        niveles = datos["niveles"]
        piso_mas_alto = (await db.execute(
            select(func.max(Area.piso)).where(
                Area.edificio_id == existente.id, Area.eliminado_en.is_(None), Area.piso.is_not(None))
        )).scalar_one()
        if piso_mas_alto is not None and piso_mas_alto >= niveles:
            raise HTTPException(409, f"El edificio tiene áreas en el piso {piso_mas_alto}; con {niveles} "
                                     f"nivel(es) solo existen {_texto_pisos(niveles)}. "
                                     "Cambia primero el piso de esas áreas o indica más niveles")


async def edificio_antes_de_eliminar(db: AsyncSession, edificio: Edificio) -> None:
    areas = await _contar_activos(db, Area, Area.edificio_id, edificio.id)
    if areas:
        raise HTTPException(409, f"El edificio tiene {areas} área(s) activa(s); elimínalas o reasígnalas primero")


async def edificio_antes_de_restaurar(db: AsyncSession, edificio: Edificio) -> None:
    await _padre_activo(db, Campus, edificio.campus_id, "Su campus está eliminado; restaura primero el campus")


router_edificios = crear_router_recurso(
    ruta="/edificios", etiqueta="Edificios", recurso="EDIFICIO", modelo=Edificio,
    Crear=EdificioCrear, Actualizar=EdificioActualizar, Salida=EdificioSalida,
    filtros=filtros_edificios, validar=validar_edificio,
    antes_de_eliminar=edificio_antes_de_eliminar, antes_de_restaurar=edificio_antes_de_restaurar,
)


# --------------------------------------------------------------------- áreas
def filtros_areas(
    campus_id: int | None = None,
    edificio_id: int | None = None,
    independientes: bool = Query(False, description="Solo áreas sin edificio"),
    tipo: str | None = None,
    estado: str | None = None,
    buscar: str | None = None,
):
    condiciones = []
    if campus_id is not None:
        condiciones.append(Area.campus_id == campus_id)
    if edificio_id is not None:
        condiciones.append(Area.edificio_id == edificio_id)
    if independientes:
        condiciones.append(Area.edificio_id.is_(None))
    if tipo:
        condiciones.append(Area.tipo == tipo)
    if estado:
        condiciones.append(Area.estado == estado)
    if buscar:
        condiciones.append(Area.nombre.ilike(f"%{buscar}%"))
    return condiciones


async def validar_area(db: AsyncSession, datos: dict, existente: Area | None) -> dict:
    """El campus de un área con edificio es siempre el del edificio.

    - Con edificio: el campus se toma del edificio (si se envía otro, error).
    - Sin edificio: el campus es obligatorio.
    """
    edificio_id = datos["edificio_id"] if "edificio_id" in datos else (existente.edificio_id if existente else None)
    campus_enviado = datos.get("campus_id")

    if edificio_id is not None:
        if "edificio_id" in datos:
            edificio = await _exige_activo(db, Edificio, edificio_id, "El edificio")
        else:
            edificio = await db.get(Edificio, edificio_id)
        if campus_enviado is not None and campus_enviado != edificio.campus_id:
            raise HTTPException(422, "El edificio elegido pertenece a otro campus; un área dentro de un "
                                     "edificio siempre está en el campus de ese edificio")
        datos["campus_id"] = edificio.campus_id
        _validar_piso(datos, existente, edificio)
    else:
        campus_id = campus_enviado if campus_enviado is not None else (existente.campus_id if existente else None)
        if campus_id is None:
            raise HTTPException(422, "Un área sin edificio necesita un campus (campus_id)")
        if campus_enviado is not None:
            await _exige_campus_fijo(db, campus_id)
        datos["campus_id"] = campus_id
        # Un área sin edificio (cancha, patio) no está en ningún piso
        if datos.get("piso") is not None:
            raise HTTPException(422, "Un área sin edificio no tiene piso; deja el piso vacío o elige un edificio")
        if existente is not None and existente.piso is not None:
            datos["piso"] = None   # se convirtió en área independiente: el piso anterior ya no aplica
    return datos


def _validar_piso(datos: dict, existente: Area | None, edificio: Edificio) -> None:
    """El piso de un área debe existir en su edificio: de 0 (planta baja) a niveles - 1."""
    # Solo se revisa si cambia el piso o el edificio; así editar otros campos no falla con datos anteriores
    if "piso" not in datos and "edificio_id" not in datos:
        return
    piso = datos["piso"] if "piso" in datos else (existente.piso if existente else None)
    if piso is None:
        return
    if edificio.niveles is None:
        raise HTTPException(422, f"El edificio {edificio.nombre} no tiene registrado su número de niveles; "
                                 "regístralo primero para poder asignar un piso al área")
    if piso >= edificio.niveles:
        raise HTTPException(422, f"El piso {piso} no existe en {edificio.nombre}: tiene {edificio.niveles} "
                                 f"nivel(es), es decir, {_texto_pisos(edificio.niveles)}")


async def area_antes_de_eliminar(db: AsyncSession, area: Area) -> None:
    elementos = await _contar_activos(db, ElementoInventario, ElementoInventario.area_id, area.id)
    if elementos:
        raise HTTPException(409, f"El área tiene {elementos} elemento(s) de inventario activo(s); "
                                 "elimínalos o muévelos primero")


async def area_antes_de_restaurar(db: AsyncSession, area: Area) -> None:
    await _padre_activo(db, Campus, area.campus_id, "Su campus está eliminado; restaura primero el campus")
    await _padre_activo(db, Edificio, area.edificio_id, "Su edificio está eliminado; restaura primero el edificio")


router_areas = crear_router_recurso(
    ruta="/areas", etiqueta="Áreas", recurso="AREA", modelo=Area,
    Crear=AreaCrear, Actualizar=AreaActualizar, Salida=AreaSalida,
    filtros=filtros_areas, validar=validar_area,
    antes_de_eliminar=area_antes_de_eliminar, antes_de_restaurar=area_antes_de_restaurar,
)


# ---------------------------------------------------------------- inventario
def filtros_inventario(
    campus_id: int | None = None,
    area_id: int | None = None,
    edificio_id: int | None = None,
    tipo: str | None = None,
    estado: str | None = None,
):
    condiciones = []
    if campus_id is not None:
        condiciones.append(ElementoInventario.area_id.in_(select(Area.id).where(Area.campus_id == campus_id)))
    if area_id is not None:
        condiciones.append(ElementoInventario.area_id == area_id)
    if edificio_id is not None:
        condiciones.append(ElementoInventario.area_id.in_(select(Area.id).where(Area.edificio_id == edificio_id)))
    if tipo:
        condiciones.append(ElementoInventario.tipo == tipo)
    if estado:
        condiciones.append(ElementoInventario.estado == estado)
    return condiciones


MEDIDAS = ("largo", "alto", "ancho", "espesor")


async def _tipo_activo(db: AsyncSession, clave: str | None) -> TipoElemento | None:
    if clave is None:
        return None
    return (await db.execute(select(TipoElemento).where(
        TipoElemento.clave == clave, TipoElemento.eliminado_en.is_(None)))).scalar_one_or_none()


def _revisar_propiedades(tipo: TipoElemento, propiedades: dict) -> tuple[dict, list[str]]:
    """Revisa las propiedades de un elemento contra las que define su tipo (reglas en comun.propiedades)."""
    return revisar_valores(tipo.propiedades_definidas, propiedades, tipo.nombre.lower())


async def validar_elemento(db: AsyncSession, datos: dict, existente: ElementoInventario | None) -> dict:
    if "area_id" in datos:
        await _exige_activo(db, Area, datos["area_id"], "El área")

    # El tipo debe estar en el catálogo; de él salen las propiedades que se revisan
    cambia_medida = any(campo in datos for campo in (*MEDIDAS, "unidad"))
    tipo = None
    if "tipo" in datos or "propiedades" in datos or cambia_medida:
        tipo = await _tipo_activo(db, datos.get("tipo") or (existente.tipo if existente else None))
    if "tipo" in datos and tipo is None:
        raise HTTPException(422, f"El tipo {datos['tipo']} no está en el catálogo; el Administrador puede "
                                 "agregarlo en «Tipos de elemento»")

    # Las medidas sin unidad no se pueden interpretar (¿2 metros o 2 centímetros?).
    # Solo se revisa si cambian, para no bloquear la edición de registros anteriores.
    if cambia_medida:
        if tipo is not None and not tipo.usa_medidas and any(datos.get(m) is not None for m in MEDIDAS):
            raise HTTPException(422, f"Los elementos de tipo {tipo.nombre.lower()} no llevan medidas "
                                     "(largo, alto, ancho o espesor); déjalas vacías")

        def valor(campo):
            return datos[campo] if campo in datos else (getattr(existente, campo) if existente else None)
        con_medida = [m for m in MEDIDAS if valor(m) is not None]
        if con_medida and valor("unidad") is None:
            raise HTTPException(422, f"Indica la unidad (mm, cm o m) de las medidas: {', '.join(con_medida)}")

    # Propiedades según el tipo: se revisan si cambian ellas o el tipo
    if tipo is not None and ("propiedades" in datos or "tipo" in datos):
        actuales = datos.get("propiedades")
        if actuales is None:
            actuales = existente.propiedades if existente else {}
        limpias, errores = _revisar_propiedades(tipo, actuales or {})
        if errores:
            raise HTTPException(422, "Revisa las propiedades: " + "; ".join(errores))
        if "propiedades" in datos:
            datos["propiedades"] = limpias
    return datos


async def elemento_antes_de_restaurar(db: AsyncSession, elemento: ElementoInventario) -> None:
    await _padre_activo(db, Area, elemento.area_id, "Su área está eliminada; restaura primero el área")


router_inventario = crear_router_recurso(
    ruta="/inventario", etiqueta="Inventario", recurso="INVENTARIO", modelo=ElementoInventario,
    Crear=ElementoCrear, Actualizar=ElementoActualizar, Salida=ElementoSalida,
    filtros=filtros_inventario, validar=validar_elemento, antes_de_restaurar=elemento_antes_de_restaurar,
    propiedades_reservadas=frozenset({
        "total", "total_lineal", "total_area", "total_volumen", "total_volumen_espesor",
    }),
)


# ---------------------------------------------------------- tipos de elemento
def filtros_tipos(buscar: str | None = Query(None, description="Clave o nombre")):
    if not buscar:
        return []
    patron = f"%{buscar}%"
    return [TipoElemento.nombre.ilike(patron) | TipoElemento.clave.ilike(patron)]


async def validar_tipo(db: AsyncSession, datos: dict, _existente) -> None:
    if "clave" in datos and await _tipo_activo(db, datos["clave"]):   # solo al crear: la clave no cambia
        raise HTTPException(409, f"Ya existe el tipo {datos['clave']}; elige otra clave")


async def tipo_antes_de_eliminar(db: AsyncSession, tipo: TipoElemento) -> None:
    elementos = await _contar_activos(db, ElementoInventario, ElementoInventario.tipo, tipo.clave)
    if elementos:
        raise HTTPException(409, f"Hay {elementos} elemento(s) de inventario de tipo {tipo.nombre.lower()}; "
                                 "elimínalos o cámbiales el tipo primero")


async def tipo_antes_de_restaurar(db: AsyncSession, tipo: TipoElemento) -> None:
    if await _tipo_activo(db, tipo.clave):
        raise HTTPException(409, f"Ya hay otro tipo activo con la clave {tipo.clave}")


# Todos pueden consultar el catálogo (el formulario de inventario lo necesita); solo el Administrador lo cambia
router_tipos = crear_router_recurso(
    ruta="/tipos-elemento", etiqueta="Tipos de elemento", recurso="TIPO_ELEMENTO", modelo=TipoElemento,
    Crear=TipoElementoCrear, Actualizar=TipoElementoActualizar, Salida=TipoElementoSalida,
    filtros=filtros_tipos, validar=validar_tipo, roles_edicion=SOLO_ADMIN,
    antes_de_eliminar=tipo_antes_de_eliminar, antes_de_restaurar=tipo_antes_de_restaurar,
)


# ------------------------------------------------------- resumen para decidir
router_resumen = APIRouter(prefix="/resumen", tags=["Resumen"])


@router_resumen.get("/inmuebles", summary="Totales para el tablero de decisiones")
async def resumen(
    campus_id: int | None = Query(None, description="Vacío = todos los campus"),
    _=Depends(requiere_rol(*TODOS)),
    db: AsyncSession = Depends(get_db),
):
    # Condición "pertenece al campus" para cada tabla
    def del_campus(modelo):
        if campus_id is None:
            return []
        if modelo is ElementoInventario:
            return [ElementoInventario.area_id.in_(select(Area.id).where(Area.campus_id == campus_id))]
        return [modelo.campus_id == campus_id]

    async def contar(modelo, *condiciones) -> int:
        consulta = (select(func.count()).select_from(modelo)
                    .where(modelo.eliminado_en.is_(None), *del_campus(modelo), *condiciones))
        return (await db.execute(consulta)).scalar_one()

    async def agrupar(columna_grupo, columna_suma=None):
        modelo = columna_grupo.class_
        valor = func.sum(columna_suma) if columna_suma is not None else func.count()
        filas = await db.execute(
            select(columna_grupo, valor)
            .where(modelo.eliminado_en.is_(None), *del_campus(modelo))
            .group_by(columna_grupo)
        )
        return {grupo: int(total or 0) for grupo, total in filas.all()}

    # Inventario por tipo y estado: {"BANCA": {"BUENO": 96, "MALO": 8}, ...}
    # Se suma la cantidad porque un registro puede representar varias piezas (6 bancas).
    filas = await db.execute(
        select(ElementoInventario.tipo, ElementoInventario.estado, func.sum(ElementoInventario.cantidad))
        .where(ElementoInventario.eliminado_en.is_(None), *del_campus(ElementoInventario))
        .group_by(ElementoInventario.tipo, ElementoInventario.estado)
    )
    inventario_por_tipo_y_estado: dict[str, dict[str, int]] = {}
    for tipo, estado, total in filas.all():
        inventario_por_tipo_y_estado.setdefault(tipo, {})[estado] = int(total or 0)

    total_campus = (await db.execute(
        select(func.count()).select_from(Campus).where(
            Campus.eliminado_en.is_(None),
            Campus.clave.in_(CLAVES_CAMPUS_FIJOS),
        )
    )).scalar_one()
    return {
        "campus": total_campus,
        "edificios": await contar(Edificio),
        "areas": await contar(Area),
        "areas_independientes": await contar(Area, Area.edificio_id.is_(None)),
        "elementos_inventario": await agrupar(ElementoInventario.tipo, ElementoInventario.cantidad),
        "inventario_por_estado": await agrupar(ElementoInventario.estado, ElementoInventario.cantidad),
        "edificios_por_estado": await agrupar(Edificio.estado),
        "areas_por_tipo": await agrupar(Area.tipo),
        "areas_por_estado": await agrupar(Area.estado),
        "inventario_por_tipo_y_estado": inventario_por_tipo_y_estado,
        "edificios_detalle": await _detalle_edificios(db, campus_id),
    }


# Orden de urgencia: primero lo que está fuera de servicio
URGENCIA_ESTADO = {"FUERA_DE_SERVICIO": 0, "EN_MANTENIMIENTO": 1, "OPERATIVO": 2}
ESTADOS_DANADOS = ("MALO", "FUERA_DE_SERVICIO")


async def _detalle_edificios(db: AsyncSession, campus_id: int | None) -> list[dict]:
    """Cada edificio con sus áreas operativas y su inventario dañado, del más urgente al menos."""
    condiciones = [Edificio.eliminado_en.is_(None)]
    if campus_id is not None:
        condiciones.append(Edificio.campus_id == campus_id)
    edificios = (await db.execute(
        select(Edificio.id, Edificio.clave, Edificio.nombre, Edificio.campus_id, Edificio.estado).where(*condiciones)
    )).all()

    # Áreas activas por edificio: total y cuántas operan
    areas = {
        edificio_id: (total, operativas)
        for edificio_id, total, operativas in (await db.execute(
            select(Area.edificio_id, func.count(), func.count().filter(Area.estado == "OPERATIVO"))
            .where(Area.eliminado_en.is_(None), Area.edificio_id.is_not(None))
            .group_by(Area.edificio_id)
        )).all()
    }
    # Piezas de inventario en mal estado o fuera de servicio, por edificio de su área
    danados = dict((await db.execute(
        select(Area.edificio_id, func.sum(ElementoInventario.cantidad))
        .join(Area, Area.id == ElementoInventario.area_id)
        .where(
            ElementoInventario.eliminado_en.is_(None), Area.eliminado_en.is_(None),
            Area.edificio_id.is_not(None), ElementoInventario.estado.in_(ESTADOS_DANADOS),
        )
        .group_by(Area.edificio_id)
    )).all())

    detalle = [
        {
            "id": e.id, "clave": e.clave, "nombre": e.nombre, "campus_id": e.campus_id, "estado": e.estado,
            "areas": areas.get(e.id, (0, 0))[0],
            "areas_operativas": areas.get(e.id, (0, 0))[1],
            "inventario_danado": int(danados.get(e.id) or 0),
        }
        for e in edificios
    ]
    detalle.sort(key=lambda d: (URGENCIA_ESTADO.get(d["estado"], 3), -d["inventario_danado"], d["nombre"]))
    return detalle


# ------------------------------------------------------------------- arranque
async def asegurar_campus_fijos() -> None:
    async with fabrica_sesiones()() as db:
        try:
            creados = 0
            for clave, nombre in CAMPUS_FIJOS:
                existente = (await db.execute(
                    select(Campus).where(Campus.clave == clave, Campus.eliminado_en.is_(None))
                )).scalar_one_or_none()
                if existente is None:
                    campus = Campus(
                        clave=clave,
                        nombre=nombre,
                        estado="OPERATIVO",
                        creado_en=datetime.now(timezone.utc),
                    )
                    db.add(campus)
                    await db.flush()
                    await db.refresh(campus)
                    await registrar_evento(
                        db,
                        accion="CREAR",
                        recurso="CAMPUS",
                        recurso_id=campus.id,
                        usuario=SISTEMA,
                        despues=CampusSalida.model_validate(campus).model_dump(mode="json"),
                        motivo="Campus fijo inicial",
                    )
                    creados += 1
                elif existente.nombre != nombre:
                    existente.nombre = nombre
            await db.commit()
            if creados:
                log.info("campus_fijos_creados", total=creados)
        except IntegrityError:
            await db.rollback()


def _consumidores():
    from comun.mantenimientos import PATRONES, manejador_de_estados
    from comun.mensajeria import consumidor

    # Un mantenimiento iniciado o terminado deja el edificio, el área o el elemento en el estado que dice su plantilla
    aplicar = manejador_de_estados("inmuebles.mantenimiento", {
        "EDIFICIO": (Edificio, EdificioSalida, ("OPERATIVO", "EN_MANTENIMIENTO", "FUERA_DE_SERVICIO")),
        "AREA": (Area, AreaSalida, ("OPERATIVO", "EN_MANTENIMIENTO", "FUERA_DE_SERVICIO")),
        "INVENTARIO": (ElementoInventario, ElementoSalida, ("BUENO", "REGULAR", "MALO", "FUERA_DE_SERVICIO")),
    })
    return [consumidor("inmuebles.mantenimiento", PATRONES, aplicar)]


app = crear_app(
    nombre="inmuebles",
    titulo="inmuebles-service",
    descripcion="Campus fijos (Centro y Norte), edificios, áreas (con o sin edificio) e inventario de cada área.",
    routers=[router_campus, router_edificios, router_areas, router_inventario, router_tipos, router_resumen],
    al_iniciar=asegurar_campus_fijos,
    consumidores=_consumidores() if configuracion().rabbitmq_url else (),
)
