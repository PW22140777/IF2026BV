"""Publicación y consumo de eventos con RabbitMQ (aio-pika).

Topología:
  exchange "eventos" (topic)  --clave recurso.accion.v1-->  colas de cada consumidor
  exchange "eventos.dlx" (fanout)  -->  cola "eventos.fallidos" (mensajes que fallaron 3 veces)
"""
import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import aio_pika
import aio_pika.abc
import structlog
from sqlalchemy import select

from .config import configuracion
from .db import fabrica_sesiones
from .modelos import Outbox

log = structlog.get_logger()

EXCHANGE = "eventos"
EXCHANGE_FALLIDOS = "eventos.dlx"
COLA_FALLIDOS = "eventos.fallidos"
MAX_REINTENTOS = 3

Manejador = Callable[[dict[str, Any]], Awaitable[None]]


async def _esperar(detener: asyncio.Event, segundos: float) -> None:
    try:
        await asyncio.wait_for(detener.wait(), timeout=segundos)
    except asyncio.TimeoutError:
        pass


async def _declarar_topologia(canal: aio_pika.abc.AbstractChannel) -> aio_pika.abc.AbstractExchange:
    exchange = await canal.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
    dlx = await canal.declare_exchange(EXCHANGE_FALLIDOS, aio_pika.ExchangeType.FANOUT, durable=True)
    fallidos = await canal.declare_queue(COLA_FALLIDOS, durable=True)
    await fallidos.bind(dlx)
    return exchange


# ----------------------------------------------------------------- publicar
async def _enviar_pendientes(exchange: aio_pika.abc.AbstractExchange, lote: int = 50) -> int:
    """Publica los eventos de la outbox que aún no se han enviado."""
    async with fabrica_sesiones()() as db:
        async with db.begin():
            filas = (await db.execute(
                select(Outbox)
                .where(Outbox.enviado_en.is_(None))
                .order_by(Outbox.id)
                .limit(lote)
                .with_for_update(skip_locked=True)   # varias réplicas no envían el mismo evento
            )).scalars().all()
            for fila in filas:
                await exchange.publish(
                    aio_pika.Message(
                        body=json.dumps(fila.cuerpo, ensure_ascii=False).encode(),
                        content_type="application/json",
                        message_id=str(fila.evento_id),
                        correlation_id=fila.cabeceras.get("correlation_id"),
                        headers=fila.cabeceras,
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    ),
                    routing_key=fila.tipo,
                )
                fila.enviado_en = datetime.now(timezone.utc)
            return len(filas)


async def publicador_outbox(detener: asyncio.Event) -> None:
    """Tarea de fondo: revisa la outbox cada segundo y publica en RabbitMQ."""
    url = configuracion().rabbitmq_url
    while not detener.is_set():
        try:
            conexion = await aio_pika.connect_robust(url)
            async with conexion:
                canal = await conexion.channel(publisher_confirms=True)
                exchange = await _declarar_topologia(canal)
                log.info("publicador_outbox_listo")
                while not detener.is_set():
                    if await _enviar_pendientes(exchange) == 0:
                        await _esperar(detener, 1.0)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("publicador_outbox_error")
            await _esperar(detener, 5.0)


# ----------------------------------------------------------------- consumir
def _texto(valor: Any) -> Any:
    return valor.decode() if isinstance(valor, bytes) else valor


async def _procesar(mensaje: aio_pika.abc.AbstractIncomingMessage, manejador: Manejador,
                    canal: aio_pika.abc.AbstractChannel, cola: str) -> None:
    cabeceras = {k: _texto(v) for k, v in (mensaje.headers or {}).items()}
    structlog.contextvars.bind_contextvars(correlation_id=cabeceras.get("correlation_id"))

    # Continúa la traza que empezó en el servicio que publicó el evento
    token = None
    span = None
    try:
        from opentelemetry import context as otel_context, trace
        from opentelemetry.propagate import extract

        token = otel_context.attach(extract({k: str(v) for k, v in cabeceras.items()}))
        span = trace.get_tracer("mensajeria").start_span(f"consumir {mensaje.routing_key}",
                                                         kind=trace.SpanKind.CONSUMER)
        span_ctx = trace.set_span_in_context(span)
        otel_context.detach(token)
        token = otel_context.attach(span_ctx)
    except ImportError:  # pragma: no cover
        pass

    try:
        await manejador(json.loads(mensaje.body))
        await mensaje.ack()
    except Exception:
        intentos = int(cabeceras.get("x-reintentos", 0))
        if intentos < MAX_REINTENTOS:
            log.warning("evento_reintento", tipo=mensaje.routing_key, intento=intentos + 1, exc_info=True)
            await asyncio.sleep(2 ** intentos)
            await canal.default_exchange.publish(
                aio_pika.Message(
                    body=mensaje.body,
                    content_type=mensaje.content_type,
                    message_id=mensaje.message_id,
                    correlation_id=mensaje.correlation_id,
                    headers={**cabeceras, "x-reintentos": intentos + 1},
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=cola,   # directo a la cola del consumidor
            )
            await mensaje.ack()
        else:
            log.error("evento_a_cola_de_fallidos", tipo=mensaje.routing_key, exc_info=True)
            await mensaje.reject(requeue=False)   # va a eventos.fallidos
    finally:
        if span is not None:
            span.end()
        if token is not None:
            from opentelemetry import context as otel_context

            otel_context.detach(token)
        structlog.contextvars.unbind_contextvars("correlation_id")


def consumidor(cola: str, patrones: list[str], manejador: Manejador):
    """Crea una tarea de fondo que consume `cola` enlazada a los `patrones` dados."""

    async def ejecutar(detener: asyncio.Event) -> None:
        url = configuracion().rabbitmq_url
        while not detener.is_set():
            try:
                conexion = await aio_pika.connect_robust(url)
                async with conexion:
                    canal = await conexion.channel()
                    await canal.set_qos(prefetch_count=10)
                    exchange = await _declarar_topologia(canal)
                    q = await canal.declare_queue(
                        cola, durable=True, arguments={"x-dead-letter-exchange": EXCHANGE_FALLIDOS}
                    )
                    for patron in patrones:
                        await q.bind(exchange, routing_key=patron)
                    log.info("consumidor_listo", cola=cola, patrones=patrones)
                    async with q.iterator() as mensajes:
                        async for mensaje in mensajes:
                            await _procesar(mensaje, manejador, canal, cola)
                            if detener.is_set():
                                break
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("consumidor_error", cola=cola)
                await _esperar(detener, 5.0)

    return ejecutar
