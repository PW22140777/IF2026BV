-- =====================================================================
-- Migración 006: catálogo de tipos de elemento de inventario.
--
-- Cada tipo define qué propiedades lleva un elemento (p. ej. un aire
-- acondicionado: capacidad en BTU, refrigerante...) y si se mide.
-- Para una base que ya existe (por ejemplo, Supabase). Una base local
-- nueva no la necesita: db/init/01_esquema.sql ya la incluye.
-- Se ejecuta como dueño de la base, ANTES de levantar el código nuevo:
-- sin la tabla, inventario no puede crear ni modificar elementos.
-- Es idempotente: se puede volver a ejecutar sin duplicar nada.
-- (Se numera 006 porque la rama IFD22140755 ya usa 004 y 005.)
-- =====================================================================
BEGIN;

-- Catálogo de tipos de elemento de inventario (dueño: inmuebles-service).
-- Cada tipo dice qué propiedades lleva un elemento de ese tipo (propiedades_definidas)
-- y si se mide (largo, alto, ancho, espesor). Lo administra el Administrador.
-- propiedades_definidas es una lista como:
--   [{"clave": "btu", "etiqueta": "Capacidad", "tipo": "numero", "unidad": "BTU",
--     "minimo": 1, "maximo": null, "opciones": null, "requerida": true}]
-- tipo: texto, numero, opcion (con "opciones"), fecha o si_no.
CREATE TABLE IF NOT EXISTS tipos_elemento (
    id                     INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clave                  TEXT NOT NULL
                           CONSTRAINT tipos_elemento_clave_valida CHECK (clave ~ '^[A-ZÑ0-9_]+$'),
    nombre                 TEXT NOT NULL,                 -- p. ej. Aire acondicionado
    descripcion            TEXT,
    usa_medidas            BOOLEAN NOT NULL DEFAULT false,
    propiedades_definidas  JSONB NOT NULL DEFAULT '[]'::jsonb
                           CONSTRAINT tipos_elemento_definiciones_lista CHECK (jsonb_typeof(propiedades_definidas) = 'array'),
    propiedades            JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en              TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por             INTEGER,
    modificado_en          TIMESTAMPTZ,
    modificado_por         INTEGER,
    eliminado_en           TIMESTAMPTZ,
    eliminado_por          INTEGER,
    motivo_eliminacion     TEXT
);
-- La clave es la que guarda elementos_inventario.tipo; solo se repite si el anterior está eliminado
CREATE UNIQUE INDEX IF NOT EXISTS tipos_elemento_clave_activa ON tipos_elemento (clave) WHERE eliminado_en IS NULL;

