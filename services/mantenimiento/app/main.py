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

from .esquemas import PlantillaActualizar, PlantillaCrear, PlantillaSalida

log = structlog.get_logger()

# Tabla de cada recurso: solo se lee, para saber si existe y a qué plantillas aplica
ABIERTAS = ("PROGRAMADA", "EN_CURSO")


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


app = crear_app(
    nombre="mantenimiento",
    titulo="mantenimiento-service",
    descripcion="Plantillas y órdenes de mantenimiento: por estado, periódicas o manuales, con técnicos asignados.",
    routers=[router_plantillas],
)
