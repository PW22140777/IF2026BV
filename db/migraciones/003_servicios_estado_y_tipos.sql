-- =====================================================================
-- Migración 003: estado de un servicio básico y catálogo de tipos ampliado.
--
-- Agrega el estado operativo de un servicio (operando, con falla,
-- suspendido, en mantenimiento), sus notas, y permite los tipos INTERNET
-- y ALCANTARILLADO además de AGUA y LUZ (IF-56, IF-60).
-- Se ejecuta como dueño de la base, ANTES de levantar el código nuevo:
-- sin la columna estado, el servicio no arranca.
-- Una base local nueva no la necesita (db/init ya la incluye).
-- =====================================================================
BEGIN;

-- El nombre del CHECK de "tipo" se busca en vez de asumirlo, por si alguna
-- base lo tiene con otro nombre.
DO $$
DECLARE
    nombre_check text;
BEGIN
    SELECT con.conname INTO nombre_check
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE rel.relname = 'servicios_basicos' AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) LIKE '%tipo%';
    EXECUTE format('ALTER TABLE servicios_basicos DROP CONSTRAINT %I', nombre_check);
END $$;

ALTER TABLE servicios_basicos
    ADD CONSTRAINT servicios_basicos_tipo_check CHECK (tipo IN ('AGUA', 'LUZ', 'INTERNET', 'ALCANTARILLADO')),
    ADD COLUMN estado TEXT NOT NULL DEFAULT 'OPERANDO'
        CHECK (estado IN ('OPERANDO', 'CON_FALLA', 'SUSPENDIDO', 'EN_MANTENIMIENTO')),
    ADD COLUMN descripcion TEXT;

COMMIT;
