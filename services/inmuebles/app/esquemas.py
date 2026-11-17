"""Esquemas Pydantic de edificios, áreas e inventario.

En los esquemas *Actualizar*, un campo omitido no se cambia. Los campos
que en la base no aceptan vacío (p. ej. nombre) tampoco aceptan null.
"""
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from comun.recursos import SalidaBase

EstadoInmueble = Literal["OPERATIVO", "EN_MANTENIMIENTO", "FUERA_DE_SERVICIO"]
EstadoElemento = Literal["BUENO", "REGULAR", "MALO", "FUERA_DE_SERVICIO"]
# Catálogo de tipos de espacio: interiores y exteriores (coincide con el CHECK de la tabla areas)
TipoArea = Literal[
    "AULA", "LABORATORIO", "BIBLIOTECA", "OFICINA", "BANO",
    "CANCHA", "ESTACIONAMIENTO", "AREA_VERDE", "BANCAS", "PATIO",
]
# Unidades lineales base del inventario: los totales salen en esa unidad, ² y ³
UnidadLineal = Literal["mm", "cm", "m"]
TEXTO_CORTO = {"min_length": 1, "max_length": 120}
# Quita espacios al inicio y al final: así "   " cuenta como vacío y no pasa min_length
LIMPIA_TEXTO = ConfigDict(str_strip_whitespace=True)

# Límites razonables para que un error de captura (un cero de más) no se guarde
MAX_SUPERFICIE_M2 = 10_000_000      # 1000 hectáreas
MAX_CAPACIDAD = 100_000
MAX_NIVELES = 200
MAX_CANTIDAD = 1_000_000
MAX_MEDIDA = 1_000_000
# El tipo de elemento es una clave: mayúsculas, números y guion bajo (AIRE_ACONDICIONADO)
PATRON_TIPO_ELEMENTO = r"^[A-ZÑ0-9_]+$"


def _anio_no_futuro(valor: int | None) -> int | None:
    if valor is not None and valor > date.today().year:
        raise ValueError(f"El año de construcción no puede ser posterior a {date.today().year}")
    return valor


def _fecha_no_futura(valor: date | None) -> date | None:
    if valor is not None and valor > date.today():
        raise ValueError("La fecha de recuento no puede ser posterior a hoy")
    return valor


# -------------------------------------------------------------------- campus
class CampusSalida(SalidaBase):
    clave: str
    nombre: str
    direccion: str | None
    ciudad: str | None
    superficie_m2: float | None
    estado: str
    descripcion: str | None


# ----------------------------------------------------------------- edificios
class EdificioCrear(BaseModel):
    model_config = LIMPIA_TEXTO

    campus_id: int = Field(description="Campus al que pertenece (no se puede cambiar después)")
    clave: str = Field(**TEXTO_CORTO, examples=["ED-A"])
    nombre: str = Field(**TEXTO_CORTO, examples=["Edificio A - Aulas"])
    niveles: int | None = Field(default=None, ge=1, le=MAX_NIVELES,
                                description="Pisos del edificio; se numeran de 0 (planta baja) a niveles - 1")
    anio_construccion: int | None = Field(default=None, ge=1800, description="No puede ser posterior al año actual")
    superficie_m2: float | None = Field(default=None, gt=0, le=MAX_SUPERFICIE_M2)
    estado: EstadoInmueble = "OPERATIVO"
    descripcion: str | None = Field(default=None, max_length=2000)
    propiedades: dict[str, Any] = Field(default_factory=dict, examples=[{"material": "concreto"}])

    _anio = field_validator("anio_construccion")(_anio_no_futuro)


class EdificioActualizar(BaseModel):
    model_config = LIMPIA_TEXTO

    clave: str = Field(default=None, **TEXTO_CORTO)
    nombre: str = Field(default=None, **TEXTO_CORTO)
    niveles: int | None = Field(default=None, ge=1, le=MAX_NIVELES,
                                description="Pisos del edificio; se numeran de 0 (planta baja) a niveles - 1")
    anio_construccion: int | None = Field(default=None, ge=1800, description="No puede ser posterior al año actual")
    superficie_m2: float | None = Field(default=None, gt=0, le=MAX_SUPERFICIE_M2)
    estado: EstadoInmueble = Field(default=None)
    descripcion: str | None = Field(default=None, max_length=2000)
    propiedades: dict[str, Any] = Field(default=None)

    _anio = field_validator("anio_construccion")(_anio_no_futuro)


class EdificioSalida(SalidaBase):
    campus_id: int
    clave: str
    nombre: str
    niveles: int | None
    anio_construccion: int | None
    superficie_m2: float | None
    estado: str
    descripcion: str | None


