"""Rutas de archivos adjuntos de un recurso: listar, subir y quitar.

    crear_router_adjuntos(ruta="/edificios", recurso="EDIFICIO", modelo=Edificio, carpeta="edificios")

agrega:

    GET    /edificios/{id}/archivos               fichas + URL de descarga (caducan)
    POST   /edificios/{id}/archivos               subir (multipart: archivo, nombre, categoria, descripcion)
    DELETE /edificios/{id}/archivos/{archivo_id}  quitar, con motivo

La ficha va a `archivos_adjuntos` (borrado lógico, en el historial como ARCHIVO); el archivo
lo guarda archivos-service. Al quitarlo, el archivo sí se borra del almacén, salvo que otra
ficha activa use el mismo contenido (mismo SHA-256 en la misma carpeta).
"""
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import almacenamiento
from .db import get_db
from .historial import registrar_evento
from .modelos import ArchivoAdjunto, Usuario
from .recursos import Eliminacion
from .seguridad import EDITORES, TODOS, UsuarioToken, requiere_rol

log = structlog.get_logger()

Categoria = Literal["FOTO", "PLANO", "DOCUMENTO", "EVIDENCIA", "OTRO"]
# Gancho opcional: revisa si se puede adjuntar al recurso (p. ej. una orden cancelada no)
AntesDeAdjuntar = Callable[[AsyncSession, Any, UsuarioToken], Awaitable[None]]


class AdjuntoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recurso: str
    recurso_id: int
    nombre: str
    descripcion: str | None
    categoria: str
    nombre_original: str
    tipo_mime: str
    tamano_bytes: int
    sha256: str
    creado_en: datetime
    creado_por: int
    creado_por_nombre: str | None = None
    url: str | None = None       # firmada y con caducidad; None si el almacén no respondió


def foto(adjunto: ArchivoAdjunto) -> dict[str, Any]:
    """Estado de la ficha para el historial (sin la URL, que caduca)."""
    datos = AdjuntoSalida.model_validate(adjunto).model_dump(mode="json", exclude={"url", "creado_por_nombre"})
    datos.update(eliminado_en=adjunto.eliminado_en and adjunto.eliminado_en.isoformat(),
                 eliminado_por=adjunto.eliminado_por, motivo_eliminacion=adjunto.motivo_eliminacion)
    return datos


