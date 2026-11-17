"""Evita procesar dos veces el mismo evento.

RabbitMQ garantiza entrega "al menos una vez": un mensaje puede llegar
repetido (p. ej. si el consumidor se reinicia antes de confirmar).
"""
import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .modelos import EventoProcesado


async def marcar_procesado(db: AsyncSession, consumidor_nombre: str, evento_id: str) -> bool:
    """Registra que este consumidor procesó el evento.

    Devuelve False si ya se había procesado (RabbitMQ puede entregar un
    mensaje más de una vez). Debe llamarse dentro de la transacción del
    manejador para que ambas cosas se confirmen juntas.
    """
    resultado = await db.execute(
        insert(EventoProcesado)
        .values(consumidor=consumidor_nombre, evento_id=uuid.UUID(evento_id))
        .on_conflict_do_nothing()
        .returning(EventoProcesado.evento_id)
    )
    return resultado.first() is not None
