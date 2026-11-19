"""Rutas CRUD genéricas para cualquier recurso administrable.

Todos los recursos (edificios, áreas, inventario, servicios básicos y
consumos) se administran igual:

  GET    /<recurso>                         listar (todos los roles)
  GET    /<recurso>/{id}                    ver uno (todos los roles)
  POST   /<recurso>                         crear (Administrador y Técnico)
  PATCH  /<recurso>/{id}                    modificar (Administrador y Técnico)
  DELETE /<recurso>/{id}                    eliminar con motivo (Administrador y Técnico)
  POST   /<recurso>/{id}/restaurar          restaurar (solo Administrador)
  PUT    /<recurso>/{id}/propiedades/{clave}   agregar o cambiar una propiedad
  DELETE /<recurso>/{id}/propiedades/{clave}   quitar una propiedad

Cada cambio guarda el estado ANTES y DESPUÉS y lo envía al historial.
La eliminación es lógica: la fila se marca y deja de aparecer en listas.
"""
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .historial import registrar_evento
from .seguridad import ADMINISTRADOR, EDITORES, SOLO_ADMIN, TODOS, UsuarioToken, requiere_rol

# Una clave de propiedad: letras, números y guion bajo
PATRON_CLAVE = r"^[A-Za-z0-9_]{1,50}$"


