"""Almacén de archivos en un volumen local (Docker) y las reglas que no dependen de dónde se guarden.

- El tipo de archivo se decide por sus primeros bytes ("número mágico"), no por el nombre ni
  por lo que diga el navegador: así nadie sube un HTML o un SVG disfrazado de imagen.
- Cada archivo se guarda con su SHA-256 como nombre: el mismo archivo no se repite dentro de
  una carpeta y se puede comprobar que nadie lo cambió.
- Las URL de descarga se firman con HMAC y caducan, como las URL prefirmadas de S3: un
  <img src> no puede mandar el JWT, así que el permiso viaja en la URL y vence solo.

Este módulo no toca la base ni la red: se prueba sin Docker (tests/test_archivos.py).
"""
import hashlib
import hmac
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

# Firmas de los formatos permitidos: tipo MIME -> extensión
EXTENSIONES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}
TIPOS_POR_EXTENSION = {ext: tipo for tipo, ext in EXTENSIONES.items()}
CATEGORIAS = {
    "imagen": ("image/jpeg", "image/png", "image/webp"),
    "documento": ("image/jpeg", "image/png", "image/webp", "application/pdf"),
}
TAMANO_MAXIMO_MB = 10

# prefijo/<sha256>.<ext>; el prefijo solo lleva minúsculas, dígitos, _ y - separados por /
CLAVE_VALIDA = re.compile(r"^(?:[a-z0-9_-]+/){1,6}[0-9a-f]{64}\.(?:jpg|png|webp|pdf)$")
PREFIJO_VALIDO = re.compile(r"^(?:[a-z0-9_-]+/){0,5}[a-z0-9_-]+$")


class ErrorArchivo(Exception):
    """Problema con el archivo; `estado` es el código HTTP que se responde."""

    def __init__(self, estado: int, mensaje: str):
        super().__init__(mensaje)
        self.estado = estado


def detectar_tipo(contenido: bytes) -> str | None:
    """Tipo MIME según los primeros bytes; None si no es un formato permitido."""
    if contenido.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contenido.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "image/webp"
    if contenido.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def validar_clave(clave: str) -> str:
    if not CLAVE_VALIDA.fullmatch(clave or ""):
        raise ErrorArchivo(400, "La clave del archivo no es válida")
    return clave


def firmar(secreto: str, clave: str, expira: int) -> str:
    return hmac.new(secreto.encode(), f"{clave}|{expira}".encode(), hashlib.sha256).hexdigest()


def url_firmada(secreto: str, clave: str, segundos: int, ahora: float | None = None) -> str:
    """Ruta pública de descarga (pasa por el gateway); vale `segundos` a partir de ahora."""
    expira = int((ahora if ahora is not None else time.time()) + segundos)
    consulta = urlencode({"clave": clave, "expira": expira, "firma": firmar(secreto, clave, expira)})
    return f"/api/v1/archivos/descarga?{consulta}"


def verificar_firma(secreto: str, clave: str, expira: int, firma: str, ahora: float | None = None) -> None:
    validar_clave(clave)
    if expira < (ahora if ahora is not None else time.time()):
        raise ErrorArchivo(403, "El enlace del archivo caducó; vuelve a abrir la página para obtener uno nuevo")
    if not hmac.compare_digest(firmar(secreto, clave, expira), firma or ""):
        raise ErrorArchivo(403, "El enlace del archivo no es válido")


@dataclass(frozen=True)
class Guardado:
    clave: str
    tipo_mime: str
    tamano_bytes: int
    sha256: str


class AlmacenLocal:
    """Guarda los archivos en una carpeta (en Docker, un volumen con nombre)."""

    def __init__(self, directorio: str | os.PathLike):
        self.base = Path(directorio).resolve()

    def _ruta(self, clave: str) -> Path:
        ruta = (self.base / validar_clave(clave)).resolve()
        # Defensa extra: la ruta final nunca sale de la carpeta base
        if self.base not in ruta.parents:
            raise ErrorArchivo(400, "La clave del archivo no es válida")
        return ruta

    def guardar(self, prefijo: str, contenido: bytes, categoria: str = "documento",
                tamano_max_mb: int = TAMANO_MAXIMO_MB) -> Guardado:
        if not PREFIJO_VALIDO.fullmatch(prefijo or ""):
            raise ErrorArchivo(400, "La carpeta del archivo no es válida")
        if not contenido:
            raise ErrorArchivo(422, "El archivo está vacío")
        if len(contenido) > tamano_max_mb * 1024 * 1024:
            raise ErrorArchivo(413, f"El archivo pesa más de {tamano_max_mb} MB; redúcelo e intenta de nuevo")
        tipo = detectar_tipo(contenido)
        permitidos = CATEGORIAS.get(categoria, CATEGORIAS["documento"])
        if tipo not in permitidos:
            nombres = "JPG, PNG o WebP" if categoria == "imagen" else "JPG, PNG, WebP o PDF"
            raise ErrorArchivo(422, f"Solo se aceptan archivos {nombres}")
        sha = hashlib.sha256(contenido).hexdigest()
        clave = f"{prefijo}/{sha}{EXTENSIONES[tipo]}"
        ruta = self._ruta(clave)
        if not ruta.exists():
            ruta.parent.mkdir(parents=True, exist_ok=True)
            # Se escribe a un temporal y se renombra: nunca queda un archivo a medias
            temporal = ruta.with_suffix(ruta.suffix + ".tmp")
            temporal.write_bytes(contenido)
            temporal.replace(ruta)
        return Guardado(clave=clave, tipo_mime=tipo, tamano_bytes=len(contenido), sha256=sha)

    def ruta_para_leer(self, clave: str) -> tuple[Path, str]:
        ruta = self._ruta(clave)
        if not ruta.is_file():
            raise ErrorArchivo(404, "El archivo ya no existe")
        return ruta, TIPOS_POR_EXTENSION[ruta.suffix]

    def borrar(self, clave: str) -> None:
        """Los adjuntos sí se borran físicamente; su ficha queda en la base con borrado lógico."""
        ruta = self._ruta(clave)
        ruta.unlink(missing_ok=True)
