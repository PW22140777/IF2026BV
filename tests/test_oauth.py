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


class MultiinquilinoTest(unittest.TestCase):
    """App registrada en otro directorio: se entra por "organizations", pero solo se acepta la institución."""

    CFG_ORG = oauth.ConfiguracionOAuth(
        inquilino=INQUILINO, cliente_id="cliente-prueba", cliente_secreto="secreto",
        redireccion="http://localhost:8080/api/v1/auth/oauth/callback",
        dominios=("queretaro.tecnm.mx",), modo_prueba=False, entrada="organizations",
    )

    def setUp(self):
        self._original = oauth._llaves
        oauth._llaves = lambda _url: _LlavesFalsas()

    def tearDown(self):
        oauth._llaves = self._original

    def test_se_entra_por_organizations_y_el_emisor_sigue_siendo_la_institucion(self):
        url = oauth.url_autorizacion(self.CFG_ORG, "estado-1", "nonce-1", "reto-1")
        self.assertTrue(url.startswith("https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?"))
        self.assertEqual(self.CFG_ORG.emisor, f"https://login.microsoftonline.com/{INQUILINO}/v2.0")

    def test_cuenta_de_la_institucion_entra(self):
        identidad = oauth.validar_id_token(self.CFG_ORG, id_token(), "n-123")
        self.assertEqual(identidad.email, "ana.perez@queretaro.tecnm.mx")

    def test_cuenta_de_otra_organizacion_se_rechaza_aunque_su_correo_parezca_institucional(self):
        otro = "99999999-8888-7777-6666-555555555555"
        token = id_token(tid=otro, iss=f"https://login.microsoftonline.com/{otro}/v2.0")
        with self.assertRaises(oauth.ErrorOAuth):
            oauth.validar_id_token(self.CFG_ORG, token, "n-123")


class CuentasPersonalesTest(unittest.TestCase):
    """Entrada por "common": cuentas personales de Microsoft creadas con el correo de la escuela."""

    CFG_PERS = oauth.ConfiguracionOAuth(
        inquilino=INQUILINO, cliente_id="cliente-prueba", cliente_secreto="secreto",
        redireccion="http://localhost:8080/api/v1/auth/oauth/callback",
        dominios=("queretaro.tecnm.mx",), modo_prueba=False, entrada="common", personales=True,
    )
    PERSONAL = {"tid": oauth.CUENTAS_PERSONALES, "iss": oauth.ConfiguracionOAuth.emisor_de(oauth.CUENTAS_PERSONALES)}

    def setUp(self):
        self._original = oauth._llaves
        oauth._llaves = lambda _url: _LlavesFalsas()

    def tearDown(self):
        oauth._llaves = self._original

    def test_cuenta_personal_con_correo_de_la_escuela_entra(self):
        identidad = oauth.validar_id_token(self.CFG_PERS, id_token(**self.PERSONAL, email="ana.perez@queretaro.tecnm.mx"), "n-123")
        self.assertEqual(identidad.email, "ana.perez@queretaro.tecnm.mx")

    def test_cuenta_de_la_institucion_tambien_entra(self):
        self.assertEqual(oauth.validar_id_token(self.CFG_PERS, id_token(), "n-123").sujeto, "oid-ana")

    def test_cuenta_personal_de_otro_dominio_se_rechaza(self):
        token = id_token(**self.PERSONAL, email="ana@outlook.com", preferred_username="ana@outlook.com")
        with self.assertRaisesRegex(oauth.ErrorOAuth, "correos institucionales"):
            oauth.validar_id_token(self.CFG_PERS, token, "n-123")

    def test_sin_activar_personales_se_rechazan(self):
        with self.assertRaisesRegex(oauth.ErrorOAuth, "directorio institucional"):
            oauth.validar_id_token(CFG, id_token(**self.PERSONAL), "n-123")

    def test_emisor_que_no_coincide_con_tid_se_rechaza(self):
        # tid de la institución, pero firmado como emisor de cuentas personales (o al revés)
        token = id_token(iss=oauth.ConfiguracionOAuth.emisor_de(oauth.CUENTAS_PERSONALES))
        with self.assertRaises(oauth.ErrorOAuth):
            oauth.validar_id_token(self.CFG_PERS, token, "n-123")

    def test_otra_organizacion_se_rechaza(self):
        otro = "99999999-8888-7777-6666-555555555555"
        with self.assertRaises(oauth.ErrorOAuth):
            oauth.validar_id_token(self.CFG_PERS, id_token(tid=otro, iss=oauth.ConfiguracionOAuth.emisor_de(otro)), "n-123")