# ------------------------------------------------------------- esquemas base
class SalidaBase(BaseModel):
    """Campos que todo recurso devuelve."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    propiedades: dict[str, Any]
    creado_en: datetime
    creado_por: int | None
    modificado_en: datetime | None
    modificado_por: int | None
    eliminado_en: datetime | None
    eliminado_por: int | None
    motivo_eliminacion: str | None


class Eliminacion(BaseModel):
    motivo: str = Field(min_length=5, max_length=500, description="Por qué se elimina (obligatorio)")


class Restauracion(BaseModel):
    motivo: str | None = Field(default=None, max_length=500)


class ValorPropiedad(BaseModel):
    valor: Any = Field(description="Cualquier valor JSON: texto, número, booleano, lista u objeto")


Validador = Callable[[AsyncSession, dict[str, Any], Any | None], Awaitable[dict[str, Any] | None]]
Gancho = Callable[[AsyncSession, Any], Awaitable[None]]
# Completa las salidas antes de responder (p. ej. la URL firmada de la foto de fachada)
Completar = Callable[[list[Any]], Awaitable[None]]


def _sin_filtros() -> list:
    return []


def crear_router_recurso(
    *,
    ruta: str,
    etiqueta: str,
    recurso: str,
    modelo: type,
    Crear: type[BaseModel],
    Actualizar: type[BaseModel],
    Salida: type[BaseModel],
    filtros: Callable[..., list] | None = None,
    validar: Validador | None = None,
    antes_de_eliminar: Gancho | None = None,
    antes_de_restaurar: Gancho | None = None,
    propiedades_reservadas: frozenset[str] = frozenset(),
    roles_edicion: tuple[str, ...] = EDITORES,
    roles_lectura: tuple[str, ...] = TODOS,
    completar_salida: Completar | None = None,
    campos_temporales: frozenset[str] = frozenset(),
) -> APIRouter:
    """Construye el router de un recurso.

    - recurso:  nombre en el historial (EDIFICIO, AREA, INVENTARIO...)
    - filtros:  dependencia que devuelve condiciones SQL para el listado
    - validar:  revisa (y puede completar) los datos antes de crear o modificar
    - antes_de_eliminar / antes_de_restaurar: reglas de negocio que pueden
      lanzar HTTPException para impedir la operación
    - roles_edicion: quién crea, modifica y elimina (por defecto Administrador y Técnico)
    - roles_lectura: quién lista y ve registros (por defecto todos; LECTORES_INTERNOS deja fuera al Observador)
    - completar_salida: agrega a las respuestas datos que no están en la tabla (p. ej. URL que caducan)
    - campos_temporales: campos de la salida que no van al historial (porque cambian solos, como una URL)

    Al cambiar una sola propiedad también se llama a `validar` con {"propiedades": ...},
    para que un recurso pueda revisar sus propiedades (p. ej. las de cada tipo de inventario).
    """
    router = APIRouter(prefix=ruta, tags=[etiqueta])
    dependencia_filtros = filtros or _sin_filtros
    reservadas = {clave.casefold() for clave in propiedades_reservadas}

    def foto(obj: Any) -> dict[str, Any]:
        """Estado completo del recurso en JSON, para el historial."""
        return Salida.model_validate(obj).model_dump(mode="json", exclude=set(campos_temporales))

    async def responder(obj: Any) -> Any:
        if completar_salida is None:
            return obj
        salida = Salida.model_validate(obj)
        await completar_salida([salida])
        return salida

    async def obtener(db: AsyncSession, id_: int, *, activo: bool = True) -> Any:
        obj = await db.get(modelo, id_)
        if obj is None or (activo and obj.eliminado_en is not None):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{etiqueta}: no existe el registro {id_}")
        return obj

    @router.get("", response_model=list[Salida], summary=f"Listar {etiqueta.lower()}")
    async def listar(
        condiciones: list = Depends(dependencia_filtros),
        incluir_eliminados: bool = Query(False, description="Solo Administrador"),
        limite: int = Query(200, ge=1, le=1000),
        desplazamiento: int = Query(0, ge=0),
        usuario: UsuarioToken = Depends(requiere_rol(*roles_lectura)),
        db: AsyncSession = Depends(get_db),
    ):
        if incluir_eliminados and usuario.rol != ADMINISTRADOR:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el Administrador puede ver registros eliminados")
        consulta = select(modelo).where(*condiciones)
        if not incluir_eliminados:
            consulta = consulta.where(modelo.eliminado_en.is_(None))
        consulta = consulta.order_by(modelo.id).limit(limite).offset(desplazamiento)
        objs = (await db.execute(consulta)).scalars().all()
        if completar_salida is None:
            return objs
        salidas = [Salida.model_validate(o) for o in objs]
        await completar_salida(salidas)   # una sola llamada para toda la lista
        return salidas

    @router.get("/{id}", response_model=Salida, summary=f"Ver un registro de {etiqueta.lower()}")
    async def ver(
        id: int,
        usuario: UsuarioToken = Depends(requiere_rol(*roles_lectura)),
        db: AsyncSession = Depends(get_db),
    ):
        return await responder(await obtener(db, id, activo=usuario.rol != ADMINISTRADOR))

    @router.post("", response_model=Salida, status_code=status.HTTP_201_CREATED,
                 summary=f"Crear en {etiqueta.lower()}")
    async def crear(
        datos: Crear,  # type: ignore[valid-type]
        usuario: UsuarioToken = Depends(requiere_rol(*roles_edicion)),
        db: AsyncSession = Depends(get_db),
    ):
        valores = datos.model_dump()
        if validar:
            valores = await validar(db, valores, None) or valores
        obj = modelo(**valores, creado_por=usuario.id, creado_en=datetime.now(timezone.utc))
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        await registrar_evento(db, accion="CREAR", recurso=recurso, recurso_id=obj.id,
                               usuario=usuario, despues=foto(obj))
        await db.commit()
        return await responder(obj)

    @router.patch("/{id}", response_model=Salida, summary=f"Modificar en {etiqueta.lower()}")
    async def modificar(
        datos: Actualizar,  # type: ignore[valid-type]
        id: int,
        usuario: UsuarioToken = Depends(requiere_rol(*roles_edicion)),
        db: AsyncSession = Depends(get_db),
    ):
        obj = await obtener(db, id)
        cambios = datos.model_dump(exclude_unset=True)
        if not cambios:
            return await responder(obj)
        if validar:
            cambios = await validar(db, cambios, obj) or cambios
        antes = foto(obj)
        for campo, valor in cambios.items():
            setattr(obj, campo, valor)
        await _guardar_cambio(db, obj, usuario, antes, accion="MODIFICAR")
        return await responder(obj)

    @router.delete("/{id}", response_model=Salida, summary=f"Eliminar en {etiqueta.lower()} (borrado lógico)")
    async def eliminar(
        datos: Eliminacion,
        id: int,
        usuario: UsuarioToken = Depends(requiere_rol(*roles_edicion)),
        db: AsyncSession = Depends(get_db),
    ):
        obj = await obtener(db, id)
        if antes_de_eliminar:
            await antes_de_eliminar(db, obj)
        antes = foto(obj)
        obj.eliminado_en = datetime.now(timezone.utc)
        obj.eliminado_por = usuario.id
        obj.motivo_eliminacion = datos.motivo
        await db.flush()
        await db.refresh(obj)
        await registrar_evento(db, accion="ELIMINAR", recurso=recurso, recurso_id=obj.id, usuario=usuario,
                               antes=antes, despues=foto(obj), motivo=datos.motivo)
        await db.commit()
        return await responder(obj)

    @router.post("/{id}/restaurar", response_model=Salida, summary="Restaurar un registro eliminado")
    async def restaurar(
        id: int,
        datos: Restauracion | None = Body(default=None),
        usuario: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN)),
        db: AsyncSession = Depends(get_db),
    ):
        datos = datos or Restauracion()
        obj = await obtener(db, id, activo=False)
        if obj.eliminado_en is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "El registro no está eliminado")
        if antes_de_restaurar:
            await antes_de_restaurar(db, obj)
        antes = foto(obj)
        obj.eliminado_en = None
        obj.eliminado_por = None
        obj.motivo_eliminacion = None
        await _guardar_cambio(db, obj, usuario, antes, accion="RESTAURAR", motivo=datos.motivo)
        return await responder(obj)

    @router.put("/{id}/propiedades/{clave}", response_model=Salida,
                summary="Agregar o cambiar una propiedad")
    async def poner_propiedad(
        datos: ValorPropiedad,
        id: int,
        clave: str = Path(pattern=PATRON_CLAVE),
        usuario: UsuarioToken = Depends(requiere_rol(*roles_edicion)),
        db: AsyncSession = Depends(get_db),
    ):
        if clave.casefold() in reservadas:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"La propiedad '{clave}' está reservada por el sistema")
        obj = await obtener(db, id)
        antes = foto(obj)
        # Se asigna un diccionario nuevo para que SQLAlchemy detecte el cambio
        obj.propiedades = await _propiedades_validadas(db, obj, {**(obj.propiedades or {}), clave: datos.valor})
        await _guardar_cambio(db, obj, usuario, antes, accion="MODIFICAR")
        return await responder(obj)

    @router.delete("/{id}/propiedades/{clave}", response_model=Salida, summary="Quitar una propiedad")
    async def quitar_propiedad(
        id: int,
        clave: str = Path(pattern=PATRON_CLAVE),
        usuario: UsuarioToken = Depends(requiere_rol(*roles_edicion)),
        db: AsyncSession = Depends(get_db),
    ):
        if clave.casefold() in reservadas:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"La propiedad '{clave}' está reservada por el sistema")
        obj = await obtener(db, id)
        if clave not in (obj.propiedades or {}):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"La propiedad '{clave}' no existe")
        antes = foto(obj)
        obj.propiedades = await _propiedades_validadas(db, obj, {k: v for k, v in obj.propiedades.items() if k != clave})
        await _guardar_cambio(db, obj, usuario, antes, accion="MODIFICAR")
        return await responder(obj)

    async def _propiedades_validadas(db: AsyncSession, obj: Any, nuevas: dict[str, Any]) -> dict[str, Any]:
        """Pasa las propiedades nuevas por el validador del recurso (puede rechazarlas o ajustarlas)."""
        if not validar:
            return nuevas
        cambios = await validar(db, {"propiedades": nuevas}, obj) or {"propiedades": nuevas}
        return cambios["propiedades"]

    async def _guardar_cambio(db: AsyncSession, obj: Any, usuario: UsuarioToken, antes: dict,
                              *, accion: str, motivo: str | None = None) -> None:
        obj.modificado_en = datetime.now(timezone.utc)
        obj.modificado_por = usuario.id
        await db.flush()
        await db.refresh(obj)
        await registrar_evento(db, accion=accion, recurso=recurso, recurso_id=obj.id, usuario=usuario,
                               antes=antes, despues=foto(obj), motivo=motivo)
        await db.commit()

    return router
