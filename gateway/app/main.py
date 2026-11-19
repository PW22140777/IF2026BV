"""API Gateway: único punto de entrada al sistema.

Responsabilidades:
  1. Asignar un X-Correlation-Id a cada petición.
  2. Limitar la tasa de peticiones (más estricto en el login).
  3. Validar el JWT antes de dejar pasar una petición a /api.
  4. Descubrir en Consul una instancia sana del servicio y reenviarle la petición.
  5. Agregar cabeceras de seguridad a las respuestas.
  6. Servir el frontend (lo pide al contenedor de Nginx).
"""
import asyncio
import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import httpx
import jwt
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

from comun import consul
from comun.config import configuracion
from comun.observabilidad import configurar_logs, configurar_metricas, configurar_trazas
from comun.seguridad import decodificar_token

configurar_logs("gateway")
log = structlog.get_logger()

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://frontend:80")

# Prefijo de la ruta -> servicio en Consul. Gana el prefijo más largo.
# Para publicar una v2 basta con agregar sus rutas aquí.
RUTAS: dict[str, str] = {
    "/api/v1/auth": "auth",
    "/api/v1/usuarios": "auth",
    "/api/v1/campus": "inmuebles",
    "/api/v1/edificios": "inmuebles",
    "/api/v1/areas": "inmuebles",
    "/api/v1/inventario": "inmuebles",
    "/api/v1/tipos-elemento": "inmuebles",
    "/api/v1/resumen/inmuebles": "inmuebles",
    "/api/v1/servicios": "servicios",
    "/api/v1/consumos": "servicios",
    "/api/v1/resumen/consumos": "servicios",
    "/api/v1/resumen/servicios": "servicios",
    "/api/v1/historial": "audit",
    "/api/v1/auditoria": "audit",
    "/api/v1/comentarios": "comentarios",
    "/api/v1/mantenimientos": "mantenimiento",
    "/api/v1/resumen/mantenimientos": "mantenimiento",
}
SERVICIOS_DOCS = ("auth", "inmuebles", "servicios", "audit", "comentarios", "mantenimiento")
# Sin token: el login y el inicio con la cuenta institucional (también cuentan en el límite de logins)
RUTAS_PUBLICAS = {"/api/v1/auth/login", "/api/v1/auth/oauth/inicio", "/api/v1/auth/oauth/callback",
                  "/api/v1/auth/oauth/canjear"}
# Sin token pero con el límite normal de la API: solo dice con qué cuenta entran los Observadores
RUTAS_SIN_TOKEN = RUTAS_PUBLICAS | {"/api/v1/auth/oauth/proveedor"}

# Cabeceras que no se deben reenviar (son de cada conexión)
SALTO_A_SALTO = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
                 "transfer-encoding", "upgrade", "host", "content-length", "content-encoding"}

CABECERAS_SEGURIDAD = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}
CSP_FRONTEND = ("default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")


# ------------------------------------------------------- límite de peticiones
class LimitadorTasa:
    """Ventana deslizante en memoria: máximo `limite` peticiones por `ventana` segundos."""

    def __init__(self) -> None:
        self._historial: dict[str, deque] = defaultdict(deque)

    def permitir(self, clave: str, limite: int, ventana: float = 60.0) -> tuple[bool, int]:
        ahora = time.monotonic()
        marcas = self._historial[clave]
        while marcas and ahora - marcas[0] > ventana:
            marcas.popleft()
        if len(marcas) >= limite:
            return False, int(ventana - (ahora - marcas[0])) + 1
        marcas.append(ahora)
        return True, 0


limitador = LimitadorTasa()
LIMITE_LOGIN = int(os.getenv("LIMITE_LOGIN_POR_MINUTO", "5"))
LIMITE_API = int(os.getenv("LIMITE_API_POR_MINUTO", "300"))

descubridor = consul.Descubridor()
cliente: httpx.AsyncClient | None = None


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    global cliente
    cliente = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    id_consul = await consul.registrar("gateway", configuracion().puerto, configuracion().servicio_version)
    yield
    await consul.dar_de_baja(id_consul)
    await cliente.aclose()


app = FastAPI(title="API Gateway", docs_url=None, redoc_url=None, openapi_url=None, lifespan=ciclo_de_vida)