class GoogleTest(unittest.TestCase):
    """OAUTH_PROVEEDOR=google: cuentas del Google Workspace de la escuela."""

    CFG_G = oauth.ConfiguracionOAuth(
        inquilino="", cliente_id="cliente-google", cliente_secreto="secreto",
        redireccion="http://localhost:8080/api/v1/auth/oauth/callback",
        dominios=("queretaro.tecnm.mx",), modo_prueba=False, proveedor=oauth.GOOGLE,
    )

    def setUp(self):
        self._original = oauth._llaves
        self.url_pedida = None

        def llaves(url):
            self.url_pedida = url
            return _LlavesFalsas()
        oauth._llaves = llaves

    def tearDown(self):
        oauth._llaves = self._original

    def token(self, **cambios):
        ahora = datetime.now(timezone.utc)
        claims = {
            "iss": "https://accounts.google.com", "aud": "cliente-google", "nonce": "n-123", "sub": "1098765",
            "email": "ana.perez@queretaro.tecnm.mx", "email_verified": True, "hd": "queretaro.tecnm.mx",
            "name": "Ana Pérez", "iat": ahora, "exp": ahora + timedelta(minutes=5),
        }
        claims.update(cambios)
        return jwt.encode(claims, LLAVE, algorithm="RS256")

    def test_cuenta_de_la_escuela_entra_con_las_llaves_de_google(self):
        identidad = oauth.validar_id_token(self.CFG_G, self.token(), "n-123")
        self.assertEqual(identidad, oauth.Identidad(sujeto="1098765", email="ana.perez@queretaro.tecnm.mx",
                                                    nombre="Ana Pérez", proveedor=oauth.GOOGLE))
        self.assertEqual(self.url_pedida, oauth.GOOGLE_LLAVES)

    def test_lista_sin_inquilino(self):
        self.assertTrue(self.CFG_G.lista)

    def test_gmail_personal_se_rechaza(self):
        # Sin `hd`: es una cuenta personal, aunque diga un correo de la escuela
        for cambio in ({"hd": None}, {"email": "ana@gmail.com", "hd": None},
                       {"hd": "otra-escuela.edu.mx", "email": "ana@otra-escuela.edu.mx"}):
            with self.subTest(cambio=cambio), self.assertRaisesRegex(oauth.ErrorOAuth, "Gmail personal"):
                oauth.validar_id_token(self.CFG_G, self.token(**cambio), "n-123")

    def test_correo_sin_verificar_se_rechaza(self):
        with self.assertRaisesRegex(oauth.ErrorOAuth, "verificado"):
            oauth.validar_id_token(self.CFG_G, self.token(email_verified=False), "n-123")

    def test_emisor_audiencia_y_nonce_distintos_se_rechazan(self):
        for cambio, nonce in (({"iss": "https://evil.example.com"}, "n-123"), ({"aud": "otra-app"}, "n-123"), ({}, "otro")):
            with self.subTest(cambio=cambio), self.assertRaises(oauth.ErrorOAuth):
                oauth.validar_id_token(self.CFG_G, self.token(**cambio), nonce)

    def test_url_de_google_con_pkce_y_sugerencia_de_dominio(self):
        url = oauth.url_autorizacion(self.CFG_G, "estado-1", "nonce-1", "reto-1")
        self.assertTrue(url.startswith(oauth.GOOGLE_AUTORIZACION + "?"))
        for parte in ("hd=queretaro.tecnm.mx", "code_challenge=reto-1", "state=estado-1", "nonce=nonce-1"):
            self.assertIn(parte, url)
        self.assertEqual(self.CFG_G.url_token, oauth.GOOGLE_TOKEN)

    def test_identidad_de_prueba_aplica_las_reglas_de_google(self):
        self.assertEqual(oauth.identidad_de_prueba(self.CFG_G, "ana@queretaro.tecnm.mx", "Ana").proveedor, oauth.GOOGLE)
        with self.assertRaises(oauth.ErrorOAuth):
            oauth.identidad_de_prueba(self.CFG_G, "ana@gmail.com", "Ana")


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
