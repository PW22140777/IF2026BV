"""Datos de la petición en curso, accesibles desde cualquier función.

Se usan variables de contexto (contextvars) para que cada petición
concurrente tenga sus propios valores sin pasarlos como parámetro.
"""
from contextvars import ContextVar

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
ip_cliente: ContextVar[str | None] = ContextVar("ip_cliente", default=None)


def trace_id_actual() -> str | None:
    """Devuelve el trace_id de OpenTelemetry de la operación actual, si existe."""
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover
        return None
    contexto = trace.get_current_span().get_span_context()
    if not contexto.is_valid:
        return None
    return format(contexto.trace_id, "032x")
