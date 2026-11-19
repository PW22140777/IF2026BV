# CLAUDE.md

Guía para Claude Code en este repositorio. Es un **proyecto estudiantil**: el código debe ser fácil de leer y explicar en una presentación, no solo correcto.

## Qué es

**Infraestructura Física** es un sistema web para administrar los recursos inmobiliarios de una escuela. Cada alta, modificación o eliminación queda en un **historial firmado criptográficamente**, para saber quién hizo cada cosa.

Jerarquía de recursos:

```text
Campus
├── Edificio ──> Área ──> Elemento de inventario (paredes, contactos, aires acondicionados, bancas…), cuyo tipo sale del catálogo tipos_elemento
├── Área independiente (cancha, bancas) ──> Inventario
└── Servicio básico (agua, luz, internet o alcantarillado), con su estado: del campus completo, de un edificio o de un área ──> Consumos
```

Roles:

| Rol | Puede |
| --- | --- |
| `ADMINISTRADOR` | Todo, más auditoría completa, verificar integridad, restaurar eliminados y administrar usuarios |
| `TECNICO` | Crear, modificar y eliminar recursos y sus propiedades, registrar consumos |
| `CONSULTA` | Solo ver recursos, historial y resumen |
| `OBSERVADOR` | Recorrer edificios, áreas, inventario y el estado de los servicios (vista «Recorrido») y comentar; no ve consumos, mantenimientos ni historial (`LECTORES_INTERNOS`). Se registra solo en `/registro` con su cuenta de Google de la escuela (dominio `queretaro.tecnm.mx`; `OAUTH_PROVEEDOR` también admite Microsoft); no tiene contraseña |

## Reglas de negocio (no romperlas)

- **Nada se borra físicamente.** Eliminar marca `eliminado_en`, `eliminado_por` y `motivo_eliminacion` (motivo obligatorio, mínimo 5 caracteres). Los usuarios de base de datos de los servicios no tienen permiso `DELETE`. Solo el Administrador restaura.
- **Todo cambio genera un evento** con el estado `antes` y `despues` completos. Se registra con `registrar_evento()` en la misma transacción que el cambio (patrón outbox).
- **Campus:** todo edificio pertenece a un campus y no puede cambiar de campus. Un área con edificio está en el campus de su edificio; la base lo garantiza con la FK compuesta `areas (edificio_id, campus_id) -> edificios (id, campus_id)`. Un área sin edificio indica su campus y se puede mover. El inventario pertenece al campus de su área (no tiene columna `campus_id`).
- **Servicios básicos:** abastecen exactamente a uno entre campus, edificio o área (`CHECK num_nonnulls(campus_id, edificio_id, area_id) = 1`). Al cambiar el destino, los otros dos se ponen en null.
- **Eliminar con dependientes:** no se elimina un campus con edificios o áreas activos, un edificio con áreas activas ni un área con inventario activo. Al eliminar un campus, edificio o área, `servicios-service` desactiva sus servicios al recibir el evento.
- **Restaurar:** el padre (campus, edificio o área) debe estar activo.
- **Propiedades flexibles:** cada recurso tiene una columna `propiedades` (JSONB) para datos según el tipo, p. ej. `{"btu": 12000}`. Se agregan, cambian o quitan con `PUT` y `DELETE /{recurso}/{id}/propiedades/{clave}`, y cada cambio queda en el historial.
- **Tipos de elemento:** el tipo de un elemento de inventario debe existir en `tipos_elemento`, que define sus propiedades (`propiedades_definidas`: clave, etiqueta, tipo texto/numero/opcion/fecha/si_no, límites, opciones, requerida) y si usa medidas. `validar_elemento` revisa las propiedades al crear, modificar o cambiar una sola. Solo el Administrador cambia el catálogo (`roles_edicion=SOLO_ADMIN` en `crear_router_recurso`); la clave no cambia y no se elimina un tipo con elementos activos.
- **Observadores y comentarios:** el rol `OBSERVADOR` solo se obtiene entrando con la cuenta institucional (`services/auth/app/oauth.py`: código + PKCE, `id_token` validado contra Google —`hd` y `email_verified`— o Microsoft —inquilino—, y el dominio). Un correo con contraseña no entra por OAuth y un Observador no entra con contraseña. `comentarios-service` guarda los comentarios: los abre un Observador; Técnico y Administrador solo responden (`respuesta_a`); solo el Administrador oculta, con motivo (borrado lógico). `OAUTH_MODO_PRUEBA=true` es solo para pruebas en base local.
- **Mantenimientos:** `mantenimiento-service` guarda plantillas (`plantillas_mantenimiento`) y órdenes (`ordenes_mantenimiento`, técnicos en `ordenes_tecnicos`). Solo el Administrador cambia plantillas, asigna y cancela; los técnicos asignados inician y terminan. El estado del recurso no lo escribe este servicio: publica `orden_mantenimiento.iniciada/terminada.v1` con `estado_recurso_nuevo` e inmuebles/servicios lo aplican (`comun/mantenimientos.py`). Las listas de verificación usan `comun/propiedades.py`, igual que los tipos de elemento. Las evidencias son un esqueleto (501).
- **Auditoría:** `audit_log` es de solo agregar (triggers bloquean `UPDATE`, `DELETE` y `TRUNCATE`). Cada registro tiene `hash = SHA-256(hash_anterior + JSON canónico)` y firma Ed25519. Solo `audit-service` escribe ahí.

