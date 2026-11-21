-- =====================================================================
-- Migración 009: archivos adjuntos (tabla archivos_adjuntos).
--
-- Para una base que ya existe y ya tiene la 008. Una base local nueva no la
-- necesita: db/init ya la incluye. Se ejecuta como dueño de la base, ANTES
-- de levantar el código nuevo:
--
--   psql -f 009_archivos_adjuntos.sql
--
-- Es idempotente: se puede volver a ejecutar sin duplicar nada.
-- =====================================================================
\set ON_ERROR_STOP on
BEGIN;

-- ---------------------------------------------------------------------
-- Archivos adjuntos (fotos, planos, PDF, evidencias de mantenimiento)
-- La ficha vive aquí; el archivo, en el almacén de archivos-service (un
-- volumen local), bajo `clave` = carpeta/<sha256>.<ext>. Escriben las fichas
-- inmuebles-service (edificios, áreas, inventario) y mantenimiento-service
-- (evidencias de una orden). Al quitar un adjunto la ficha se marca como
-- eliminada (borrado lógico) y el archivo sí se borra del almacén.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS archivos_adjuntos (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recurso             TEXT NOT NULL
                        CONSTRAINT adjuntos_recurso_valido
                        CHECK (recurso IN ('EDIFICIO', 'AREA', 'INVENTARIO', 'ORDEN_MANTENIMIENTO')),
    recurso_id          INTEGER NOT NULL,
    nombre              TEXT NOT NULL CONSTRAINT adjuntos_nombre_valido CHECK (length(btrim(nombre)) BETWEEN 1 AND 120),
    descripcion         TEXT CONSTRAINT adjuntos_descripcion_valida CHECK (length(descripcion) <= 500),
    categoria           TEXT NOT NULL
                        CONSTRAINT adjuntos_categoria_valida
                        CHECK (categoria IN ('FOTO', 'PLANO', 'DOCUMENTO', 'EVIDENCIA', 'OTRO')),
    nombre_original     TEXT NOT NULL,
    tipo_mime           TEXT NOT NULL
                        CONSTRAINT adjuntos_tipo_valido
                        CHECK (tipo_mime IN ('image/jpeg', 'image/png', 'image/webp', 'application/pdf')),
    tamano_bytes        INTEGER NOT NULL CONSTRAINT adjuntos_tamano_valido CHECK (tamano_bytes > 0),
    sha256              CHAR(64) NOT NULL,
    clave               TEXT NOT NULL,
    propiedades         JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por          INTEGER NOT NULL REFERENCES usuarios (id),
    modificado_en       TIMESTAMPTZ,
    modificado_por      INTEGER,
    eliminado_en        TIMESTAMPTZ,
    eliminado_por       INTEGER,
    motivo_eliminacion  TEXT
);
CREATE INDEX IF NOT EXISTS adjuntos_por_recurso ON archivos_adjuntos (recurso, recurso_id) WHERE eliminado_en IS NULL;
CREATE INDEX IF NOT EXISTS adjuntos_por_clave ON archivos_adjuntos (clave) WHERE eliminado_en IS NULL;

-- Solo agregar, leer y marcar como eliminada; ningún servicio tiene DELETE
GRANT SELECT, INSERT, UPDATE ON archivos_adjuntos TO inmuebles_svc, mantenimiento_svc;

COMMIT;
