"""Pruebas del almacén local de archivos-service, sin Docker.

    pip install pytest
    pytest tests/test_archivos.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from services.archivos.app import almacen  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"0" * 64
SECRETO = "s" * 48


class TipoTest(unittest.TestCase):
    def test_el_tipo_sale_del_contenido(self):
        for contenido, tipo in ((PNG, "image/png"), (JPG, "image/jpeg"), (WEBP, "image/webp"), (PDF, "application/pdf")):
            self.assertEqual(almacen.detectar_tipo(contenido), tipo)

    def test_html_o_svg_disfrazados_no_pasan(self):
        for contenido in (b"<html><script>alert(1)</script>", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"MZ\x90\x00"):
            self.assertIsNone(almacen.detectar_tipo(contenido))


class AlmacenTest(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory()
        self.almacen = almacen.AlmacenLocal(self.carpeta.name)

    def tearDown(self):
        self.carpeta.cleanup()

    def test_guarda_con_su_sha256_y_no_repite(self):
        uno = self.almacen.guardar("edificios/7", PNG, "imagen")
        dos = self.almacen.guardar("edificios/7", PNG, "imagen")
        self.assertEqual(uno, dos)
        self.assertRegex(uno.clave, r"^edificios/7/[0-9a-f]{64}\.png$")
        self.assertEqual(self.almacen.ruta_para_leer(uno.clave)[0].read_bytes(), PNG)

    def test_rechaza_tipo_tamano_y_vacio(self):
        casos = ((b"hola", "documento", 422), (PDF, "imagen", 422), (b"", "documento", 422),
                 (PDF + b"0" * (1024 * 1024), "documento", 413))
        for contenido, categoria, estado in casos:
            with self.subTest(estado=estado, categoria=categoria), self.assertRaises(almacen.ErrorArchivo) as e:
                self.almacen.guardar("ordenes/1", contenido, categoria, tamano_max_mb=1)
            self.assertEqual(e.exception.estado, estado)

    def test_claves_y_carpetas_que_salen_del_almacen_se_rechazan(self):
        for clave in ("../../etc/passwd", "edificios/../../x/" + "a" * 64 + ".png", "/abs/" + "a" * 64 + ".png",
                      "edificios/7/" + "a" * 64 + ".html"):
            with self.subTest(clave=clave), self.assertRaises(almacen.ErrorArchivo):
                self.almacen.ruta_para_leer(clave)
        with self.assertRaises(almacen.ErrorArchivo):
            self.almacen.guardar("../fuera", PNG)

    def test_borrar_quita_el_archivo(self):
        guardado = self.almacen.guardar("areas/3", PDF)
        self.almacen.borrar(guardado.clave)
        with self.assertRaises(almacen.ErrorArchivo) as e:
            self.almacen.ruta_para_leer(guardado.clave)
        self.assertEqual(e.exception.estado, 404)


class FirmaTest(unittest.TestCase):
    CLAVE = "edificios/7/" + "a" * 64 + ".png"

    def test_url_firmada_vale_hasta_que_caduca(self):
        url = almacen.url_firmada(SECRETO, self.CLAVE, 60, ahora=1000)
        self.assertTrue(url.startswith("/api/v1/archivos/descarga?"))
        firma = almacen.firmar(SECRETO, self.CLAVE, 1060)
        almacen.verificar_firma(SECRETO, self.CLAVE, 1060, firma, ahora=1059)   # no lanza
        with self.assertRaisesRegex(almacen.ErrorArchivo, "caducó"):
            almacen.verificar_firma(SECRETO, self.CLAVE, 1060, firma, ahora=1061)

    def test_firma_cambiada_otra_clave_u_otro_secreto_no_valen(self):
        firma = almacen.firmar(SECRETO, self.CLAVE, 2000)
        otra = "edificios/8/" + "a" * 64 + ".png"
        for clave, f in ((self.CLAVE, firma[:-1] + "0"), (otra, firma), (self.CLAVE, almacen.firmar("x" * 48, self.CLAVE, 2000))):
            with self.subTest(clave=clave), self.assertRaisesRegex(almacen.ErrorArchivo, "no es válido"):
                almacen.verificar_firma(SECRETO, clave, 2000, f, ahora=1000)


if __name__ == "__main__":
    unittest.main()
