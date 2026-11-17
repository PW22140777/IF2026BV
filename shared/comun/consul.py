"""Registro y descubrimiento de servicios con Consul."""
import asyncio
import itertools
import os
import socket
import time

import httpx
import structlog

from .config import configuracion

log = structlog.get_logger()


async def registrar(nombre: str, puerto: int, version: str) -> str | None:
    """Anuncia esta instancia en Consul con un health check HTTP."""
    url = configuracion().consul_url
    if not url:
        return None
    host = socket.gethostname()
    ip = socket.gethostbyname(host)
    servicio_id = f"{nombre}-{host}"
    cuerpo = {
        "ID": servicio_id,
        "Name": nombre,
        "Address": ip,
        "Port": puerto,
        "Tags": ["api", "v1"],
        "Meta": {"version": version},
        "Check": {
            "HTTP": f"http://{ip}:{puerto}/health",
            "Interval": "10s",
            "Timeout": "3s",
            # Si la instancia muere sin darse de baja, Consul la quita sola
            "DeregisterCriticalServiceAfter": "1m",
        },
    }
    for intento in range(10):
        try:
            async with httpx.AsyncClient(timeout=5) as cliente:
                r = await cliente.put(f"{url}/v1/agent/service/register", json=cuerpo)
                r.raise_for_status()
            log.info("registrado_en_consul", id=servicio_id, ip=ip)
            return servicio_id
        except httpx.HTTPError:
            log.warning("consul_no_disponible", intento=intento + 1)
            await asyncio.sleep(2)
    log.error("no_se_pudo_registrar_en_consul")
    return None


async def dar_de_baja(servicio_id: str | None) -> None:
    url = configuracion().consul_url
    if not url or not servicio_id:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as cliente:
            await cliente.put(f"{url}/v1/agent/service/deregister/{servicio_id}")
        log.info("baja_en_consul", id=servicio_id)
    except httpx.HTTPError:
        log.warning("no_se_pudo_dar_de_baja_en_consul")


class Descubridor:
    """Pregunta a Consul por las instancias sanas de un servicio y las reparte (round robin).

    Guarda la respuesta 5 segundos para no consultar Consul en cada petición.
    Si Consul no responde, usa el nombre DNS del contenedor (http://<nombre>:8000).
    """

    def __init__(self, cache_segundos: float = 5.0) -> None:
        self.cache_segundos = cache_segundos
        self._cache: dict[str, tuple[float, list[str]]] = {}
        self._contadores: dict[str, itertools.count] = {}

    async def _instancias(self, nombre: str) -> list[str]:
        guardado = self._cache.get(nombre)
        if guardado and time.monotonic() - guardado[0] < self.cache_segundos:
            return guardado[1]
        urls: list[str] = []
        consul = configuracion().consul_url
        if consul:
            try:
                async with httpx.AsyncClient(timeout=3) as cliente:
                    r = await cliente.get(f"{consul}/v1/health/service/{nombre}", params={"passing": "true"})
                    r.raise_for_status()
                    urls = [f"http://{s['Service']['Address']}:{s['Service']['Port']}" for s in r.json()]
            except httpx.HTTPError:
                log.warning("consul_no_responde", servicio=nombre)
        if not urls:
            # Sin Consul: nombre DNS del contenedor, o una URL fija para desarrollo local
            urls = [os.getenv(f"SERVICIO_{nombre.upper()}_URL", f"http://{nombre}:8000")]
        self._cache[nombre] = (time.monotonic(), urls)
        return urls

    async def url(self, nombre: str) -> str:
        urls = await self._instancias(nombre)
        contador = self._contadores.setdefault(nombre, itertools.count())
        return urls[next(contador) % len(urls)]

    def olvidar(self, nombre: str) -> None:
        """Descarta la caché (p. ej. si una instancia dejó de responder)."""
        self._cache.pop(nombre, None)
