-- =====================================================================
-- Migración 001: sesiones en la base y correos en minúsculas.
--
-- Para una base que ya existe (por ejemplo, Supabase). Una base local
-- nueva no la necesita: db/init/01_esquema.sql ya incluye estos cambios.
-- Se ejecuta como dueño de la base, ANTES de levantar el código nuevo:
-- sin la tabla sesiones nadie puede iniciar sesión.
-- =====================================================================
BEGIN;

-- Correos en minúsculas, como los guarda auth-service
UPDATE usuarios SET email = lower(email) WHERE email <> lower(email);
ALTER TABLE usuarios
    ADD CONSTRAINT usuarios_email_minusculas CHECK (email = lower(email));

CREATE TABLE sesiones (
    id                 UUID PRIMARY KEY,
    usuario_id         INTEGER NOT NULL REFERENCES usuarios (id),
    creada_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_en          TIMESTAMPTZ NOT NULL,
    vence_en           TIMESTAMPTZ NOT NULL,
    revocada_en        TIMESTAMPTZ,
    motivo_revocacion  TEXT,
    ip                 TEXT
);
CREATE INDEX sesiones_abiertas ON sesiones (usuario_id) WHERE revocada_en IS NULL;

GRANT SELECT, INSERT, UPDATE ON sesiones TO auth_svc;
GRANT SELECT ON sesiones TO inmuebles_svc, servicios_svc, audit_svc;
GRANT SELECT (id, nombre, rol, activo) ON usuarios TO inmuebles_svc, servicios_svc, audit_svc;

COMMIT;
