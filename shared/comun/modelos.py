"""Modelos SQLAlchemy de la base de datos única.

Las tablas se crean con db/init/01_esquema.sql; estos modelos solo las
mapean a clases de Python. Cada servicio usa únicamente sus tablas.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    # Todas las fechas de la base son TIMESTAMPTZ (con zona horaria)
    type_annotation_map = {datetime: DateTime(timezone=True)}


class ConResponsabilidad:
    """Columnas de quién creó, modificó o eliminó cada recurso."""

    creado_en: Mapped[datetime] = mapped_column(default=ahora)
    creado_por: Mapped[int | None]
    modificado_en: Mapped[datetime | None]
    modificado_por: Mapped[int | None]
    eliminado_en: Mapped[datetime | None]
    eliminado_por: Mapped[int | None]
    motivo_eliminacion: Mapped[str | None]


# --------------------------------------------------------------------- auth
class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str]
    email: Mapped[str]
    hash_contrasena: Mapped[str | None]   # None en un Observador: entra solo con Microsoft
    rol: Mapped[str]
    activo: Mapped[bool] = mapped_column(default=True)
    debe_cambiar_contrasena: Mapped[bool] = mapped_column(default=False)   # tiene una contraseña temporal
    creado_en: Mapped[datetime] = mapped_column(default=ahora)
    creado_por: Mapped[int | None]
    modificado_en: Mapped[datetime | None]
    modificado_por: Mapped[int | None]
    proveedor_oauth: Mapped[str | None]   # p. ej. "microsoft"
    sujeto_oauth: Mapped[str | None]      # identificador estable de la persona en ese proveedor


class Sesion(Base):
    """Sesión iniciada. Permite cerrarla de verdad y revisar el rol en cada petición."""

    __tablename__ = "sesiones"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creada_en: Mapped[datetime] = mapped_column(default=ahora)
    expira_en: Mapped[datetime]          # se extiende con la actividad
    vence_en: Mapped[datetime]           # máximo absoluto, no se extiende
    revocada_en: Mapped[datetime | None]
    motivo_revocacion: Mapped[str | None]
    ip: Mapped[str | None]


class OauthCanje(Base):
    """Código de un solo uso que el navegador cambia por el JWT tras entrar con Microsoft."""

    __tablename__ = "oauth_canjes"

    hash_codigo: Mapped[str] = mapped_column(primary_key=True)   # SHA-256 del código, nunca el código
    sesion_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sesiones.id"))
    creado_en: Mapped[datetime] = mapped_column(default=ahora)
    expira_en: Mapped[datetime]
    usado_en: Mapped[datetime | None]


# ---------------------------------------------------------------- inmuebles
class Campus(ConResponsabilidad, Base):
    """Nivel superior: de un campus dependen edificios, áreas, inventario y servicios."""

    __tablename__ = "campus"

    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str]
    nombre: Mapped[str]
    direccion: Mapped[str | None]
    ciudad: Mapped[str | None]
    superficie_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    estado: Mapped[str] = mapped_column(default="OPERATIVO")
    descripcion: Mapped[str | None]
    propiedades: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Edificio(ConResponsabilidad, Base):
    __tablename__ = "edificios"

    id: Mapped[int] = mapped_column(primary_key=True)
    campus_id: Mapped[int] = mapped_column(ForeignKey("campus.id"))
    clave: Mapped[str]
    nombre: Mapped[str]
    niveles: Mapped[int | None]
    anio_construccion: Mapped[int | None]
    superficie_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    estado: Mapped[str] = mapped_column(default="OPERATIVO")
    descripcion: Mapped[str | None]
    carpeta_planos: Mapped[str | None]    # enlace a una carpeta externa (Drive, OneDrive...)
    fachada_s3: Mapped[str | None]        # clave de la foto de fachada en archivos-service (mismo nombre que en develop)
    propiedades: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Area(ConResponsabilidad, Base):
    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    campus_id: Mapped[int] = mapped_column(ForeignKey("campus.id"))
    edificio_id: Mapped[int | None] = mapped_column(ForeignKey("edificios.id"))
    nombre: Mapped[str]
    tipo: Mapped[str]
    piso: Mapped[int | None]
    capacidad: Mapped[int | None]
    superficie_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    exterior: Mapped[bool] = mapped_column(default=False)
    estado: Mapped[str] = mapped_column(default="OPERATIVO")
    descripcion: Mapped[str | None]
    propiedades: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class TipoElemento(ConResponsabilidad, Base):
    """Catálogo: qué propiedades lleva cada tipo de elemento de inventario."""

    __tablename__ = "tipos_elemento"

    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str]
    nombre: Mapped[str]
    descripcion: Mapped[str | None]
    usa_medidas: Mapped[bool] = mapped_column(default=False)
    propiedades_definidas: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    propiedades: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ElementoInventario(ConResponsabilidad, Base):
    __tablename__ = "elementos_inventario"

    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"))
    tipo: Mapped[str]
    eje: Mapped[str | None]
    tramo: Mapped[str | None]
    unidad: Mapped[str | None]
    largo: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    alto: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    ancho: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    espesor: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    fecha_recuento: Mapped[date | None]
    descripcion: Mapped[str | None]
    cantidad: Mapped[int] = mapped_column(default=1)
    marca: Mapped[str | None]
    modelo: Mapped[str | None]
    numero_serie: Mapped[str | None]
    estado: Mapped[str] = mapped_column(default="BUENO")
    propiedades: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# ---------------------------------------------------------------- servicios
class ServicioBasico(ConResponsabilidad, Base):
    __tablename__ = "servicios_basicos"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str]
    nombre: Mapped[str]
    numero_medidor: Mapped[str | None]
    proveedor: Mapped[str | None]
    campus_id: Mapped[int | None] = mapped_column(ForeignKey("campus.id"))
    edificio_id: Mapped[int | None] = mapped_column(ForeignKey("edificios.id"))
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"))
    activo: Mapped[bool] = mapped_column(default=True)
    estado: Mapped[str] = mapped_column(default="OPERANDO")
    descripcion: Mapped[str | None]
    propiedades: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Consumo(ConResponsabilidad, Base):
    __tablename__ = "consumos"

    id: Mapped[int] = mapped_column(primary_key=True)
    servicio_id: Mapped[int] = mapped_column(ForeignKey("servicios_basicos.id"))
    periodo: Mapped[date]
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unidad: Mapped[str]
    costo: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    propiedades: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# --------------------------------------------------------------- mensajería
class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    evento_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    tipo: Mapped[str]
    origen: Mapped[str]
    cuerpo: Mapped[dict[str, Any]] = mapped_column(JSONB)
    cabeceras: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    creado_en: Mapped[datetime] = mapped_column(default=ahora)
    enviado_en: Mapped[datetime | None]


class EventoProcesado(Base):
    __tablename__ = "eventos_procesados"

    consumidor: Mapped[str] = mapped_column(primary_key=True)
    evento_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    procesado_en: Mapped[datetime] = mapped_column(default=ahora)


# ---------------------------------------------------------- archivos adjuntos
class ArchivoAdjunto(ConResponsabilidad, Base):
    """Ficha de un archivo adjunto; el archivo lo guarda archivos-service bajo `clave`."""

    __tablename__ = "archivos_adjuntos"

    id: Mapped[int] = mapped_column(primary_key=True)
    recurso: Mapped[str]                  # EDIFICIO, AREA, INVENTARIO u ORDEN_MANTENIMIENTO
    recurso_id: Mapped[int]
    nombre: Mapped[str]
    descripcion: Mapped[str | None]
    categoria: Mapped[str]                # FOTO, PLANO, DOCUMENTO, EVIDENCIA u OTRO
    nombre_original: Mapped[str]
    tipo_mime: Mapped[str]
    tamano_bytes: Mapped[int]
    sha256: Mapped[str]
    clave: Mapped[str]
    propiedades: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# -------------------------------------------------------------- comentarios
class Comentario(ConResponsabilidad, Base):
    """Comentario de un Observador sobre un recurso, o la respuesta de un Técnico o Administrador."""

    __tablename__ = "comentarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    recurso: Mapped[str]                  # EDIFICIO, AREA, INVENTARIO, SERVICIO o CONSUMO
    recurso_id: Mapped[int]
    respuesta_a: Mapped[int | None] = mapped_column(ForeignKey("comentarios.id"))
    texto: Mapped[str]
    propiedades: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# ------------------------------------------------------------ mantenimientos
class PlantillaMantenimiento(ConResponsabilidad, Base):
    """A qué recursos aplica un mantenimiento, cuándo se abre, qué se registra y cómo queda el recurso."""

    __tablename__ = "plantillas_mantenimiento"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str]
    descripcion: Mapped[str | None]
    recurso: Mapped[str]                     # EDIFICIO, AREA, INVENTARIO o SERVICIO
    tipo_elemento: Mapped[str | None]        # solo inventario
    disparo: Mapped[str]                     # ESTADO, PERIODICO o MANUAL
    estados_disparo: Mapped[list[str]] = mapped_column(JSONB, default=list)
    cada_dias: Mapped[int | None]
    estado_al_iniciar: Mapped[str | None]
    estado_resuelto: Mapped[str]
    estado_parcial: Mapped[str]
    estado_no_resuelto: Mapped[str]
    lista_verificacion: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    activa: Mapped[bool] = mapped_column(default=True)
    propiedades: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class OrdenMantenimiento(ConResponsabilidad, Base):
    """Un mantenimiento concreto: Programada -> En curso -> Terminada (o Cancelada)."""

    __tablename__ = "ordenes_mantenimiento"

    id: Mapped[int] = mapped_column(primary_key=True)
    plantilla_id: Mapped[int] = mapped_column(ForeignKey("plantillas_mantenimiento.id"))
    recurso: Mapped[str]
    recurso_id: Mapped[int]
    origen: Mapped[str]                      # ESTADO, PERIODICO o MANUAL
    estado: Mapped[str] = mapped_column(default="PROGRAMADA")
    fecha_programada: Mapped[date] = mapped_column(default=date.today)
    iniciada_en: Mapped[datetime | None]
    iniciada_por: Mapped[int | None]
    terminada_en: Mapped[datetime | None]
    terminada_por: Mapped[int | None]
    resultado: Mapped[str | None]            # RESUELTO, PARCIAL o NO_RESUELTO
    respuestas: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notas: Mapped[str | None]
    estado_recurso_nuevo: Mapped[str | None]
    motivo_cancelacion: Mapped[str | None]
    propiedades: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class OrdenTecnico(Base):
    """Técnico asignado a una orden. Quitarlo marca quitado_en; la fila no se borra."""

    __tablename__ = "ordenes_tecnicos"

    id: Mapped[int] = mapped_column(primary_key=True)
    orden_id: Mapped[int] = mapped_column(ForeignKey("ordenes_mantenimiento.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    asignado_en: Mapped[datetime] = mapped_column(default=ahora)
    asignado_por: Mapped[int | None]
    quitado_en: Mapped[datetime | None]
    quitado_por: Mapped[int | None]


# -------------------------------------------------------------------- audit
class RegistroAuditoria(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    evento_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    fecha: Mapped[datetime]
    registrado_en: Mapped[datetime] = mapped_column(default=ahora)
    usuario_id: Mapped[int | None]
    usuario_nombre: Mapped[str | None]
    rol: Mapped[str | None]
    ip: Mapped[str | None]
    accion: Mapped[str]
    recurso: Mapped[str]
    recurso_id: Mapped[int | None]
    antes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    despues: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    motivo: Mapped[str | None]
    correlation_id: Mapped[str | None]
    trace_id: Mapped[str | None]
    hash_anterior: Mapped[str]
    hash: Mapped[str]
    firma: Mapped[str]
    llave_id: Mapped[str]
