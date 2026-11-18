-- =====================================================================
-- Esquema de la base de datos única de Infraestructura Física
-- Se ejecuta automáticamente la primera vez que arranca el contenedor
-- de PostgreSQL (carpeta /docker-entrypoint-initdb.d).
-- =====================================================================

-- ---------------------------------------------------------------------
-- Usuarios del sistema (dueño: auth-service)
-- ---------------------------------------------------------------------
CREATE TABLE usuarios (
    id               INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre           TEXT NOT NULL,
    -- Siempre en minúsculas: así UNIQUE también impide «Ana@...» y «ana@...»
    email            TEXT NOT NULL UNIQUE CONSTRAINT usuarios_email_minusculas CHECK (email = lower(email)),
    hash_contrasena  TEXT,                 -- NULL en un Observador: entra solo con Microsoft
    rol              TEXT NOT NULL CONSTRAINT usuarios_rol_check
                     CHECK (rol IN ('ADMINISTRADOR', 'TECNICO', 'CONSULTA', 'OBSERVADOR')),
    activo           BOOLEAN NOT NULL DEFAULT true,
    -- true = contraseña temporal (cuenta nueva o restablecida): solo puede cambiarla
    debe_cambiar_contrasena  BOOLEAN NOT NULL DEFAULT false,
    creado_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por       INTEGER,
    modificado_en    TIMESTAMPTZ,
    modificado_por   INTEGER,
    -- Cuenta externa con la que entra (Observador): proveedor + identificador estable de la persona
    proveedor_oauth  TEXT,
    sujeto_oauth     TEXT,
    CONSTRAINT usuarios_oauth_unico UNIQUE (proveedor_oauth, sujeto_oauth),
    -- Toda cuenta tiene una forma de entrar: contraseña o cuenta externa
    CONSTRAINT usuarios_con_acceso CHECK (hash_contrasena IS NOT NULL OR sujeto_oauth IS NOT NULL)
);

-- Sesiones iniciadas (dueño: auth-service). Los demás servicios las leen en
-- cada petición para saber si la sesión sigue viva y el rol actual.
-- expira_en se extiende con la actividad; vence_en es el máximo y no cambia.
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

-- Códigos de un solo uso para entregar la sesión tras entrar con Microsoft (dueño: auth-service).
-- El navegador recibe el código en la URL y lo cambia por el JWT con POST /auth/oauth/canjear:
-- así el token nunca viaja en una URL. Se guarda el hash del código, no el código.
CREATE TABLE oauth_canjes (
    hash_codigo   TEXT PRIMARY KEY,
    sesion_id     UUID NOT NULL REFERENCES sesiones (id),
    creado_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_en     TIMESTAMPTZ NOT NULL,
    usado_en      TIMESTAMPTZ
);

-- ---------------------------------------------------------------------
-- Recursos inmobiliarios (dueño: inmuebles-service)
-- Jerarquía: campus > edificio > área > inventario.
-- Un área puede no tener edificio (cancha, bancas), pero SIEMPRE
-- pertenece a un campus.
-- Todas las tablas de recursos llevan columnas de responsabilidad y
-- borrado lógico: nunca se borra una fila, solo se marca eliminado_en.
-- ---------------------------------------------------------------------
CREATE TABLE campus (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clave               TEXT NOT NULL,                 -- p. ej. CU
    nombre              TEXT NOT NULL,                 -- p. ej. Campus Centro
    direccion           TEXT,
    ciudad              TEXT,
    superficie_m2       NUMERIC(12, 2) CHECK (superficie_m2 >= 0),
    estado              TEXT NOT NULL DEFAULT 'OPERATIVO'
                        CHECK (estado IN ('OPERATIVO', 'EN_MANTENIMIENTO', 'FUERA_DE_SERVICIO')),
    descripcion         TEXT,
    propiedades         JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por          INTEGER,
    modificado_en       TIMESTAMPTZ,
    modificado_por      INTEGER,
    eliminado_en        TIMESTAMPTZ,
    eliminado_por       INTEGER,
    motivo_eliminacion  TEXT
);
CREATE UNIQUE INDEX campus_clave_activa ON campus (clave) WHERE eliminado_en IS NULL;

-- Los dos únicos campus de la institución (fijos)
INSERT INTO campus (clave, nombre, estado) VALUES
    ('CENTRO', 'Campus Centro', 'OPERATIVO'),
    ('NORTE',  'Campus Norte',  'OPERATIVO');

