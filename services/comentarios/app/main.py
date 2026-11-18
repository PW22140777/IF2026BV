"""comentarios-service: comentarios de los Observadores sobre los recursos del sistema.

Reglas:
- Un Observador escribe comentarios sobre un edificio, área, elemento de inventario,
  servicio o consumo, y puede responder dentro de un hilo.
- El Técnico y el Administrador pueden responder (opcional); no abren comentarios nuevos.
- Consulta solo los lee.
- Solo el Administrador oculta un comentario: borrado lógico con motivo, queda en el historial.
- Los hilos tienen un nivel: se responde al comentario original, no a otra respuesta.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from comun.app import crear_app
from comun.db import get_db
from comun.historial import registrar_evento
from comun.modelos import Area, Comentario, Consumo, Edificio, ElementoInventario, ServicioBasico, Usuario
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
MAXIMO_POR_MINUTO = 10   # evita que una cuenta llene un recurso de comentarios


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


class ComentarioConAutor(ComentarioSalida):
    autor_nombre: str
    autor_rol: str


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
    # Una respuesta cuyo comentario original se ocultó tampoco se muestra
    return [
        ComentarioConAutor(**ComentarioSalida.model_validate(c).model_dump(), autor_nombre=nombre, autor_rol=rol)
        for c, nombre, rol in filas
        if c.respuesta_a is None or c.respuesta_a in visibles
    ]


@router.post("", response_model=ComentarioSalida, status_code=201, summary="Comentar un recurso o responder un comentario")
async def comentar(
    datos: ComentarioCrear,
    usuario: UsuarioToken = Depends(requiere_rol(*QUIENES_ESCRIBEN)),
    db: AsyncSession = Depends(get_db),
):
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
    await db.commit()
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
