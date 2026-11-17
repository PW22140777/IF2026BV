"""Quita de `propiedades` de cada elemento de inventario las claves que su tipo no define.

Desde que existe el catálogo `tipos_elemento`, cada tipo dice qué propiedades lleva.
Las que se capturaron antes con otro nombre o para otro tipo ya no se muestran en
el formulario; este script las quita para dejar el inventario limpio.

Uso, con la misma base que usa el servicio (la de .env):

    docker compose run --rm --no-deps inmuebles python -m app.limpiar_propiedades            # solo muestra
    docker compose run --rm --no-deps inmuebles python -m app.limpiar_propiedades --aplicar  # guarda

- No borra filas ni columnas: solo cambia la columna JSONB `propiedades`.
- Cada elemento modificado deja un evento MODIFICAR en el historial, hecho por el sistema,
  con los valores quitados en «antes» (patrón outbox, igual que la API).
- Todo va en una sola transacción: o se limpian todos los elementos o ninguno.
- Los elementos cuyo tipo no está en el catálogo no se tocan.
"""
import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from comun.db import fabrica_sesiones
from comun.historial import registrar_evento
from comun.modelos import ElementoInventario, TipoElemento
from comun.seguridad import SISTEMA

from .esquemas import ElementoSalida

MOTIVO = "Limpieza: propiedades que su tipo de elemento no define"


def foto(elemento: ElementoInventario) -> dict:
    """Estado completo del elemento, igual que el que guarda la API en el historial."""
    return ElementoSalida.model_validate(elemento).model_dump(mode="json")


async def limpiar(aplicar: bool) -> int:
    async with fabrica_sesiones()() as db:
        # Claves que define cada tipo activo: {"AIRE_ACONDICIONADO": {"btu", "refrigerante", ...}}
        tipos = (await db.execute(select(TipoElemento).where(TipoElemento.eliminado_en.is_(None)))).scalars()
        definidas = {t.clave: {d["clave"] for d in t.propiedades_definidas} for t in tipos}

        elementos = (await db.execute(
            select(ElementoInventario).where(ElementoInventario.eliminado_en.is_(None)).order_by(ElementoInventario.id)
        )).scalars().all()

        cambiados = 0
        for elemento in elementos:
            if elemento.tipo not in definidas:
                continue
            sobran = sorted(set(elemento.propiedades or {}) - definidas[elemento.tipo])
            if not sobran:
                continue
            cambiados += 1
            print(f"Elemento {elemento.id} ({elemento.tipo}): se quita {', '.join(sobran)}")
            if aplicar:
                antes = foto(elemento)
                # Diccionario nuevo para que SQLAlchemy detecte el cambio en la columna JSONB
                elemento.propiedades = {k: v for k, v in elemento.propiedades.items() if k not in sobran}
                elemento.modificado_en = datetime.now(timezone.utc)
                elemento.modificado_por = None   # acción automática del sistema
                await db.flush()
                await db.refresh(elemento)
                await registrar_evento(db, accion="MODIFICAR", recurso="INVENTARIO", recurso_id=elemento.id,
                                       usuario=SISTEMA, antes=antes, despues=foto(elemento), motivo=MOTIVO)

        if aplicar:
            await db.commit()
            print(f"Listo: {cambiados} elemento(s) limpiados; el historial los recibirá en unos segundos.")
        else:
            print(f"{cambiados} elemento(s) tienen propiedades que su tipo no define. "
                  "No se cambió nada; agrega --aplicar para guardar.")
        return cambiados


if __name__ == "__main__":
    argumentos = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    argumentos.add_argument("--aplicar", action="store_true", help="guarda los cambios (sin esto solo muestra)")
    asyncio.run(limpiar(argumentos.parse_args().aplicar))