# --------------------------------------------------------------------- áreas
class AreaCrear(BaseModel):
    model_config = LIMPIA_TEXTO

    campus_id: int | None = Field(default=None, description="Obligatorio si no tiene edificio; si tiene, se toma el del edificio")
    edificio_id: int | None = Field(default=None, description="Vacío = área independiente (cancha, bancas...)")
    nombre: str = Field(**TEXTO_CORTO, examples=["Laboratorio 3"])
    tipo: TipoArea = Field(examples=["LABORATORIO"])
    piso: int | None = Field(default=None, ge=0, lt=MAX_NIVELES,
                             description="0 = planta baja; debe existir en el edificio. Vacío si no tiene edificio")
    capacidad: int | None = Field(default=None, ge=0, le=MAX_CAPACIDAD)
    superficie_m2: float | None = Field(default=None, gt=0, le=MAX_SUPERFICIE_M2)
    exterior: bool = False
    estado: EstadoInmueble = "OPERATIVO"
    descripcion: str | None = Field(default=None, max_length=2000)
    propiedades: dict[str, Any] = Field(default_factory=dict)


class AreaActualizar(BaseModel):
    model_config = LIMPIA_TEXTO

    campus_id: int = Field(default=None, description="Solo para áreas independientes")
    edificio_id: int | None = Field(default=None, description="null = convertir en área independiente")
    nombre: str = Field(default=None, **TEXTO_CORTO)
    tipo: TipoArea = Field(default=None)
    piso: int | None = Field(default=None, ge=0, lt=MAX_NIVELES,
                             description="0 = planta baja; debe existir en el edificio. Vacío si no tiene edificio")
    capacidad: int | None = Field(default=None, ge=0, le=MAX_CAPACIDAD)
    superficie_m2: float | None = Field(default=None, gt=0, le=MAX_SUPERFICIE_M2)
    exterior: bool = Field(default=None)
    estado: EstadoInmueble = Field(default=None)
    descripcion: str | None = Field(default=None, max_length=2000)
    propiedades: dict[str, Any] = Field(default=None)


class AreaSalida(SalidaBase):
    campus_id: int
    edificio_id: int | None
    nombre: str
    tipo: str
    piso: int | None
    capacidad: int | None
    superficie_m2: float | None
    exterior: bool
    estado: str
    descripcion: str | None


# ---------------------------------------------------------- tipos de elemento
TipoPropiedad = Literal["texto", "numero", "opcion", "fecha", "si_no"]
PROPIEDADES_RESERVADAS = {"total", "total_lineal", "total_area", "total_volumen", "total_volumen_espesor"}


