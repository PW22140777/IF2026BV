"""Fábrica de aplicaciones: todos los servicios arrancan igual.

crear_app() devuelve una app FastAPI que ya trae:
  - /health y /metrics
  - middleware de correlation id e IP
  - logs JSON, trazas y métricas
  - registro en Consul al arrancar y baja al apagarse
  - publicador de la outbox y consumidores de RabbitMQ como tareas de fondo
  - documentación Swagger en /docs/<servicio>
"""
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from . import consul, db
from .config import configuracion
from .observabilidad import configurar_logs, configurar_metricas, configurar_trazas, middleware_contexto

TareaFondo = Callable[[asyncio.Event], Awaitable[None]]


def crear_app(
    *,
    nombre: str,
    titulo: str,
    descripcion: str,
    routers: Sequence[APIRouter],
    publica_eventos: bool = True,
    consumidores: Sequence[TareaFondo] = (),
    al_iniciar: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    cfg = configuracion()
    configurar_logs(nombre)
    log = structlog.get_logger()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        detener = asyncio.Event()
        tareas: list[asyncio.Task] = []
        if al_iniciar:
            await al_iniciar()
        if cfg.rabbitmq_url:
            from .mensajeria import publicador_outbox   # importa aio-pika solo si se usa

            if publica_eventos:
                tareas.append(asyncio.create_task(publicador_outbox(detener)))
            tareas += [asyncio.create_task(c(detener)) for c in consumidores]
        id_consul = await consul.registrar(nombre, cfg.puerto, cfg.servicio_version)
        log.info("servicio_iniciado", servicio=nombre)
        yield
        detener.set()
        await consul.dar_de_baja(id_consul)
        for tarea in tareas:
            tarea.cancel()
        await asyncio.gather(*tareas, return_exceptions=True)
        await db.cerrar()

    app = FastAPI(
        title=titulo,
        description=descripcion,
        version=cfg.servicio_version,
        lifespan=ciclo_de_vida,
        docs_url=f"/docs/{nombre}",
        redoc_url=None,
        openapi_url=f"/docs/{nombre}/openapi.json",
        swagger_ui_parameters={"persistAuthorization": True},
    )
    app.middleware("http")(middleware_contexto)

    @app.exception_handler(IntegrityError)
    async def conflicto(_: Request, exc: IntegrityError):
        log.warning("conflicto_integridad", error=str(exc.orig))
        return JSONResponse(
            status_code=409,
            content={"detail": "El dato choca con otro registro (valor duplicado o referencia inválida)"},
        )

    @app.get("/health", include_in_schema=False)
    async def salud():
        async with db.fabrica_sesiones()() as sesion:
            await sesion.execute(text("SELECT 1"))
        return {"estado": "ok", "servicio": nombre}

    for router in routers:
        app.include_router(router, prefix="/api/v1")

    configurar_metricas(app)
    configurar_trazas(app, nombre, motor_sync=db.motor().sync_engine if cfg.database_url else None)
    return app
