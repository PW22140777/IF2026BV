"""auth-service: inicio de sesión, sesiones, emisión de JWT y administración de usuarios."""
import os
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from comun import contexto
from comun.app import crear_app
from comun.config import configuracion
from comun.db import fabrica_sesiones, get_db
from comun.historial import registrar_evento
from comun.modelos import Sesion, Usuario
from comun.seguridad import (
    ADMINISTRADOR, CONSULTA, SISTEMA, SOLO_ADMIN, TECNICO, TODOS, UsuarioToken, crear_token, requiere_rol,
)

log = structlog.get_logger()

PATRON_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
PATRON_ROL = f"^({ADMINISTRADOR}|{TECNICO}|{CONSULTA})$"

# bcrypt solo usa los primeros 72 BYTES; una letra con acento ocupa 2 y un emoji 4
MAX_BYTES_CONTRASENA = 72


def validar_bytes_contrasena(contrasena: str | None) -> str | None:
    if contrasena is not None and len(contrasena.encode()) > MAX_BYTES_CONTRASENA:
        raise PydanticCustomError(
            "contrasena_larga",
            "La contraseña ocupa más de 72 bytes; las letras con acento y los emojis ocupan 2 o más. Acórtala",
        )
    return contrasena


# Reglas de seguridad de una contraseña nueva (iguales a frontend/src/contrasenas.js).
# Solo se aplican al crear, restablecer o cambiar: las contraseñas ya guardadas siguen sirviendo.
MIN_CARACTERES_CONTRASENA = 10
COMUNES = ("contrasena", "password", "qwerty", "123456", "abc123", "escuela", "admin", "tecnico", "consulta")


def _normalizar(texto: str) -> str:
    """'José Pérez' -> 'jose perez': para comparar sin mayúsculas ni acentos."""
    sin_acentos = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return sin_acentos.lower()


def problema_de_contrasena(contrasena: str, nombre: str = "", email: str = "") -> str | None:
    """Devuelve qué le falta a la contraseña para ser segura, o None si cumple todo."""
    texto = _normalizar(contrasena)
    personales = [p for p in _normalizar(nombre).split() + [_normalizar(email.split("@")[0])] if len(p) >= 3]
    faltas = [
        (len(contrasena) >= MIN_CARACTERES_CONTRASENA, f"al menos {MIN_CARACTERES_CONTRASENA} caracteres"),
        (any(c.isupper() for c in contrasena), "una letra mayúscula"),
        (any(c.islower() for c in contrasena), "una letra minúscula"),
        (any(c.isdigit() for c in contrasena), "un número"),
        (any(not c.isalnum() for c in contrasena), "un símbolo, como ! # $ % o -"),
        (not any(c in texto for c in COMUNES), "no usar palabras muy usadas (password, 123456, escuela…)"),
        (not any(p in texto for p in personales), "no incluir tu nombre ni tu correo"),
    ]
    pendientes = [texto_falta for cumple, texto_falta in faltas if not cumple]
    if pendientes:
        return "La contraseña no es suficientemente segura; le falta: " + "; ".join(pendientes)
    return None


def exigir_contrasena_segura(contrasena: str, nombre: str = "", email: str = "") -> None:
    problema = problema_de_contrasena(contrasena, nombre, email)
    if problema:
        raise HTTPException(422, problema)


# ------------------------------------------------------------------ esquemas
class UsuarioSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    email: str
    rol: str
    activo: bool
    debe_cambiar_contrasena: bool
    creado_en: datetime
    creado_por: int | None
    modificado_en: datetime | None
    modificado_por: int | None


