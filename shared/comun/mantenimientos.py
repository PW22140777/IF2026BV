"""Aplicar al recurso el estado que deja un mantenimiento.

mantenimiento-service no escribe las tablas de los recursos: al iniciar o terminar una
orden publica `orden_mantenimiento.iniciada.v1` / `.terminada.v1` con `estado_recurso_nuevo`.
inmuebles-service (edificios, áreas, inventario) y servicios-service (servicios básicos)
escuchan esos eventos y cambian el estado con este manejador, dejando su propio evento en
el historial a nombre del sistema.
"""
from datetime import datetime, timezone
from typing import Any

from .db import fabrica_sesiones
from .historial import registrar_evento
from .idempotencia import marcar_procesado
from .seguridad import SISTEMA

PATRONES = ["orden_mantenimiento.iniciada.v1", "orden_mantenimiento.terminada.v1"]


def manejador_de_estados(consumidor_nombre: str, recursos: dict[str, tuple[type, type, tuple[str, ...]]]):
    """Crea el manejador para los recursos de un servicio.

    recursos = {"INVENTARIO": (ElementoInventario, ElementoSalida, ("BUENO", "REGULAR", ...)), ...}
    """

    async def aplicar(evento: dict[str, Any]) -> None:
        despues = evento.get("despues") or {}
        recurso, nuevo = despues.get("recurso"), despues.get("estado_recurso_nuevo")
        if recurso not in recursos:
            return       # el recurso es de otro servicio
        modelo, Salida, validos = recursos[recurso]
        async with fabrica_sesiones()() as db:
            async with db.begin():
                if not await marcar_procesado(db, consumidor_nombre, evento["evento_id"]):
                    return
                if not nuevo or nuevo not in validos:
                    return
                objeto = await db.get(modelo, despues["recurso_id"])
                if objeto is None or objeto.eliminado_en is not None or objeto.estado == nuevo:
                    return
                antes = Salida.model_validate(objeto).model_dump(mode="json")
                objeto.estado = nuevo
                objeto.modificado_en = datetime.now(timezone.utc)
                objeto.modificado_por = None    # acción automática del sistema
                await db.flush()
                await db.refresh(objeto)
                que = "iniciado" if evento.get("accion") == "INICIAR" else "terminado"
                resultado = despues.get("resultado")
                motivo = f"Mantenimiento #{despues['id']} {que}" + (
                    f": {resultado.lower().replace('_', ' ')}" if resultado else "")
                await registrar_evento(db, accion="MODIFICAR", recurso=recurso, recurso_id=objeto.id, usuario=SISTEMA,
                                       antes=antes, despues=Salida.model_validate(objeto).model_dump(mode="json"),
                                       motivo=motivo)

    return aplicar
