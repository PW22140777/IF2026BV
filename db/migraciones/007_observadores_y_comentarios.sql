-- =====================================================================
-- Migración 007: rol Observador (entra con Microsoft Entra ID) y comentarios.
--
-- Para una base que ya existe. Una base local nueva no la necesita:
-- db/init ya incluye estos cambios. Se ejecuta como dueño de la base,
-- ANTES de levantar el código nuevo, pasando la contraseña del usuario
-- de base del servicio nuevo:
--
--   psql -v pass_comentarios="$DB_PASS_COMENTARIOS" -f 007_observadores_y_comentarios.sql
--
-- Es idempotente: se puede volver a ejecutar sin duplicar nada.
-- =====================================================================
\set ON_ERROR_STOP on
BEGIN;

-- ---------------------------------------------------------------- usuarios
-- El rol nuevo; el nombre del CHECK se busca porque las bases viejas lo tienen sin nombre fijo
DO $$
DECLARE
    nombre_check text;
BEGIN
    FOR nombre_check IN
        SELECT con.conname FROM pg_constraint con JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = 'usuarios' AND con.contype = 'c' AND pg_get_constraintdef(con.oid) LIKE '%rol%'
    LOOP
        EXECUTE format('ALTER TABLE usuarios DROP CONSTRAINT %I', nombre_check);
    END LOOP;
END $$;
ALTER TABLE usuarios
    ADD CONSTRAINT usuarios_rol_check CHECK (rol IN ('ADMINISTRADOR', 'TECNICO', 'CONSULTA', 'OBSERVADOR')),
    ALTER COLUMN hash_contrasena DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS proveedor_oauth TEXT,
    ADD COLUMN IF NOT EXISTS sujeto_oauth TEXT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'usuarios_oauth_unico') THEN
        ALTER TABLE usuarios ADD CONSTRAINT usuarios_oauth_unico UNIQUE (proveedor_oauth, sujeto_oauth);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'usuarios_con_acceso') THEN
        ALTER TABLE usuarios ADD CONSTRAINT usuarios_con_acceso
            CHECK (hash_contrasena IS NOT NULL OR sujeto_oauth IS NOT NULL);
    END IF;
END $$;

-- ------------------------------------------------- canjes del inicio OAuth
CREATE TABLE IF NOT EXISTS oauth_canjes (
    hash_codigo   TEXT PRIMARY KEY,
    sesion_id     UUID NOT NULL REFERENCES sesiones (id),
    creado_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_en     TIMESTAMPTZ NOT NULL,
    usado_en      TIMESTAMPTZ
);

-- ------------------------------------------------------------- comentarios
CREATE TABLE IF NOT EXISTS comentarios (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recurso             TEXT NOT NULL
                        CONSTRAINT comentarios_recurso_valido
                        CHECK (recurso IN ('EDIFICIO', 'AREA', 'INVENTARIO', 'SERVICIO', 'CONSUMO')),
    recurso_id          INTEGER NOT NULL,
    respuesta_a         INTEGER REFERENCES comentarios (id),
    texto               TEXT NOT NULL CONSTRAINT comentarios_texto_valido CHECK (length(btrim(texto)) BETWEEN 1 AND 2000),
    propiedades         JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por          INTEGER NOT NULL REFERENCES usuarios (id),
    modificado_en       TIMESTAMPTZ,
    modificado_por      INTEGER,
    eliminado_en        TIMESTAMPTZ,
    eliminado_por       INTEGER,
    motivo_eliminacion  TEXT
);
CREATE INDEX IF NOT EXISTS comentarios_por_recurso ON comentarios (recurso, recurso_id) WHERE eliminado_en IS NULL;

-- ------------------------------------------------- usuario de base nuevo
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'comentarios_svc') AS falta_rol \gset
\if :falta_rol
    CREATE ROLE comentarios_svc LOGIN PASSWORD :'pass_comentarios';
\endif

GRANT USAGE ON SCHEMA public TO comentarios_svc;
GRANT SELECT, INSERT, UPDATE ON oauth_canjes TO auth_svc;
GRANT SELECT ON sesiones TO comentarios_svc;
GRANT SELECT (id, nombre, rol, activo, debe_cambiar_contrasena) ON usuarios TO comentarios_svc;
GRANT SELECT, INSERT, UPDATE ON comentarios TO comentarios_svc;
GRANT SELECT ON edificios, areas, elementos_inventario, servicios_basicos, consumos TO comentarios_svc;
GRANT SELECT, INSERT, UPDATE ON outbox TO comentarios_svc;

COMMIT;