CREATE TABLE edificios (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    campus_id           INTEGER NOT NULL REFERENCES campus (id),
    clave               TEXT NOT NULL,                 -- p. ej. ED-A
    nombre              TEXT NOT NULL,
    niveles             INTEGER CHECK (niveles >= 1),
    anio_construccion   INTEGER CHECK (anio_construccion BETWEEN 1800 AND 2200),
    superficie_m2       NUMERIC(10, 2) CHECK (superficie_m2 >= 0),
    estado              TEXT NOT NULL DEFAULT 'OPERATIVO'
                        CHECK (estado IN ('OPERATIVO', 'EN_MANTENIMIENTO', 'FUERA_DE_SERVICIO')),
    funcional           BOOLEAN NOT NULL DEFAULT true,
    rehabilitado        BOOLEAN NOT NULL DEFAULT false,
    fecha_inicio_rehabilitacion  DATE,
    fecha_termino_rehabilitacion DATE,
    carpeta_planos      TEXT,
    fachada_s3          TEXT,                          -- clave en S3 de la foto de fachada
    descripcion         TEXT,
    propiedades         JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por          INTEGER,
    modificado_en       TIMESTAMPTZ,
    modificado_por      INTEGER,
    eliminado_en        TIMESTAMPTZ,
    eliminado_por       INTEGER,
    motivo_eliminacion  TEXT,
    CONSTRAINT edificios_fechas_rehabilitacion_validas CHECK (
        fecha_termino_rehabilitacion IS NULL
        OR fecha_inicio_rehabilitacion IS NULL
        OR fecha_termino_rehabilitacion >= fecha_inicio_rehabilitacion
    )
);
-- La clave solo debe ser única entre los edificios activos del mismo campus
CREATE UNIQUE INDEX edificios_clave_activa ON edificios (campus_id, clave) WHERE eliminado_en IS NULL;
CREATE INDEX edificios_campus ON edificios (campus_id);
-- Permite que las áreas referencien (edificio, campus) y la base garantice
-- que un área nunca quede en un campus distinto al de su edificio
ALTER TABLE edificios ADD CONSTRAINT edificios_id_campus UNIQUE (id, campus_id);

-- Planos, fotos y documentos de un edificio. El archivo vive en S3; aquí solo su ficha.
CREATE TABLE archivos_edificio (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    edificio_id         INTEGER NOT NULL REFERENCES edificios (id),
    nombre              TEXT NOT NULL,                 -- p. ej. Plano arquitectónico Planta Baja
    descripcion         TEXT,
    nombre_original     TEXT NOT NULL,                 -- p. ej. plano_pb.pdf
    tipo_mime           TEXT NOT NULL
                        CHECK (tipo_mime IN (
                            'application/pdf',
                            'image/jpeg',
                            'image/png',
                            'image/webp'
                        )),
    tamano_bytes        INTEGER NOT NULL CHECK (tamano_bytes > 0),
    clave_s3            TEXT NOT NULL UNIQUE,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por          INTEGER,
    modificado_en       TIMESTAMPTZ,
    modificado_por      INTEGER,
    eliminado_en        TIMESTAMPTZ,
    eliminado_por       INTEGER,
    motivo_eliminacion  TEXT
);
CREATE INDEX archivos_edificio_activos ON archivos_edificio (edificio_id) WHERE eliminado_en IS NULL;

CREATE TABLE areas (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    campus_id           INTEGER NOT NULL REFERENCES campus (id),
    edificio_id         INTEGER,                              -- NULL = área independiente
    nombre              TEXT NOT NULL,                        -- p. ej. Cancha de básquetbol
    tipo                TEXT NOT NULL                         -- catálogo de tipos de espacio (interiores y exteriores)
                        CONSTRAINT areas_tipo_valido CHECK (tipo IN ('AULA', 'LABORATORIO', 'BIBLIOTECA', 'OFICINA', 'BANO',
                                        'CANCHA', 'ESTACIONAMIENTO', 'AREA_VERDE', 'BANCAS', 'PATIO')),
    piso                INTEGER,
    capacidad           INTEGER CHECK (capacidad >= 0),
    superficie_m2       NUMERIC(10, 2) CHECK (superficie_m2 >= 0),
    exterior            BOOLEAN NOT NULL DEFAULT false,
    estado              TEXT NOT NULL DEFAULT 'OPERATIVO'
                        CHECK (estado IN ('OPERATIVO', 'EN_MANTENIMIENTO', 'FUERA_DE_SERVICIO')),
    descripcion         TEXT,
    propiedades         JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por          INTEGER,
    modificado_en       TIMESTAMPTZ,
    modificado_por      INTEGER,
    eliminado_en        TIMESTAMPTZ,
    eliminado_por       INTEGER,
    motivo_eliminacion  TEXT,
    -- Si tiene edificio, debe ser un edificio del mismo campus
    CONSTRAINT areas_edificio_mismo_campus FOREIGN KEY (edificio_id, campus_id)
        REFERENCES edificios (id, campus_id)
);
CREATE INDEX areas_edificio ON areas (edificio_id);
CREATE INDEX areas_campus ON areas (campus_id);

