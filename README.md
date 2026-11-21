# Infraestructura Física

Proyecto estudiantil que administra los **campus** de una escuela y todo lo que depende de ellos: sus **edificios**, sus **áreas** (con o sin edificio, como una cancha o unas bancas), el **inventario** de cada área (paredes, contactos, aires acondicionados…) y los **servicios básicos** (agua, luz, internet, alcantarillado), con su estado y sus consumos.

```text
Campus
├── Edificio ──> Área ──> Inventario
├── Área independiente (cancha, bancas) ──> Inventario
└── Servicios básicos (agua, luz, internet, alcantarillado): del campus completo,
    de un edificio o de un área ──> estado y Consumos
``` Cada alta, modificación o eliminación queda en un **historial firmado criptográficamente**, para saber siempre quién hizo qué.

| Rol | Puede |
| --- | --- |
| Administrador | Todo, más ver la auditoría completa, verificar su integridad, restaurar registros eliminados y administrar usuarios |
| Técnico | Crear, modificar y eliminar recursos y sus propiedades |
| Consulta | Solo ver recursos, historial y el resumen para tomar decisiones |

## Arrancar el sistema

Requisitos: [Docker Desktop](https://www.docker.com/products/docker-desktop/) (o Docker Engine con Compose v2) y unos 8 GB de RAM libres, porque son 12 contenedores.

```bash
cp .env.example .env          # en Windows: copy .env.example .env
docker compose up --build
```

> **¿Ya lo usabas cuando se llamaba `inmuebles-escolares`?** Docker nombra los volúmenes con el nombre del proyecto, así que el nuevo arrancaría sin tu llave de firma de auditoría y el historial ya firmado dejaría de verificar. Cópiala una sola vez antes de arrancar (sirve igual en PowerShell y en bash):
>
> ```bash
> docker compose -p inmuebles-escolares down
> docker compose up --no-start
> docker run --rm -v inmuebles-escolares_llaves_audit:/de:ro -v infraestructura-fisica_llaves_audit:/a alpine cp -a /de/. /a/
> docker compose up -d
> ```
>
> Si usas el Postgres local (`--profile local-db`), copia también `datos_postgres` con la misma línea `docker run`. RabbitMQ no hace falta: sus mensajes ya se entregaron. Cuando confirmes que todo funciona, borra los volúmenes viejos con `docker volume rm inmuebles-escolares_llaves_audit inmuebles-escolares_datos_rabbitmq`.

La primera vez tarda varios minutos porque descarga imágenes e instala dependencias. Cuando en los logs aparezca `servicio_iniciado` para los cuatro servicios, abre:

| Qué | Dirección |
| --- | --- |
| Aplicación web | http://localhost:8080 |
| Documentación de la API (Swagger) | http://localhost:8080/docs |
| RabbitMQ (colas) | http://localhost:15672 (usuario y contraseña de `.env`) |
| Consul (servicios registrados) | http://localhost:8500 |
| Jaeger (trazas) | http://localhost:16686 |
| Grafana (métricas) | http://localhost:3000, tablero «Salud de los servicios» |
| Prometheus | http://localhost:9090 |

Usuarios de demostración (se crean solo si la base está vacía):

| Correo | Contraseña | Rol |
| --- | --- | --- |
| admin@escuela.mx | Admin12345 | Administrador |
| tecnico@escuela.mx | Tecnico12345 | Técnico |
| consulta@escuela.mx | Consulta12345 | Consulta |

Para comprobar que todo funciona, con el sistema arriba:

```bash
pip install httpx
python tests/prueba_sistema.py
```

Para borrar todo y empezar de cero (base de datos, colas y llave de firma): `docker compose down -v`.

## Recorrido sugerido para la presentación

1. Entra como **Técnico**. Los campus son fijos (Campus Centro y Campus Norte): elige «Campus Centro» en el selector «Campus con el que trabajas» de la barra superior y desde ese momento todas las pantallas muestran solo lo de ese campus. Crea el edificio `ED-A` con 2 niveles, el área «Laboratorio 3» en su piso 1 (la lista de pisos solo ofrece los que existen) y el área «Cancha» sin edificio.
2. En **Inventario**, agrega un aire acondicionado al laboratorio: al elegir el tipo aparecen sus propiedades y la capacidad (`12000` BTU) es obligatoria. Luego cambia su estado a «Fuera de servicio». En el panel de la derecha, el **Historial** muestra quién cambió qué. Como Administrador, en **Tipos de elemento** puedes ver o cambiar qué propiedades pide cada tipo.
3. En **Agua y luz**, crea una toma de agua para la cancha. Cambia su estado a «Con falla»: en **Resumen** (o filtrando por estado) aparece como servicio con falla. Luego elimina la cancha indicando un motivo: unos segundos después la toma aparece como inactiva. Ese cambio lo hizo `servicios-service` al recibir el evento por RabbitMQ (puedes verlo en http://localhost:15672).
4. Entra como **Consulta**: puede ver todo y el resumen, pero no hay botones para modificar. Si intentas la API directamente, responde `403`.
5. Entra como **Administrador** y en **Auditoría** pulsa «Verificar integridad». Después altera un registro directamente en la base y vuelve a verificar:

   ```bash
   docker compose exec postgres psql -U postgres -d escuela -c "UPDATE audit_log SET motivo='x' WHERE id=3"
   # ERROR: audit_log es de solo lectura  (el trigger lo impide)

   docker compose exec postgres psql -U postgres -d escuela -c "
     ALTER TABLE audit_log DISABLE TRIGGER audit_inmutable;
     UPDATE audit_log SET motivo='alterado' WHERE id=3;
     ALTER TABLE audit_log ENABLE TRIGGER audit_inmutable;"
   ```

   La verificación ahora señala el registro 3 como modificado.
6. Copia el `correlation_id` de un registro de la bitácora y búscalo en los logs (`docker compose logs | grep <id>`). Con el `trace_id` puedes ver la traza completa en Jaeger.
7. Escala un servicio con `docker compose up -d --scale inmuebles=3`. Las réplicas aparecen en Consul y en Grafana, y el gateway reparte las peticiones entre ellas.

## Cómo se cumple cada requisito

| Requisito | Dónde está |
| --- | --- |
| Interfaz web | `frontend/` (React + Vite, servido por Nginx) |
| Autenticación JWT | `services/auth/app/main.py` (login, renovar y salir), `shared/comun/seguridad.py` (validación del token y de la sesión en la base) |
| Roles | `requiere_rol(...)` en `shared/comun/seguridad.py`; cada endpoint lo declara |
| API Gateway seguro | `gateway/app/main.py`: valida JWT, limita peticiones (5 logins por minuto por IP), agrega cabeceras de seguridad y solo él expone puerto |
| Versionado de API | Rutas `/api/v1/...`; tabla `RUTAS` del gateway; eventos `recurso.accion.v1` |
| Cola de mensajes | RabbitMQ; `shared/comun/mensajeria.py` (publicador y consumidores con reintentos y cola de fallidos) |
| Registro y descubrimiento | Consul; `shared/comun/consul.py` (registro al arrancar, health check y round robin en el gateway) |
| Trazabilidad de eventos | OpenTelemetry → Jaeger; `traceparent` viaja también dentro de los mensajes de RabbitMQ |
| Correlación de eventos | `X-Correlation-Id` creado en el gateway; viaja en HTTP, eventos, logs y auditoría |
| Observabilidad | Logs JSON (structlog), métricas `/metrics` (Prometheus) y tablero de Grafana |
| Auditoría criptográfica | `services/audit/app/cadena.py`: SHA-256 encadenado y firma Ed25519 |
| Trazabilidad auditable | Historial por recurso y por usuario, con estado antes y después y motivo; verificación de integridad |
| Jerarquía campus > edificio > área | `campus_id` en edificios y áreas; la base garantiza con una llave foránea compuesta que un área esté en el mismo campus que su edificio |
| Base de datos relacional única | PostgreSQL; `db/init/01_esquema.sql`, un usuario de base por servicio sin permiso `DELETE` |
| Contenedores y escalabilidad | `docker-compose.yml`; servicios sin estado, escalables con `--scale` |

## Arquitectura

```text
Navegador ──> gateway :8080 ──(Consul)──> auth / inmuebles / servicios / comentarios / mantenimiento / audit ──> PostgreSQL (única)
                 │                         └── inmuebles / mantenimiento ──> archivos ──> volumen datos_archivos
                 │                                    │
                 └── frontend (Nginx)                 └─ outbox ──> RabbitMQ ──> audit (historial firmado)
                                                                         └────> servicios (reacciones)
Todos ──> Jaeger (trazas), Prometheus + Grafana (métricas), logs JSON
```

**Patrón outbox.** Cada servicio guarda el evento en la tabla `outbox` en la misma transacción que el cambio. Un proceso de fondo lo publica en RabbitMQ. Así, si RabbitMQ está caído, el cambio no se pierde del historial: se publica cuando vuelve.

**Borrado lógico.** Eliminar marca `eliminado_en`, `eliminado_por` y `motivo_eliminacion`. Los usuarios de base de datos de los servicios no tienen permiso `DELETE`.

**Sesiones en la base.** Al iniciar sesión, `auth-service` guarda una fila en `sesiones`, y el JWT lleva su identificador. En cada petición, el servicio que responde revisa en la base que esa sesión siga abierta y lee el rol actual del usuario. Por eso:

- Un cambio de rol aplica en la siguiente petición, y desactivar una cuenta cierra sus sesiones al instante.
- «Cerrar sesión» invalida el token en el servidor, aunque alguien lo haya copiado.
- En «Mi perfil» (GET /auth/perfil) cada quien ve sus datos, lo que puede hacer su rol, cómo entra y sus sesiones abiertas, y puede cerrar las demás con POST /auth/cerrar-otras-sesiones (la actual sigue abierta).
- «Mi perfil», «Cambiar contraseña» y «Cerrar sesión» están en el menú del usuario, a la derecha de la barra superior; ahí también está el selector de campus.
- El panel de detalle (ver y editar un registro) tiene tamaño fijo: en computadora, de 340 a 460 px de ancho según la pantalla (`--ancho-panel`) y el alto de la ventana; en tableta y teléfono flota encima de la lista. Todo su contenido se ajusta a ese ancho: los textos largos, aunque no tengan espacios (claves, enlaces, valores del historial), se parten en varias líneas, así que nada ensancha la página. Si el contenido es más alto, solo el panel se desplaza hacia abajo.
- La sesión se cierra tras 30 minutos sin actividad y, como máximo, 4 horas después de entrar (`SESION_INACTIVIDAD_MINUTOS` y `SESION_MAXIMA_HORAS` en `.env`). Mientras trabajas, el frontend la renueva sola con `/auth/renovar`.

Los servicios solo pueden leer `id`, `nombre`, `rol`, `activo` y `debe_cambiar_contrasena` de `usuarios`: nunca el hash de la contraseña.

**Usuarios y contraseñas.**

- Un correo no se puede repetir, aunque cambien las mayúsculas (responde 409 con un mensaje claro).
- Una contraseña nueva (al crear, restablecer o cambiar) debe tener al menos 10 caracteres, mayúscula, minúscula, número y símbolo, no usar palabras muy comunes (`password`, `123456`, `escuela`…) ni contener el nombre o el correo de su dueño. El formulario muestra un medidor con lo que falta y el servidor revisa las mismas reglas (`problema_de_contrasena` en auth y `contrasenas.js`). Las contraseñas que ya existían, incluidas las de demostración, siguen funcionando.
- Como máximo 72 bytes: `bcrypt` ignora lo que pasa de 72 bytes, y una letra con acento ocupa 2.
- Cada quien cambia su contraseña en «Cambiar contraseña» (`POST /auth/cambiar-contrasena`), indicando la actual; sus otras sesiones se cierran.
- La contraseña de una cuenta nueva es **temporal**, igual que la que asigna el Administrador con «Restablecer contraseña». Con una contraseña temporal, la cuenta solo puede cambiarla: cualquier otra petición responde 403. Restablecer también cierra las sesiones de esa cuenta.
- No hay recuperación por correo: quien olvide su contraseña pide al Administrador que la restablezca. Los usuarios de demostración no tienen contraseña temporal.

## Reglas del campus

- Todo edificio pertenece a un campus, y ese campus no se puede cambiar después.
- Un área con edificio está siempre en el campus de su edificio. Un área sin edificio indica su campus y se puede mover a otro.
- El inventario pertenece al campus de su área.
- Un servicio básico (agua, luz, internet o alcantarillado) abastece al campus completo (toma o medidor general), a un edificio o a un área. Solo agua y luz registran consumo mensual.
- El estado de un servicio (operando, con falla, suspendido, en mantenimiento) se actualiza como cualquier otro campo y queda en su historial; `/resumen/servicios` lista los que no están operando con normalidad.
- No se puede eliminar un campus con edificios o áreas activos. Al eliminarlo, sus servicios generales quedan inactivos automáticamente (evento por RabbitMQ). Para restaurar un edificio o un área, su campus debe estar activo.
- Todas las listas, el resumen y las rutas de la API aceptan `?campus_id=` para filtrar.

## Archivos adjuntos (fotos, planos, PDF y evidencias)

Se aceptan JPG, PNG, WebP y PDF de hasta 10 MB. Los edificios tienen las mismas propiedades con archivo que en la rama `develop` de IF2026B:

| Propiedad del edificio | Qué guarda | Cómo se cambia |
| --- | --- | --- |
| Foto de fachada (`fachada_s3`, y `fachada_url` firmada en las respuestas) | Una imagen (JPG, PNG o WebP); la nueva reemplaza a la anterior, que se borra del almacén | `PUT /edificios/{id}/fachada` o «Agregar / Cambiar foto de fachada» en el panel |
| Archivos del edificio | Varios archivos con nombre y descripción (planos, dictámenes, fotos) | `/edificios/{id}/archivos` o la sección «Archivos del edificio» |
| Carpeta de planos (`carpeta_planos`) | Un enlace a una carpeta externa (Drive, OneDrive); sin `https://` se le agrega, y `javascript:` se rechaza | En el formulario del edificio |

Además de lo de `develop`, las áreas y el inventario tienen **«Fotos y documentos»** (con tipo: foto, plano, documento u otro) y cada orden de mantenimiento tiene **«Evidencias»**. En el «Recorrido», el Observador ve la fachada, la carpeta de planos y los archivos de edificios y áreas, pero no las evidencias.

| Rol | Puede |
| --- | --- |
| Administrador, Técnico | Subir y quitar adjuntos de edificios, áreas e inventario (quitar pide motivo) |
| Técnicos asignados, Administrador | Subir y quitar evidencias de una orden que no esté cancelada |
| Consulta | Ver todo lo anterior |
| Observador | Ver las fotos y planos de edificios, áreas e inventario, y adjuntar hasta 4 fotos a sus comentarios |

**Cómo funciona.**

1. El navegador sube el archivo a `POST /api/v1/edificios/{id}/archivos` (o `/areas`, `/inventario`, `/mantenimientos/ordenes/{id}/evidencias`).
2. `inmuebles-service` (o `mantenimiento-service`) se lo pasa a **`archivos-service`** por la red interna con `X-Token-Interno` (`comun/almacenamiento.py`).
3. `archivos-service` decide el tipo por los primeros bytes del archivo, no por su nombre, así que un HTML o SVG disfrazado de imagen se rechaza. Lo guarda en el volumen de Docker `datos_archivos`, con su SHA-256 como nombre (`edificios/7/<sha256>.png`).
4. El servicio guarda la ficha en `archivos_adjuntos` (nombre, tipo, tamaño, SHA-256, clave, quién lo subió) y deja el evento `archivo.creado.v1` en el historial firmado.
5. Al listar, cada archivo trae una **URL firmada que caduca en 1 hora**: `/api/v1/archivos/descarga?clave=…&expira=…&firma=…`. Es la única ruta pública de `archivos-service`. Un `<img src>` no puede mandar el JWT, así que el permiso va en la firma HMAC (`ARCHIVOS_SECRETO_FIRMA`); alterada o vencida responde 403.

**Quitar un adjunto** pide motivo: la ficha queda con borrado lógico y en el historial (`ARCHIVO`), y **el archivo sí se borra del almacén**, salvo que otra ficha activa use el mismo contenido. Es la excepción a «nada se borra físicamente», porque un archivo no tiene historial propio.

**Dónde se guardan.** `ARCHIVOS_BACKEND=local` usa el volumen `datos_archivos`. Para respaldarlo:

```bash
docker run --rm -v infraestructura-fisica-bv_datos_archivos:/datos -v "$PWD":/respaldo alpine tar czf /respaldo/archivos.tgz -C /datos .
```

La versión para S3 vive en la rama `develop` de IF2026B. Al unirlas se agrega como otro backend de `archivos-service` (guardar, URL, borrar); `inmuebles` y `mantenimiento` no cambian. Diferencia con `develop`: aquí los archivos del edificio van en `archivos_adjuntos` (con `recurso = 'EDIFICIO'`), no en `archivos_edificio`; esa tabla sigue en el esquema por compatibilidad, pero este código no la usa.

**Base que ya existe:** aplica `db/migraciones/009_archivos_adjuntos.sql` como dueño de la base. En `.env` agrega `ARCHIVOS_SECRETO_FIRMA` y `ARCHIVOS_TOKEN_INTERNO` (32 caracteres o más cada uno; ver `.env.example`).

## Tipos de elemento y sus propiedades

Cada elemento de inventario tiene un **tipo** (pared, aire acondicionado, mesa…) que sale del catálogo `tipos_elemento`. El tipo define:

- **Qué propiedades lleva**, en `propiedades_definidas`. Por ejemplo, un aire acondicionado lleva capacidad en BTU (obligatoria), tipo de equipo, refrigerante, voltaje y fecha del último mantenimiento. Cada propiedad tiene una clase de dato: texto, número (con mínimo, máximo y unidad), lista de opciones, fecha o sí/no.
- **Si usa medidas** (largo, alto, ancho, espesor). Una pared sí; un contacto no.

Los valores se guardan en la columna `propiedades` (JSONB) del elemento, así que agregar un tipo o una propiedad **no requiere cambiar el esquema**.

- **Quién lo administra:** solo el Administrador, en «Administración → Tipos de elemento» (`/api/v1/tipos-elemento`). Todos los roles pueden consultar el catálogo.
- **Formulario:** al elegir el tipo de un elemento aparecen sus propiedades con el control adecuado, y las medidas se ocultan si el tipo no las usa.
- **API:** rechaza (422) un tipo que no está en el catálogo, una propiedad obligatoria vacía, un número fuera de rango, una opción que no existe y medidas en un tipo que no las usa. Lo mismo aplica al cambiar una sola propiedad con `PUT /inventario/{id}/propiedades/{clave}`. Se siguen aceptando propiedades extra que el tipo no define.
- **Reglas del catálogo:** la clave de un tipo no se puede cambiar, porque es la que guarda cada elemento. Un tipo con elementos activos no se puede eliminar. Si se cambian las propiedades de un tipo, los elementos existentes se revisan cuando se vuelvan a editar.
- **Datos iniciales:** la base empieza con 11 tipos (pared, contacto, aire acondicionado, luminaria, puerta, ventana, pizarrón, banca, mesa, bebedero y proyector).
- **Base que ya existe (Supabase):** hay que aplicar `db/migraciones/006_tipos_elemento.sql` como dueño de la base **antes** de levantar este código. Crea la tabla y carga los tipos iniciales si el catálogo está vacío. Si el inventario ya usa tipos que no están en el catálogo, los registra sin propiedades. Se puede ejecutar más de una vez.

### Limpiar propiedades que el tipo no define

Si un elemento tiene en `propiedades` claves que su tipo ya no define (capturadas antes del catálogo o con otro nombre), este script las quita. Usa la base de `.env`:

```bash
docker compose run --rm --no-deps inmuebles python -m app.limpiar_propiedades            # solo muestra qué quitaría
docker compose run --rm --no-deps inmuebles python -m app.limpiar_propiedades --aplicar  # guarda los cambios
```

No borra filas ni columnas. Cada elemento que cambia deja un evento `MODIFICAR` del sistema en el historial, con los valores quitados en «antes». Todo va en una sola transacción y los elementos cuyo tipo no está en el catálogo no se tocan.

## Valores válidos de edificios, áreas e inventario

La API rechaza (422 o 409, con un mensaje que dice qué corregir) y los formularios impiden capturar:

- **Pisos:** un edificio de N niveles tiene los pisos 0 (planta baja) a N − 1. El piso de un área debe existir en su edificio; si el edificio no tiene registrados sus niveles, primero hay que registrarlos. Un área sin edificio no tiene piso (al convertirla en independiente, su piso se borra). No se pueden reducir los niveles de un edificio si alguna área quedaría en un piso que ya no existe. En el formulario, el piso se elige de una lista con los pisos del edificio.
- **Números:** superficie, largo, alto, ancho y espesor deben ser mayores que 0; capacidad 0 o más; cantidad 1 o más; niveles de 1 a 200. Cada uno tiene un máximo razonable para detectar errores de captura.
- **Fechas:** el año de construcción va de 1800 al año actual y la fecha de recuento no puede ser futura.
- **Inventario:** si se registra alguna medida, la unidad es obligatoria y solo puede ser `mm`, `cm` o `m`. El tipo es una clave en mayúsculas (`AIRE_ACONDICIONADO`).
- **Textos:** se quitan los espacios al inicio y al final; un nombre o clave hecho solo de espacios se rechaza.

Las reglas de pisos y unidades solo se revisan cuando cambian esos campos, para que los registros anteriores se puedan seguir editando. Estas reglas viven en la API (`esquemas.py` y los ganchos `validar_*` de inmuebles), no en la base, para no cambiar el esquema compartido con Supabase.

## Teléfonos, tabletas y computadoras

La interfaz se adapta al ancho de la pantalla (reglas al final de `frontend/src/estilos.css`):

| Ancho | Cómo se ve |
| --- | --- |
| Más de 1100 px (computadora) | Menú lateral, tablas completas y panel de detalle a la derecha. Una tabla con muchas columnas se desplaza de lado dentro de su recuadro |
| 761 a 1100 px (tableta) | Menú lateral más angosto; el panel de detalle flota sobre la lista y se cierra con «Cerrar», tocando el fondo o con Escape |
| 900 px o menos | Cada fila de una tabla se muestra como tarjeta con el título de cada dato (`data-etiqueta` en el JSX); los datos vacíos se ocultan |
| 760 px o menos (teléfono) | El menú es una barra superior con botón «Menú», el panel de detalle ocupa toda la pantalla, botones y campos más altos para el dedo y texto de 16 px en los campos para que el teléfono no haga zoom |

## Pantalla de Resumen

Es la primera pantalla después de iniciar sesión y la ven todos los roles. Va de lo general a lo particular:

1. **Indicadores:** edificios y áreas operativos, porcentaje del inventario en buen estado y servicios con problema.
2. **Estado de edificios y áreas** y **estado del inventario por tipo**, en barras apiladas (bueno, regular, malo, fuera de servicio).
3. **Tabla de edificios**, de la más urgente a la menos urgente: estado, áreas operativas e inventario dañado. Al hacer clic se abre el edificio.
4. **Servicios que no operan con normalidad** y **consumos de luz y agua** de los últimos 12 meses.

Usa tres rutas: `/resumen/inmuebles` (además de los totales devuelve `areas_por_estado`, `inventario_por_tipo_y_estado` y `edificios_detalle`), `/resumen/servicios` y `/resumen/consumos`. Las gráficas son barras hechas con CSS, sin librerías de gráficas. El inventario se cuenta por piezas: un registro de 6 bancas suma 6.

## Cálculos derivados del inventario

Los elementos de inventario conservan `cantidad` y pueden registrar `largo`, `alto`,
`ancho`, `espesor` y una unidad base. La API calcula en cada respuesta, sin guardar
resultados redundantes en PostgreSQL:

| Campo de respuesta | Fórmula | Magnitud si la unidad base es `m` |
| --- | --- | --- |
| `total_lineal` | `cantidad × largo` | `m` |
| `total_area` | `cantidad × largo × alto` | `m²` |
| `total_volumen` | `cantidad × largo × alto × ancho` | `m³` |
| `total_volumen_espesor` | `cantidad × largo × alto × espesor` | `m³` |

Si falta una medida necesaria, el cálculo correspondiente devuelve `null`. Estos
campos son de solo lectura: no se aceptan en `POST`, `PATCH` ni como propiedades
JSONB. Los resultados se redondean a cuatro decimales.

## Estructura

```text
├── db/init/                 esquema SQL y usuarios de base (se ejecutan la primera vez)
├── db/migraciones/          scripts para actualizar una base que ya existe
├── shared/comun/            paquete Python común a todos los servicios
├── services/
│   ├── auth/                login, JWT y usuarios
│   ├── inmuebles/           campus, edificios, áreas e inventario
│   ├── servicios/           agua, luz, internet, alcantarillado, su estado y consumos
│   ├── archivos/            adjuntos en un volumen local, enlaces de descarga firmados
│   └── audit/               historial firmado y verificación
├── gateway/                 API Gateway
├── frontend/                interfaz web (React)
├── observabilidad/          Prometheus y Grafana
├── tests/                   prueba unitaria de la cadena y prueba del sistema completo
├── backend.Dockerfile       imagen común de los servicios Python
└── docker-compose.yml
```

## Desarrollo

- **Frontend con recarga en vivo:** con el sistema arriba, entra en `frontend/` y ejecuta `npm install` y luego `npm run dev`. Abre http://localhost:5173 (Vite envía `/api` al gateway).
- **Pruebas unitarias:** `pip install pytest cryptography` y luego `pytest tests/test_cadena.py`.
- **Agregar un recurso nuevo:** define el modelo en `shared/comun/modelos.py` y la tabla en `01_esquema.sql`. Luego crea sus esquemas Pydantic y llama a `crear_router_recurso(...)`: con eso obtiene CRUD, propiedades, borrado lógico e historial.
- **Base local y Supabase:** `db/init/01_esquema.sql` tiene la misma estructura que la base del equipo en Supabase (tablas, columnas, restricciones con los mismos nombres, índices, disparadores y permisos), incluida la tabla `archivos_edificio` y las columnas de rehabilitación, planos y fachada de `edificios`. No copia datos: la base local arranca con los dos campus fijos y los usuarios de demostración. No incluye las tablas de respaldo `_backup_*` ni las extensiones propias de Supabase.
- **Cambios al esquema:** `db/init` solo se ejecuta con una base vacía. Tras modificarlo, usa `docker compose down -v` (borra los datos) o escribe un script en `db/migraciones/` y aplícalo con `psql` como dueño de la base. Como mejora se puede incorporar Alembic.

## Solución de problemas

- **Un servicio se reinicia en bucle:** revisa sus logs con `docker compose logs auth`. Lo más común es que `.env` no exista o que se cambiaran contraseñas con la base ya creada. En ese caso, `docker compose down -v`.
- **`remaining connection slots are reserved…` o `max clients reached`:** la base se quedó sin conexiones. Cada servicio abre hasta `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` conexiones, así que un sistema completo usa hasta 4 × (5 + 5) = 40 con los valores por defecto. Con una base compartida (por ejemplo, Supabase), usa `DB_POOL_SIZE=1` y `DB_MAX_OVERFLOW=2` (hasta 12 por sistema) y el puerto 6543 del pooler (modo transacción), y apaga tu sistema con `docker compose down` cuando no lo uses. El código ya desactiva las sentencias preparadas, que ese modo no admite.
- **Nadie puede iniciar sesión y los logs dicen `relation "sesiones" does not exist` o `column usuarios.debe_cambiar_contrasena does not exist`:** la base se creó antes de esos cambios. Aplica, en orden y como dueño de la base, los scripts de `db/migraciones/` que falten (`001_sesiones.sql`, `002_cambio_contrasena.sql`).
- **Inventario responde 500 y los logs dicen `relation "tipos_elemento" does not exist`:** falta aplicar `db/migraciones/006_tipos_elemento.sql`.
- **«Debes cambiar tu contraseña temporal antes de continuar»:** la cuenta es nueva o el Administrador restableció su contraseña. Al entrar, la aplicación muestra el formulario para cambiarla.
- **«Tu sesión se cerró (…)»:** alguien cerró la sesión, la cuenta se desactivó o el Administrador cambió la contraseña. Vuelve a iniciar sesión.
- **La página dice «Demasiadas peticiones»:** el gateway permite 5 intentos de login por minuto por IP. Se ajusta en `.env`.
- **El historial tarda en aparecer:** llega de forma asíncrona por RabbitMQ, normalmente en 1 o 2 segundos.
- **Puertos ocupados:** cambia el lado izquierdo de `ports:` en `docker-compose.yml`, por ejemplo `"8081:8000"`.