class UsuarioCrear(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    email: str = Field(pattern=PATRON_EMAIL, max_length=200)
    contrasena: str = Field(min_length=1, max_length=72, description="Ver problema_de_contrasena")
    rol: str = Field(pattern=PATRON_ROL)

    _bytes = field_validator("contrasena")(validar_bytes_contrasena)


class UsuarioActualizar(BaseModel):
    # Los campos omitidos no se cambian
    nombre: str = Field(default=None, min_length=2, max_length=120)
    rol: str = Field(default=None, pattern=PATRON_ROL)
    activo: bool = Field(default=None)
    contrasena: str = Field(default=None, min_length=1, max_length=72, description="Ver problema_de_contrasena")

    _bytes = field_validator("contrasena")(validar_bytes_contrasena)


class CambioContrasena(BaseModel):
    actual: str = Field(min_length=1, max_length=200)
    nueva: str = Field(min_length=1, max_length=72, description="Ver problema_de_contrasena")

    _bytes = field_validator("nueva")(validar_bytes_contrasena)


class RespuestaLogin(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_en: datetime      # vence si no hay actividad; se extiende con /auth/renovar
    vence_en: datetime       # máximo de la sesión: después hay que volver a iniciar sesión
    usuario: dict


# ---------------------------------------------------------------- utilidades
def hashear(contrasena: str) -> str:
    # Las contraseñas nuevas ya se validan en bytes; el recorte solo protege a bcrypt
    return bcrypt.hashpw(contrasena.encode()[:MAX_BYTES_CONTRASENA], bcrypt.gensalt()).decode()


def coincide(contrasena: str, hash_guardado: str) -> bool:
    # Se recorta igual que al guardar, para que sigan entrando las contraseñas largas que
    # se crearon antes de validar en bytes
    return bcrypt.checkpw(contrasena.encode()[:MAX_BYTES_CONTRASENA], hash_guardado.encode())


# Hash ficticio para que un correo inexistente tarde lo mismo que uno real
_HASH_FICTICIO = hashear("contrasena-que-nadie-usa")


def foto(usuario: Usuario) -> dict:
    """Estado del usuario para el historial (sin el hash de la contraseña)."""
    return UsuarioSalida.model_validate(usuario).model_dump(mode="json")


def _expiracion_por_inactividad(vence_en: datetime) -> datetime:
    """Ahora más el tiempo de inactividad permitido, sin pasar del máximo de la sesión."""
    minutos = configuracion().sesion_inactividad_minutos
    return min(datetime.now(timezone.utc) + timedelta(minutes=minutos), vence_en)


def _respuesta_sesion(usuario: Usuario, sesion: Sesion) -> "RespuestaLogin":
    return RespuestaLogin(
        access_token=crear_token(usuario.id, usuario.nombre, usuario.rol, sesion.id, sesion.expira_en),
        expira_en=sesion.expira_en,
        vence_en=sesion.vence_en,
        usuario={"id": usuario.id, "nombre": usuario.nombre, "email": usuario.email, "rol": usuario.rol,
                 "debe_cambiar_contrasena": usuario.debe_cambiar_contrasena},
    )


async def _revocar_sesiones(db: AsyncSession, usuario_id: int, motivo: str, *,
                            sesion_id: uuid.UUID | None = None, excepto: uuid.UUID | None = None) -> None:
    """Cierra las sesiones abiertas del usuario: todas, solo `sesion_id` o todas menos `excepto`.

    Surte efecto en la siguiente petición de cada sesión.
    """
    consulta = update(Sesion).where(Sesion.usuario_id == usuario_id, Sesion.revocada_en.is_(None))
    if sesion_id is not None:
        consulta = consulta.where(Sesion.id == sesion_id)
    if excepto is not None:
        consulta = consulta.where(Sesion.id != excepto)
    await db.execute(consulta.values(revocada_en=datetime.now(timezone.utc), motivo_revocacion=motivo))


# --------------------------------------------------------------------- rutas
router_auth = APIRouter(prefix="/auth", tags=["Autenticación"])
router_usuarios = APIRouter(prefix="/usuarios", tags=["Usuarios"])


@router_auth.post("/login", response_model=RespuestaLogin, summary="Iniciar sesión (usuario = correo)")
async def login(formulario: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    email = formulario.username.strip().lower()
    usuario = (await db.execute(select(Usuario).where(Usuario.email == email))).scalar_one_or_none()
    valido = coincide(formulario.password, usuario.hash_contrasena if usuario else _HASH_FICTICIO)

    if not usuario or not valido or not usuario.activo:
        motivo = "Usuario desactivado" if (usuario and valido) else "Credenciales inválidas"
        await registrar_evento(db, accion="LOGIN_FALLIDO", recurso="SESION",
                               recurso_id=usuario.id if usuario else None, usuario=None,
                               despues={"email": email}, motivo=motivo)
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Correo o contraseña incorrectos",
                            headers={"WWW-Authenticate": "Bearer"})

    # La sesión queda en la base: así se puede cerrar de verdad y revisar el rol en cada petición
    vence_en = datetime.now(timezone.utc) + timedelta(hours=configuracion().sesion_maxima_horas)
    sesion = Sesion(id=uuid.uuid4(), usuario_id=usuario.id, creada_en=datetime.now(timezone.utc),
                    expira_en=_expiracion_por_inactividad(vence_en), vence_en=vence_en,
                    ip=contexto.ip_cliente.get())
    db.add(sesion)
    quien = UsuarioToken(id=usuario.id, nombre=usuario.nombre, rol=usuario.rol, sesion_id=sesion.id)
    await registrar_evento(db, accion="LOGIN", recurso="SESION", recurso_id=usuario.id, usuario=quien,
                           despues={"email": email, "sesion_id": str(sesion.id)})
    await db.commit()
    return _respuesta_sesion(usuario, sesion)


@router_auth.post("/renovar", response_model=RespuestaLogin,
                  summary="Extender la sesión actual (el frontend lo llama mientras hay actividad)")
async def renovar(actual: UsuarioToken = Depends(requiere_rol(*TODOS, aunque_deba_cambiar_contrasena=True)),
                  db: AsyncSession = Depends(get_db)):
    sesion = await db.get(Sesion, actual.sesion_id)
    usuario = await db.get(Usuario, actual.id)
    sesion.expira_en = _expiracion_por_inactividad(sesion.vence_en)
    await db.commit()
    # El token nuevo lleva el rol actual: si cambió, el frontend ajusta su menú
    return _respuesta_sesion(usuario, sesion)


@router_auth.post("/salir", status_code=204, summary="Cerrar la sesión actual")
async def salir(actual: UsuarioToken = Depends(requiere_rol(*TODOS, aunque_deba_cambiar_contrasena=True)),
                db: AsyncSession = Depends(get_db)):
    await _revocar_sesiones(db, actual.id, "Cierre de sesión", sesion_id=actual.sesion_id)
    await registrar_evento(db, accion="LOGOUT", recurso="SESION", recurso_id=actual.id, usuario=actual,
                           despues={"sesion_id": str(actual.sesion_id)})
    await db.commit()
    return Response(status_code=204)


@router_auth.post("/cambiar-contrasena", response_model=RespuestaLogin,
                  summary="Cambiar la propia contraseña (también la temporal)")
async def cambiar_contrasena(datos: CambioContrasena,
                             actual: UsuarioToken = Depends(requiere_rol(*TODOS, aunque_deba_cambiar_contrasena=True)),
                             db: AsyncSession = Depends(get_db)):
    usuario = await db.get(Usuario, actual.id)
    if not coincide(datos.actual, usuario.hash_contrasena):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La contraseña actual no es correcta; revísala e intenta de nuevo")
    if coincide(datos.nueva, usuario.hash_contrasena):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La nueva contraseña debe ser distinta de la actual")
    exigir_contrasena_segura(datos.nueva, usuario.nombre, usuario.email)

    antes = foto(usuario)
    usuario.hash_contrasena = hashear(datos.nueva)
    usuario.debe_cambiar_contrasena = False
    usuario.modificado_en = datetime.now(timezone.utc)
    usuario.modificado_por = usuario.id
    # Si alguien más conocía la contraseña anterior, sus sesiones dejan de servir; esta sigue abierta
    await _revocar_sesiones(db, usuario.id, "Contraseña cambiada por su dueño", excepto=actual.sesion_id)
    await db.flush()
    await db.refresh(usuario)
    await registrar_evento(db, accion="MODIFICAR", recurso="USUARIO", recurso_id=usuario.id, usuario=actual,
                           antes=antes, despues=foto(usuario), motivo="Cambio de contraseña por su dueño")
    await db.commit()
    return _respuesta_sesion(usuario, await db.get(Sesion, actual.sesion_id))


@router_auth.get("/yo", summary="Datos del usuario de la sesión actual")
async def yo(usuario: UsuarioToken = Depends(requiere_rol(*TODOS, aunque_deba_cambiar_contrasena=True))):
    return {"id": usuario.id, "nombre": usuario.nombre, "rol": usuario.rol,
            "debe_cambiar_contrasena": usuario.debe_cambiar_contrasena}


@router_usuarios.get("", response_model=list[UsuarioSalida], summary="Listar usuarios (Administrador)")
async def listar_usuarios(_: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN)),
                          db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Usuario).order_by(Usuario.id))).scalars().all()