-- Tipos iniciales: solo se cargan si el catálogo está vacío
INSERT INTO tipos_elemento (clave, nombre, usa_medidas, propiedades_definidas)
SELECT clave, nombre, usa_medidas, propiedades_definidas::jsonb
FROM (VALUES
    ('PARED', 'Pared', true, '[
        {"clave": "material", "etiqueta": "Material", "tipo": "opcion", "opciones": ["Block", "Concreto", "Tablaroca", "Ladrillo", "Otro"]},
        {"clave": "acabado", "etiqueta": "Acabado", "tipo": "opcion", "opciones": ["Aplanado", "Pintura", "Azulejo", "Aparente"]},
        {"clave": "color", "etiqueta": "Color", "tipo": "texto"}]'),
    ('CONTACTO', 'Contacto eléctrico', false, '[
        {"clave": "voltaje", "etiqueta": "Voltaje", "tipo": "opcion", "opciones": ["127 V", "220 V"]},
        {"clave": "tipo_contacto", "etiqueta": "Tipo de contacto", "tipo": "opcion", "opciones": ["Sencillo", "Doble", "Regulado", "Con USB"]},
        {"clave": "con_tierra", "etiqueta": "Con tierra física", "tipo": "si_no"}]'),
    ('AIRE_ACONDICIONADO', 'Aire acondicionado', false, '[
        {"clave": "btu", "etiqueta": "Capacidad", "tipo": "numero", "unidad": "BTU", "minimo": 1, "requerida": true},
        {"clave": "tipo_equipo", "etiqueta": "Tipo de equipo", "tipo": "opcion", "opciones": ["Minisplit", "Ventana", "Central", "Paquete"]},
        {"clave": "refrigerante", "etiqueta": "Refrigerante", "tipo": "opcion", "opciones": ["R410A", "R32", "R22"]},
        {"clave": "voltaje", "etiqueta": "Voltaje", "tipo": "opcion", "opciones": ["127 V", "220 V"]},
        {"clave": "ultimo_mantenimiento", "etiqueta": "Último mantenimiento", "tipo": "fecha"}]'),
    ('LUMINARIA', 'Luminaria', false, '[
        {"clave": "tecnologia", "etiqueta": "Tecnología", "tipo": "opcion", "opciones": ["LED", "Fluorescente", "Incandescente", "Halógena"]},
        {"clave": "potencia", "etiqueta": "Potencia", "tipo": "numero", "unidad": "W", "minimo": 0.1}]'),
    ('PUERTA', 'Puerta', true, '[
        {"clave": "material", "etiqueta": "Material", "tipo": "opcion", "opciones": ["Madera", "Metal", "Vidrio", "Aluminio"]},
        {"clave": "con_cerradura", "etiqueta": "Con cerradura", "tipo": "si_no"}]'),
    ('VENTANA', 'Ventana', true, '[
        {"clave": "material_marco", "etiqueta": "Material del marco", "tipo": "opcion", "opciones": ["Aluminio", "PVC", "Madera", "Herrería"]},
        {"clave": "tipo_vidrio", "etiqueta": "Tipo de vidrio", "tipo": "opcion", "opciones": ["Sencillo", "Doble", "Templado"]},
        {"clave": "con_proteccion", "etiqueta": "Con protección", "tipo": "si_no"}]'),
    ('PIZARRON', 'Pizarrón', true, '[
        {"clave": "tipo_pizarron", "etiqueta": "Tipo", "tipo": "opcion", "opciones": ["Blanco", "Verde", "Interactivo"]}]'),
    ('BANCA', 'Banca', false, '[
        {"clave": "material", "etiqueta": "Material", "tipo": "opcion", "opciones": ["Madera", "Metal", "Plástico", "Concreto"]},
        {"clave": "asientos", "etiqueta": "Asientos", "tipo": "numero", "minimo": 1}]'),
    ('MESA', 'Mesa', true, '[
        {"clave": "material", "etiqueta": "Material", "tipo": "opcion", "opciones": ["Madera", "Metal", "Plástico", "Melamina"]},
        {"clave": "forma", "etiqueta": "Forma", "tipo": "opcion", "opciones": ["Rectangular", "Cuadrada", "Redonda"]},
        {"clave": "asientos", "etiqueta": "Asientos", "tipo": "numero", "minimo": 1}]'),
    ('BEBEDERO', 'Bebedero', false, '[
        {"clave": "con_filtro", "etiqueta": "Con filtro", "tipo": "si_no"},
        {"clave": "ultimo_cambio_filtro", "etiqueta": "Último cambio de filtro", "tipo": "fecha"}]'),
    ('PROYECTOR', 'Proyector', false, '[
        {"clave": "lumenes", "etiqueta": "Brillo", "tipo": "numero", "unidad": "lm", "minimo": 1},
        {"clave": "resolucion", "etiqueta": "Resolución", "tipo": "opcion", "opciones": ["SVGA", "XGA", "WXGA", "Full HD", "4K"]},
        {"clave": "horas_lampara", "etiqueta": "Horas de lámpara", "tipo": "numero", "unidad": "h", "minimo": 0}]')
) AS semilla (clave, nombre, usa_medidas, propiedades_definidas)
WHERE NOT EXISTS (SELECT 1 FROM tipos_elemento);

-- Los tipos que ya se usan en el inventario y no están en el catálogo se
-- registran sin propiedades, para que esos elementos se puedan seguir editando
INSERT INTO tipos_elemento (clave, nombre)
SELECT DISTINCT e.tipo, initcap(replace(lower(e.tipo), '_', ' '))
FROM elementos_inventario e
WHERE e.tipo ~ '^[A-ZÑ0-9_]+$'
  AND NOT EXISTS (SELECT 1 FROM tipos_elemento t WHERE t.clave = e.tipo AND t.eliminado_en IS NULL);

GRANT SELECT, INSERT, UPDATE ON tipos_elemento TO inmuebles_svc;

COMMIT;
