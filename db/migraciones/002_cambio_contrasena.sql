-- =====================================================================
-- Migración 002: contraseñas temporales con cambio obligatorio.
--
-- Requiere la 001. Se ejecuta como dueño de la base, ANTES de levantar el
-- código nuevo: sin esta columna, ninguna petición pasa la revisión de sesión.
-- Una base local nueva no la necesita (db/init ya la incluye).
-- =====================================================================
BEGIN;

-- Las cuentas que ya existen conservan su contraseña: no se les obliga a cambiarla
ALTER TABLE usuarios
    ADD COLUMN debe_cambiar_contrasena BOOLEAN NOT NULL DEFAULT false;

-- Los demás servicios revisan esta columna en cada petición
GRANT SELECT (debe_cambiar_contrasena) ON usuarios TO inmuebles_svc, servicios_svc, audit_svc;

COMMIT;
