"""Evidencias de un mantenimiento (fotos, PDF): ESQUELETO, todavía no funciona.

Se dejará funcionando cuando el equipo defina cómo se guardarán los archivos
(la rama IFD22140755 usa S3; se planea cambiarlo). Para conectarlo:

  1. Implementar una clase con la interfaz de `AlmacenEvidencias`.
  2. Crear la tabla de la ficha de cada archivo (orden, nombre, tipo, tamaño, ubicación,
     quién lo subió). Los archivos adjuntos sí se pueden borrar físicamente.
  3. Cambiar `almacen()` para que devuelva esa implementación.

Mientras tanto, las rutas responden 501 con un mensaje claro y la interfaz muestra
el botón deshabilitado.
"""
from typing import Protocol

TIPOS_PERMITIDOS = ("image/jpeg", "image/png", "image/webp", "application/pdf")
TAMANO_MAXIMO_BYTES = 10 * 1024 * 1024
MENSAJE_NO_DISPONIBLE = ("Las evidencias todavía no están disponibles: falta definir dónde se guardarán los "
                         "archivos. Por ahora registra lo observado en las notas de la orden")


class AlmacenEvidencias(Protocol):
    """Lo que necesita el servicio para guardar y entregar los archivos de una orden."""

    async def guardar(self, orden_id: int, nombre: str, tipo_mime: str, contenido: bytes) -> str:
        """Guarda el archivo y devuelve su ubicación."""

    async def url_descarga(self, ubicacion: str) -> str:
        """Devuelve una URL temporal para descargarlo."""

    async def borrar(self, ubicacion: str) -> None:
        """Borra el archivo."""


def almacen() -> AlmacenEvidencias | None:
    """Sin almacén configurado todavía."""
    return None
