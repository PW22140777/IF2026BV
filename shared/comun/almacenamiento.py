"""Cliente de archivos-service para los demás servicios (guardar, URL de descarga, borrar).

Los servicios no tocan el almacén: le piden a archivos-service por la red interna, con
`X-Token-Interno`, y guardan en la base solo la clave que les devuelve. Así, cambiar el
almacén (volumen local, S3...) no cambia a inmuebles ni a mantenimiento.
"""
import os

import httpx
import structlog
from fastapi import HTTPException, UploadFile

from . import consul, contexto

log = structlog.get_logger()
_descubridor = consul.Descubridor()


def _cabeceras() -> dict[str, str]:
    cabeceras = {"X-Token-Interno": os.getenv("ARCHIVOS_TOKEN_INTERNO", "")}
    if cid := contexto.correlation_id.get():
        cabeceras["X-Correlation-Id"] = cid   # la traza sigue al archivo hasta el almacén
    return cabeceras


async def _llamar(metodo: str, ruta: str, **kwargs) -> httpx.Response:
    base = await _descubridor.url("archivos")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as cliente:
            r = await cliente.request(metodo, f"{base}/api/v1/archivos{ruta}", headers=_cabeceras(), **kwargs)
    except httpx.HTTPError:
        _descubridor.olvidar("archivos")
        raise HTTPException(503, "El servicio de archivos no está disponible; intenta de nuevo en unos minutos")
    if r.status_code >= 400:
        try:
            detalle = r.json().get("detail")
        except ValueError:
            detalle = None
        # Los errores del archivo (tipo, tamaño) se pasan tal cual a quien lo subió
        raise HTTPException(r.status_code if r.status_code < 500 else 502,
                            detalle if isinstance(detalle, str) else "No se pudo procesar el archivo")
    return r


async def guardar(prefijo: str, archivo: UploadFile, categoria: str = "documento") -> dict:
    """Devuelve clave, tipo_mime, tamano_bytes, sha256 y una URL de descarga."""
    contenido = await archivo.read()
    r = await _llamar("POST", "", data={"prefijo": prefijo, "categoria": categoria},
                      files={"archivo": (archivo.filename or "archivo", contenido, "application/octet-stream")})
    return r.json()


async def urls(claves: list[str]) -> dict[str, str]:
    """URL de descarga firmadas, en una sola llamada; si el almacén no responde, sin URL."""
    if not claves:
        return {}
    try:
        return (await _llamar("POST", "/urls", json={"claves": claves})).json()["urls"]
    except HTTPException:
        log.warning("sin_urls_de_archivos", cuantos=len(claves))
        return {}


async def borrar(clave: str) -> None:
    await _llamar("DELETE", "", params={"clave": clave})
