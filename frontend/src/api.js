// Cliente de la API: todas las llamadas pasan por el gateway en /api/v1
const BASE = '/api/v1'
const CLAVE_SESION = 'sesion-inmuebles'

// Si al token le quedan menos de 5 minutos, la siguiente petición renueva la sesión.
// Cada petición cuenta como actividad: quien deja el sistema 30 minutos sin usar sale solo.
const MARGEN_RENOVACION_MS = 5 * 60 * 1000

let sesion = leerSesion()
let alExpirar = () => {}
let alActualizar = () => {}
let renovando = null   // una sola renovación aunque haya varias peticiones a la vez

function leerSesion() {
  try {
    return JSON.parse(sessionStorage.getItem(CLAVE_SESION)) || null
  } catch {
    return null
  }
}

export function sesionActual() {
  return sesion
}

// funcion(mensaje): se llama cuando el servidor rechaza la sesión (expiró, se cerró o se desactivó la cuenta)
export function alCerrarSesion(funcion) {
  alExpirar = funcion
}

// funcion(sesion): se llama al renovar, por si cambió el rol o el nombre del usuario
export function alActualizarSesion(funcion) {
  alActualizar = funcion
}

export function cerrarSesion() {
  sesion = null
  try { sessionStorage.removeItem(CLAVE_SESION) } catch { /* sin almacenamiento */ }
}

// Cierra la sesión también en el servidor: así el token deja de servir aunque alguien lo haya copiado
export async function salir() {
  const token = sesion?.token
  cerrarSesion()
  if (!token) return
  try {
    await fetch(`${BASE}/auth/salir`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
  } catch { /* sin conexión: la sesión vencerá sola */ }
}

function guardarSesion(datos) {
  sesion = { token: datos.access_token, usuario: datos.usuario, expira: datos.expira_en, vence: datos.vence_en }
  try { sessionStorage.setItem(CLAVE_SESION, JSON.stringify(sesion)) } catch { /* sin almacenamiento */ }
  return sesion
}

export async function iniciarSesion(email, contrasena) {
  const cuerpo = new URLSearchParams({ username: email, password: contrasena })
  const r = await fetch(`${BASE}/auth/login`, { method: 'POST', body: cuerpo })
  const datos = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(mensajeDeError(datos, r.status))
  return guardarSesion(datos)
}

// Devuelve la sesión con debe_cambiar_contrasena en false; avisa a la aplicación para que se abra
export async function cambiarContrasena(actual, nueva) {
  const datos = await api('/auth/cambiar-contrasena', { metodo: 'POST', cuerpo: { actual, nueva } })
  const nuevaSesion = guardarSesion(datos)
  alActualizar(nuevaSesion)
  return nuevaSesion
}

async function renovarSiHaceFalta() {
  if (!sesion) return
  const expira = Date.parse(sesion.expira)
  // Aún hay tiempo, o la sesión ya llegó a su máximo y no se puede extender
  if (expira - Date.now() > MARGEN_RENOVACION_MS || expira >= Date.parse(sesion.vence)) return
  if (!renovando) {
    renovando = fetch(`${BASE}/auth/renovar`, { method: 'POST', headers: { Authorization: `Bearer ${sesion.token}` } })
      .then(async (r) => { if (r.ok) alActualizar(guardarSesion(await r.json())) })
      .catch(() => { /* si falla, la petición siguiente recibe 401 y se pide entrar de nuevo */ })
      .finally(() => { renovando = null })
  }
  await renovando
}

// Errores de validación de Pydantic en español (los más comunes); los demás se muestran tal cual
function traducirValidacion(e) {
  const c = e.ctx || {}
  switch (e.type) {
    case 'greater_than': return `debe ser mayor que ${c.gt}`
    case 'greater_than_equal': return `debe ser ${c.ge} o más`
    case 'less_than': return `debe ser menor que ${c.lt}`
    case 'less_than_equal': return `debe ser ${c.le} o menos`
    case 'string_too_short': return c.min_length > 1 ? `debe tener al menos ${c.min_length} caracteres` : 'no puede quedar vacío'
    case 'string_too_long': return `admite como máximo ${c.max_length} caracteres`
    case 'string_pattern_mismatch': return 'tiene un formato no válido'
    case 'literal_error': return `debe ser uno de: ${c.expected}`
    case 'missing': return 'es obligatorio'
    case 'value_error': return e.msg.replace(/^Value error, /, '')
    default: return e.msg
  }
}

function mensajeDeError(datos, estado) {
  const d = datos?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    // Errores de validación de FastAPI: [{loc: [...], type: '...', msg: '...'}]
    return d.map((e) => `${e.loc?.slice(1).join('.') || 'dato'}: ${traducirValidacion(e)}`).join('; ')
  }
  return `Error ${estado}`
}

// Envía un formulario con archivos (multipart); el navegador pone el Content-Type con su separador
export async function apiFormulario(ruta, formulario, metodo = 'POST') {
  await renovarSiHaceFalta()
  const r = await fetch(BASE + ruta, {
    method: metodo,
    headers: sesion ? { Authorization: `Bearer ${sesion.token}` } : {},
    body: formulario,
  })
  const datos = await r.json().catch(() => null)
  if (r.status === 401) {
    cerrarSesion()
    alExpirar(mensajeDeError(datos, r.status))
  }
  if (!r.ok) throw new Error(mensajeDeError(datos, r.status))
  return datos
}

export async function api(ruta, { metodo = 'GET', cuerpo, consulta } = {}) {
  await renovarSiHaceFalta()
  const url = new URL(BASE + ruta, window.location.origin)
  Object.entries(consulta || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
  })
  const r = await fetch(url, {
    method: metodo,
    headers: {
      ...(cuerpo !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(sesion ? { Authorization: `Bearer ${sesion.token}` } : {}),
    },
    body: cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined,
  })
  const datos = r.status === 204 ? null : await r.json().catch(() => null)
  if (r.status === 401) {
    cerrarSesion()
    alExpirar(mensajeDeError(datos, r.status))   // el servidor dice por qué: expiró, se cerró, cuenta desactivada…
  }
  if (!r.ok) {
    const error = new Error(mensajeDeError(datos, r.status))
    error.correlationId = r.headers.get('X-Correlation-Id')
    throw error
  }
  return datos
}