@router_usuarios.post("", response_model=UsuarioSalida, status_code=201, summary="Crear usuario (Administrador)")
async def crear_usuario(datos: UsuarioCrear, admin: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN)),
                        db: AsyncSession = Depends(get_db)):
    email = datos.email.strip().lower()
    exigir_contrasena_segura(datos.contrasena, datos.nombre, email)
    duplicado = HTTPException(status.HTTP_409_CONFLICT,
                              f"Ya existe una cuenta con el correo {email}; usa otro o reactiva la existente")
    if (await db.execute(select(Usuario.id).where(Usuario.email == email))).first():
        raise duplicado
    usuario = Usuario(
        nombre=datos.nombre.strip(),
        email=email,
        hash_contrasena=hashear(datos.contrasena),
        rol=datos.rol,
        activo=True,
        debe_cambiar_contrasena=True,   # la contraseña inicial la conoce el Administrador
        creado_por=admin.id,
        creado_en=datetime.now(timezone.utc),
    )
    db.add(usuario)
    try:
        await db.flush()
    except IntegrityError:
        # Otra petición creó el mismo correo entre la revisión y este momento
        await db.rollback()
        raise duplicado
    await db.refresh(usuario)
    await registrar_evento(db, accion="CREAR", recurso="USUARIO", recurso_id=usuario.id, usuario=admin,
                           despues=foto(usuario))
    await db.commit()
    return usuario


