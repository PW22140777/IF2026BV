"""Configuración leída de variables de entorno (o de un archivo .env)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Identidad del servicio
    servicio_nombre: str = "servicio"
    servicio_version: str = "1.0.0"
    puerto: int = 8000

    # Base de datos única, p. ej. postgresql+psycopg://usuario:clave@postgres:5432/escuela
    database_url: str = ""
    db_pool_size: int = 5        # conexiones que cada servicio mantiene abiertas
    db_max_overflow: int = 5     # conexiones extra en momentos de carga

    # JWT
    jwt_secret: str = "cambia-este-secreto-en-el-archivo-env"
    jwt_algoritmo: str = "HS256"

    # Sesiones: vencen tras 30 min sin peticiones y, como máximo, 4 h después de iniciar sesión
    sesion_inactividad_minutos: int = 30
    sesion_maxima_horas: int = 4

    # Infraestructura (vacío = deshabilitado, útil para pruebas locales)
    rabbitmq_url: str = ""          # amqp://usuario:clave@rabbitmq:5672/
    consul_url: str = ""            # http://consul:8500
    otlp_endpoint: str = ""         # http://jaeger:4318

    log_level: str = "INFO"


@lru_cache
def configuracion() -> Configuracion:
    return Configuracion()
