"""Llave de firma Ed25519 de audit-service.

La primera vez que arranca, el servicio genera la llave y la guarda en
un volumen de Docker (LLAVE_FIRMA_PATH). Solo este servicio la tiene.
La llave pública se puede entregar a un auditor externo para verificar.
"""
import hashlib
import os
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

RUTA = Path(os.getenv("LLAVE_FIRMA_PATH", "/data/llaves/audit_ed25519.pem"))


@lru_cache
def llave_privada() -> Ed25519PrivateKey:
    if not RUTA.exists():
        RUTA.parent.mkdir(parents=True, exist_ok=True)
        nueva = Ed25519PrivateKey.generate()
        RUTA.write_bytes(nueva.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        RUTA.chmod(0o600)
    llave = serialization.load_pem_private_key(RUTA.read_bytes(), password=None)
    assert isinstance(llave, Ed25519PrivateKey)
    return llave


def llave_publica() -> Ed25519PublicKey:
    return llave_privada().public_key()


def llave_publica_pem() -> str:
    return llave_publica().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def llave_id() -> str:
    """Identificador corto de la llave: permite rotarla en el futuro."""
    crudo = llave_publica().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(crudo).hexdigest()[:16]