@router_usuarios.patch("/{id}", response_model=UsuarioSalida, summary="Modificar usuario (Administrador)")
async def modificar_usuario(id: int, datos: UsuarioActualizar,
                            admin: UsuarioToken = Depends(requiere_rol(*SOLO_ADMIN)),
                            db: AsyncSession = Depends(get_db)):
    usuario = await db.get(Usuario, id)
    if usuario is None:
        raise HTTPException(404, "El usuario no existe")
    cambios = datos.model_dump(exclude_unset=True)
    if usuario.id == admin.id and (cambios.get("rol", ADMINISTRADOR) != ADMINISTRADOR
                                   or cambios.get("activo") is False):
        raise HTTPException(409, "No puedes quitarte tu propio rol de Administrador ni desactivarte")
    if usuario.id == admin.id and "contrasena" in cambios:
        raise HTTPException(409, "Para cambiar tu propia contraseña usa «Cambiar contraseña»; "
                                 "aquí se asigna una temporal a otras cuentas")
    if not cambios:
        return usuario
    if cambios.get("contrasena"):
        exigir_contrasena_segura(cambios["contrasena"], cambios.get("nombre", usuario.nombre), usuario.email)

    antes = foto(usuario)
    contrasena = cambios.pop("contrasena", None)
    for campo, valor in cambios.items():
        setattr(usuario, campo, valor)
    if contrasena:
        # Restablecer: la contraseña nueva es temporal y su dueño debe cambiarla al entrar
        usuario.hash_contrasena = hashear(contrasena)
        usuario.debe_cambiar_contrasena = True
    # Un cambio de rol no necesita cerrar sesiones: el rol se lee de la base en cada petición
    if cambios.get("activo") is False:
        await _revocar_sesiones(db, usuario.id, "Cuenta desactivada")
    elif contrasena:
        await _revocar_sesiones(db, usuario.id, "Contraseña restablecida por el Administrador")
    usuario.modificado_en = datetime.now(timezone.utc)
    usuario.modificado_por = admin.id
    await db.flush()
    await db.refresh(usuario)
    await registrar_evento(db, accion="MODIFICAR", recurso="USUARIO", recurso_id=usuario.id, usuario=admin,
                           antes=antes, despues=foto(usuario),
                           motivo="Contraseña restablecida por el Administrador" if contrasena else None)
    await db.commit()
    return usuario


# ------------------------------------------------------------------- arranque
async def crear_usuarios_iniciales() -> None:
    """Si no hay usuarios, crea el Administrador (y usuarios de demostración)."""
    iniciales = [(
        os.getenv("ADMIN_NOMBRE", "Administrador"),
        os.getenv("ADMIN_EMAIL", "admin@escuela.mx"),
        os.getenv("ADMIN_PASSWORD", "Admin12345"),
        ADMINISTRADOR,
    )]
    if os.getenv("CREAR_USUARIOS_DEMO", "true").lower() == "true":
        iniciales += [
            ("Técnico de demostración", "tecnico@escuela.mx", "Tecnico12345", TECNICO),
            ("Consulta de demostración", "consulta@escuela.mx", "Consulta12345", CONSULTA),
        ]
    async with fabrica_sesiones()() as db:
        if (await db.execute(select(func.count()).select_from(Usuario))).scalar_one() > 0:
            return
        try:
            for nombre, email, contrasena, rol in iniciales:
                # En minúsculas como en el login; si no, un ADMIN_EMAIL con mayúsculas no podría entrar
                usuario = Usuario(nombre=nombre, email=email.strip().lower(), hash_contrasena=hashear(contrasena), rol=rol,
                                  activo=True, creado_en=datetime.now(timezone.utc))
                db.add(usuario)
                await db.flush()
                await db.refresh(usuario)
                await registrar_evento(db, accion="CREAR", recurso="USUARIO", recurso_id=usuario.id,
                                       usuario=SISTEMA, despues=foto(usuario), motivo="Usuario inicial")
            await db.commit()
            log.info("usuarios_iniciales_creados", total=len(iniciales))
        except IntegrityError:
            # Otra réplica los creó al mismo tiempo
            await db.rollback()


app = crear_app(
    nombre="auth",
    titulo="auth-service",
    descripcion="Inicio de sesión con JWT y administración de usuarios y roles.",
    routers=[router_auth, router_usuarios],
    al_iniciar=crear_usuarios_iniciales,
)
