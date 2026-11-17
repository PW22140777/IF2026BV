"""Logs estructurados, trazas distribuidas y métricas.

- Logs: JSON con correlation_id y trace_id en cada línea (structlog).
- Trazas: OpenTelemetry exportadas a Jaeger por OTLP/HTTP.
- Métricas: /metrics en formato Prometheus.
"""
import logging
import sys
import uuid

import structlog
from fastapi import FastAPI, Request

from . import contexto
from .config import configuracion


def _agregar_traza(_, __, evento: dict) -> dict:
    trace_id = contexto.trace_id_actual()
    if trace_id:
        evento["trace_id"] = trace_id
    return evento


def configurar_logs(servicio: str) -> None:
    nivel = getattr(logging, configuracion().log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=nivel)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _agregar_traza,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(nivel),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(servicio=servicio)


def configurar_trazas(app: FastAPI, servicio: str, motor_sync=None) -> None:
    endpoint = configuracion().otlp_endpoint
    if not endpoint:
        return
    log = structlog.get_logger()
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning("opentelemetry_no_instalado")
        return

    proveedor = TracerProvider(resource=Resource.create({"service.name": servicio}))
    proveedor.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
    trace.set_tracer_provider(proveedor)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")
    HTTPXClientInstrumentor().instrument()
    if motor_sync is not None:
        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument(engine=motor_sync)
        except ImportError:
            pass


def configurar_metricas(app: FastAPI) -> None:
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
    except ImportError:
        structlog.get_logger().warning("prometheus_instrumentator_no_instalado")
        return
    Instrumentator(excluded_handlers=["/health", "/metrics"]).instrument(app).expose(
        app, include_in_schema=False
    )


async def middleware_contexto(request: Request, call_next):
    """Toma (o crea) el correlation id y la IP del cliente para esta petición."""
    cid = request.headers.get("x-correlation-id") or str(uuid.uuid4())
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
    contexto.correlation_id.set(cid)
    contexto.ip_cliente.set(ip)
    structlog.contextvars.bind_contextvars(correlation_id=cid)
    try:
        respuesta = await call_next(request)
    finally:
        structlog.contextvars.unbind_contextvars("correlation_id")
    respuesta.headers["X-Correlation-Id"] = cid
    return respuesta
