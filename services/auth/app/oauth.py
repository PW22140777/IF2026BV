"""Inicio de sesión de los Observadores con su cuenta institucional (Microsoft Entra ID).

Flujo OpenID Connect con código de autorización + PKCE:

  1. /auth/oauth/inicio   -> guarda en una cookie firmada el `state`, el `nonce` y el
                             verificador PKCE, y redirige a Microsoft.
  2. Microsoft            -> la persona entra con su cuenta y vuelve a /auth/oauth/callback.
  3. /auth/oauth/callback -> cambia el código por un id_token, lo valida (firma, emisor,
                             audiencia, inquilino, nonce, dominio del correo), crea la sesión
                             y redirige al frontend con un código de un solo uso.
  4. /auth/oauth/canjear  -> el frontend cambia ese código por el JWT de siempre.

Este módulo tiene solo la lógica que no toca la base, para poder probarla sin Docker.
"""
import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlencode

import jwt

PROVEEDOR = "microsoft"
NOMBRE_COOKIE = "oauth_estado"
MINUTOS_ESTADO = 10      # tiempo para volver de Microsoft
SEGUNDOS_CANJE = 60      # tiempo para que el frontend canjee su código


class ErrorOAuth(Exception):
    """Algo impide entrar; el mensaje se muestra a la persona en la página de registro."""


@dataclass(frozen=True)
class ConfiguracionOAuth:
    inquilino: str            # id del directorio (tenant) de la institución en Entra
    cliente_id: str
    cliente_secreto: str
    redireccion: str          # p. ej. http://localhost:8080/api/v1/auth/oauth/callback
    dominios: tuple[str, ...]
    modo_prueba: bool         # SOLO desarrollo: entra sin Microsoft (ver identidad_de_prueba)

    @property
    def autoridad(self) -> str:
        return f"https://login.microsoftonline.com/{self.inquilino}"

    @property
    def emisor(self) -> str:
        return f"{self.autoridad}/v2.0"

    @property
    def lista(self) -> bool:
        return bool(self.inquilino and self.cliente_id and self.cliente_secreto and self.redireccion)


@lru_cache
def configuracion_oauth() -> ConfiguracionOAuth:
    dominios = os.getenv("DOMINIOS_INSTITUCIONALES", "queretaro.tecnm.mx")
    return ConfiguracionOAuth(
        inquilino=os.getenv("OAUTH_INQUILINO", ""),
        cliente_id=os.getenv("OAUTH_CLIENTE_ID", ""),
        cliente_secreto=os.getenv("OAUTH_CLIENTE_SECRETO", ""),
        redireccion=os.getenv("OAUTH_REDIRECCION", ""),
        dominios=tuple(d.strip().lower() for d in dominios.split(",") if d.strip()),
        modo_prueba=os.getenv("OAUTH_MODO_PRUEBA", "false").lower() == "true",
    )


# --------------------------------------------------------------- PKCE y estado
def par_pkce() -> tuple[str, str]:
    """Verificador aleatorio y su reto S256 (RFC 7636)."""
    verificador = secrets.token_urlsafe(64)
    reto = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    return verificador, reto


def firmar_estado(secreto: str, estado: str, nonce: str, verificador: str) -> str:
    """Contenido de la cookie: firmado para que nadie lo cambie; vive 10 minutos."""
    datos = {"typ": "oauth-estado", "state": estado, "nonce": nonce, "pkce": verificador,
             "exp": datetime.now(timezone.utc) + timedelta(minutes=MINUTOS_ESTADO)}
    return jwt.encode(datos, secreto, algorithm="HS256")


def leer_estado(secreto: str, cookie: str | None, estado_recibido: str | None) -> dict:
    """Valida la cookie y que el `state` que volvió de Microsoft sea el mismo (evita CSRF)."""
    if not cookie or not estado_recibido:
        raise ErrorOAuth("El inicio de sesión expiró o se abrió en otra pestaña; inténtalo de nuevo")
    try:
        datos = jwt.decode(cookie, secreto, algorithms=["HS256"], options={"require": ["exp", "state"]})
    except jwt.PyJWTError:
        raise ErrorOAuth("El inicio de sesión expiró; inténtalo de nuevo")
    if datos.get("typ") != "oauth-estado" or not secrets.compare_digest(datos["state"], estado_recibido):
        raise ErrorOAuth("La respuesta de Microsoft no corresponde a este inicio de sesión; inténtalo de nuevo")
    return datos


