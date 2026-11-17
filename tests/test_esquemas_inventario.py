"""Pruebas del contrato HTTP para los atributos de inventario."""
import unittest
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import ValidationError

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "shared"))

from services.inmuebles.app.esquemas import ElementoActualizar, ElementoCrear, ElementoSalida


class ContratoInventarioTest(unittest.TestCase):
    def test_crear_acepta_atributos_nuevos_y_no_expone_total_como_entrada(self):
        datos = ElementoCrear(
            area_id=1,
            tipo="MURO",
            eje="A",
            tramo="1-2",
            unidad="m",
            largo=3.25,
            alto=2.5,
            ancho=0.2,
            espesor=0.15,
            fecha_recuento="2026-11-09",
        )

        self.assertEqual(datos.fecha_recuento, date(2026, 11, 9))
        self.assertNotIn("total", datos.model_dump())

        with self.assertRaisesRegex(ValidationError, "total_lineal"):
            ElementoCrear(area_id=1, tipo="MURO", total_lineal=99)

    def test_medidas_negativas_se_rechazan(self):
        for campo in ("largo", "alto", "ancho", "espesor"):
            with self.subTest(campo=campo), self.assertRaises(ValidationError):
                ElementoCrear(area_id=1, tipo="MURO", **{campo: -0.01})

    def test_actualizar_permite_limpiar_atributos_opcionales(self):
        cambios = ElementoActualizar(eje=None, largo=None, fecha_recuento=None)

        self.assertEqual(cambios.model_dump(exclude_unset=True), {
            "eje": None,
            "largo": None,
            "fecha_recuento": None,
        })

    def test_actualizar_rechaza_total_y_campos_desconocidos(self):
        with self.assertRaisesRegex(ValidationError, "total"):
            ElementoActualizar(total=10)

        with self.assertRaisesRegex(ValidationError, "atributo_inexistente"):
            ElementoActualizar(atributo_inexistente="x")

    def test_propiedades_no_admiten_una_clave_total(self):
        with self.assertRaisesRegex(ValidationError, "reservad"):
            ElementoCrear(area_id=1, tipo="MURO", propiedades={"total": 10})

        with self.assertRaisesRegex(ValidationError, "reservad"):
            ElementoActualizar(propiedades={"TOTAL": 10})

        with self.assertRaisesRegex(ValidationError, "reservados"):
            ElementoActualizar(propiedades={"total_area": 10})

    def test_salida_calcula_todas_las_magnitudes_disponibles(self):
        salida = ElementoSalida(
            id=1,
            area_id=1,
            tipo="MURO",
            eje="A",
            tramo="1-2",
            unidad="m",
            largo=2,
            alto=1.5,
            ancho=0.2,
            espesor=0.15,
            fecha_recuento=date(2026, 11, 10),
            descripcion=None,
            cantidad=3,
            marca=None,
            modelo=None,
            numero_serie=None,
            estado="BUENO",
            propiedades={},
            creado_en=datetime.now(timezone.utc),
            creado_por=1,
            modificado_en=None,
            modificado_por=None,
            eliminado_en=None,
            eliminado_por=None,
            motivo_eliminacion=None,
        )

        self.assertEqual(salida.total_lineal, 6)
        self.assertEqual(salida.total_area, 9)
        self.assertEqual(salida.total_volumen, 1.8)
        self.assertEqual(salida.total_volumen_espesor, 1.35)

    def test_salida_deja_en_null_calculos_sin_medidas_suficientes(self):
        datos = {
            "id": 1, "area_id": 1, "tipo": "CABLE", "eje": None, "tramo": None,
            "unidad": "m", "largo": 5, "alto": None, "ancho": None, "espesor": None,
            "fecha_recuento": None, "descripcion": None, "cantidad": 2, "marca": None,
            "modelo": None, "numero_serie": None, "estado": "BUENO", "propiedades": {},
            "creado_en": datetime.now(timezone.utc), "creado_por": 1, "modificado_en": None,
            "modificado_por": None, "eliminado_en": None, "eliminado_por": None,
            "motivo_eliminacion": None,
        }
        salida = ElementoSalida(**datos)

        self.assertEqual(salida.total_lineal, 10)
        self.assertIsNone(salida.total_area)
        self.assertIsNone(salida.total_volumen)
        self.assertIsNone(salida.total_volumen_espesor)


if __name__ == "__main__":
    unittest.main()
