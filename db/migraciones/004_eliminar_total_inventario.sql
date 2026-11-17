-- Los totales del inventario se calculan al construir la respuesta de la API.
-- Esta migracion tambien cubre entornos que recibieron temporalmente la columna total.

BEGIN;

ALTER TABLE public.elementos_inventario
    DROP CONSTRAINT IF EXISTS elementos_inventario_total_no_negativo,
    DROP COLUMN IF EXISTS total;

COMMIT;
