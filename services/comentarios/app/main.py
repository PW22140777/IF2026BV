"""comentarios-service: comentarios de los Observadores sobre los recursos del sistema.

Reglas:
- Un Observador escribe comentarios sobre un edificio, área, elemento de inventario,
  servicio o consumo, y puede responder dentro de un hilo.
- El Técnico y el Administrador pueden responder (opcional); no abren comentarios nuevos.
- Consulta solo los lee.
- Solo el Administrador oculta un comentario: borrado lógico con motivo, queda en el historial.
- Los hilos tienen un nivel: se responde al comentario original, no a otra respuesta.
- Un Observador puede adjuntar hasta 4 fotos a su comentario (POST /comentarios/con-fotos).
  Las guarda archivos-service; aquí queda su ficha en archivos_adjuntos (recurso COMENTARIO).
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from comun import almacenamiento
from comun.adjuntos import foto as foto_adjunto
from comun.app import crear_app
from comun.db import get_db
from comun.historial import registrar_evento
from comun.modelos import Area, ArchivoAdjunto, Comentario, Consumo, Edificio, ElementoInventario, ServicioBasico, Usuario
from comun.recursos import Eliminacion
from comun.seguridad import ADMINISTRADOR, OBSERVADOR, SOLO_ADMIN, TECNICO, TODOS, UsuarioToken, requiere_rol

log = structlog.get_logger()

# Recursos que se pueden comentar y la tabla donde se comprueba que existan
RECURSOS = {
    "EDIFICIO": Edificio,
    "AREA": Area,
    "INVENTARIO": ElementoInventario,
    "SERVICIO": ServicioBasico,
    "CONSUMO": Consumo,
}
RecursoComentable = Literal["EDIFICIO", "AREA", "INVENTARIO", "SERVICIO", "CONSUMO"]
QUIENES_ESCRIBEN = (OBSERVADOR, TECNICO, ADMINISTRADOR)
# El Observador no ve consumos: tampoco los comenta ni lee sus comentarios
SOLO_INTERNOS = {"CONSUMO"}
MAXIMO_POR_MINUTO = 10
MAXIMO_FOTOS = 4          # fotos por comentario   # evita que una cuenta llene un recurso de comentarios


# ------------------------------------------------------------------ esquemas
class ComentarioCrear(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    recurso: RecursoComentable
    recurso_id: int = Field(gt=0)
    texto: str = Field(min_length=1, max_length=2000)
    respuesta_a: int | None = Field(default=None, gt=0, description="Comentario al que responde; vacío = comentario nuevo")


class ComentarioSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recurso: str
    recurso_id: int
    respuesta_a: int | None
    texto: str
    creado_en: datetime
    creado_por: int
    eliminado_en: datetime | None
    eliminado_por: int | None
    motivo_eliminacion: str | None


class FotoComentario(BaseModel):
    id: int
    nombre_original: str
    tamano_bytes: int
    url: str | None = None      # firmada y con caducidad; None si el almacén no respondió


class ComentarioConAutor(ComentarioSalida):
    autor_nombre: str
    autor_rol: str
    fotos: list[FotoComentario] = []


def _revisar_alcance(recurso: str, usuario: UsuarioToken) -> None:
    if recurso in SOLO_INTERNOS and usuario.rol == OBSERVADOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Los Observadores no pueden ver ni comentar consumos")


def foto(comentario: Comentario) -> dict:
    """Estado del comentario para el historial."""
    return ComentarioSalida.model_validate(comentario).model_dump(mode="json")


# --------------------------------------------------------------------- rutas
router = APIRouter(prefix="/comentarios", tags=["Comentarios"])


@router.get("", response_model=list[ComentarioConAutor], summary="Comentarios de un recurso, del más antiguo al más nuevo")
async def listar(
    recurso: RecursoComentable,
    recurso_id: int = Query(gt=0),
    incluir_ocultos: bool = Query(False, description="Solo Administrador"),
    usuario: UsuarioToken = Depends(requiere_rol(*TODOS)),
    db: AsyncSession = Depends(get_db),
):
    _revisar_alcance(recurso, usuario)
    if incluir_ocultos and usuario.rol != ADMINISTRADOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el Administrador puede ver comentarios ocultos")
    # Solo columnas de usuarios que este servicio puede leer (nunca el hash de la contraseña)
    consulta = (
        select(Comentario, Usuario.nombre, Usuario.rol)
        .join(Usuario, Usuario.id == Comentario.creado_por)
        .where(Comentario.recurso == recurso, Comentario.recurso_id == recurso_id)
        .order_by(Comentario.creado_en, Comentario.id)
    )
    if not incluir_ocultos:
        consulta = consulta.where(Comentario.eliminado_en.is_(None))
    filas = (await db.execute(consulta)).all()
    visibles = {c.id for c, _, _ in filas}
    # Fotos de todos los comentarios en una consulta, y sus URL en una sola llamada a archivos-service
    fotos = (await db.execute(select(ArchivoAdjunto).where(
        ArchivoAdjunto.recurso == "COMENTARIO", ArchivoAdjunto.recurso_id.in_(visibles),
        ArchivoAdjunto.eliminado_en.is_(None)).order_by(ArchivoAdjunto.id))).scalars().all() if visibles else []
    urls = await almacenamiento.urls(sorted({f.clave for f in fotos}))
    por_comentario: dict[int, list[FotoComentario]] = {}
    for f in fotos:
        por_comentario.setdefault(f.recurso_id, []).append(FotoComentario(
            id=f.id, nombre_original=f.nombre_original, tamano_bytes=f.tamano_bytes, url=urls.get(f.clave)))
    # Una respuesta cuyo comentario original se ocultó tampoco se muestra
    return [
        ComentarioConAutor(**ComentarioSalida.model_validate(c).model_dump(), autor_nombre=nombre, autor_rol=rol,
                           fotos=por_comentario.get(c.id, []))
        for c, nombre, rol in filas
        if c.respuesta_a is None or c.respuesta_a in visibles
    ]


@router.post("", response_model=ComentarioSalida, status_code=201, summary="Comentar un recurso o responder un comentario")
async def comentar(
    datos: ComentarioCrear,
    usuario: UsuarioToken = Depends(requiere_rol(*QUIENES_ESCRIBEN)),
    db: AsyncSession = Depends(get_db),
):
    comentario = await _crear_comentario(db, datos, usuario)
    await db.commit()
    return comentario


@router.post("/con-fotos", response_model=ComentarioConAutor, status_code=201,
             summary="Comentar con 1 a 4 fotos (solo Observadores; multipart)")
async def comentar_con_fotos(
    recurso: RecursoComentable = Form(),
    recurso_id: int = Form(gt=0),
    texto: str = Form(min_length=1, max_length=2000),
    respuesta_a: int | None = Form(default=None, gt=0),
    fotos: list[UploadFile] = File(description="JPG, PNG o WebP, hasta 10 MB cada una"),
    usuario: UsuarioToken = Depends(requiere_rol(OBSERVADOR)),
    db: AsyncSession = Depends(get_db),
):
    if not 1 <= len(fotos) <= MAXIMO_FOTOS:
        raise HTTPException(422, f"Adjunta de 1 a {MAXIMO_FOTOS} fotos por comentario")
    try:
        datos = ComentarioCrear(recurso=recurso, recurso_id=recurso_id, texto=texto, respuesta_a=respuesta_a)
    except ValidationError:
        raise HTTPException(422, "Escribe el texto del comentario (de 1 a 2000 caracteres)")
    comentario = await _crear_comentario(db, datos, usuario)   # valida todo antes de guardar fotos
    guardadas: list[dict] = []
    try:
        for archivo in fotos:
            guardadas.append(await almacenamiento.guardar(f"comentarios/{comentario.id}", archivo, categoria="imagen"))
        salida = []
        for archivo, g in zip(fotos, guardadas):
            adjunto = ArchivoAdjunto(
                recurso="COMENTARIO", recurso_id=comentario.id, nombre=(archivo.filename or "foto")[:120],
                categoria="FOTO", nombre_original=(archivo.filename or "foto")[:200], tipo_mime=g["tipo_mime"],
                tamano_bytes=g["tamano_bytes"], sha256=g["sha256"], clave=g["clave"], propiedades={},
                creado_por=usuario.id, creado_en=datetime.now(timezone.utc))
            db.add(adjunto)
            await db.flush()
            await registrar_evento(db, accion="CREAR", recurso="ARCHIVO", recurso_id=adjunto.id, usuario=usuario,
                                   despues=foto_adjunto(adjunto))
            salida.append(FotoComentario(id=adjunto.id, nombre_original=adjunto.nombre_original,
                                         tamano_bytes=adjunto.tamano_bytes, url=g.get("url")))
        await db.commit()
    except Exception:
        # Si una foto no pasa (tipo, tamaño) no queda nada: ni el comentario ni las fotos ya guardadas
        await db.rollback()
        for g in guardadas:
            try:
                await almacenamiento.borrar(g["clave"])
            except HTTPException:
                log.warning("foto_de_comentario_no_borrada", clave=g["clave"])
        raise
    return ComentarioConAutor(**ComentarioSalida.model_validate(comentario).model_dump(),
                              autor_nombre=usuario.nombre, autor_rol=usuario.rol, fotos=salida)


async def _crear_comentario(db: AsyncSession, datos: "ComentarioCrear", usuario: UsuarioToken) -> Comentario:
    """Revisa las reglas, agrega el comentario y su evento. Quien llama hace commit."""
    _revisar_alcance(datos.recurso, usuario)
    if datos.respuesta_a is None and usuario.rol != OBSERVADOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Los comentarios nuevos los escriben los Observadores; tú puedes responder a uno de ellos")

    # Lo comentado debe existir y estar activo
    objetivo = await db.get(RECURSOS[datos.recurso], datos.recurso_id)
    if objetivo is None or objetivo.eliminado_en is not None:
        raise HTTPException(422, f"No existe un registro activo de {datos.recurso.lower()} con id {datos.recurso_id}")

    if datos.respuesta_a is not None:
        original = await db.get(Comentario, datos.respuesta_a)
        if (original is None or original.eliminado_en is not None
                or (original.recurso, original.recurso_id) != (datos.recurso, datos.recurso_id)):
            raise HTTPException(422, "El comentario al que respondes no existe en este recurso o está oculto")
        if original.respuesta_a is not None:
            raise HTTPException(422, "Responde al comentario original del hilo, no a una respuesta")

    hace_un_minuto = datetime.now(timezone.utc) - timedelta(minutes=1)
    recientes = (await db.execute(select(func.count()).select_from(Comentario).where(
        Comentario.creado_por == usuario.id, Comentario.creado_en >= hace_un_minuto))).scalar_one()
    if recientes >= MAXIMO_POR_MINUTO:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Escribiste {recientes} comentarios en el último minuto; espera un momento")

    comentario = Comentario(**datos.model_dump(), creado_por=usuario.id, creado_en=datetime.now(timezone.utc))
    db.add(comentario)
    await db.flush()
    await db.refresh(comentario)
    await registrar_evento(db, accion="CREAR", recurso="COMENTARIO", recurso_id=comentario.id,
                           usuario=usuario, despues=foto(comentario))
    return comentario


@router.delete("/{id}", response_model=ComentarioSalida, summary="Ocultar un comentario (solo Administrador)")
async def ocultar(
    id: int,
    datos: Eliminacion,
    usuario: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    comentario = await db.get(Comentario, id)
    if comentario is None or comentario.eliminado_en is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe un comentario visible con id {id}")
    antes = foto(comentario)
    # Borrado lógico: el texto se conserva para la auditoría, pero deja de mostrarse
    comentario.eliminado_en = datetime.now(timezone.utc)
    comentario.eliminado_por = usuario.id
    comentario.motivo_eliminacion = datos.motivo
    await db.flush()
    await db.refresh(comentario)
    await registrar_evento(db, accion="ELIMINAR", recurso="COMENTARIO", recurso_id=comentario.id, usuario=usuario,
                           antes=antes, despues=foto(comentario), motivo=datos.motivo)
    await db.commit()
    return comentario


app = crear_app(
    nombre="comentarios",
    titulo="comentarios-service",
    descripcion="Comentarios de los Observadores sobre edificios, áreas, inventario, servicios y consumos.",
    routers=[router],
)