-- Catálogo de tipos de elemento de inventario (dueño: inmuebles-service).
-- Cada tipo dice qué propiedades lleva un elemento de ese tipo (propiedades_definidas)
-- y si se mide (largo, alto, ancho, espesor). Lo administra el Administrador.
-- propiedades_definidas es una lista como:
--   [{"clave": "btu", "etiqueta": "Capacidad", "tipo": "numero", "unidad": "BTU",
--     "minimo": 1, "maximo": null, "opciones": null, "requerida": true}]
-- tipo: texto, numero, opcion (con "opciones"), fecha o si_no.
CREATE TABLE tipos_elemento (
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
CREATE UNIQUE INDEX tipos_elemento_clave_activa ON tipos_elemento (clave) WHERE eliminado_en IS NULL;

-- Tipos iniciales con sus propiedades (el Administrador puede cambiarlos después)
INSERT INTO tipos_elemento (clave, nombre, usa_medidas, propiedades_definidas) VALUES
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
        {"clave": "horas_lampara", "etiqueta": "Horas de lámpara", "tipo": "numero", "unidad": "h", "minimo": 0}]');

CREATE TABLE elementos_inventario (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    area_id             INTEGER NOT NULL REFERENCES areas (id),
    tipo                TEXT NOT NULL,      -- clave de tipos_elemento: PARED, CONTACTO, AIRE_ACONDICIONADO...
    eje                 TEXT,
    tramo               TEXT,
    unidad              TEXT,
    -- Mismos nombres de restricción que crea la migración 003 en Supabase
    largo               NUMERIC(14, 4) CONSTRAINT elementos_inventario_largo_no_negativo CHECK (largo >= 0),
    alto                NUMERIC(14, 4) CONSTRAINT elementos_inventario_alto_no_negativo CHECK (alto >= 0),
    ancho               NUMERIC(14, 4) CONSTRAINT elementos_inventario_ancho_no_negativo CHECK (ancho >= 0),
    espesor             NUMERIC(14, 4) CONSTRAINT elementos_inventario_espesor_no_negativo CHECK (espesor >= 0),
    fecha_recuento      DATE,
    descripcion         TEXT,
    cantidad            INTEGER NOT NULL DEFAULT 1 CHECK (cantidad > 0),
    marca               TEXT,
    modelo              TEXT,
    numero_serie        TEXT,
    estado              TEXT NOT NULL DEFAULT 'BUENO'
                        CHECK (estado IN ('BUENO', 'REGULAR', 'MALO', 'FUERA_DE_SERVICIO')),
    propiedades         JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {"btu": 12000, "gas": "R410A"}
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por          INTEGER,
    modificado_en       TIMESTAMPTZ,
    modificado_por      INTEGER,
    eliminado_en        TIMESTAMPTZ,
    eliminado_por       INTEGER,
    motivo_eliminacion  TEXT
);
CREATE INDEX inventario_area ON elementos_inventario (area_id);

-- ---------------------------------------------------------------------
-- Servicios básicos y consumos (dueño: servicios-service)
-- ---------------------------------------------------------------------
CREATE TABLE servicios_basicos (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo                TEXT NOT NULL CHECK (tipo IN ('AGUA', 'LUZ', 'INTERNET', 'ALCANTARILLADO')),
    nombre              TEXT NOT NULL,          -- p. ej. Medidor general edificio A
    numero_medidor      TEXT,
    proveedor           TEXT,                   -- p. ej. CFE, organismo de agua municipal
    campus_id           INTEGER REFERENCES campus (id),       -- toma general del campus
    edificio_id         INTEGER REFERENCES edificios (id),
    area_id             INTEGER REFERENCES areas (id),
    activo              BOOLEAN NOT NULL DEFAULT true,
    estado              TEXT NOT NULL DEFAULT 'OPERANDO'       -- catálogo de estado operativo
                        CHECK (estado IN ('OPERANDO', 'CON_FALLA', 'SUSPENDIDO', 'EN_MANTENIMIENTO')),
    descripcion         TEXT,                   -- notas libres, p. ej. motivo de la falla
    propiedades         JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por          INTEGER,
    modificado_en       TIMESTAMPTZ,
    modificado_por      INTEGER,
    eliminado_en        TIMESTAMPTZ,
    eliminado_por       INTEGER,
    motivo_eliminacion  TEXT,
    -- Un servicio abastece a exactamente uno: el campus completo, un edificio o un área
    CONSTRAINT servicio_un_destino CHECK (num_nonnulls(campus_id, edificio_id, area_id) = 1)
);

