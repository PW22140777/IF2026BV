"""Pruebas unitarias de la cadena de hashes y la firma (no necesitan Docker).

    pip install pytest cryptography
    pytest tests/test_cadena.py
"""
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "audit"))
from app.cadena import HASH_INICIAL, calcular_hash, diferencias, firma_valida, firmar  # noqa: E402


def evento(n, **cambios):
    base = {
        "evento_id": f"00000000-0000-0000-0000-00000000000{n}",
        "fecha": "2026-10-31T18:00:00-06:00",
        "usuario_id": 2, "usuario_nombre": "Ana", "rol": "TECNICO", "ip": "10.0.0.5",
        "accion": "MODIFICAR", "recurso": "INVENTARIO", "recurso_id": 87,
        "antes": {"estado": "BUENO"}, "despues": {"estado": "FUERA_DE_SERVICIO"},
        "motivo": None, "correlation_id": "abc", "trace_id": None,
    }
    return base | cambios


def construir_cadena(eventos):
    hashes, anterior = [], HASH_INICIAL
    for e in eventos:
        anterior = calcular_hash(anterior, e)
        hashes.append(anterior)
    return hashes


def test_misma_entrada_mismo_hash_y_zona_horaria_normalizada():
    a = calcular_hash(HASH_INICIAL, evento(1))
    b = calcular_hash(HASH_INICIAL, evento(1, fecha="2026-11-01T00:00:00+00:00"))  # misma hora en UTC
    assert a == b and len(a) == 64


def test_alterar_un_registro_cambia_todos_los_siguientes():
    eventos = [evento(1), evento(2), evento(3)]
    original = construir_cadena(eventos)
    eventos[1] = evento(2, despues={"estado": "BUENO"})
    alterada = construir_cadena(eventos)
    assert original[0] == alterada[0]
    assert original[1] != alterada[1] and original[2] != alterada[2]


def test_firma():
    llave = Ed25519PrivateKey.generate()
    h = calcular_hash(HASH_INICIAL, evento(1))
    firma = firmar(llave, h)
    assert firma_valida(llave.public_key(), h, firma)
    assert not firma_valida(llave.public_key(), "0" * 64, firma)
    assert not firma_valida(Ed25519PrivateKey.generate().public_key(), h, firma)


def test_diferencias_legibles():
    cambios = diferencias(
        {"estado": "BUENO", "propiedades": {"btu": 12000}, "modificado_en": "x"},
        {"estado": "MALO", "propiedades": {"btu": 12000, "gas": "R410A"}, "modificado_en": "y"},
    )
    assert cambios == [
        {"campo": "estado", "antes": "BUENO", "despues": "MALO"},
        {"campo": "propiedades.gas", "antes": None, "despues": "R410A"},
    ]
