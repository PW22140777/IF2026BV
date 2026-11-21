-- =====================================================================
-- Migración 010: fotos en los comentarios de los Observadores.
--
-- Las fotos son archivos adjuntos con recurso = 'COMENTARIO' (máximo 4 por
-- comentario; lo revisa comentarios-service). Para una base que ya tiene la
-- 009. Una base local nueva no la necesita: db/init ya la incluye.
--
--   psql -f 010_fotos_en_comentarios.sql
--
-- Es idempotente: se puede volver a ejecutar sin duplicar nada.
-- =====================================================================
\set ON_ERROR_STOP on
BEGIN;

ALTER TABLE archivos_adjuntos DROP CONSTRAINT IF EXISTS adjuntos_recurso_valido;
ALTER TABLE archivos_adjuntos ADD CONSTRAINT adjuntos_recurso_valido
    CHECK (recurso IN ('EDIFICIO', 'AREA', 'INVENTARIO', 'ORDEN_MANTENIMIENTO', 'COMENTARIO'));

-- comentarios-service guarda las fichas de las fotos de sus comentarios
GRANT SELECT, INSERT, UPDATE ON archivos_adjuntos TO comentarios_svc;

COMMIT;
