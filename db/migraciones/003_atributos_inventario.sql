-- Atributos adicionales del inventario de areas.
-- Es idempotente para instalaciones donde el DDL se aplico previamente.

BEGIN;

ALTER TABLE public.elementos_inventario
    ADD COLUMN IF NOT EXISTS eje TEXT,
    ADD COLUMN IF NOT EXISTS tramo TEXT,
    ADD COLUMN IF NOT EXISTS unidad TEXT,
    ADD COLUMN IF NOT EXISTS largo NUMERIC(14, 4),
    ADD COLUMN IF NOT EXISTS alto NUMERIC(14, 4),
    ADD COLUMN IF NOT EXISTS ancho NUMERIC(14, 4),
    ADD COLUMN IF NOT EXISTS espesor NUMERIC(14, 4),
    ADD COLUMN IF NOT EXISTS fecha_recuento DATE;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'elementos_inventario_largo_no_negativo') THEN
        ALTER TABLE public.elementos_inventario
            ADD CONSTRAINT elementos_inventario_largo_no_negativo CHECK (largo >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'elementos_inventario_alto_no_negativo') THEN
        ALTER TABLE public.elementos_inventario
            ADD CONSTRAINT elementos_inventario_alto_no_negativo CHECK (alto >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'elementos_inventario_ancho_no_negativo') THEN
        ALTER TABLE public.elementos_inventario
            ADD CONSTRAINT elementos_inventario_ancho_no_negativo CHECK (ancho >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'elementos_inventario_espesor_no_negativo') THEN
        ALTER TABLE public.elementos_inventario
            ADD CONSTRAINT elementos_inventario_espesor_no_negativo CHECK (espesor >= 0);
    END IF;
END $$;

COMMIT;
