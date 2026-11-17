// Reglas de contraseña, iguales a las del servidor (problema_de_contrasena en services/auth/app/main.py).
// Se aplican al crear una cuenta, al restablecerla y al cambiar la propia contraseña.

// El servidor cuenta bytes, no letras: una letra con acento ocupa 2 y un emoji 4
export const MAX_BYTES_CONTRASENA = 72
export const MIN_CARACTERES_CONTRASENA = 10

// Partes de contraseñas muy usadas: con ellas una contraseña se adivina en pocos intentos
const COMUNES = ['contrasena', 'password', 'qwerty', '123456', 'abc123', 'escuela', 'admin', 'tecnico', 'consulta']

export const bytesDe = (texto) => new TextEncoder().encode(texto).length

// "José Pérez" -> "jose perez": para comparar sin mayúsculas ni acentos
const normalizar = (texto) => texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()

// Palabras del nombre y del correo que no deben aparecer en la contraseña (de 3 letras o más)
function datosPersonales(nombre = '', email = '') {
  const usuarioCorreo = email.split('@')[0]
  return [...normalizar(nombre).split(/\s+/), normalizar(usuarioCorreo)].filter((p) => p.length >= 3)
}

// Lista de requisitos con si se cumplen o no; el medidor visual la muestra tal cual
export function requisitosContrasena(texto, { nombre = '', email = '' } = {}) {
  const t = normalizar(texto)
  const personales = datosPersonales(nombre, email)
  return [
    { id: 'longitud', texto: `Al menos ${MIN_CARACTERES_CONTRASENA} caracteres`, cumple: texto.length >= MIN_CARACTERES_CONTRASENA },
    { id: 'mayuscula', texto: 'Una letra mayúscula', cumple: /\p{Lu}/u.test(texto) },
    { id: 'minuscula', texto: 'Una letra minúscula', cumple: /\p{Ll}/u.test(texto) },
    { id: 'numero', texto: 'Un número', cumple: /\d/.test(texto) },
    { id: 'simbolo', texto: 'Un símbolo, como ! # $ % o -', cumple: /[^\p{L}\d]/u.test(texto) },
    { id: 'comun', texto: 'Sin palabras muy usadas (password, 123456, escuela…)', cumple: !COMUNES.some((c) => t.includes(c)) },
    ...(personales.length
      ? [{ id: 'personal', texto: 'Sin tu nombre ni tu correo', cumple: !personales.some((p) => t.includes(p)) }]
      : []),
    { id: 'bytes', texto: 'Máximo 72 bytes (los acentos y emojis ocupan más de uno)', cumple: bytesDe(texto) <= MAX_BYTES_CONTRASENA },
  ]
}

// Nivel de 0 a 4 para la barra: requisitos cumplidos y, después, más largo es más seguro
export function nivelContrasena(texto, datos) {
  if (!texto) return 0
  const requisitos = requisitosContrasena(texto, datos)
  const faltan = requisitos.filter((r) => !r.cumple).length
  if (faltan >= 3) return 1
  if (faltan > 0) return 2
  return texto.length >= 16 ? 4 : 3
}

export const NOMBRES_NIVEL = ['', 'Muy débil', 'Débil', 'Segura', 'Muy segura']

// Devuelve el primer problema de la contraseña, o '' si cumple todo
export function problemaDeContrasena(texto, datos) {
  const falta = requisitosContrasena(texto, datos).find((r) => !r.cumple)
  return falta ? `La contraseña no cumple un requisito: ${falta.texto.toLowerCase()}.` : ''
}