## Arquitectura

```text
Navegador ──> gateway :8080 ──(Consul)──> auth / inmuebles / servicios / comentarios / mantenimiento / audit ──> PostgreSQL (una sola base)
                 │                     └── auth ⇄ Google (o Microsoft Entra ID): registro de Observadores
                 └── frontend (Nginx)              └─ outbox ──> RabbitMQ ──> audit (historial firmado)
                                                                       └────> servicios (reacciones)
Todos ──> Jaeger (trazas), Prometheus + Grafana (métricas), logs JSON con correlation_id
```

| Carpeta | Qué hace |
| --- | --- |
| `gateway/` | Único punto de entrada. Valida JWT, limita peticiones, asigna `X-Correlation-Id`, descubre servicios en Consul y reenvía. Sirve también el frontend y Swagger en `/docs/<servicio>`. La tabla `RUTAS` mapea prefijos de URL a servicios. |
| `services/auth/` | Login con JWT, usuarios y roles. Crea los usuarios de demostración si la tabla está vacía. |
| `services/inmuebles/` | Campus, edificios, áreas, inventario y el catálogo `/tipos-elemento`, y `/resumen/inmuebles`. |
| `services/servicios/` | Agua, luz, consumos, `/resumen/consumos`; consume `campus/edificio/area.eliminado.*`. |
| `services/comentarios/` | Comentarios de los Observadores sobre edificios, áreas, inventario y servicios (los consumos solo entre roles internos); respuestas y moderación. |
| `services/mantenimiento/` | Plantillas y órdenes de mantenimiento: por estado, periódicas o manuales; técnicos asignados; iniciar y terminar con lista de verificación. |
| `services/audit/` | Consume todos los eventos (`#`), mantiene la cadena firmada, historial por recurso, bitácora y verificación. `cadena.py` tiene la lógica pura de hash y firma. |
| `shared/comun/` | Paquete común instalado en cada imagen (ver abajo). |
| `frontend/` | React + Vite. Selector global «Campus con el que trabajas» que filtra todas las pantallas. |
| `db/init/` | `01_esquema.sql` (tablas, índices, triggers) y `02_usuarios_bd.sh` (un usuario de base por servicio). |
| `observabilidad/` | `prometheus.yml` (descubre instancias en Consul) y tablero de Grafana. |
| `tests/` | `test_cadena.py` (unitarias, sin Docker) y `prueba_sistema.py` (humo contra el sistema levantado). |

### Paquete `shared/comun`

- `app.py` → `crear_app()`: todos los servicios arrancan así (health, métricas, trazas, Consul, publicador de outbox, consumidores, Swagger).
- `recursos.py` → `crear_router_recurso()`: CRUD genérico con filtros, propiedades, borrado lógico, restauración e historial. **Para un recurso nuevo usa esto** con ganchos `validar`, `antes_de_eliminar` y `antes_de_restaurar`; `roles_edicion` y `roles_lectura` limitan quién escribe y quién lee.
- `seguridad.py` → `requiere_rol(*TODOS | *EDITORES | *SOLO_ADMIN)`; en cada petición revisa en la tabla `sesiones` que la sesión del JWT siga abierta y usa el rol que dice la base, no el del token. Con una contraseña temporal responde 403, salvo en las rutas marcadas con `aunque_deba_cambiar_contrasena=True`. `SISTEMA` es el usuario de las acciones automáticas.
- `historial.py` → `registrar_evento()`; el tipo de evento es `recurso.accion.v1`, p. ej. `edificio.creado.v1`.
- `mensajeria.py` → publicador de outbox y `consumidor()` con 3 reintentos y cola `eventos.fallidos`. Importa `aio_pika`, así que solo se carga si hay `RABBITMQ_URL`.
- `idempotencia.py` → `marcar_procesado()` en `eventos_procesados`.
- `modelos.py` → modelos SQLAlchemy que **mapean** las tablas de `01_esquema.sql`; no crean tablas.