def url_autorizacion(cfg: ConfiguracionOAuth, estado: str, nonce: str, reto: str) -> str:
    parametros = {
        "client_id": cfg.cliente_id,
        "response_type": "code",
        "redirect_uri": cfg.redireccion,
        "response_mode": "query",
        "scope": "openid profile email",
        "state": estado,
        "nonce": nonce,
        "code_challenge": reto,
        "code_challenge_method": "S256",
        "prompt": "select_account",   # deja elegir la cuenta institucional si hay varias abiertas
    }
    return f"{cfg.autoridad}/oauth2/v2.0/authorize?{urlencode(parametros)}"


# ------------------------------------------------------------- id_token y correo
@dataclass(frozen=True)
class Identidad:
    sujeto: str     # oid: identificador estable de la persona en el directorio
    email: str
    nombre: str


def validar_claims(cfg: ConfiguracionOAuth, claims: dict, nonce: str) -> Identidad:
    """Reglas que decide la escuela, sobre un id_token cuya firma ya se comprobó."""
    if claims.get("tid") != cfg.inquilino:
        raise ErrorOAuth("Esa cuenta no pertenece al directorio institucional; entra con tu cuenta de la escuela")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ErrorOAuth("La respuesta de Microsoft no corresponde a este inicio de sesión; inténtalo de nuevo")
    # En cuentas de trabajo el correo viene en `email` (si se configuró) o en `preferred_username`
    email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    dominio = email.rpartition("@")[2]
    if not email or dominio not in cfg.dominios:
        permitidos = ", ".join(f"@{d}" for d in cfg.dominios)
        raise ErrorOAuth(f"Solo se pueden registrar correos institucionales ({permitidos})")
    sujeto = claims.get("oid") or claims.get("sub")
    if not sujeto:
        raise ErrorOAuth("Microsoft no envió el identificador de la cuenta; inténtalo de nuevo")
    nombre = str(claims.get("name") or email.split("@")[0]).strip()[:120]
    return Identidad(sujeto=str(sujeto), email=email, nombre=nombre if len(nombre) >= 2 else email)


@lru_cache
def _llaves(url: str) -> jwt.PyJWKClient:
    # Guarda en caché las llaves públicas de Microsoft; las vuelve a pedir si llega una nueva
    return jwt.PyJWKClient(url, cache_keys=True)


def validar_id_token(cfg: ConfiguracionOAuth, id_token: str, nonce: str) -> Identidad:
    """Firma RS256 con las llaves publicadas por Microsoft, emisor, audiencia y vigencia."""
    try:
        llave = _llaves(f"{cfg.autoridad}/discovery/v2.0/keys").get_signing_key_from_jwt(id_token)
        claims = jwt.decode(id_token, llave.key, algorithms=["RS256"], audience=cfg.cliente_id,
                            issuer=cfg.emisor, options={"require": ["exp", "iat", "aud", "iss"]}, leeway=60)
    except jwt.PyJWTError:
        raise ErrorOAuth("No se pudo comprobar la respuesta de Microsoft; inténtalo de nuevo")
    return validar_claims(cfg, claims, nonce)


def identidad_de_prueba(cfg: ConfiguracionOAuth, email: str, nombre: str) -> Identidad:
    """SOLO con OAUTH_MODO_PRUEBA=true (pruebas locales): una identidad sin pasar por Microsoft.

    Aplica las mismas reglas de dominio que una cuenta real.
    """
    claims = {"tid": cfg.inquilino, "nonce": "prueba", "email": email, "name": nombre,
              "oid": f"prueba:{email.strip().lower()}"}
    return validar_claims(cfg, claims, "prueba")


# ----------------------------------------------------------- código de canje
def nuevo_codigo_canje() -> tuple[str, str]:
    """Código que recibe el navegador y su hash, que es lo único que se guarda."""
    codigo = secrets.token_urlsafe(32)
    return codigo, hash_codigo(codigo)


def hash_codigo(codigo: str) -> str:
    return hashlib.sha256(codigo.encode()).hexdigest()