class DefinicionPropiedad(BaseModel):
    """Una propiedad que llevan los elementos de un tipo, p. ej. la capacidad en BTU de un aire."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    clave: str = Field(pattern=r"^[a-z][a-z0-9_]{0,49}$", examples=["btu"],
                       description="Nombre interno: minúsculas, números y guion bajo")
    etiqueta: str = Field(min_length=1, max_length=80, examples=["Capacidad"])
    tipo: TipoPropiedad
    unidad: str | None = Field(default=None, max_length=20, examples=["BTU"])
    minimo: float | None = None
    maximo: float | None = None
    opciones: list[str] | None = Field(default=None, max_length=50)
    requerida: bool = False

    @model_validator(mode="after")
    def coherente(self):
        if self.tipo == "opcion":
            opciones = [o.strip() for o in self.opciones or [] if o.strip()]
            if len(opciones) < 2:
                raise ValueError(f"La propiedad «{self.etiqueta}» es de opción: indica al menos dos opciones")
            if len(set(opciones)) != len(opciones):
                raise ValueError(f"La propiedad «{self.etiqueta}» tiene opciones repetidas")
            self.opciones = opciones
        elif self.opciones:
            raise ValueError(f"Solo las propiedades de tipo opción llevan opciones («{self.etiqueta}»)")
        if self.tipo != "numero" and (self.minimo is not None or self.maximo is not None):
            raise ValueError(f"Solo las propiedades numéricas llevan mínimo y máximo («{self.etiqueta}»)")
        if self.minimo is not None and self.maximo is not None and self.minimo > self.maximo:
            raise ValueError(f"En «{self.etiqueta}» el mínimo es mayor que el máximo")
        if self.clave in PROPIEDADES_RESERVADAS:
            raise ValueError(f"La clave «{self.clave}» está reservada por el sistema")
        return self


def _claves_unicas(definiciones: list[DefinicionPropiedad] | None):
    if definiciones:
        claves = [d.clave for d in definiciones]
        repetidas = sorted({c for c in claves if claves.count(c) > 1})
        if repetidas:
            raise ValueError(f"Hay propiedades con la misma clave: {', '.join(repetidas)}")
    return definiciones


class TipoElementoCrear(BaseModel):
    model_config = LIMPIA_TEXTO

    clave: str = Field(min_length=1, max_length=60, pattern=PATRON_TIPO_ELEMENTO, examples=["AIRE_ACONDICIONADO"],
                       description="La que se guarda en cada elemento; no se puede cambiar después")
    nombre: str = Field(**TEXTO_CORTO, examples=["Aire acondicionado"])
    descripcion: str | None = Field(default=None, max_length=2000)
    usa_medidas: bool = Field(default=False, description="Si sus elementos llevan largo, alto, ancho o espesor")
    propiedades_definidas: list[DefinicionPropiedad] = Field(default_factory=list, max_length=40)
    propiedades: dict[str, Any] = Field(default_factory=dict)

    _unicas = field_validator("propiedades_definidas")(_claves_unicas)


class TipoElementoActualizar(BaseModel):
    model_config = LIMPIA_TEXTO

    nombre: str = Field(default=None, **TEXTO_CORTO)
    descripcion: str | None = Field(default=None, max_length=2000)
    usa_medidas: bool = Field(default=None)
    propiedades_definidas: list[DefinicionPropiedad] = Field(default=None, max_length=40)
    propiedades: dict[str, Any] = Field(default=None)

    _unicas = field_validator("propiedades_definidas")(_claves_unicas)


class TipoElementoSalida(SalidaBase):
    clave: str
    nombre: str
    descripcion: str | None
    usa_medidas: bool
    propiedades_definidas: list[dict[str, Any]]


# ---------------------------------------------------------------- inventario
def _sin_total_en_propiedades(valor: dict[str, Any] | None):
    if valor and any(clave.casefold() in PROPIEDADES_RESERVADAS for clave in valor):
        raise ValueError("Los campos de totales están reservados por el sistema")
    return valor


def _producto(cantidad: int, *medidas: float | None) -> float | None:
    if any(medida is None for medida in medidas):
        return None
    resultado = float(cantidad)
    for medida in medidas:
        resultado *= medida  # type: ignore[operator]
    return round(resultado, 4)


class ElementoCrear(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    area_id: int
    tipo: str = Field(**TEXTO_CORTO, pattern=PATRON_TIPO_ELEMENTO, examples=["AIRE_ACONDICIONADO"])
    eje: str | None = Field(default=None, min_length=1, max_length=120)
    tramo: str | None = Field(default=None, min_length=1, max_length=120)
    unidad: UnidadLineal | None = Field(default=None, description="Obligatoria si se registra alguna medida")
    largo: float | None = Field(default=None, gt=0, le=MAX_MEDIDA)
    alto: float | None = Field(default=None, gt=0, le=MAX_MEDIDA)
    ancho: float | None = Field(default=None, gt=0, le=MAX_MEDIDA)
    espesor: float | None = Field(default=None, gt=0, le=MAX_MEDIDA)
    fecha_recuento: date | None = None
    descripcion: str | None = Field(default=None, max_length=2000)
    cantidad: int = Field(default=1, ge=1, le=MAX_CANTIDAD)
    marca: str | None = Field(default=None, max_length=120)
    modelo: str | None = Field(default=None, max_length=120)
    numero_serie: str | None = Field(default=None, max_length=120)
    estado: EstadoElemento = "BUENO"
    propiedades: dict[str, Any] = Field(default_factory=dict, examples=[{"btu": 12000, "gas": "R410A"}])

    _validar_propiedades = field_validator("propiedades")(_sin_total_en_propiedades)
    _fecha = field_validator("fecha_recuento")(_fecha_no_futura)


class ElementoActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    area_id: int = Field(default=None, description="Mover el elemento a otra área")
    tipo: str = Field(default=None, **TEXTO_CORTO, pattern=PATRON_TIPO_ELEMENTO)
    eje: str | None = Field(default=None, min_length=1, max_length=120)
    tramo: str | None = Field(default=None, min_length=1, max_length=120)
    unidad: UnidadLineal | None = Field(default=None, description="Obligatoria si se registra alguna medida")
    largo: float | None = Field(default=None, gt=0, le=MAX_MEDIDA)
    alto: float | None = Field(default=None, gt=0, le=MAX_MEDIDA)
    ancho: float | None = Field(default=None, gt=0, le=MAX_MEDIDA)
    espesor: float | None = Field(default=None, gt=0, le=MAX_MEDIDA)
    fecha_recuento: date | None = None
    descripcion: str | None = Field(default=None, max_length=2000)
    cantidad: int = Field(default=None, ge=1, le=MAX_CANTIDAD)
    marca: str | None = Field(default=None, max_length=120)
    modelo: str | None = Field(default=None, max_length=120)
    numero_serie: str | None = Field(default=None, max_length=120)
    estado: EstadoElemento = Field(default=None)
    propiedades: dict[str, Any] = Field(default=None)

    _validar_propiedades = field_validator("propiedades")(_sin_total_en_propiedades)
    _fecha = field_validator("fecha_recuento")(_fecha_no_futura)


class ElementoSalida(SalidaBase):
    area_id: int
    tipo: str
    eje: str | None
    tramo: str | None
    unidad: str | None
    largo: float | None
    alto: float | None
    ancho: float | None
    espesor: float | None
    fecha_recuento: date | None
    descripcion: str | None
    cantidad: int
    marca: str | None
    modelo: str | None
    numero_serie: str | None
    estado: str

    @computed_field
    @property
    def total_lineal(self) -> float | None:
        return _producto(self.cantidad, self.largo)

    @computed_field
    @property
    def total_area(self) -> float | None:
        return _producto(self.cantidad, self.largo, self.alto)

    @computed_field
    @property
    def total_volumen(self) -> float | None:
        return _producto(self.cantidad, self.largo, self.alto, self.ancho)

    @computed_field
    @property
    def total_volumen_espesor(self) -> float | None:
        return _producto(self.cantidad, self.largo, self.alto, self.espesor)
