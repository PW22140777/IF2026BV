"""Pruebas del registro de Observadores con Microsoft Entra ID, sin Docker ni Microsoft.

Se firma un id_token con una llave RSA de prueba y se sustituye la descarga de las
llaves públicas de Microsoft, para comprobar cada regla que decide quién entra.

    pip install pytest PyJWT cryptography
    pytest tests/test_oauth.py
"""
import base64
import hashlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from services.auth.app import oauth  # noqa: E402

INQUILINO = "11111111-2222-3333-4444-555555555555"
CFG = oauth.ConfiguracionOAuth(
    inquilino=INQUILINO, cliente_id="cliente-prueba", cliente_secreto="secreto",
    redireccion="http://localhost:8080/api/v1/auth/oauth/callback",
    dominios=("queretaro.tecnm.mx",), modo_prueba=False,
)
LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTRA_LLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _LlavesFalsas:
    """Sustituye a PyJWKClient: devuelve siempre la llave pública de prueba."""

    def get_signing_key_from_jwt(self, _token):
        return type("Llave", (), {"key": LLAVE.public_key()})()


def id_token(llave=LLAVE, **cambios):
    ahora = datetime.now(timezone.utc)
    claims = {
        "iss": CFG.emisor, "aud": CFG.cliente_id, "tid": INQUILINO, "nonce": "n-123",
        "oid": "oid-ana", "name": "Ana Pérez", "preferred_username": "ana.perez@queretaro.tecnm.mx",
        "iat": ahora, "exp": ahora + timedelta(minutes=5),
    }
    claims.update(cambios)
    return jwt.encode(claims, llave, algorithm="RS256")


class IdTokenTest(unittest.TestCase):
    def setUp(self):
        self._original = oauth._llaves
        oauth._llaves = lambda _url: _LlavesFalsas()

    def tearDown(self):
        oauth._llaves = self._original

    def test_cuenta_institucional_valida(self):
        identidad = oauth.validar_id_token(CFG, id_token(), "n-123")
        self.assertEqual(identidad, oauth.Identidad(sujeto="oid-ana", email="ana.perez@queretaro.tecnm.mx",
                                                    nombre="Ana Pérez"))

    def test_correo_de_otro_dominio_se_rechaza(self):
        with self.assertRaisesRegex(oauth.ErrorOAuth, "correos institucionales"):
            oauth.validar_id_token(CFG, id_token(preferred_username="ana@gmail.com"), "n-123")

    def test_subdominio_parecido_se_rechaza(self):
        with self.assertRaises(oauth.ErrorOAuth):
            oauth.validar_id_token(CFG, id_token(preferred_username="ana@queretaro.tecnm.mx.evil.com"), "n-123")

    def test_otro_inquilino_se_rechaza(self):
        with self.assertRaisesRegex(oauth.ErrorOAuth, "directorio institucional"):
            oauth.validar_id_token(CFG, id_token(tid="otro-directorio"), "n-123")

    def test_nonce_distinto_se_rechaza(self):
        with self.assertRaises(oauth.ErrorOAuth):
            oauth.validar_id_token(CFG, id_token(), "otro-nonce")

    def test_firma_de_otra_llave_se_rechaza(self):
        with self.assertRaisesRegex(oauth.ErrorOAuth, "comprobar"):
            oauth.validar_id_token(CFG, id_token(llave=OTRA_LLAVE), "n-123")

    def test_audiencia_y_emisor_distintos_se_rechazan(self):
        for cambio in ({"aud": "otra-aplicacion"}, {"iss": "https://login.microsoftonline.com/otro/v2.0"}):
            with self.subTest(cambio=cambio), self.assertRaises(oauth.ErrorOAuth):
                oauth.validar_id_token(CFG, id_token(**cambio), "n-123")

    def test_token_vencido_se_rechaza(self):
        hace_rato = datetime.now(timezone.utc) - timedelta(hours=1)
        with self.assertRaises(oauth.ErrorOAuth):
            oauth.validar_id_token(CFG, id_token(iat=hace_rato, exp=hace_rato + timedelta(minutes=5)), "n-123")


class EstadoYPkceTest(unittest.TestCase):
    def test_estado_firmado_ida_y_vuelta(self):
        cookie = oauth.firmar_estado("secreto-jwt-de-prueba-con-mas-de-32-bytes", "estado-1", "nonce-1", "verificador-1")
        datos = oauth.leer_estado("secreto-jwt-de-prueba-con-mas-de-32-bytes", cookie, "estado-1")
        self.assertEqual((datos["nonce"], datos["pkce"]), ("nonce-1", "verificador-1"))

    def test_estado_distinto_o_cookie_alterada_se_rechazan(self):
        cookie = oauth.firmar_estado("secreto-jwt-de-prueba-con-mas-de-32-bytes", "estado-1", "nonce-1", "verificador-1")
        with self.assertRaises(oauth.ErrorOAuth):
            oauth.leer_estado("secreto-jwt-de-prueba-con-mas-de-32-bytes", cookie, "estado-de-otra-pestana")
        with self.assertRaises(oauth.ErrorOAuth):
            oauth.leer_estado("otro-secreto-de-prueba-con-mas-de-32-bytes", cookie, "estado-1")
        with self.assertRaises(oauth.ErrorOAuth):
            oauth.leer_estado("secreto-jwt-de-prueba-con-mas-de-32-bytes", None, "estado-1")

    def test_reto_pkce_es_sha256_del_verificador(self):
        verificador, reto = oauth.par_pkce()
        esperado = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(reto, esperado)

    def test_url_lleva_pkce_estado_y_nonce(self):
        url = oauth.url_autorizacion(CFG, "estado-1", "nonce-1", "reto-1")
        self.assertTrue(url.startswith(f"https://login.microsoftonline.com/{INQUILINO}/oauth2/v2.0/authorize?"))
        for parte in ("code_challenge=reto-1", "code_challenge_method=S256", "state=estado-1", "nonce=nonce-1"):
            self.assertIn(parte, url)

    def test_codigo_de_canje_solo_se_guarda_como_hash(self):
        codigo, guardado = oauth.nuevo_codigo_canje()
        self.assertNotEqual(codigo, guardado)
        self.assertEqual(oauth.hash_codigo(codigo), guardado)


if __name__ == "__main__":
    unittest.main()
