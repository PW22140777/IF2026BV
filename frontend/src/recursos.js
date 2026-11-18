// Descripción de cada recurso: columnas de la tabla y campos del formulario.
// La página genérica (PaginaRecurso) se arma a partir de esto.

export const ESTADOS_INMUEBLE = [
  ['OPERATIVO', 'Operativo'],
  ['EN_MANTENIMIENTO', 'En mantenimiento'],
  ['FUERA_DE_SERVICIO', 'Fuera de servicio'],
]

export const ESTADOS_ELEMENTO = [
  ['BUENO', 'Bueno'],
  ['REGULAR', 'Regular'],
  ['MALO', 'Malo'],
  ['FUERA_DE_SERVICIO', 'Fuera de servicio'],
]

// Catálogo de tipos de espacio: interiores y exteriores (coincide con el CHECK de la tabla areas)
export const TIPOS_AREA = [
  ['AULA', 'Aula'], ['LABORATORIO', 'Laboratorio'], ['BIBLIOTECA', 'Biblioteca'],
  ['OFICINA', 'Oficina'], ['BANO', 'Baño'],
  ['CANCHA', 'Cancha'], ['ESTACIONAMIENTO', 'Estacionamiento'], ['AREA_VERDE', 'Área verde'],
  ['BANCAS', 'Bancas'], ['PATIO', 'Patio'],
]
// Unidades lineales base del inventario (coinciden con UnidadLineal en esquemas.py)
const UNIDADES_LINEALES = [['', 'Sin medidas'], ['m', 'Metros (m)'], ['cm', 'Centímetros (cm)'], ['mm', 'Milímetros (mm)']]
const anioActual = () => new Date().getFullYear()
const hoy = () => new Date().toLocaleDateString('en-CA')   // AAAA-MM-DD en la zona horaria local

// Catálogo de tipos de servicio básico (coincide con el CHECK de servicios_basicos).
// Solo agua y luz registran consumo mensual (m³ / kWh); internet y alcantarillado no.
export const TIPOS_SERVICIO = [
  ['AGUA', 'Agua'], ['LUZ', 'Luz'], ['INTERNET', 'Internet'], ['ALCANTARILLADO', 'Alcantarillado'],
]

// Catálogo de estados de un servicio (coincide con el CHECK de servicios_basicos)
export const ESTADOS_SERVICIO = [
  ['OPERANDO', 'Operando'], ['CON_FALLA', 'Con falla'], ['SUSPENDIDO', 'Suspendido'], ['EN_MANTENIMIENTO', 'En mantenimiento'],
]

// Estados de cada tipo de recurso que puede recibir mantenimiento (coinciden con los CHECK de sus tablas)
export const ESTADOS_POR_RECURSO = {
  EDIFICIO: ESTADOS_INMUEBLE.map(([v]) => v),
  AREA: ESTADOS_INMUEBLE.map(([v]) => v),
  INVENTARIO: ESTADOS_ELEMENTO.map(([v]) => v),
  SERVICIO: ESTADOS_SERVICIO.map(([v]) => v),
}
export const RECURSOS_MANTENIBLES = [['EDIFICIO', 'Edificio'], ['AREA', 'Área'], ['INVENTARIO', 'Elemento de inventario'], ['SERVICIO', 'Servicio básico']]
const DISPAROS = [['MANUAL', 'Manual'], ['ESTADO', 'Por estado del recurso'], ['PERIODICO', 'Periódico (cada N días)']]

// Campos cuyos valores son claves fijas en mayúsculas (FUERA_DE_SERVICIO, AIRE_ACONDICIONADO...)
const CAMPOS_CLAVE = new Set(['estado', 'tipo', 'rol', 'accion', 'recurso', 'disparo', 'resultado', 'origen'])

