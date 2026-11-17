"""Registro de cambios como eventos (patrón Transactional Outbox).

Cada alta, modificación, eliminación o restauración se guarda en la
tabla `outbox` dentro de la MISMA transacción que el cambio. Si la
transacción falla, el evento tampoco existe; si se confirma, el evento
se publicará en RabbitMQ aunque RabbitMQ esté caído en ese momento.
audit-service lo recibe y lo agrega al historial firmado.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from . import contexto
from .config import configuracion
from .modelos import Outbox
from .seguridad import UsuarioToken

# Acción -> participio usado en el nombre del evento (recurso.accion.v1)
PARTICIPIOS = {
    "CREAR": "creado",
    "MODIFICAR": "modificado",
    "ELIMINAR": "eliminado",
    "RESTAURAR": "restaurado",
    "LOGIN": "iniciada",
    "LOGIN_FALLIDO": "fallida",
    "LOGOUT": "cerrada",
}

VERSION_EVENTOS = "v1"


def tipo_evento(recurso: str, accion: str) -> str:
    """('EDIFICIO', 'CREAR') -> 'edificio.creado.v1'"""
    return f"{recurso.lower()}.{PARTICIPIOS[accion]}.{VERSION_EVENTOS}"


def _cabeceras_de_traza() -> dict[str, str]:
    """traceparent de la operación actual, para continuar la traza en el consumidor."""
    cabeceras: dict[str, str] = {}
    try:
        from opentelemetry.propagate import inject

        inject(cabeceras)
    except ImportError:  # pragma: no cover
        pass
    return cabeceras


async def registrar_evento(
    db: AsyncSession,
    *,
    accion: str,
    recurso: str,
    recurso_id: int | None,
    usuario: UsuarioToken | None,
    antes: dict[str, Any] | None = None,
    despues: dict[str, Any] | None = None,
    motivo: str | None = None,
) -> uuid.UUID:
    """Agrega el evento a la outbox. El llamador debe hacer commit."""
    evento_id = uuid.uuid4()
    cid = contexto.correlation_id.get() or str(uuid.uuid4())
    cuerpo = {
        "evento_id": str(evento_id),
        "tipo": tipo_evento(recurso, accion),
        "fecha": datetime.now(timezone.utc).isoformat(),
        "origen": configuracion().servicio_nombre,
        "accion": accion,
        "recurso": recurso,
        "recurso_id": recurso_id,
        "usuario_id": usuario.id if usuario else None,
        "usuario_nombre": usuario.nombre if usuario else None,
        "rol": usuario.rol if usuario else None,
        "ip": contexto.ip_cliente.get(),
        "antes": antes,
        "despues": despues,
        "motivo": motivo,
        "correlation_id": cid,
        "trace_id": contexto.trace_id_actual(),
    }
    cabeceras = {"correlation_id": cid, **_cabeceras_de_traza()}
    db.add(Outbox(
        evento_id=evento_id,
        tipo=cuerpo["tipo"],
        origen=cuerpo["origen"],
        cuerpo=cuerpo,
        cabeceras=cabeceras,
    ))
    return evento_id
