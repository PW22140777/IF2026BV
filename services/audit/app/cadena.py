"""Cadena de hashes y firma digital del historial.

Cada registro se convierte a un JSON canónico (llaves ordenadas, sin
espacios). Su hash es SHA-256(hash_anterior + JSON canónico), así que
modificar, borrar o reordenar cualquier registro rompe todos los
siguientes. Además, cada hash se firma con Ed25519: sin la llave privada
nadie puede fabricar un registro válido.
"""
import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

HASH_INICIAL = "0" * 64

# Campos que se protegen con el hash (todo lo que describe la acción)
CAMPOS = (
    "evento_id", "fecha", "usuario_id", "usuario_nombre", "rol", "ip", "accion",
    "recurso", "recurso_id", "antes", "despues", "motivo", "correlation_id", "trace_id",
)


def normalizar_fecha(valor: str | datetime) -> str:
    """Misma representación al guardar y al verificar: UTC con microsegundos."""
    fecha = datetime.fromisoformat(valor) if isinstance(valor, str) else valor
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return fecha.astimezone(timezone.utc).isoformat(timespec="microseconds")


def canonico(registro: dict[str, Any]) -> str:
    datos = {campo: registro.get(campo) for campo in CAMPOS}
    datos["evento_id"] = str(datos["evento_id"])
    datos["fecha"] = normalizar_fecha(datos["fecha"])
    return json.dumps(datos, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def calcular_hash(hash_anterior: str, registro: dict[str, Any]) -> str:
    return hashlib.sha256((hash_anterior + canonico(registro)).encode("utf-8")).hexdigest()


def firmar(llave: Ed25519PrivateKey, hash_hex: str) -> str:
    return base64.b64encode(llave.sign(hash_hex.encode())).decode()


def firma_valida(publica: Ed25519PublicKey, hash_hex: str, firma_b64: str) -> bool:
    try:
        publica.verify(base64.b64decode(firma_b64), hash_hex.encode())
        return True
    except (InvalidSignature, ValueError):
        return False


def diferencias(antes: dict | None, despues: dict | None) -> list[dict[str, Any]]:
    """Lista de campos que cambiaron, para mostrar el historial de forma legible."""
    antes, despues = antes or {}, despues or {}
    ignorar = {"modificado_en", "modificado_por", "creado_en", "creado_por"}
    cambios = []
    for campo in sorted(set(antes) | set(despues)):
        if campo in ignorar:
            continue
        if campo == "propiedades":
            pa, pd = antes.get(campo) or {}, despues.get(campo) or {}
            for clave in sorted(set(pa) | set(pd)):
                if pa.get(clave) != pd.get(clave):
                    cambios.append({"campo": f"propiedades.{clave}", "antes": pa.get(clave),
                                    "despues": pd.get(clave)})
        elif antes.get(campo) != despues.get(campo):
            cambios.append({"campo": campo, "antes": antes.get(campo), "despues": despues.get(campo)})
    return cambios