// Texto legible de un valor. Si el campo es una clave fija: FUERA_DE_SERVICIO -> Fuera de servicio
export function legible(valor, campo = 'estado') {
  if (valor === null || valor === undefined || valor === '') return '—'
  if (typeof valor === 'boolean') return valor ? 'Sí' : 'No'
  if (typeof valor === 'string' && CAMPOS_CLAVE.has(campo) && /^[A-Z_]+$/.test(valor)) {
    const t = valor.replace(/_/g, ' ').toLowerCase()
    return t.charAt(0).toUpperCase() + t.slice(1)
  }
  if (typeof valor === 'object') return JSON.stringify(valor)
  return String(valor)
}

export const RECURSOS = {
  edificios: {
    titulo: 'Edificios',
    singular: 'edificio',
    ruta: '/edificios',
    comentable: 'EDIFICIO',   // los Observadores pueden comentarlo
    mantenible: 'EDIFICIO',   // se le programan mantenimientos
    historial: 'edificio',
    serviciosFiltro: 'edificio_id',   // para mostrar sus servicios en el detalle (IF-59)
    nombre: (r) => `${r.nombre} (${r.clave})`,
    columnas: [
      ['clave', 'Clave'], ['nombre', 'Nombre'], ['campus_id', 'Campus'], ['niveles', 'Niveles'], ['estado', 'Estado'],
    ],
    campos: [
      { nombre: 'campus_id', etiqueta: 'Campus', tipo: 'campus', requerido: true, soloAlCrear: true,
        ayuda: 'El campus de un edificio no se puede cambiar después' },
      { nombre: 'clave', etiqueta: 'Clave', tipo: 'texto', requerido: true, ayuda: 'Por ejemplo ED-A' },
      { nombre: 'nombre', etiqueta: 'Nombre', tipo: 'texto', requerido: true },
      { nombre: 'niveles', etiqueta: 'Niveles', tipo: 'numero', minimo: 1, maximo: 200,
        ayuda: 'Los pisos se numeran de 0 (planta baja) a niveles − 1' },
      { nombre: 'anio_construccion', etiqueta: 'Año de construcción', tipo: 'numero', minimo: 1800, maximo: anioActual },
      { nombre: 'superficie_m2', etiqueta: 'Superficie (m²)', tipo: 'numero', paso: '0.01', minimo: 0.01, maximo: 10000000 },
      { nombre: 'estado', etiqueta: 'Estado', tipo: 'opciones', opciones: ESTADOS_INMUEBLE, inicial: 'OPERATIVO' },
      { nombre: 'descripcion', etiqueta: 'Descripción', tipo: 'parrafo' },
    ],
  },

  areas: {
    titulo: 'Áreas',
    singular: 'área',
    ruta: '/areas',
    comentable: 'AREA',
    mantenible: 'AREA',
    historial: 'area',
    serviciosFiltro: 'area_id',   // para mostrar sus servicios en el detalle (IF-59)
    nombre: (r) => r.nombre,
    columnas: [
      ['nombre', 'Nombre'], ['tipo', 'Tipo'], ['campus_id', 'Campus'], ['edificio_id', 'Edificio'], ['estado', 'Estado'],
    ],
    filtros: [{ nombre: 'edificio', etiqueta: 'Edificio', tipo: 'edificio' }],
    campos: [
      { nombre: 'campus_id', etiqueta: 'Campus', tipo: 'campus', requerido: true },
      { nombre: 'edificio_id', etiqueta: 'Edificio', tipo: 'edificio', ayuda: 'Déjalo vacío para un área independiente, como una cancha o unas bancas. Solo aparecen los edificios del campus elegido.' },
      { nombre: 'nombre', etiqueta: 'Nombre', tipo: 'texto', requerido: true },
      { nombre: 'tipo', etiqueta: 'Tipo', tipo: 'opciones', opciones: TIPOS_AREA, inicial: 'AULA', requerido: true },
      { nombre: 'piso', etiqueta: 'Piso', tipo: 'piso', ayuda: 'Solo aparecen los pisos que existen en el edificio elegido' },
      { nombre: 'capacidad', etiqueta: 'Capacidad (personas)', tipo: 'numero', minimo: 0, maximo: 100000 },
      { nombre: 'superficie_m2', etiqueta: 'Superficie (m²)', tipo: 'numero', paso: '0.01', minimo: 0.01, maximo: 10000000 },
      { nombre: 'exterior', etiqueta: 'Es un espacio exterior', tipo: 'casilla' },
      { nombre: 'estado', etiqueta: 'Estado', tipo: 'opciones', opciones: ESTADOS_INMUEBLE, inicial: 'OPERATIVO' },
      { nombre: 'descripcion', etiqueta: 'Descripción', tipo: 'parrafo' },
    ],
  },

  inventario: {
    titulo: 'Inventario',
    singular: 'elemento',
    ruta: '/inventario',
    comentable: 'INVENTARIO',
    mantenible: 'INVENTARIO',
    historial: 'inventario',
    nombre: (r) => `${legible(r.tipo)}${r.marca ? ' ' + r.marca : ''}`,
    columnas: [
      ['tipo', 'Tipo de elemento'], ['area_id', 'Área'], ['eje', 'Eje'], ['tramo', 'Tramo'],
      ['cantidad', 'Cantidad'], ['total_lineal', 'Total lineal'], ['total_area', 'Área total'],
      ['total_volumen', 'Volumen total'], ['estado', 'Estado'],
    ],
    filtros: [{ nombre: 'area_id', etiqueta: 'Área', tipo: 'area' }],
    propiedadesReservadas: ['total', 'total_lineal', 'total_area', 'total_volumen', 'total_volumen_espesor'],
    // Las propiedades de cada elemento las define su tipo (catálogo «Tipos de elemento»)
    propiedadesPorTipo: true,
    campos: [
      { nombre: 'area_id', etiqueta: 'Área', tipo: 'area', requerido: true },
      { nombre: 'tipo', etiqueta: 'Tipo de elemento', tipo: 'tipoElemento', requerido: true,
        ayuda: 'Al elegirlo aparecen sus propiedades. El Administrador agrega tipos en «Tipos de elemento».' },
      { nombre: 'eje', etiqueta: 'Eje', tipo: 'texto' },
      { nombre: 'tramo', etiqueta: 'Tramo', tipo: 'texto' },
      // medida: true -> solo aparece si el tipo elegido usa medidas
      { nombre: 'unidad', etiqueta: 'Unidad de las medidas', tipo: 'opciones', opciones: UNIDADES_LINEALES, inicial: '', medida: true,
        ayuda: 'Obligatoria si registras largo, alto, ancho o espesor' },
      { nombre: 'largo', etiqueta: 'Largo', tipo: 'numero', paso: '0.0001', minimo: 0.0001, maximo: 1000000, medida: true },
      { nombre: 'alto', etiqueta: 'Alto', tipo: 'numero', paso: '0.0001', minimo: 0.0001, maximo: 1000000, medida: true },
      { nombre: 'ancho', etiqueta: 'Ancho', tipo: 'numero', paso: '0.0001', minimo: 0.0001, maximo: 1000000, medida: true },
      { nombre: 'espesor', etiqueta: 'Espesor', tipo: 'numero', paso: '0.0001', minimo: 0.0001, maximo: 1000000, medida: true },
      { nombre: 'cantidad', etiqueta: 'Cantidad', tipo: 'numero', inicial: 1, minimo: 1, maximo: 1000000, requerido: true },
      { nombre: 'marca', etiqueta: 'Marca', tipo: 'texto' },
      { nombre: 'modelo', etiqueta: 'Modelo', tipo: 'texto' },
      { nombre: 'numero_serie', etiqueta: 'Número de serie', tipo: 'texto' },
      { nombre: 'fecha_recuento', etiqueta: 'Fecha de recuento', tipo: 'fecha', maximo: hoy },
      { nombre: 'estado', etiqueta: 'Estado', tipo: 'opciones', opciones: ESTADOS_ELEMENTO, inicial: 'BUENO' },
      { nombre: 'descripcion', etiqueta: 'Observaciones', tipo: 'parrafo' },
    ],
    camposSoloLectura: [
      { nombre: 'total_lineal', etiqueta: 'Total lineal', tipo: 'total_lineal' },
      { nombre: 'total_area', etiqueta: 'Área total', tipo: 'total_area' },
      { nombre: 'total_volumen', etiqueta: 'Volumen total (con ancho)', tipo: 'total_volumen' },
      { nombre: 'total_volumen_espesor', etiqueta: 'Volumen total (con espesor)', tipo: 'total_volumen' },
    ],
  },

  // Catálogo de tipos de elemento: qué propiedades lleva cada tipo (solo Administrador)
  tipos_elemento: {
    titulo: 'Tipos de elemento',
    singular: 'tipo de elemento',
    ruta: '/tipos-elemento',
    historial: 'tipo_elemento',
    sinFiltroCampus: true,
    sinPropiedadesLibres: true,
    nombre: (r) => r.nombre,
    columnas: [
      ['nombre', 'Nombre'], ['clave', 'Clave'], ['usa_medidas', 'Usa medidas'], ['propiedades_definidas', 'Propiedades'],
    ],
    campos: [
      { nombre: 'clave', etiqueta: 'Clave', tipo: 'sugerencias', sugerencias: [], requerido: true, soloAlCrear: true,
        ayuda: 'En mayúsculas y sin espacios, por ejemplo AIRE_ACONDICIONADO. No se puede cambiar después.' },
      { nombre: 'nombre', etiqueta: 'Nombre', tipo: 'texto', requerido: true, ayuda: 'Por ejemplo, Aire acondicionado' },
      { nombre: 'usa_medidas', etiqueta: 'Sus elementos llevan medidas (largo, alto, ancho, espesor)', tipo: 'casilla' },
      { nombre: 'descripcion', etiqueta: 'Descripción', tipo: 'parrafo' },
      { nombre: 'propiedades_definidas', etiqueta: 'Propiedades de este tipo', tipo: 'definiciones' },
    ],
  },

  // Plantillas de mantenimiento: qué se revisa, cuándo se abre una orden y cómo queda el recurso (solo Administrador)
  plantillas_mantenimiento: {
    titulo: 'Plantillas de mantenimiento',
    singular: 'plantilla',
    ruta: '/mantenimientos/plantillas',
    historial: 'plantilla_mantenimiento',
    sinFiltroCampus: true,
    sinPropiedadesLibres: true,
    nombre: (r) => r.nombre,
    columnas: [['nombre', 'Nombre'], ['recurso', 'Recurso'], ['disparo', 'Se abre'], ['activa', 'Activa']],
    campos: [
      { nombre: 'nombre', etiqueta: 'Nombre', tipo: 'texto', requerido: true, ayuda: 'Por ejemplo, Preventivo de aire acondicionado' },
      { nombre: 'descripcion', etiqueta: 'Descripción', tipo: 'parrafo' },
      { nombre: 'recurso', etiqueta: 'Se aplica a', tipo: 'opciones', opciones: RECURSOS_MANTENIBLES, inicial: 'INVENTARIO',
        requerido: true, soloAlCrear: true, ayuda: 'No se puede cambiar después' },
      { nombre: 'tipo_elemento', etiqueta: 'Tipo de elemento', tipo: 'tipoElemento',
        ayuda: 'Solo para inventario; vacío = cualquier tipo' },
      { nombre: 'disparo', etiqueta: 'Cuándo se abre una orden', tipo: 'opciones', opciones: DISPAROS, inicial: 'MANUAL' },
      { nombre: 'estados_disparo', etiqueta: 'Estados que abren una orden', tipo: 'estados',
        ayuda: 'Para «Por estado»: cuando una persona deja el recurso en uno de estos estados' },
      { nombre: 'cada_dias', etiqueta: 'Cada cuántos días', tipo: 'numero', minimo: 1, maximo: 3650,
        ayuda: 'Para «Periódico»: días desde el último mantenimiento terminado' },
      { nombre: 'estado_al_iniciar', etiqueta: 'Estado del recurso al iniciar', tipo: 'estado', vacio: 'Sin cambio' },
      { nombre: 'estado_resuelto', etiqueta: 'Estado si se resuelve', tipo: 'estado', requerido: true },
      { nombre: 'estado_parcial', etiqueta: 'Estado si queda parcial', tipo: 'estado', requerido: true },
      { nombre: 'estado_no_resuelto', etiqueta: 'Estado si no se resuelve', tipo: 'estado', requerido: true },
      { nombre: 'activa', etiqueta: 'Activa', tipo: 'casilla', inicial: true },
      { nombre: 'lista_verificacion', etiqueta: 'Lista de verificación (lo que registra el técnico)', tipo: 'definiciones' },
    ],
  },

  servicios: {
    titulo: 'Agua y luz',
    singular: 'servicio',
    ruta: '/servicios',
    comentable: 'SERVICIO',
    mantenible: 'SERVICIO',
    historial: 'servicio',
    nombre: (r) => r.nombre,
    columnas: [
      ['tipo', 'Tipo'], ['nombre', 'Nombre'], ['destino', 'Abastece a'], ['estado', 'Estado'], ['activo', 'Activo'],
    ],
    filtros: [
      { nombre: 'tipo', etiqueta: 'Tipo', tipo: 'opciones', opciones: TIPOS_SERVICIO },
      { nombre: 'edificio', etiqueta: 'Edificio', tipo: 'edificio', sinIndependientes: true },
      { nombre: 'area_id', etiqueta: 'Área', tipo: 'area' },
      { nombre: 'estado', etiqueta: 'Estado', tipo: 'opciones', opciones: ESTADOS_SERVICIO },
    ],
    campos: [
      { nombre: 'tipo', etiqueta: 'Tipo', tipo: 'opciones', opciones: TIPOS_SERVICIO, inicial: 'LUZ', soloAlCrear: true },
      { nombre: 'nombre', etiqueta: 'Nombre', tipo: 'texto', requerido: true, ayuda: 'Por ejemplo, Medidor general del edificio A' },
      { nombre: 'destino', etiqueta: 'Abastece a', tipo: 'destino', requerido: true, ayuda: 'El campus completo (toma o medidor general), un edificio o un área' },
      { nombre: 'numero_medidor', etiqueta: 'Número de medidor', tipo: 'texto' },
      { nombre: 'proveedor', etiqueta: 'Proveedor', tipo: 'texto', ayuda: 'Por ejemplo CFE o el organismo de agua municipal' },
      { nombre: 'estado', etiqueta: 'Estado', tipo: 'opciones', opciones: ESTADOS_SERVICIO, inicial: 'OPERANDO' },
      { nombre: 'activo', etiqueta: 'Activo', tipo: 'casilla', inicial: true },
      { nombre: 'descripcion', etiqueta: 'Notas', tipo: 'parrafo', ayuda: 'Por ejemplo, el motivo de una falla' },
    ],
  },

  consumos: {
    titulo: 'Consumos',
    singular: 'consumo',
    ruta: '/consumos',
    comentable: 'CONSUMO',
    historial: 'consumo',
    nombre: (r) => `Consumo de ${r.periodo?.slice(0, 7)}`,
    cantidadConUnidad: true,
    columnas: [
      ['periodo', 'Mes'], ['servicio_id', 'Servicio'], ['cantidad', 'Cantidad'], ['costo', 'Costo ($)'],
    ],
    filtros: [{ nombre: 'servicio_id', etiqueta: 'Servicio', tipo: 'servicio' }],
    campos: [
      { nombre: 'servicio_id', etiqueta: 'Servicio', tipo: 'servicio', requerido: true, soloAlCrear: true },
      { nombre: 'periodo', etiqueta: 'Mes', tipo: 'mes', requerido: true, soloAlCrear: true },
      { nombre: 'cantidad', etiqueta: 'Cantidad (m³ o kWh)', tipo: 'numero', paso: '0.001', requerido: true },
      { nombre: 'costo', etiqueta: 'Costo ($)', tipo: 'numero', paso: '0.01' },
    ],
  },
}
