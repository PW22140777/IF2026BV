"""Prueba de humo del sistema completo, a través del gateway.

Con el sistema levantado (docker compose up), ejecuta:
    pip install httpx
    python tests/prueba_sistema.py

Recorre los tres roles, crea recursos, espera a que el historial llegue
por RabbitMQ, verifica la integridad de la auditoría y prueba las
sesiones (cambio de rol, desactivación, renovación y cierre de sesión) y
las contraseñas temporales.
Inicia sesión 5 veces: el gateway permite 5 por minuto, así que espera un
minuto antes de volver a ejecutarla.
"""
import sys
import time
import uuid

import httpx

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
cliente = httpx.Client(base_url=URL, timeout=15)
sufijo = uuid.uuid4().hex[:5].upper()


def paso(texto):
    print(f"  ok  {texto}")


def login(email, password):
    r = cliente.post("/api/v1/auth/login", data={"username": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def esperar(condicion, descripcion, segundos=20):
    limite = time.time() + segundos
    while time.time() < limite:
        if condicion():
            paso(descripcion)
            return
        time.sleep(1)
    raise SystemExit(f"FALLÓ: {descripcion} (no ocurrió en {segundos} s)")


def main():
    print(f"Probando {URL}")
    adm = login("admin@escuela.mx", "Admin12345")
    tec = login("tecnico@escuela.mx", "Tecnico12345")
    con = login("consulta@escuela.mx", "Consulta12345")
    paso("inicio de sesión de los tres roles")

    assert cliente.get("/api/v1/edificios").status_code == 401
    paso("sin token no se puede consultar")

    lista_campus = cliente.get("/api/v1/campus", headers=con)
    lista_campus.raise_for_status()
    campus_disponibles = lista_campus.json()
    assert {c["nombre"] for c in campus_disponibles} == {"Campus Centro", "Campus Norte"}, campus_disponibles
    assert cliente.post("/api/v1/campus", headers=tec, json={"clave": "OTRO", "nombre": "Otro"}).status_code == 405
    campus = campus_disponibles[0]
    ed = cliente.post("/api/v1/edificios", headers=tec,
                      json={"campus_id": campus["id"], "clave": f"ED-{sufijo}", "nombre": f"Edificio {sufijo}"})
    ed.raise_for_status()
    ed = ed.json()
    area = cliente.post("/api/v1/areas", headers=tec,
                        json={"campus_id": campus["id"], "nombre": f"Cancha {sufijo}", "tipo": "CANCHA", "exterior": True}).json()
    elem = cliente.post("/api/v1/inventario", headers=tec,
                        json={"area_id": area["id"], "tipo": "BANCA", "cantidad": 6}).json()
    agua = cliente.post("/api/v1/servicios", headers=tec,
                        json={"tipo": "AGUA", "nombre": f"Toma {sufijo}", "area_id": area["id"]}).json()
    general = cliente.post("/api/v1/servicios", headers=tec,
                           json={"tipo": "LUZ", "nombre": f"Medidor edificio {sufijo}", "edificio_id": ed["id"]}).json()
    servicios_campus = cliente.get("/api/v1/servicios", headers=con, params={"campus_id": campus["id"]}).json()
    assert {agua["id"], general["id"]}.issubset({s["id"] for s in servicios_campus})
    paso("campus fijos verificados (Centro y Norte); el Técnico crea edificio, área independiente, inventario y servicios")

    # Pisos: un edificio de 2 niveles solo tiene los pisos 0 (planta baja) y 1
    cliente.patch(f"/api/v1/edificios/{ed['id']}", headers=tec, json={"niveles": 2}).raise_for_status()
    aula = {"edificio_id": ed["id"], "nombre": f"Aula {sufijo}", "tipo": "AULA"}
    assert cliente.post("/api/v1/areas", headers=tec, json={**aula, "piso": 2}).status_code == 422
    aula = cliente.post("/api/v1/areas", headers=tec, json={**aula, "piso": 1})
    aula.raise_for_status()
    r = cliente.patch(f"/api/v1/edificios/{ed['id']}", headers=tec, json={"niveles": 1})
    assert r.status_code == 409 and "piso 1" in r.json()["detail"], r.text
    r = cliente.post("/api/v1/areas", headers=tec,
                     json={"campus_id": campus["id"], "nombre": f"Patio {sufijo}", "tipo": "PATIO", "piso": 0})
    assert r.status_code == 422, r.text
    assert cliente.post("/api/v1/inventario", headers=tec,
                        json={"area_id": area["id"], "tipo": "PARED", "largo": 3}).status_code == 422
    assert cliente.post("/api/v1/inventario", headers=tec,
                        json={"area_id": area["id"], "tipo": "PARED", "largo": -3, "unidad": "m"}).status_code == 422
    cliente.request("DELETE", f"/api/v1/areas/{aula.json()['id']}", headers=tec,
                    json={"motivo": "Limpieza de la prueba de pisos"}).raise_for_status()
    paso("el piso de un área debe existir en su edificio; las medidas son positivas y llevan unidad")

    # Catálogo de tipos de elemento: solo el Administrador lo cambia; cada tipo define sus propiedades
    clave_tipo = f"PRUEBA_{sufijo}"
    definicion = {"clave": clave_tipo, "nombre": f"Prueba {sufijo}", "usa_medidas": False, "propiedades_definidas": [
        {"clave": "potencia", "etiqueta": "Potencia", "tipo": "numero", "unidad": "W", "minimo": 1, "requerida": True},
        {"clave": "color", "etiqueta": "Color", "tipo": "opcion", "opciones": ["Rojo", "Azul"]},
    ]}
    assert cliente.post("/api/v1/tipos-elemento", headers=tec, json=definicion).status_code == 403
    tipo = cliente.post("/api/v1/tipos-elemento", headers=adm, json=definicion)
    tipo.raise_for_status()
    assert cliente.post("/api/v1/tipos-elemento", headers=adm, json=definicion).status_code == 409
    base = {"area_id": area["id"], "tipo": clave_tipo}
    for propiedades, extra in [({"color": "Rojo"}, {}),                       # falta la potencia (obligatoria)
                               ({"potencia": 0}, {}),                        # menor que el mínimo
                               ({"potencia": 60, "color": "Verde"}, {}),     # opción que no existe
                               ({"potencia": 60}, {"largo": 2, "unidad": "m"})]:   # el tipo no usa medidas
        r = cliente.post("/api/v1/inventario", headers=tec, json={**base, "propiedades": propiedades, **extra})
        assert r.status_code == 422, (propiedades, r.text)
    assert cliente.post("/api/v1/inventario", headers=tec, json={**base, "tipo": "NO_EXISTE"}).status_code == 422
    foco = cliente.post("/api/v1/inventario", headers=tec, json={**base, "propiedades": {"potencia": 60, "color": "Azul"}})
    foco.raise_for_status()
    foco = foco.json()
    r = cliente.put(f"/api/v1/inventario/{foco['id']}/propiedades/potencia", headers=tec, json={"valor": "mucha"})
    assert r.status_code == 422, r.text
    r = cliente.request("DELETE", f"/api/v1/tipos-elemento/{tipo.json()['id']}", headers=adm, json={"motivo": "Prueba"})
    assert r.status_code == 409, r.text
    cliente.request("DELETE", f"/api/v1/inventario/{foco['id']}", headers=tec, json={"motivo": "Limpieza de la prueba"}).raise_for_status()
    cliente.request("DELETE", f"/api/v1/tipos-elemento/{tipo.json()['id']}", headers=adm,
                    json={"motivo": "Limpieza de la prueba"}).raise_for_status()
    paso("cada tipo de elemento define sus propiedades y la API las valida; solo el Administrador cambia el catálogo")

    probar_observadores(adm, tec, con, ed)
    probar_mantenimientos(adm, tec, con, area, agua)

    internet = cliente.post("/api/v1/servicios", headers=tec,
                            json={"tipo": "INTERNET", "nombre": f"Enlace {sufijo}", "campus_id": campus["id"]}).json()
    assert cliente.post("/api/v1/consumos", headers=tec,
                        json={"servicio_id": internet["id"], "periodo": "2026-01-01", "cantidad": 10}).status_code == 422
    paso("internet y alcantarillado no registran consumo mensual")

    cliente.patch(f"/api/v1/servicios/{general['id']}", headers=tec, json={"estado": "CON_FALLA"}).raise_for_status()
    fallas = cliente.get("/api/v1/resumen/servicios", headers=con, params={"campus_id": campus["id"]}).json()
    assert any(s["id"] == general["id"] for s in fallas)
    paso("el resumen de servicios muestra el medidor general con falla")

    assert cliente.patch(f"/api/v1/inventario/{elem['id']}", headers=con, json={"estado": "MALO"}).status_code == 403
    paso("Consulta no puede modificar")

    cliente.patch(f"/api/v1/inventario/{elem['id']}", headers=tec, json={"estado": "MALO"}).raise_for_status()
    resumen = cliente.get("/api/v1/resumen/inmuebles", headers=con, params={"campus_id": campus["id"]}).json()
    assert resumen["inventario_por_tipo_y_estado"]["BANCA"].get("MALO", 0) >= 6, resumen
    assert resumen["areas_por_estado"].get("OPERATIVO", 0) >= 1, resumen
    assert any(e["id"] == ed["id"] for e in resumen["edificios_detalle"]), resumen
    paso("el resumen cuenta las 6 bancas en mal estado y lista el edificio nuevo")
    cliente.request("DELETE", f"/api/v1/inventario/{elem['id']}", headers=tec,
                    json={"motivo": "Bancas retiradas por daño"}).raise_for_status()
    cliente.request("DELETE", f"/api/v1/areas/{area['id']}", headers=tec,
                    json={"motivo": "Prueba de eliminación"}).raise_for_status()
    paso("el Técnico modifica y elimina con motivo")

    esperar(lambda: len(cliente.get(f"/api/v1/historial/inventario/{elem['id']}", headers=con).json()) == 3,
            "el historial del elemento llegó por RabbitMQ (crear, modificar, eliminar)")
    esperar(lambda: cliente.get(f"/api/v1/servicios/{agua['id']}", headers=con).json()["activo"] is False,
            "servicios-service desactivó el agua del área eliminada (evento asíncrono)")

    r = cliente.get("/api/v1/auditoria/verificar", headers=adm).json()
    assert r["integra"], r
    paso(f"auditoría íntegra ({r['registros_revisados']} registros firmados)")

    cliente.request("DELETE", f"/api/v1/edificios/{ed['id']}", headers=adm, json={"motivo": "Limpieza de la prueba"}).raise_for_status()
    esperar(lambda: cliente.get(f"/api/v1/servicios/{general['id']}", headers=con).json()["activo"] is False,
            "al eliminar el edificio se desactivó su medidor")
    cliente.request("DELETE", f"/api/v1/servicios/{agua['id']}", headers=adm, json={"motivo": "Limpieza de la prueba"})
    cliente.request("DELETE", f"/api/v1/servicios/{general['id']}", headers=adm, json={"motivo": "Limpieza de la prueba"})

    probar_usuarios_y_sesiones(adm, tec, con)
    print("Todo funcionó.")


def entrar_como_observador(correo, nombre):
    """Registro con cuenta institucional en modo de prueba (OAUTH_MODO_PRUEBA=true, solo base local)."""
    r = cliente.get("/api/v1/auth/oauth/inicio", params={"correo_prueba": correo, "nombre_prueba": nombre},
                    follow_redirects=False)
    assert r.status_code == 302, r.text
    destino = r.headers["location"]
    if "#codigo=" not in destino:
        return None, destino
    canje = cliente.post("/api/v1/auth/oauth/canjear", json={"codigo": destino.split("#codigo=")[1]})
    canje.raise_for_status()
    return {"Authorization": f"Bearer {canje.json()['access_token']}"}, canje.json()


def probar_mantenimientos(adm, tec, con, area, agua):
    plantillas = {p["nombre"]: p for p in cliente.get("/api/v1/mantenimientos/plantillas", headers=con).json()}
    correctivo = plantillas["Correctivo de aire acondicionado"]
    preventivo = plantillas["Preventivo de aire acondicionado"]
    reparacion = plantillas["Reparación de servicio con falla"]
    id_tecnico = cliente.get("/api/v1/auth/yo", headers=tec).json()["id"]
    assert cliente.post("/api/v1/mantenimientos/plantillas", headers=tec, json={
        "nombre": "No debe crearse", "recurso": "AREA", "estado_resuelto": "OPERATIVO",
        "estado_parcial": "OPERATIVO", "estado_no_resuelto": "FUERA_DE_SERVICIO"}).status_code == 403
    r = cliente.post("/api/v1/mantenimientos/plantillas", headers=adm, json={
        "nombre": "Mala", "recurso": "AREA", "estado_resuelto": "BUENO",
        "estado_parcial": "OPERATIVO", "estado_no_resuelto": "FUERA_DE_SERVICIO"})
    assert r.status_code == 422 and "no es un estado" in r.text, r.text
    paso("solo el Administrador crea plantillas, y sus estados deben ser del tipo de recurso")

    # Por estado: un aire acondicionado que pasa a «Malo» abre su orden correctiva
    aire = cliente.post("/api/v1/inventario", headers=tec, json={
        "area_id": area["id"], "tipo": "AIRE_ACONDICIONADO", "propiedades": {"btu": 12000}})
    aire.raise_for_status()
    aire = aire.json()
    cliente.patch(f"/api/v1/inventario/{aire['id']}", headers=tec, json={"estado": "MALO"}).raise_for_status()
    abiertas = lambda: cliente.get("/api/v1/mantenimientos/ordenes", headers=con, params={
        "recurso": "INVENTARIO", "recurso_id": aire["id"], "estado": "PROGRAMADA,EN_CURSO"}).json()
    esperar(lambda: any(o["plantilla_id"] == correctivo["id"] for o in abiertas()),
            "un aire acondicionado en mal estado abre solo su orden correctiva")
    orden = next(o for o in abiertas() if o["plantilla_id"] == correctivo["id"])
    url = f"/api/v1/mantenimientos/ordenes/{orden['id']}"

    assert cliente.post(f"{url}/iniciar", headers=tec).status_code == 403          # todavía sin asignar
    cliente.put(f"{url}/tecnicos", headers=adm, json={"tecnicos": [id_tecnico]}).raise_for_status()
    assert cliente.post(f"{url}/iniciar", headers=con).status_code == 403
    r = cliente.post(f"{url}/iniciar", headers=tec)
    assert r.status_code == 200 and r.json()["estado"] == "EN_CURSO", r.text
    r = cliente.post(f"{url}/terminar", headers=tec, json={"resultado": "RESUELTO", "respuestas": {}})
    assert r.status_code == 422 and "Diagnóstico" in r.text, r.text
    r = cliente.post(f"{url}/terminar", headers=tec, json={
        "resultado": "RESUELTO", "respuestas": {"diagnostico": "Capacitor dañado", "refrigerante_recargado": False},
        "notas": "Se cambió el capacitor"})
    r.raise_for_status()
    assert r.json()["terminada_por"] == id_tecnico and r.json()["estado_recurso_nuevo"] == "BUENO", r.text
    esperar(lambda: cliente.get(f"/api/v1/inventario/{aire['id']}", headers=con).json()["estado"] == "BUENO",
            "el técnico asignado inicia y termina con su lista de verificación; el aire queda en buen estado")

    # Un servicio con falla: al iniciar pasa a «En mantenimiento»; el Administrador puede cancelar
    cliente.patch(f"/api/v1/servicios/{agua['id']}", headers=tec, json={"estado": "CON_FALLA"}).raise_for_status()
    abiertas_agua = lambda: cliente.get("/api/v1/mantenimientos/ordenes", headers=con, params={
        "recurso": "SERVICIO", "recurso_id": agua["id"], "estado": "PROGRAMADA,EN_CURSO"}).json()
    esperar(lambda: any(o["plantilla_id"] == reparacion["id"] for o in abiertas_agua()),
            "un servicio con falla abre solo su orden de reparación")
    orden_agua = next(o for o in abiertas_agua() if o["plantilla_id"] == reparacion["id"])
    url_agua = f"/api/v1/mantenimientos/ordenes/{orden_agua['id']}"
    cliente.put(f"{url_agua}/tecnicos", headers=adm, json={"tecnicos": [id_tecnico]}).raise_for_status()
    cliente.post(f"{url_agua}/iniciar", headers=tec).raise_for_status()
    esperar(lambda: cliente.get(f"/api/v1/servicios/{agua['id']}", headers=con).json()["estado"] == "EN_MANTENIMIENTO",
            "al iniciar la reparación, el servicio pasa a «en mantenimiento»")
    assert cliente.post(f"{url_agua}/cancelar", headers=tec, json={"motivo": "No aplica"}).status_code == 403
    r = cliente.post(f"{url_agua}/cancelar", headers=adm, json={"motivo": "Prueba de cancelación"})
    assert r.status_code == 200 and r.json()["estado"] == "CANCELADA", r.text

    # A mano: el técnico programa un preventivo y queda asignado; no se duplica; evidencias aún no
    r = cliente.post("/api/v1/mantenimientos/ordenes", headers=tec,
                     json={"plantilla_id": preventivo["id"], "recurso_id": aire["id"]})
    r.raise_for_status()
    manual = r.json()
    assert manual["tecnicos"] == [id_tecnico] and manual["origen"] == "MANUAL", manual
    assert cliente.post("/api/v1/mantenimientos/ordenes", headers=tec,
                        json={"plantilla_id": preventivo["id"], "recurso_id": aire["id"]}).status_code == 409
    assert cliente.post(f"/api/v1/mantenimientos/ordenes/{manual['id']}/evidencias", headers=tec).status_code == 501
    assert cliente.post("/api/v1/mantenimientos/programar", headers=adm).status_code == 200
    paso("el Administrador cancela con motivo; un técnico programa a mano y queda asignado; las evidencias aún no están")

    resumen = cliente.get("/api/v1/resumen/mantenimientos", headers=con).json()
    assert resumen["por_resultado"]["RESUELTO"] >= 1 and resumen["programadas"] >= 1, resumen
    assert resumen["minutos_promedio"] is not None, resumen
    paso("el resumen cuenta las órdenes abiertas y las terminadas por resultado")

    # Si el recurso se elimina, sus órdenes abiertas se cancelan solas
    cliente.request("DELETE", f"/api/v1/inventario/{aire['id']}", headers=tec,
                    json={"motivo": "Limpieza de la prueba de mantenimientos"}).raise_for_status()
    esperar(lambda: cliente.get(f"/api/v1/mantenimientos/ordenes/{manual['id']}", headers=con).json()["estado"] == "CANCELADA",
            "al eliminar el recurso, sus órdenes abiertas se cancelan solas")


def probar_observadores(adm, tec, con, ed):
    correo = f"obs-{sufijo.lower()}@queretaro.tecnm.mx"
    obs, datos = entrar_como_observador(correo, f"Observadora {sufijo}")
    if obs is None:
        paso("(se omiten los Observadores: activa OAUTH_MODO_PRUEBA=true en la base local para probarlos)")
        return
    assert datos["usuario"]["rol"] == "OBSERVADOR", datos
    otra, destino = entrar_como_observador(f"intrusa-{sufijo.lower()}@gmail.com", "Intrusa")
    assert otra is None and destino.startswith("/registro?error="), destino
    r = cliente.post("/api/v1/auth/login", data={"username": correo, "password": "Cualquier#Cosa-2026"})
    assert r.status_code == 401, r.text
    paso("un Observador se registra solo con un correo institucional y no puede entrar con contraseña")

    assert cliente.get(f"/api/v1/edificios/{ed['id']}", headers=obs).status_code == 200
    assert cliente.patch(f"/api/v1/edificios/{ed['id']}", headers=obs, json={"niveles": 3}).status_code == 403
    base = {"recurso": "EDIFICIO", "recurso_id": ed["id"]}
    c = cliente.post("/api/v1/comentarios", headers=obs, json={**base, "texto": "La rampa de acceso está rota"})
    c.raise_for_status()
    assert cliente.post("/api/v1/comentarios", headers=tec, json={**base, "texto": "Comentario nuevo"}).status_code == 403
    assert cliente.post("/api/v1/comentarios", headers=con, json={**base, "texto": "Hola"}).status_code == 403
    assert cliente.post("/api/v1/comentarios", headers=obs,
                        json={"recurso": "EDIFICIO", "recurso_id": 999999, "texto": "x"}).status_code == 422
    respuesta = cliente.post("/api/v1/comentarios", headers=tec,
                             json={**base, "texto": "Gracias, ya se reportó", "respuesta_a": c.json()["id"]})
    respuesta.raise_for_status()
    lista = cliente.get("/api/v1/comentarios", headers=con, params=base).json()
    assert [x["autor_rol"] for x in lista] == ["OBSERVADOR", "TECNICO"], lista
    paso("el Observador comenta un edificio, el Técnico responde y Consulta solo lee")

    assert cliente.request("DELETE", f"/api/v1/comentarios/{c.json()['id']}", headers=tec,
                           json={"motivo": "No aplica"}).status_code == 403
    cliente.request("DELETE", f"/api/v1/comentarios/{c.json()['id']}", headers=adm,
                    json={"motivo": "Prueba de moderación"}).raise_for_status()
    assert cliente.get("/api/v1/comentarios", headers=obs, params=base).json() == []
    ocultos = cliente.get("/api/v1/comentarios", headers=adm, params={**base, "incluir_ocultos": True}).json()
    assert any(x["motivo_eliminacion"] == "Prueba de moderación" for x in ocultos), ocultos
    paso("solo el Administrador oculta un comentario (con su hilo) y conserva el texto con su motivo")

    for ruta in ("/api/v1/edificios", "/api/v1/areas", "/api/v1/inventario", "/api/v1/servicios", "/api/v1/resumen/servicios"):
        assert cliente.get(ruta, headers=obs).status_code == 200, ruta
    for ruta in ("/api/v1/consumos", "/api/v1/resumen/consumos", "/api/v1/mantenimientos/ordenes",
                 "/api/v1/mantenimientos/plantillas", "/api/v1/resumen/mantenimientos", f"/api/v1/historial/EDIFICIO/{ed['id']}"):
        assert cliente.get(ruta, headers=obs).status_code == 403, ruta
        assert cliente.get(ruta, headers=con).status_code == 200, ruta
    r = cliente.get("/api/v1/comentarios", headers=obs, params={"recurso": "CONSUMO", "recurso_id": 1})
    assert r.status_code == 403, r.text
    paso("el Observador ve inmuebles y el estado de los servicios, pero no consumos, mantenimientos ni historial")


def probar_usuarios_y_sesiones(adm, tec, con):
    email = f"prueba-{sufijo.lower()}@escuela.mx"
    nuevo = cliente.post("/api/v1/usuarios", headers=adm,
                         json={"nombre": f"Prueba {sufijo}", "email": email, "contrasena": "Inicial#Llave-77", "rol": "TECNICO"})
    nuevo.raise_for_status()
    nuevo = nuevo.json()

    r = cliente.post("/api/v1/usuarios", headers=adm,
                     json={"nombre": "Repetido", "email": email.upper(), "contrasena": "Inicial#Llave-77", "rol": "CONSULTA"})
    assert r.status_code == 409 and email in r.json()["detail"], r.text
    paso("un correo repetido (aunque cambien mayúsculas) responde 409 con un mensaje claro")

    r = cliente.post("/api/v1/usuarios", headers=adm,
                     json={"nombre": "Larga", "email": f"larga-{email}", "contrasena": "ñ" * 40, "rol": "CONSULTA"})
    assert r.status_code == 422 and "72 bytes" in r.text, r.text
    paso("una contraseña de más de 72 bytes se rechaza (40 letras ñ = 80 bytes)")

    for debil in ("Corta#1", "sinmayusculas#2026", "SinSimbolo2026", f"Prueba#{sufijo}-2026"):
        r = cliente.post("/api/v1/usuarios", headers=adm,
                         json={"nombre": f"Prueba {sufijo}", "email": f"debil-{email}", "contrasena": debil, "rol": "CONSULTA"})
        assert r.status_code == 422 and "segura" in r.json()["detail"], (debil, r.text)
    paso("se rechazan contraseñas cortas, sin mayúscula, sin símbolo o con el nombre del usuario")

    prueba = login(email, "Inicial#Llave-77")
    r = cliente.get("/api/v1/campus", headers=prueba)
    assert r.status_code == 403 and "temporal" in r.json()["detail"], r.text
    paso("una cuenta nueva solo puede cambiar su contraseña temporal")

    r = cliente.post("/api/v1/auth/cambiar-contrasena", headers=prueba, json={"actual": "otra-cosa", "nueva": "Propia#Llave-88"})
    assert r.status_code == 400, r.text
    r = cliente.post("/api/v1/auth/cambiar-contrasena", headers=prueba, json={"actual": "Inicial#Llave-77", "nueva": "Propia#Llave-88"})
    r.raise_for_status()
    assert r.json()["usuario"]["debe_cambiar_contrasena"] is False
    prueba = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert cliente.get("/api/v1/campus", headers=prueba).status_code == 200
    paso("tras cambiar la contraseña (y solo con la actual correcta), la cuenta funciona sin volver a entrar")

    assert cliente.get("/api/v1/auth/yo", headers=prueba).json()["rol"] == "TECNICO"
    cliente.patch(f"/api/v1/usuarios/{nuevo['id']}", headers=adm, json={"rol": "CONSULTA"}).raise_for_status()
    assert cliente.get("/api/v1/auth/yo", headers=prueba).json()["rol"] == "CONSULTA"
    r = cliente.post("/api/v1/edificios", headers=prueba, json={"campus_id": 1, "clave": f"R-{sufijo}", "nombre": "No debe crearse"})
    assert r.status_code == 403, r.text
    paso("el cambio de rol aplica en la siguiente petición, con el mismo token")

    yo_admin = cliente.get("/api/v1/auth/yo", headers=adm).json()
    r = cliente.patch(f"/api/v1/usuarios/{yo_admin['id']}", headers=adm, json={"contrasena": "Temporal#Llave-99"})
    assert r.status_code == 409, r.text
    cliente.patch(f"/api/v1/usuarios/{nuevo['id']}", headers=adm, json={"contrasena": "Temporal#Llave-99"}).raise_for_status()
    r = cliente.get("/api/v1/campus", headers=prueba)
    assert r.status_code == 401 and "restablecida" in r.json()["detail"], r.text
    prueba = login(email, "Temporal#Llave-99")
    r = cliente.get("/api/v1/campus", headers=prueba)
    assert r.status_code == 403 and "temporal" in r.json()["detail"], r.text
    paso("al restablecer la contraseña se cierran sus sesiones y la nueva es temporal")

    cliente.patch(f"/api/v1/usuarios/{nuevo['id']}", headers=adm, json={"activo": False}).raise_for_status()
    r = cliente.get("/api/v1/campus", headers=prueba)
    assert r.status_code == 401 and "desactivada" in r.json()["detail"], r.text
    paso("al desactivar la cuenta, su sesión se cierra de inmediato")

    r = cliente.post("/api/v1/auth/renovar", headers=con)
    r.raise_for_status()
    renovada = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert cliente.get("/api/v1/campus", headers=renovada).status_code == 200
    paso("la sesión se renueva y el token nuevo funciona")

    assert cliente.post("/api/v1/auth/salir", headers=tec).status_code == 204
    r = cliente.get("/api/v1/campus", headers=tec)
    assert r.status_code == 401 and "se cerró" in r.json()["detail"], r.text
    paso("después de cerrar sesión, el mismo token ya no sirve")

    computadora, telefono = login("tecnico@escuela.mx", "Tecnico12345"), login("tecnico@escuela.mx", "Tecnico12345")
    perfil = cliente.get("/api/v1/auth/perfil", headers=telefono).json()
    assert perfil["email"] == "tecnico@escuela.mx" and perfil["acceso"] == "contrasena", perfil
    assert len(perfil["sesiones"]) >= 2 and sum(s["actual"] for s in perfil["sesiones"]) == 1, perfil
    assert "id" not in perfil["sesiones"][0]
    r = cliente.post("/api/v1/auth/cerrar-otras-sesiones", headers=telefono)
    assert r.status_code == 200 and r.json()["cerradas"] >= 1, r.text
    assert cliente.get("/api/v1/campus", headers=computadora).status_code == 401
    assert cliente.get("/api/v1/campus", headers=telefono).status_code == 200
    paso("el perfil lista las sesiones abiertas y «cerrar las demás» deja abierta solo la actual")


if __name__ == "__main__":
    main()
