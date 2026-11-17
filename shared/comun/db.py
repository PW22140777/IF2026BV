"""Conexión a la base de datos única (PostgreSQL) con SQLAlchemy asíncrono."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import configuracion

_motor: AsyncEngine | None = None
_fabrica: async_sessionmaker[AsyncSession] | None = None


def motor() -> AsyncEngine:
    global _motor, _fabrica
    if _motor is None:
        cfg = configuracion()
        _motor = create_async_engine(
            cfg.database_url,
            # Cada servicio guarda hasta pool_size conexiones abiertas y abre hasta max_overflow
            # más en momentos de carga. En una base compartida conviene bajarlos (ver .env.example).
            pool_size=cfg.db_pool_size,
            max_overflow=cfg.db_max_overflow,
            pool_pre_ping=True,
            # Sin sentencias preparadas: con el modo transacción de Supabase (puerto 6543) cada
            # transacción puede caer en otra conexión real, donde la sentencia preparada no existe
            connect_args={"prepare_threshold": None},
        )
        _fabrica = async_sessionmaker(_motor, expire_on_commit=False)
    return _motor


def fabrica_sesiones() -> async_sessionmaker[AsyncSession]:
    motor()
    assert _fabrica is not None
    return _fabrica


async def get_db() -> AsyncIterator[AsyncSession]:
    """Dependencia de FastAPI: una sesión por petición."""
    async with fabrica_sesiones()() as sesion:
        yield sesion


async def cerrar() -> None:
    global _motor, _fabrica
    if _motor is not None:
        await _motor.dispose()
    _motor = None
    _fabrica = None