CREATE TABLE consumos (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    servicio_id         INTEGER NOT NULL REFERENCES servicios_basicos (id),
    periodo             DATE NOT NULL,                       -- primer día del mes
    cantidad            NUMERIC(14, 3) NOT NULL CHECK (cantidad >= 0),
    unidad              TEXT NOT NULL CHECK (unidad IN ('m3', 'kWh')),
    costo               NUMERIC(12, 2) CHECK (costo >= 0),
    propiedades         JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por          INTEGER,
    modificado_en       TIMESTAMPTZ,
    modificado_por      INTEGER,
    eliminado_en        TIMESTAMPTZ,
    eliminado_por       INTEGER,
    motivo_eliminacion  TEXT
);
CREATE UNIQUE INDEX consumos_periodo_activo ON consumos (servicio_id, periodo) WHERE eliminado_en IS NULL;

-- ---------------------------------------------------------------------
-- Comentarios sobre los recursos (dueño: comentarios-service)
-- Los escribe un Observador; el Técnico y el Administrador pueden responder
-- (respuesta_a). Solo el Administrador los oculta: borrado lógico con motivo.
-- ---------------------------------------------------------------------
CREATE TABLE comentarios (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recurso             TEXT NOT NULL
                        CONSTRAINT comentarios_recurso_valido
                        CHECK (recurso IN ('EDIFICIO', 'AREA', 'INVENTARIO', 'SERVICIO', 'CONSUMO')),
    recurso_id          INTEGER NOT NULL,
    respuesta_a         INTEGER REFERENCES comentarios (id),   -- NULL = comentario nuevo; si no, responde a ese
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
CREATE INDEX comentarios_por_recurso ON comentarios (recurso, recurso_id) WHERE eliminado_en IS NULL;

-- ---------------------------------------------------------------------
-- Mantenimientos (dueño: mantenimiento-service)
-- Una plantilla dice a qué recursos aplica, cuándo se crea una orden (por
-- estado, por calendario o a mano), qué se registra al terminar y en qué
-- estado queda el recurso según el resultado. Cada orden es un mantenimiento
-- concreto: Programada -> En curso -> Terminada (o Cancelada).
-- El estado del recurso lo cambian inmuebles/servicios al recibir el evento.
-- ---------------------------------------------------------------------
CREATE TABLE plantillas_mantenimiento (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre              TEXT NOT NULL,
    descripcion         TEXT,
    recurso             TEXT NOT NULL
                        CONSTRAINT plantillas_recurso_valido CHECK (recurso IN ('EDIFICIO', 'AREA', 'INVENTARIO', 'SERVICIO')),
    tipo_elemento       TEXT,           -- solo inventario: clave de tipos_elemento (NULL = cualquier tipo)
    disparo             TEXT NOT NULL
                        CONSTRAINT plantillas_disparo_valido CHECK (disparo IN ('ESTADO', 'PERIODICO', 'MANUAL')),
    estados_disparo     JSONB NOT NULL DEFAULT '[]'::jsonb,   -- disparo ESTADO: ["MALO", "FUERA_DE_SERVICIO"]
    cada_dias           INTEGER CONSTRAINT plantillas_cada_dias_valido CHECK (cada_dias BETWEEN 1 AND 3650),
    estado_al_iniciar   TEXT,           -- NULL = el recurso no cambia al iniciar
    estado_resuelto     TEXT NOT NULL,
    estado_parcial      TEXT NOT NULL,
    estado_no_resuelto  TEXT NOT NULL,
    lista_verificacion  JSONB NOT NULL DEFAULT '[]'::jsonb,   -- mismo formato que propiedades_definidas
    activa              BOOLEAN NOT NULL DEFAULT true,
    propiedades         JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por          INTEGER,
    modificado_en       TIMESTAMPTZ,
    modificado_por      INTEGER,
    eliminado_en        TIMESTAMPTZ,
    eliminado_por       INTEGER,
    motivo_eliminacion  TEXT,
    CONSTRAINT plantillas_periodo CHECK (disparo <> 'PERIODICO' OR cada_dias IS NOT NULL)
);

CREATE TABLE ordenes_mantenimiento (
    id                    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plantilla_id          INTEGER NOT NULL REFERENCES plantillas_mantenimiento (id),
    recurso               TEXT NOT NULL
                          CONSTRAINT ordenes_recurso_valido CHECK (recurso IN ('EDIFICIO', 'AREA', 'INVENTARIO', 'SERVICIO')),
    recurso_id            INTEGER NOT NULL,
    origen                TEXT NOT NULL CONSTRAINT ordenes_origen_valido CHECK (origen IN ('ESTADO', 'PERIODICO', 'MANUAL')),
    estado                TEXT NOT NULL DEFAULT 'PROGRAMADA'
                          CONSTRAINT ordenes_estado_valido CHECK (estado IN ('PROGRAMADA', 'EN_CURSO', 'TERMINADA', 'CANCELADA')),
    fecha_programada      DATE NOT NULL DEFAULT CURRENT_DATE,
    iniciada_en           TIMESTAMPTZ,
    iniciada_por          INTEGER,
    terminada_en          TIMESTAMPTZ,
    terminada_por         INTEGER,
    resultado             TEXT CONSTRAINT ordenes_resultado_valido CHECK (resultado IN ('RESUELTO', 'PARCIAL', 'NO_RESUELTO')),
    respuestas            JSONB NOT NULL DEFAULT '{}'::jsonb,  -- lo que se registró de la lista de verificación
    notas                 TEXT,
    estado_recurso_nuevo  TEXT,          -- estado que se pidió aplicar al recurso en la última transición
    motivo_cancelacion    TEXT,
    propiedades           JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en             TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por            INTEGER,
    modificado_en         TIMESTAMPTZ,
    modificado_por        INTEGER,
    eliminado_en          TIMESTAMPTZ,
    eliminado_por         INTEGER,
    motivo_eliminacion    TEXT,
    CONSTRAINT ordenes_terminada_con_resultado CHECK (estado <> 'TERMINADA' OR resultado IS NOT NULL)
);
-- Una sola orden abierta por plantilla y recurso, aunque un evento llegue dos veces
CREATE UNIQUE INDEX ordenes_una_abierta ON ordenes_mantenimiento (plantilla_id, recurso, recurso_id)
    WHERE estado IN ('PROGRAMADA', 'EN_CURSO') AND eliminado_en IS NULL;
CREATE INDEX ordenes_por_recurso ON ordenes_mantenimiento (recurso, recurso_id);

-- Técnicos asignados a cada orden (uno o más). Quitar a uno no borra la fila:
-- marca quitado_en, así se sabe quién estuvo asignado y cuándo
CREATE TABLE ordenes_tecnicos (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    orden_id      INTEGER NOT NULL REFERENCES ordenes_mantenimiento (id),
    usuario_id    INTEGER NOT NULL REFERENCES usuarios (id),
    asignado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    asignado_por  INTEGER,
    quitado_en    TIMESTAMPTZ,
    quitado_por   INTEGER
);
CREATE UNIQUE INDEX ordenes_tecnicos_vigente ON ordenes_tecnicos (orden_id, usuario_id) WHERE quitado_en IS NULL;

-- Plantillas iniciales (el Administrador puede cambiarlas)
INSERT INTO plantillas_mantenimiento
    (nombre, descripcion, recurso, tipo_elemento, disparo, estados_disparo, cada_dias, estado_al_iniciar,
     estado_resuelto, estado_parcial, estado_no_resuelto, lista_verificacion) VALUES
    ('Correctivo de aire acondicionado', 'Se abre sola cuando un aire acondicionado pasa a malo o fuera de servicio.',
     'INVENTARIO', 'AIRE_ACONDICIONADO', 'ESTADO', '["MALO", "FUERA_DE_SERVICIO"]', NULL, NULL,
     'BUENO', 'REGULAR', 'FUERA_DE_SERVICIO', '[
        {"clave": "diagnostico", "etiqueta": "Diagnóstico", "tipo": "texto", "requerida": true},
        {"clave": "piezas_cambiadas", "etiqueta": "Piezas cambiadas", "tipo": "texto"},
        {"clave": "refrigerante_recargado", "etiqueta": "Se recargó refrigerante", "tipo": "si_no"},
        {"clave": "temperatura_salida", "etiqueta": "Temperatura de salida", "tipo": "numero", "unidad": "°C", "minimo": -10, "maximo": 40}]'),
    ('Preventivo de aire acondicionado', 'Limpieza y revisión de cada aire acondicionado cada 90 días.',
     'INVENTARIO', 'AIRE_ACONDICIONADO', 'PERIODICO', '[]', 90, NULL,
     'BUENO', 'REGULAR', 'MALO', '[
        {"clave": "filtros_limpios", "etiqueta": "Filtros limpios", "tipo": "si_no", "requerida": true},
        {"clave": "serpentin_limpio", "etiqueta": "Serpentín limpio", "tipo": "si_no"},
        {"clave": "drenaje_libre", "etiqueta": "Drenaje libre", "tipo": "si_no"},
        {"clave": "presion_refrigerante", "etiqueta": "Presión del refrigerante", "tipo": "numero", "unidad": "psi", "minimo": 0, "maximo": 600}]'),
    ('Reparación de servicio con falla', 'Se abre sola cuando un servicio básico pasa a «con falla».',
     'SERVICIO', NULL, 'ESTADO', '["CON_FALLA"]', NULL, 'EN_MANTENIMIENTO',
     'OPERANDO', 'OPERANDO', 'CON_FALLA', '[
        {"clave": "causa", "etiqueta": "Causa de la falla", "tipo": "texto", "requerida": true},
        {"clave": "proveedor_contactado", "etiqueta": "Se contactó al proveedor", "tipo": "si_no"},
        {"clave": "folio_reporte", "etiqueta": "Folio del reporte", "tipo": "texto"}]');

-- ---------------------------------------------------------------------
-- Mensajería confiable
-- outbox: cada servicio escribe aquí sus eventos en la MISMA transacción
--         que el cambio de negocio; un proceso los publica en RabbitMQ.
-- eventos_procesados: evita que un consumidor procese dos veces un evento.
-- ---------------------------------------------------------------------
CREATE TABLE outbox (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    evento_id    UUID NOT NULL UNIQUE,
    tipo         TEXT NOT NULL,           -- p. ej. edificio.creado.v1
    origen       TEXT NOT NULL,           -- servicio que lo generó
    cuerpo       JSONB NOT NULL,
    cabeceras    JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
    enviado_en   TIMESTAMPTZ
);
CREATE INDEX outbox_pendientes ON outbox (id) WHERE enviado_en IS NULL;

CREATE TABLE eventos_procesados (
    consumidor    TEXT NOT NULL,
    evento_id     UUID NOT NULL,
    procesado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (consumidor, evento_id)
);

-- ---------------------------------------------------------------------
-- Historial firmado (dueño: audit-service)
-- Cada registro guarda el hash del anterior y una firma Ed25519.
-- ---------------------------------------------------------------------
CREATE TABLE audit_log (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    evento_id       UUID NOT NULL UNIQUE,
    fecha           TIMESTAMPTZ NOT NULL,         -- cuándo ocurrió la acción
    registrado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    usuario_id      INTEGER,
    usuario_nombre  TEXT,
    rol             TEXT,
    ip              TEXT,
    accion          TEXT NOT NULL,                -- CREAR, MODIFICAR, ELIMINAR, RESTAURAR, LOGIN...
    recurso         TEXT NOT NULL,                -- CAMPUS, EDIFICIO, AREA, INVENTARIO, SERVICIO, CONSUMO, USUARIO, SESION
    recurso_id      INTEGER,
    antes           JSONB,
    despues         JSONB,
    motivo          TEXT,
    correlation_id  TEXT,
    trace_id        TEXT,
    hash_anterior   TEXT NOT NULL,
    hash            TEXT NOT NULL,
    firma           TEXT NOT NULL,
    llave_id        TEXT NOT NULL
);
CREATE INDEX audit_recurso ON audit_log (recurso, recurso_id);
CREATE INDEX audit_usuario ON audit_log (usuario_id);

-- La bitácora es de solo agregar: se rechaza cualquier UPDATE, DELETE o TRUNCATE
CREATE FUNCTION bloquear_cambios_audit() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log es de solo lectura: no se puede modificar ni borrar';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_inmutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION bloquear_cambios_audit();

CREATE TRIGGER audit_sin_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION bloquear_cambios_audit();