## Tecnologías

Python 3.12, FastAPI, SQLAlchemy 2 asíncrono con `psycopg` 3, Pydantic 2, PyJWT, `bcrypt` (directo, no `passlib`), `aio-pika`, `httpx`, structlog, OpenTelemetry, `prometheus-fastapi-instrumentator`, `cryptography`; PostgreSQL 16, RabbitMQ 3.13, Consul 1.20, Jaeger, Prometheus, Grafana; React 18 + Vite 5 con fuente Public Sans.

## Ejecutar y probar

Esta copia (`IF2026BV`) trabaja con la **base local** (`COMPOSE_PROFILES=local-db` y `COMPOSE_PROJECT_NAME=infraestructura-fisica-bv` en `.env`), nunca con la de Supabase del equipo.

```bash
cp .env.example .env
docker compose up --build            # app: http://localhost:8080   API: http://localhost:8080/docs
python tests/prueba_sistema.py        # requiere: pip install httpx
pytest tests/test_cadena.py           # requiere: pip install pytest cryptography
docker compose up -d --scale inmuebles=3
docker compose logs <servicio> --tail 50
```

Usuarios de demostración: `admin@escuela.mx` / `Admin12345`, `tecnico@escuela.mx` / `Tecnico12345`, `consulta@escuela.mx` / `Consulta12345`.

Paneles: RabbitMQ `:15672`, Consul `:8500`, Jaeger `:16686`, Grafana `:3000`, Prometheus `:9090` (solo localhost).

Frontend con recarga en vivo: `cd frontend && npm install && npm run dev` (puerto 5173, envía `/api` al gateway).

## Cuidado con

- **Cambios al esquema:** `db/init` solo se ejecuta con un volumen vacío. Si cambias `01_esquema.sql`, la base existente no se actualiza y aparecen errores como `column edificios.campus_id does not exist`. Opciones: `docker compose down -v` (borra datos) o escribir un script SQL de migración en `db/migraciones/`. Actualiza también `modelos.py` y los permisos en `02_usuarios_bd.sh`.
- **Conexiones a la base:** cada servicio abre hasta `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` (5 + 5 por defecto). `db.py` desactiva las sentencias preparadas (`prepare_threshold=None`) para funcionar con poolers en modo transacción, como el puerto 6543 de Supabase; no uses funciones que dependan de la conexión entre transacciones (`SET` de sesión, `pg_advisory_lock` sin `xact`, `LISTEN`).
- **Sesiones y permisos:** los servicios distintos de `auth` solo tienen `SELECT (id, nombre, rol, activo, debe_cambiar_contrasena)` sobre `usuarios`. Si una consulta suya pide el modelo `Usuario` completo, PostgreSQL responde `permission denied`: selecciona solo esas columnas.
- **Rutas nuevas:** agrégalas a `RUTAS` en `gateway/app/main.py` o el gateway responde 404. Un recurso nuevo también va en `RECURSOS` de `services/audit/app/main.py` para que tenga historial.
- **Orden de rutas en FastAPI:** una ruta fija como `/consumos/resumen` choca con `/consumos/{id}`; por eso los resúmenes viven en `/resumen/...`.
- **JSON canónico del hash:** si cambias `CAMPOS` o `normalizar_fecha` en `cadena.py`, todos los registros existentes dejarán de verificar.
- **Windows:** los `.sh` y `.sql` deben quedar con fin de línea LF (ver `.gitattributes`); con CRLF el script de PostgreSQL falla.
- **`.env`** contiene secretos y no se versiona.

## Convenciones

- Código, nombres, comentarios, mensajes de error y textos de la interfaz **en español** (variables sin acentos: `anio_construccion`, `contrasena`).
- Mensajes de error que digan qué pasó y qué hacer, p. ej. «El edificio tiene 2 áreas activas; elimínalas o reasígnalas primero».
- Comentarios breves que expliquen el **porqué**; el proyecto se presenta en clase.
- Versionado: la versión mayor va en la URL (`/api/v1`). Agregar campos opcionales no requiere `v2`.
- Al cambiar el comportamiento, actualiza también `README.md` y, si aplica, `tests/prueba_sistema.py`.
- El documento de arquitectura del proyecto vive en claude.ai (Claude Docs); si un cambio altera la arquitectura, menciónalo para actualizarlo.
