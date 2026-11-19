#!/bin/bash
# =====================================================================
# Crea un usuario de base de datos por servicio con permisos mínimos.
# Las contraseñas vienen de variables de entorno (ver .env).
#
# Nota: ningún servicio tiene permiso DELETE sobre las tablas de
# recursos; el borrado es lógico (columna eliminado_en). Así, aunque un
# servicio tuviera un error, no podría borrar físicamente información.
# =====================================================================
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
     --username "${POSTGRES_USER:-postgres}" \
     --dbname "${POSTGRES_DB:-escuela}" \
     -v pass_auth="${DB_PASS_AUTH:?Falta DB_PASS_AUTH}" \
     -v pass_inmuebles="${DB_PASS_INMUEBLES:?Falta DB_PASS_INMUEBLES}" \
     -v pass_servicios="${DB_PASS_SERVICIOS:?Falta DB_PASS_SERVICIOS}" \
     -v pass_audit="${DB_PASS_AUDIT:?Falta DB_PASS_AUDIT}" \
     -v pass_comentarios="${DB_PASS_COMENTARIOS:?Falta DB_PASS_COMENTARIOS}"      -v pass_mantenimiento="${DB_PASS_MANTENIMIENTO:?Falta DB_PASS_MANTENIMIENTO}" <<'EOSQL'
CREATE ROLE auth_svc      LOGIN PASSWORD :'pass_auth';
CREATE ROLE inmuebles_svc LOGIN PASSWORD :'pass_inmuebles';
CREATE ROLE servicios_svc LOGIN PASSWORD :'pass_servicios';
CREATE ROLE audit_svc     LOGIN PASSWORD :'pass_audit';
CREATE ROLE comentarios_svc LOGIN PASSWORD :'pass_comentarios';
CREATE ROLE mantenimiento_svc LOGIN PASSWORD :'pass_mantenimiento';

-- Necesario explícitamente: algunos proveedores (p. ej. Supabase) no le dan
-- USAGE sobre el esquema "public" a un rol nuevo por default.
GRANT USAGE ON SCHEMA public TO auth_svc, inmuebles_svc, servicios_svc, audit_svc, comentarios_svc, mantenimiento_svc;

-- auth-service: usuarios, sesiones y canjes del inicio con Microsoft
GRANT SELECT, INSERT, UPDATE ON usuarios, sesiones, oauth_canjes TO auth_svc;

-- Los demás servicios revisan en cada petición que la sesión siga vigente y
-- leen el rol actual. De usuarios solo ven estas columnas, nunca el hash.
GRANT SELECT ON sesiones TO inmuebles_svc, servicios_svc, audit_svc, comentarios_svc, mantenimiento_svc;
GRANT SELECT (id, nombre, rol, activo, debe_cambiar_contrasena) ON usuarios
    TO inmuebles_svc, servicios_svc, audit_svc, comentarios_svc, mantenimiento_svc;

-- inmuebles-service: campus, edificios, archivos de edificio, áreas, inventario y su catálogo de tipos
GRANT SELECT, INSERT, UPDATE ON campus, edificios, archivos_edificio, areas, elementos_inventario, tipos_elemento TO inmuebles_svc;

-- servicios-service: servicios básicos y consumos; solo lectura de
-- campus, edificios y áreas para validar a quién abastece cada servicio
GRANT SELECT, INSERT, UPDATE ON servicios_basicos, consumos TO servicios_svc;
GRANT SELECT ON campus, edificios, archivos_edificio, areas TO servicios_svc;

-- comentarios-service: sus comentarios; solo lectura de los recursos para validar
-- que lo comentado exista y esté activo
GRANT SELECT, INSERT, UPDATE ON comentarios TO comentarios_svc;
GRANT SELECT ON edificios, areas, elementos_inventario, servicios_basicos, consumos TO comentarios_svc;

-- mantenimiento-service: plantillas, órdenes y técnicos asignados; solo lectura de los
-- recursos (y su catálogo de tipos) para saber a qué aplica cada plantilla
GRANT SELECT, INSERT, UPDATE ON plantillas_mantenimiento, ordenes_mantenimiento TO mantenimiento_svc;
GRANT SELECT, INSERT, UPDATE ON ordenes_tecnicos TO mantenimiento_svc;
GRANT SELECT ON edificios, areas, elementos_inventario, servicios_basicos, tipos_elemento TO mantenimiento_svc;

-- Fichas de los archivos adjuntos (los archivos los guarda archivos-service, que no usa la base)
GRANT SELECT, INSERT, UPDATE ON archivos_adjuntos TO inmuebles_svc, mantenimiento_svc;

-- Todos los servicios que generan eventos escriben en la outbox
GRANT SELECT, INSERT, UPDATE ON outbox TO auth_svc, inmuebles_svc, servicios_svc, comentarios_svc, mantenimiento_svc;

-- Consumidores de eventos (inmuebles aplica el estado que deja un mantenimiento)
GRANT SELECT, INSERT ON eventos_procesados TO servicios_svc, audit_svc, inmuebles_svc, mantenimiento_svc;

-- audit-service: solo puede AGREGAR y LEER la bitácora
GRANT SELECT, INSERT ON audit_log TO audit_svc;
EOSQL

echo "Usuarios de base de datos por servicio creados."
