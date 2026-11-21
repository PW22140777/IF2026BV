"""Esquemas Pydantic de plantillas y órdenes de mantenimiento."""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from comun.propiedades import DefinicionPropiedad, claves_unicas
from comun.recursos import SalidaBase

RecursoMantenible = Literal["EDIFICIO", "AREA", "INVENTARIO", "SERVICIO"]
Disparo = Literal["ESTADO", "PERIODICO", "MANUAL"]
Resultado = Literal["RESUELTO", "PARCIAL", "NO_RESUELTO"]

# Estados válidos de cada recurso (coinciden con los CHECK de sus tablas)
ESTADOS_RECURSO: dict[str, tuple[str, ...]] = {
    "EDIFICIO": ("OPERATIVO", "EN_MANTENIMIENTO", "FUERA_DE_SERVICIO"),
    "AREA": ("OPERATIVO", "EN_MANTENIMIENTO", "FUERA_DE_SERVICIO"),
    "INVENTARIO": ("BUENO", "REGULAR", "MALO", "FUERA_DE_SERVICIO"),
    "SERVICIO": ("OPERANDO", "CON_FALLA", "SUSPENDIDO", "EN_MANTENIMIENTO"),
}
TEXTO_CORTO = {"min_length": 1, "max_length": 120}


# ---------------------------------------------------------------- plantillas
class _ReglasPlantilla(BaseModel):
    """Revisa que los estados correspondan al tipo de recurso y que el disparo tenga lo que necesita."""

    @model_validator(mode="after")
    def coherente(self):
        recurso = getattr(self, "recurso", None)
        if recurso is None:      # al modificar, el recurso no cambia: lo revisa el gancho validar
            return self
        validos = ESTADOS_RECURSO[recurso]
        for campo in ("estado_al_iniciar", "estado_resuelto", "estado_parcial", "estado_no_resuelto"):
            valor = getattr(self, campo, None)
            if valor is not None and valor not in validos:
                raise ValueError(f"«{valor}» no es un estado de {recurso.lower()}; usa uno de: {', '.join(validos)}")
        for estado in getattr(self, "estados_disparo", None) or []:
            if estado not in validos:
                raise ValueError(f"«{estado}» no es un estado de {recurso.lower()}; usa uno de: {', '.join(validos)}")
        if getattr(self, "tipo_elemento", None) and recurso != "INVENTARIO":
            raise ValueError("Solo las plantillas de inventario llevan tipo de elemento")
        disparo = getattr(self, "disparo", None)
        if disparo == "ESTADO" and not self.estados_disparo:
            raise ValueError("Una plantilla que se dispara por estado necesita al menos un estado")
        if disparo == "PERIODICO" and not self.cada_dias:
            raise ValueError("Una plantilla periódica necesita «cada cuántos días»")
        return self


class PlantillaCrear(_ReglasPlantilla):
    model_config = ConfigDict(str_strip_whitespace=True)

    nombre: str = Field(**TEXTO_CORTO, examples=["Preventivo de aire acondicionado"])
    descripcion: str | None = Field(default=None, max_length=2000)
    recurso: RecursoMantenible
    tipo_elemento: str | None = Field(default=None, max_length=60, description="Solo inventario; vacío = cualquier tipo")
    disparo: Disparo = "MANUAL"
    estados_disparo: list[str] = Field(default_factory=list, max_length=4)
    cada_dias: int | None = Field(default=None, ge=1, le=3650)
    estado_al_iniciar: str | None = None
    estado_resuelto: str
    estado_parcial: str
    estado_no_resuelto: str
    lista_verificacion: list[DefinicionPropiedad] = Field(default_factory=list, max_length=40)
    activa: bool = True
    propiedades: dict[str, Any] = Field(default_factory=dict)

    _unicas = field_validator("lista_verificacion")(claves_unicas)


class PlantillaActualizar(BaseModel):
    """El recurso de una plantilla no cambia: sus órdenes ya apuntan a ese tipo de recurso."""

    model_config = ConfigDict(str_strip_whitespace=True)

    nombre: str = Field(default=None, **TEXTO_CORTO)
    descripcion: str | None = Field(default=None, max_length=2000)
    tipo_elemento: str | None = Field(default=None, max_length=60)
    disparo: Disparo = Field(default=None)
    estados_disparo: list[str] = Field(default=None, max_length=4)
    cada_dias: int | None = Field(default=None, ge=1, le=3650)
    estado_al_iniciar: str | None = None
    estado_resuelto: str = Field(default=None)
    estado_parcial: str = Field(default=None)
    estado_no_resuelto: str = Field(default=None)
    lista_verificacion: list[DefinicionPropiedad] = Field(default=None, max_length=40)
    activa: bool = Field(default=None)
    propiedades: dict[str, Any] = Field(default=None)

    _unicas = field_validator("lista_verificacion")(claves_unicas)


class PlantillaSalida(SalidaBase):
    nombre: str
    descripcion: str | None
    recurso: str
    tipo_elemento: str | None
    disparo: str
    estados_disparo: list[str]
    cada_dias: int | None
    estado_al_iniciar: str | None
    estado_resuelto: str
    estado_parcial: str
    estado_no_resuelto: str
    lista_verificacion: list[dict[str, Any]]
    activa: bool


# -------------------------------------------------------------------- órdenes
class OrdenCrear(BaseModel):
    plantilla_id: int = Field(gt=0)
    recurso_id: int = Field(gt=0, description="El tipo de recurso lo dice la plantilla")
    fecha_programada: date | None = Field(default=None, description="Vacío = hoy")
    tecnicos: list[int] = Field(default_factory=list, max_length=10,
                                description="Vacío: si la crea un Técnico, queda asignada a él")


class OrdenSalida(BaseModel):
    """Estado completo de una orden: es lo que guarda el historial (antes y después)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    plantilla_id: int
    recurso: str
    recurso_id: int
    origen: str
    estado: str
    fecha_programada: date
    iniciada_en: datetime | None
    iniciada_por: int | None
    terminada_en: datetime | None
    terminada_por: int | None
    resultado: str | None
    respuestas: dict[str, Any]
    notas: str | None
    estado_recurso_nuevo: str | None
    motivo_cancelacion: str | None
    creado_en: datetime
    creado_por: int | None
    tecnicos: list[int] = []


class Persona(BaseModel):
    id: int
    nombre: str


class OrdenDetalle(OrdenSalida):
    """Lo que ve la interfaz: la orden con los nombres que necesita para mostrarse."""

    plantilla_nombre: str
    recurso_nombre: str
    lista_verificacion: list[dict[str, Any]]
    asignados: list[Persona]
    iniciada_por_nombre: str | None = None
    terminada_por_nombre: str | None = None
