"""Propiedades definidas: listas de campos que un catálogo pide capturar.

Las usan dos catálogos con el mismo formato:
  - tipos_elemento.propiedades_definidas: qué datos lleva cada tipo de inventario (inmuebles).
  - plantillas_mantenimiento.lista_verificacion: qué se registra al terminar un mantenimiento.

Cada definición: {"clave", "etiqueta", "tipo", "unidad", "minimo", "maximo", "opciones", "requerida"}
con tipo texto, numero, opcion, fecha o si_no.
"""
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TipoPropiedad = Literal["texto", "numero", "opcion", "fecha", "si_no"]
# Claves que calcula el sistema (totales del inventario): nadie las define ni las captura
PROPIEDADES_RESERVADAS = {"total", "total_lineal", "total_area", "total_volumen", "total_volumen_espesor"}


class DefinicionPropiedad(BaseModel):
    """Un campo que se pide capturar, p. ej. la capacidad en BTU de un aire acondicionado."""

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


def claves_unicas(definiciones: list[DefinicionPropiedad] | None):
    """Validador de Pydantic: dos campos de la misma lista no pueden tener la misma clave."""
    if definiciones:
        claves = [d.clave for d in definiciones]
        repetidas = sorted({c for c in claves if claves.count(c) > 1})
        if repetidas:
            raise ValueError(f"Hay propiedades con la misma clave: {', '.join(repetidas)}")
    return definiciones


def revisar_valores(definiciones: list[dict], valores: dict[str, Any], donde: str) -> tuple[dict, list[str]]:
    """Revisa valores capturados contra sus definiciones.

    Devuelve los valores sin los vacíos y la lista de problemas encontrados.
    `donde` completa el mensaje de lo obligatorio, p. ej. «aire acondicionado».
    Las claves que no están definidas se aceptan tal cual (datos extra).
    """
    limpias = {clave: valor for clave, valor in valores.items() if valor is not None and valor != ""}
    errores = []
    for definicion in definiciones:
        clave, etiqueta, clase = definicion["clave"], definicion["etiqueta"], definicion["tipo"]
        if clave not in limpias:
            if definicion.get("requerida"):
                errores.append(f"«{etiqueta}» es obligatoria en {donde}")
            continue
        valor = limpias[clave]
        if clase == "numero":
            # bool es subclase de int en Python: true no debe pasar como número
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                errores.append(f"«{etiqueta}» debe ser un número")
            elif definicion.get("minimo") is not None and valor < definicion["minimo"]:
                errores.append(f"«{etiqueta}» debe ser {definicion['minimo']:g} o más")
            elif definicion.get("maximo") is not None and valor > definicion["maximo"]:
                errores.append(f"«{etiqueta}» debe ser {definicion['maximo']:g} o menos")
        elif clase == "opcion" and valor not in definicion["opciones"]:
            errores.append(f"«{etiqueta}» debe ser una de: {', '.join(definicion['opciones'])}")
        elif clase == "si_no" and not isinstance(valor, bool):
            errores.append(f"«{etiqueta}» debe ser sí o no (true o false)")
        elif clase == "texto" and (not isinstance(valor, str) or len(valor) > 500):
            errores.append(f"«{etiqueta}» debe ser un texto de hasta 500 caracteres")
        elif clase == "fecha":
            try:
                if date.fromisoformat(valor) > date.today():
                    errores.append(f"«{etiqueta}» no puede ser una fecha futura")
            except (TypeError, ValueError):
                errores.append(f"«{etiqueta}» debe ser una fecha AAAA-MM-DD")
    return limpias, errores
