-- =====================================================================
-- Migración 008: mantenimientos (plantillas, órdenes y técnicos asignados).
--
-- Para una base que ya existe y ya tiene la 007. Una base local nueva no la
-- necesita: db/init ya la incluye. Se ejecuta como dueño de la base, ANTES
-- de levantar el código nuevo:
--
--   psql -v pass_mantenimiento="$DB_PASS_MANTENIMIENTO" -f 008_mantenimientos.sql
--
-- Es idempotente: se puede volver a ejecutar sin duplicar nada.
-- =====================================================================
\set ON_ERROR_STOP on
BEGIN;

-- ---------------------------------------------------------------------
-- Mantenimientos (dueño: mantenimiento-service)
-- Una plantilla dice a qué recursos aplica, cuándo se crea una orden (por
-- estado, por calendario o a mano), qué se registra al terminar y en qué
-- estado queda el recurso según el resultado. Cada orden es un mantenimiento
-- concreto: Programada -> En curso -> Terminada (o Cancelada).
-- El estado del recurso lo cambian inmuebles/servicios al recibir el evento.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plantillas_mantenimiento (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre              TEXT NOT NULL,
    descripcion         TEXT,
    recurso             TEXT NOT NULL
                        CONSTRAINT plantillas_recurso_valido CHECK (recurso IN ('EDIFICIO', 'AREA', 'INVENTARIO', 'SERVICIO')),
    tipo_elemento       TEXT,           -- solo inventario: clave de tipos_elemento (NULL = cualquier tipo)
    disparo             TEXT NOT NULL
                        CONSTRAINT plantillas_disparo_valido CHECK (disparo IN ('ESTADO', 'PERIODICO', 'MANUAL')),
    estados_disparo     JSONB NOT NULL DEFAULT '[]'::jsonb,   -- disparo ESTADO: ["MALO", "FUERA_DE_SERVICIO"]
    cada_dias           INTEGER CONSTRAINT plantillas_cada_dias_valido CHECK (cada_dias BETWEEN 1 AND 3650),
    estado_al_iniciar   TEXT,           -- NULL = el recurso no cambia al iniciar
    estado_resuelto     TEXT NOT NULL,
    estado_parcial      TEXT NOT NULL,
    estado_no_resuelto  TEXT NOT NULL,
    lista_verificacion  JSONB NOT NULL DEFAULT '[]'::jsonb,   -- mismo formato que propiedades_definidas
    activa              BOOLEAN NOT NULL DEFAULT true,
    propiedades         JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por          INTEGER,
    modificado_en       TIMESTAMPTZ,
    modificado_por      INTEGER,
    eliminado_en        TIMESTAMPTZ,
    eliminado_por       INTEGER,
    motivo_eliminacion  TEXT,
    CONSTRAINT plantillas_periodo CHECK (disparo <> 'PERIODICO' OR cada_dias IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS ordenes_mantenimiento (
    id                    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plantilla_id          INTEGER NOT NULL REFERENCES plantillas_mantenimiento (id),
    recurso               TEXT NOT NULL
                          CONSTRAINT ordenes_recurso_valido CHECK (recurso IN ('EDIFICIO', 'AREA', 'INVENTARIO', 'SERVICIO')),
    recurso_id            INTEGER NOT NULL,
    origen                TEXT NOT NULL CONSTRAINT ordenes_origen_valido CHECK (origen IN ('ESTADO', 'PERIODICO', 'MANUAL')),
    estado                TEXT NOT NULL DEFAULT 'PROGRAMADA'
                          CONSTRAINT ordenes_estado_valido CHECK (estado IN ('PROGRAMADA', 'EN_CURSO', 'TERMINADA', 'CANCELADA')),
    fecha_programada      DATE NOT NULL DEFAULT CURRENT_DATE,
    iniciada_en           TIMESTAMPTZ,
    iniciada_por          INTEGER,
    terminada_en          TIMESTAMPTZ,
    terminada_por         INTEGER,
    resultado             TEXT CONSTRAINT ordenes_resultado_valido CHECK (resultado IN ('RESUELTO', 'PARCIAL', 'NO_RESUELTO')),
    respuestas            JSONB NOT NULL DEFAULT '{}'::jsonb,  -- lo que se registró de la lista de verificación
    notas                 TEXT,
    estado_recurso_nuevo  TEXT,          -- estado que se pidió aplicar al recurso en la última transición
    motivo_cancelacion    TEXT,
    propiedades           JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en             TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por            INTEGER,
    modificado_en         TIMESTAMPTZ,
    modificado_por        INTEGER,
    eliminado_en          TIMESTAMPTZ,
    eliminado_por         INTEGER,
    motivo_eliminacion    TEXT,
    CONSTRAINT ordenes_terminada_con_resultado CHECK (estado <> 'TERMINADA' OR resultado IS NOT NULL)
);
-- Una sola orden abierta por plantilla y recurso, aunque un evento llegue dos veces
CREATE UNIQUE INDEX IF NOT EXISTS ordenes_una_abierta ON ordenes_mantenimiento (plantilla_id, recurso, recurso_id)
    WHERE estado IN ('PROGRAMADA', 'EN_CURSO') AND eliminado_en IS NULL;
CREATE INDEX IF NOT EXISTS ordenes_por_recurso ON ordenes_mantenimiento (recurso, recurso_id);

-- Técnicos asignados a cada orden (uno o más). Quitar a uno no borra la fila:
-- marca quitado_en, así se sabe quién estuvo asignado y cuándo
CREATE TABLE IF NOT EXISTS ordenes_tecnicos (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    orden_id      INTEGER NOT NULL REFERENCES ordenes_mantenimiento (id),
    usuario_id    INTEGER NOT NULL REFERENCES usuarios (id),
    asignado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    asignado_por  INTEGER,
    quitado_en    TIMESTAMPTZ,
    quitado_por   INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ordenes_tecnicos_vigente ON ordenes_tecnicos (orden_id, usuario_id) WHERE quitado_en IS NULL;

-- Plantillas iniciales: solo si todavía no hay ninguna
INSERT INTO plantillas_mantenimiento
    (nombre, descripcion, recurso, tipo_elemento, disparo, estados_disparo, cada_dias, estado_al_iniciar,
     estado_resuelto, estado_parcial, estado_no_resuelto, lista_verificacion)
SELECT nombre, descripcion, recurso, tipo_elemento, disparo, estados_disparo::jsonb, cada_dias::integer, estado_al_iniciar,
       estado_resuelto, estado_parcial, estado_no_resuelto, lista_verificacion::jsonb
FROM (VALUES
    ('Correctivo de aire acondicionado', 'Se abre sola cuando un aire acondicionado pasa a malo o fuera de servicio.',
     'INVENTARIO', 'AIRE_ACONDICIONADO', 'ESTADO', '["MALO", "FUERA_DE_SERVICIO"]', NULL, NULL,
     'BUENO', 'REGULAR', 'FUERA_DE_SERVICIO', '[
        {"clave": "diagnostico", "etiqueta": "Diagnóstico", "tipo": "texto", "requerida": true},
        {"clave": "piezas_cambiadas", "etiqueta": "Piezas cambiadas", "tipo": "texto"},
        {"clave": "refrigerante_recargado", "etiqueta": "Se recargó refrigerante", "tipo": "si_no"},
        {"clave": "temperatura_salida", "etiqueta": "Temperatura de salida", "tipo": "numero", "unidad": "°C", "minimo": -10, "maximo": 40}]'),
    ('Preventivo de aire acondicionado', 'Limpieza y revisión de cada aire acondicionado cada 90 días.',
     'INVENTARIO', 'AIRE_ACONDICIONADO', 'PERIODICO', '[]', 90, NULL,
     'BUENO', 'REGULAR', 'MALO', '[
        {"clave": "filtros_limpios", "etiqueta": "Filtros limpios", "tipo": "si_no", "requerida": true},
        {"clave": "serpentin_limpio", "etiqueta": "Serpentín limpio", "tipo": "si_no"},
        {"clave": "drenaje_libre", "etiqueta": "Drenaje libre", "tipo": "si_no"},
        {"clave": "presion_refrigerante", "etiqueta": "Presión del refrigerante", "tipo": "numero", "unidad": "psi", "minimo": 0, "maximo": 600}]'),
    ('Reparación de servicio con falla', 'Se abre sola cuando un servicio básico pasa a «con falla».',
     'SERVICIO', NULL, 'ESTADO', '["CON_FALLA"]', NULL, 'EN_MANTENIMIENTO',
     'OPERANDO', 'OPERANDO', 'CON_FALLA', '[
        {"clave": "causa", "etiqueta": "Causa de la falla", "tipo": "texto", "requerida": true},
        {"clave": "proveedor_contactado", "etiqueta": "Se contactó al proveedor", "tipo": "si_no"},
        {"clave": "folio_reporte", "etiqueta": "Folio del reporte", "tipo": "texto"}]')
) AS semilla (nombre, descripcion, recurso, tipo_elemento, disparo, estados_disparo, cada_dias, estado_al_iniciar,
     estado_resuelto, estado_parcial, estado_no_resuelto, lista_verificacion)
WHERE NOT EXISTS (SELECT 1 FROM plantillas_mantenimiento);

SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mantenimiento_svc') AS falta_rol \gset
\if :falta_rol
    CREATE ROLE mantenimiento_svc LOGIN PASSWORD :'pass_mantenimiento';
\endif

GRANT USAGE ON SCHEMA public TO mantenimiento_svc;
GRANT SELECT ON sesiones TO mantenimiento_svc;
GRANT SELECT (id, nombre, rol, activo, debe_cambiar_contrasena) ON usuarios TO mantenimiento_svc;
GRANT SELECT, INSERT, UPDATE ON plantillas_mantenimiento, ordenes_mantenimiento, ordenes_tecnicos TO mantenimiento_svc;
GRANT SELECT ON edificios, areas, elementos_inventario, servicios_basicos, tipos_elemento TO mantenimiento_svc;
GRANT SELECT, INSERT, UPDATE ON outbox TO mantenimiento_svc;
GRANT SELECT, INSERT ON eventos_procesados TO mantenimiento_svc, inmuebles_svc;

COMMIT;