def crear_router_adjuntos(
    *,
    ruta: str,
    recurso: str,
    modelo: type,
    carpeta: str,
    sufijo: str = "archivos",
    etiqueta: str = "Archivos adjuntos",
    roles_lectura: tuple[str, ...] = TODOS,
    roles_edicion: tuple[str, ...] = EDITORES,
    categoria_inicial: Categoria = "DOCUMENTO",
    antes_de_adjuntar: AntesDeAdjuntar | None = None,
) -> APIRouter:
    router = APIRouter(prefix=ruta, tags=[etiqueta])

    async def padre(db: AsyncSession, id_: int, *, activo: bool) -> Any:
        obj = await db.get(modelo, id_)
        if obj is None or (activo and obj.eliminado_en is not None):
            raise HTTPException(404, f"No existe un registro activo con id {id_}")
        return obj

    @router.get(f"/{{id}}/{sufijo}", response_model=list[AdjuntoSalida], summary="Listar los archivos adjuntos")
    async def listar(id: int, _: UsuarioToken = Depends(requiere_rol(*roles_lectura)),
                     db: AsyncSession = Depends(get_db)):
        await padre(db, id, activo=False)
        filas = (await db.execute(
            select(ArchivoAdjunto).where(ArchivoAdjunto.recurso == recurso, ArchivoAdjunto.recurso_id == id,
                                         ArchivoAdjunto.eliminado_en.is_(None))
            .order_by(ArchivoAdjunto.creado_en.desc())
        )).scalars().all()
        # Solo las columnas de usuarios que este servicio puede leer
        nombres = dict((await db.execute(
            select(Usuario.id, Usuario.nombre).where(Usuario.id.in_({f.creado_por for f in filas}))
        )).all()) if filas else {}
        enlaces = await almacenamiento.urls(sorted({f.clave for f in filas}))
        return [AdjuntoSalida.model_validate(f).model_copy(update={
            "creado_por_nombre": nombres.get(f.creado_por), "url": enlaces.get(f.clave)}) for f in filas]

    @router.post(f"/{{id}}/{sufijo}", response_model=AdjuntoSalida, status_code=201, summary="Subir un archivo adjunto")
    async def subir(
        id: int,
        archivo: UploadFile = File(..., description="JPG, PNG, WebP o PDF, hasta 10 MB"),
        nombre: str = Form(min_length=1, max_length=120),
        categoria: Categoria = Form(categoria_inicial),
        descripcion: str | None = Form(default=None, max_length=500),
        usuario: UsuarioToken = Depends(requiere_rol(*roles_edicion)),
        db: AsyncSession = Depends(get_db),
    ):
        obj = await padre(db, id, activo=True)
        if antes_de_adjuntar:
            await antes_de_adjuntar(db, obj, usuario)
        guardado = await almacenamiento.guardar(f"{carpeta}/{id}", archivo)
        adjunto = ArchivoAdjunto(
            recurso=recurso, recurso_id=id, nombre=nombre.strip(), descripcion=(descripcion or "").strip() or None,
            categoria=categoria, nombre_original=(archivo.filename or "archivo")[:200],
            tipo_mime=guardado["tipo_mime"], tamano_bytes=guardado["tamano_bytes"], sha256=guardado["sha256"],
            clave=guardado["clave"], propiedades={}, creado_por=usuario.id, creado_en=datetime.now(timezone.utc),
        )
        db.add(adjunto)
        await db.flush()
        await registrar_evento(db, accion="CREAR", recurso="ARCHIVO", recurso_id=adjunto.id, usuario=usuario,
                               despues=foto(adjunto))
        await db.commit()
        return AdjuntoSalida.model_validate(adjunto).model_copy(update={
            "creado_por_nombre": usuario.nombre, "url": guardado.get("url")})

    @router.delete(f"/{{id}}/{sufijo}/{{archivo_id}}", response_model=AdjuntoSalida,
                   summary="Quitar un archivo adjunto (con motivo)")
    async def quitar(id: int, archivo_id: int, datos: Eliminacion,
                     usuario: UsuarioToken = Depends(requiere_rol(*roles_edicion)),
                     db: AsyncSession = Depends(get_db)):
        adjunto = await db.get(ArchivoAdjunto, archivo_id)
        if adjunto is None or adjunto.recurso != recurso or adjunto.recurso_id != id or adjunto.eliminado_en:
            raise HTTPException(404, f"Este registro no tiene un archivo activo con id {archivo_id}")
        antes = foto(adjunto)
        adjunto.eliminado_en, adjunto.eliminado_por = datetime.now(timezone.utc), usuario.id
        adjunto.motivo_eliminacion = datos.motivo
        await db.flush()
        await registrar_evento(db, accion="ELIMINAR", recurso="ARCHIVO", recurso_id=adjunto.id, usuario=usuario,
                               antes=antes, despues=foto(adjunto), motivo=datos.motivo)
        await db.commit()
        # El archivo se borra del almacén si ninguna otra ficha activa lo usa
        en_uso = (await db.execute(select(func.count()).select_from(ArchivoAdjunto).where(
            ArchivoAdjunto.clave == adjunto.clave, ArchivoAdjunto.eliminado_en.is_(None)))).scalar_one()
        if not en_uso:
            try:
                await almacenamiento.borrar(adjunto.clave)
            except HTTPException:
                log.warning("archivo_no_borrado_del_almacen", archivo_id=adjunto.id)
        return AdjuntoSalida.model_validate(adjunto).model_copy(update={"creado_por_nombre": None})

    return router
