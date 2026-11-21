"""archivos-service: guarda y entrega los archivos adjuntos (fotos, planos, PDF, evidencias).

Es el único que toca el almacén. Los demás servicios le hablan por la red interna con
`X-Token-Interno` (comun/almacenamiento.py) y guardan en la base solo la clave del archivo.
El navegador descarga por `/api/v1/archivos/descarga`, la única ruta pública: no lleva JWT,
lleva una firma que caduca.

ARCHIVOS_BACKEND elige dónde se guardan. "local" = un volumen de Docker (almacen.py). La rama
develop de IF2026B tiene la versión para S3; al unir ambas, se agrega aquí como otro backend
con la misma interfaz (guardar, ruta para leer / URL, borrar).
"""
import hmac
import os

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from comun.app import crear_app

from .almacen import TAMANO_MAXIMO_MB, AlmacenLocal, ErrorArchivo, url_firmada, validar_clave, verificar_firma

BACKEND = os.getenv("ARCHIVOS_BACKEND", "local").strip().lower()
DIRECTORIO = os.getenv("ARCHIVOS_DIRECTORIO", "/data/archivos")
SECRETO_FIRMA = os.getenv("ARCHIVOS_SECRETO_FIRMA", "")
TOKEN_INTERNO = os.getenv("ARCHIVOS_TOKEN_INTERNO", "")
SEGUNDOS_URL = int(os.getenv("ARCHIVOS_URL_EXPIRACION", "3600"))

if BACKEND != "local":
    raise RuntimeError(f"ARCHIVOS_BACKEND={BACKEND} no está disponible aquí; usa 'local' "
                       "(el de S3 está en la rama develop de IF2026B)")
if len(SECRETO_FIRMA) < 32 or len(TOKEN_INTERNO) < 32:
    raise RuntimeError("Define ARCHIVOS_SECRETO_FIRMA y ARCHIVOS_TOKEN_INTERNO (32 caracteres o más) en .env")

almacen = AlmacenLocal(DIRECTORIO)


def solo_servicios(x_token_interno: str | None = Header(default=None)) -> None:
    """Las rutas internas solo las usan los otros servicios (el gateway no las publica)."""
    if not x_token_interno or not hmac.compare_digest(x_token_interno, TOKEN_INTERNO):
        raise HTTPException(403, "Solo los servicios internos pueden usar esta ruta")


def _http(error: ErrorArchivo) -> HTTPException:
    return HTTPException(error.estado, str(error))


class Claves(BaseModel):
    claves: list[str] = Field(min_length=1, max_length=500)


router = APIRouter(prefix="/archivos", tags=["Archivos"])


@router.post("", summary="Guardar un archivo (interna)", dependencies=[Depends(solo_servicios)])
async def guardar(
    archivo: UploadFile = File(...),
    prefijo: str = Form(description="Carpeta, p. ej. edificios/7"),
    categoria: str = Form("documento", pattern="^(imagen|documento)$"),
    tamano_max_mb: int = Form(TAMANO_MAXIMO_MB, ge=1, le=50),
):
    # Se lee como máximo un byte más del límite: basta para saber si se pasó
    contenido = await archivo.read(tamano_max_mb * 1024 * 1024 + 1)
    try:
        guardado = almacen.guardar(prefijo, contenido, categoria, tamano_max_mb)
    except ErrorArchivo as e:
        raise _http(e)
    return {**guardado.__dict__, "url": url_firmada(SECRETO_FIRMA, guardado.clave, SEGUNDOS_URL)}


@router.post("/urls", summary="URL de descarga de varios archivos (interna)", dependencies=[Depends(solo_servicios)])
async def urls(datos: Claves):
    try:
        return {"urls": {c: url_firmada(SECRETO_FIRMA, validar_clave(c), SEGUNDOS_URL) for c in datos.claves}}
    except ErrorArchivo as e:
        raise _http(e)


@router.delete("", status_code=204, summary="Borrar un archivo (interna)", dependencies=[Depends(solo_servicios)])
async def borrar(clave: str = Query()):
    try:
        almacen.borrar(clave)
    except ErrorArchivo as e:
        raise _http(e)


@router.get("/descarga", summary="Descargar con un enlace firmado (pública, caduca)")
async def descarga(clave: str = Query(), expira: int = Query(), firma: str = Query()):
    try:
        verificar_firma(SECRETO_FIRMA, clave, expira, firma)
        ruta, tipo = almacen.ruta_para_leer(clave)
    except ErrorArchivo as e:
        raise _http(e)
    return FileResponse(ruta, media_type=tipo, content_disposition_type="inline", headers={
        "X-Content-Type-Options": "nosniff",          # el navegador no adivina otro tipo
        "Cache-Control": "private, max-age=300",
    })


app = crear_app(
    nombre="archivos",
    titulo="Servicio de archivos",
    descripcion="Guarda los adjuntos en un volumen local y los entrega con enlaces firmados que caducan.",
    routers=[router],
    publica_eventos=False,
)
