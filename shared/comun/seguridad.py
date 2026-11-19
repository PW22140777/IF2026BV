"""Autenticación con JWT, sesiones guardadas en la base y control de acceso por roles.

El JWT dice QUIÉN eres y en qué sesión entraste; la base dice si esa
sesión sigue viva y qué rol tienes HOY. Así, cerrar sesión, desactivar
una cuenta o cambiar un rol surten efecto en la siguiente petición, sin
esperar a que el token expire.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import configuracion
from .db import get_db
from .modelos import Sesion, Usuario

# Roles del sistema
ADMINISTRADOR = "ADMINISTRADOR"   # control completo y auditoría
TECNICO = "TECNICO"               # crea, modifica y elimina recursos
CONSULTA = "CONSULTA"             # solo visualiza
OBSERVADOR = "OBSERVADOR"         # visualiza y comenta; entra solo con su cuenta institucional

ROLES = (ADMINISTRADOR, TECNICO, CONSULTA, OBSERVADOR)
TODOS = ROLES
# El Observador ve inmuebles y el estado de los servicios, pero no consumos ni mantenimientos
LECTORES_INTERNOS = (ADMINISTRADOR, TECNICO, CONSULTA)
EDITORES = (ADMINISTRADOR, TECNICO)
SOLO_ADMIN = (ADMINISTRADOR,)

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


@dataclass(frozen=True)
class UsuarioToken:
    """Usuario autenticado. En las rutas, `rol` y `nombre` ya vienen de la base, no del token."""

    id: int | None
    nombre: str
    rol: str
    sesion_id: uuid.UUID | None = None
    debe_cambiar_contrasena: bool = False


# Usuario que firma las acciones automáticas (p. ej. un consumidor de eventos)
SISTEMA = UsuarioToken(id=None, nombre="sistema", rol="SISTEMA")


def crear_token(usuario_id: int, nombre: str, rol: str, sesion_id: uuid.UUID, expira: datetime) -> str:
    """El token vence junto con la sesión; al renovarla se emite uno nuevo."""
    datos = {
        "sub": str(usuario_id),
        "nombre": nombre,
        "rol": rol,
        "sid": str(sesion_id),
        "iat": datetime.now(timezone.utc),
        "exp": expira,
        "jti": str(uuid.uuid4()),
    }
    cfg = configuracion()
    return jwt.encode(datos, cfg.jwt_secret, algorithm=cfg.jwt_algoritmo)


def decodificar_token(token: str) -> UsuarioToken:
    """Valida firma y expiración. Lanza jwt.PyJWTError si el token no es válido."""
    cfg = configuracion()
    datos = jwt.decode(
        token,
        cfg.jwt_secret,
        algorithms=[cfg.jwt_algoritmo],
        options={"require": ["sub", "exp", "rol", "sid"]},
    )
    if datos["rol"] not in ROLES:
        raise jwt.InvalidTokenError("Rol desconocido")
    try:
        sesion_id = uuid.UUID(datos["sid"])
    except ValueError:
        raise jwt.InvalidTokenError("Sesión inválida")
    return UsuarioToken(id=int(datos["sub"]), nombre=datos.get("nombre", ""), rol=datos["rol"],
                        sesion_id=sesion_id)


def _no_autorizado(mensaje: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, mensaje, headers={"WWW-Authenticate": "Bearer"})


def usuario_del_token(token: str = Depends(oauth2)) -> UsuarioToken:
    try:
        return decodificar_token(token)
    except jwt.ExpiredSignatureError:
        raise _no_autorizado("La sesión expiró, vuelve a iniciar sesión")
    except jwt.PyJWTError:
        raise _no_autorizado("Token inválido")


async def sesion_vigente(
    token: UsuarioToken = Depends(usuario_del_token),
    db: AsyncSession = Depends(get_db),
) -> UsuarioToken:
    """Revisa en la base que la sesión siga viva y devuelve el usuario con su rol actual.

    Solo lee id, nombre, rol, activo y debe_cambiar_contrasena de `usuarios`:
    los demás servicios no tienen permiso para ver el hash de la contraseña.
    """
    fila = (await db.execute(
        select(Usuario.nombre, Usuario.rol, Usuario.activo, Usuario.debe_cambiar_contrasena,
               Sesion.expira_en, Sesion.vence_en, Sesion.revocada_en, Sesion.motivo_revocacion)
        .join(Usuario, Usuario.id == Sesion.usuario_id)
        .where(Sesion.id == token.sesion_id, Sesion.usuario_id == token.id)
    )).one_or_none()

    if fila is None:
        raise _no_autorizado("La sesión no existe; vuelve a iniciar sesión")
    if fila.revocada_en is not None:
        raise _no_autorizado(f"Tu sesión se cerró ({fila.motivo_revocacion or 'sin motivo'}); vuelve a iniciar sesión")
    if not fila.activo:
        raise _no_autorizado("Tu cuenta está desactivada; pide ayuda al Administrador")
    if min(fila.expira_en, fila.vence_en) <= datetime.now(timezone.utc):
        raise _no_autorizado("La sesión expiró, vuelve a iniciar sesión")
    return UsuarioToken(id=token.id, nombre=fila.nombre, rol=fila.rol, sesion_id=token.sesion_id,
                        debe_cambiar_contrasena=fila.debe_cambiar_contrasena)


def requiere_rol(*roles: str, aunque_deba_cambiar_contrasena: bool = False):
    """Dependencia que deja pasar solo a los roles indicados, con el rol que tiene HOY el usuario.

    Quien tiene una contraseña temporal solo puede usar las rutas marcadas con
    aunque_deba_cambiar_contrasena=True (cambiarla, renovar y cerrar sesión).

    Uso:  usuario = Depends(requiere_rol(*EDITORES))
    """

    def revisar(usuario: UsuarioToken = Depends(sesion_vigente)) -> UsuarioToken:
        if usuario.debe_cambiar_contrasena and not aunque_deba_cambiar_contrasena:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Debes cambiar tu contraseña temporal antes de continuar")
        if usuario.rol not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Tu rol ({usuario.rol}) no tiene permiso para esta acción")
        return usuario

    return revisar