origenes = [o for o in os.getenv("CORS_ORIGENES", "").split(",") if o]
if origenes:   # solo hace falta si el frontend se sirve desde otro origen (p. ej. Vite en desarrollo)
    app.add_middleware(CORSMiddleware, allow_origins=origenes, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Correlation-Id"])


def _ip(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


def _error(status: int, detalle: str, cid: str, **cabeceras: str) -> JSONResponse:
    return JSONResponse({"detail": detalle}, status_code=status,
                        headers={"X-Correlation-Id": cid, **CABECERAS_SEGURIDAD, **cabeceras})


def _destino(ruta: str) -> str | None:
    if ruta.startswith("/docs/"):
        servicio = ruta.split("/")[2]
        return servicio if servicio in SERVICIOS_DOCS else None
    coincidencias = [p for p in RUTAS if ruta == p or ruta.startswith(p + "/")]
    return RUTAS[max(coincidencias, key=len)] if coincidencias else None


async def _reenviar(request: Request, base: str, cid: str) -> httpx.Response:
    assert cliente is not None
    cabeceras = {k: v for k, v in request.headers.items() if k.lower() not in SALTO_A_SALTO}
    cabeceras["X-Correlation-Id"] = cid
    cabeceras["X-Real-IP"] = _ip(request)
    cabeceras["X-Forwarded-For"] = _ip(request)
    return await cliente.request(
        request.method,
        base + request.url.path,
        params=request.query_params,
        headers=cabeceras,
        content=await request.body(),
    )


def _respuesta(r: httpx.Response, cid: str, extra: dict[str, str] | None = None) -> Response:
    cabeceras = {k: v for k, v in r.headers.items() if k.lower() not in SALTO_A_SALTO}
    cabeceras.update(CABECERAS_SEGURIDAD)
    cabeceras["X-Correlation-Id"] = cid
    if extra:
        cabeceras.update(extra)
    return Response(content=r.content, status_code=r.status_code, headers=cabeceras)


@app.get("/health", include_in_schema=False)
async def salud():
    return {"estado": "ok", "servicio": "gateway"}


@app.get("/docs", include_in_schema=False)
async def indice_docs():
    enlaces = "".join(f'<li><a href="/docs/{s}">{s}-service</a></li>' for s in SERVICIOS_DOCS)
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>Documentación de la API</title>"
        "<body style='font-family:system-ui;max-width:640px;margin:40px auto'>"
        "<h1>Documentación de la API (Swagger)</h1>"
        "<p>En cada servicio usa el botón <b>Authorize</b> con tu correo y contraseña.</p>"
        f"<ul>{enlaces}</ul></body>"
    )


configurar_metricas(app)   # /metrics antes de la ruta comodín


@app.api_route("/{ruta:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
               include_in_schema=False)
async def proxy(request: Request, ruta: str):
    cid = request.headers.get("x-correlation-id") or str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(correlation_id=cid)
    ruta_completa = request.url.path
    ip = _ip(request)

    # 1. Límite de peticiones
    if ruta_completa in RUTAS_PUBLICAS:
        permitido, espera = limitador.permitir(f"login:{ip}", LIMITE_LOGIN)
    elif ruta_completa.startswith("/api/"):
        permitido, espera = limitador.permitir(f"api:{ip}", LIMITE_API)
    else:
        permitido, espera = True, 0
    if not permitido:
        log.warning("limite_excedido", ip=ip, ruta=ruta_completa)
        return _error(429, f"Demasiadas peticiones, intenta de nuevo en {espera} s", cid,
                      **{"Retry-After": str(espera)})

    # 2. Frontend: todo lo que no es /api ni /docs
    servicio = _destino(ruta_completa)
    if servicio is None:
        if ruta_completa.startswith("/api/"):
            return _error(404, "Ruta de API desconocida", cid)
        try:
            r = await _reenviar(request, FRONTEND_URL, cid)
        except httpx.HTTPError:
            return _error(503, "El frontend no está disponible", cid)
        return _respuesta(r, cid, {"Content-Security-Policy": CSP_FRONTEND})

    # 3. Autenticación (las páginas de Swagger y el login son públicos)
    if ruta_completa.startswith("/api/") and ruta_completa not in RUTAS_SIN_TOKEN and request.method != "OPTIONS":
        autorizacion = request.headers.get("authorization", "")
        if not autorizacion.lower().startswith("bearer "):
            return _error(401, "Falta el token de acceso", cid, **{"WWW-Authenticate": "Bearer"})
        try:
            usuario = decodificar_token(autorizacion[7:])
        except jwt.ExpiredSignatureError:
            return _error(401, "La sesión expiró, vuelve a iniciar sesión", cid, **{"WWW-Authenticate": "Bearer"})
        except jwt.PyJWTError:
            return _error(401, "Token inválido", cid, **{"WWW-Authenticate": "Bearer"})
        structlog.contextvars.bind_contextvars(usuario_id=usuario.id, rol=usuario.rol)

    # 4. Descubrimiento y reenvío (si una instancia falla, se intenta otra)
    for intento in range(2):
        base = await descubridor.url(servicio)
        try:
            inicio = time.perf_counter()
            r = await _reenviar(request, base, cid)
            log.info("peticion", metodo=request.method, ruta=ruta_completa, servicio=servicio,
                     destino=base, estado=r.status_code, ms=round((time.perf_counter() - inicio) * 1000))
            return _respuesta(r, cid)
        except httpx.ConnectError:
            log.warning("instancia_no_responde", servicio=servicio, destino=base, intento=intento + 1)
            descubridor.olvidar(servicio)
            await asyncio.sleep(0.2)
        except httpx.TimeoutException:
            return _error(504, f"El servicio {servicio} tardó demasiado en responder", cid)
        finally:
            structlog.contextvars.unbind_contextvars("usuario_id", "rol")
    return _error(503, f"El servicio {servicio} no está disponible", cid)


configurar_trazas(app, "gateway")
