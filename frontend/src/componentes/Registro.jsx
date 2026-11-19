// Registro e inicio de sesión de los Observadores con su cuenta institucional (Google o Microsoft,
// según OAUTH_PROVEEDOR en el servidor).
//   /registro       -> explica y manda a /api/v1/auth/oauth/inicio (que redirige al proveedor)
//   /registro/listo -> el proveedor ya regresó: cambia el código de un solo uso por la sesión
import { useEffect, useState } from 'react'
import { canjearCodigoOAuth, proveedorOAuth } from '../api'

export const DOMINIO_INSTITUCIONAL = 'queretaro.tecnm.mx'

function Logotipo() {
  return (
    <svg className="logotipo" viewBox="0 0 48 48" aria-hidden="true">
      <path d="M6 42V20L24 8l18 12v22" fill="none" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" />
      <path d="M18 42V30h12v12" fill="none" stroke="currentColor" strokeWidth="3" />
      <rect x="21" y="16" width="6" height="6" fill="var(--senal)" />
    </svg>
  )
}

// Con qué cuenta se entra; se pregunta una sola vez al servidor y se comparte entre pantallas
let proveedorEnCamino = null
export function useProveedorOAuth() {
  const [proveedor, setProveedor] = useState(null)   // null = todavía no se sabe
  useEffect(() => {
    let vigente = true
    proveedorEnCamino ??= proveedorOAuth().catch(() => null)
    proveedorEnCamino.then((p) => vigente && setProveedor(p))
    return () => { vigente = false }
  }, [])
  return proveedor
}

// Si el proveedor bloquea la entrada, la persona se queda en su página y nunca regresa aquí.
// Por eso se anota que se intentó entrar: si vuelve (con «Atrás» o con un error) sin haber
// entrado, se le explica qué revisar.
const CLAVE_INTENTO = 'oauth-intento'
const MINUTOS_INTENTO = 30

function anotarIntento() {
  try { sessionStorage.setItem(CLAVE_INTENTO, String(Date.now())) } catch { /* sin almacenamiento */ }
}

export function olvidarIntento() {
  try { sessionStorage.removeItem(CLAVE_INTENTO) } catch { /* sin almacenamiento */ }
}

function huboIntentoFallido() {
  try {
    const cuando = Number(sessionStorage.getItem(CLAVE_INTENTO))
    return Boolean(cuando) && Date.now() - cuando < MINUTOS_INTENTO * 60 * 1000
  } catch {
    return false
  }
}

// true si la persona regresó sin entrar; se vuelve a revisar al regresar con «Atrás»,
// porque el navegador puede mostrar la página guardada sin volver a cargarla
export function useIntentoFallido(hayError = false) {
  const [fallo, setFallo] = useState(() => hayError || huboIntentoFallido())
  useEffect(() => {
    const revisar = () => setFallo(hayError || huboIntentoFallido())
    revisar()
    window.addEventListener('pageshow', revisar)
    return () => window.removeEventListener('pageshow', revisar)
  }, [hayError])
  return fallo
}

// Aviso para quien no pudo entrar: qué revisar según el proveedor
export function AyudaCuenta({ proveedor }) {
  if (proveedor?.proveedor === 'microsoft') {
    return (
      <div className="aviso aviso-ayuda" role="status">
        <strong>¿No pudiste entrar?</strong>
        <p>
          Si Microsoft dijo que tu nombre de usuario «puede ser incorrecto», tu correo
          @{DOMINIO_INSTITUCIONAL} todavía no tiene cuenta de Microsoft. Créala una sola vez:
        </p>
        <ol>
          <li>Abre <strong>Crear cuenta de Microsoft</strong> y elige «Usar un correo existente».</li>
          <li>Escribe tu correo @{DOMINIO_INSTITUCIONAL} y una contraseña para tu cuenta de Microsoft.</li>
          <li>Microsoft te manda un código a tu correo de la escuela: escríbelo para confirmar.</li>
          <li>Regresa aquí y pulsa otra vez el botón para entrar.</li>
        </ol>
        <a className="boton-secundario boton-ancho boton-enlace" href="https://signup.live.com/" target="_blank" rel="noreferrer">
          Crear cuenta de Microsoft (se abre en otra pestaña)
        </a>
      </div>
    )
  }
  return (
    <div className="aviso aviso-ayuda" role="status">
      <strong>¿No pudiste entrar?</strong>
      <ol>
        <li>
          Elige tu cuenta <strong>@{DOMINIO_INSTITUCIONAL}</strong>, no tu Gmail personal. Si no aparece en la lista,
          pulsa «Usar otra cuenta» y escribe tu correo de la escuela.
        </li>
        <li>
          Si Google dice «Acceso bloqueado» o que tu administrador no permite esta app, la escuela no la ha autorizado:
          avisa al Administrador del sistema.
        </li>
        <li>Después, regresa aquí y pulsa otra vez el botón para entrar.</li>
      </ol>
    </div>
  )
}

// Botón que inicia el flujo: es un enlace normal, el servidor hace la redirección
export function BotonCuentaInstitucional({ texto }) {
  const proveedor = useProveedorOAuth()
  const etiqueta = texto || (proveedor ? `Continuar con ${proveedor.nombre}` : 'Continuar con tu cuenta institucional')
  return (
    <a className="boton-principal boton-ancho boton-enlace" href="/api/v1/auth/oauth/inicio" onClick={anotarIntento}>
      {etiqueta}
    </a>
  )
}

export function Registro({ alEntrar, alIrAlInicio }) {
  const listo = window.location.pathname.startsWith('/registro/listo')
  const [error, setError] = useState(() => new URLSearchParams(window.location.search).get('error') || '')
  const [canjeando, setCanjeando] = useState(listo)
  const intentoFallido = useIntentoFallido(Boolean(error))
  const proveedor = useProveedorOAuth()
  const nombre = proveedor?.nombre || 'tu proveedor'

  useEffect(() => {
    if (!listo) return
    // El código viene en el fragmento (#codigo=...): se lee y se borra de la barra de direcciones
    const codigo = new URLSearchParams(window.location.hash.slice(1)).get('codigo')
    window.history.replaceState(null, '', '/')
    if (!codigo) {
      setError('No llegó el código de acceso; vuelve a intentarlo.')
      setCanjeando(false)
      return
    }
    canjearCodigoOAuth(codigo)
      .then((sesion) => { olvidarIntento(); alEntrar(sesion) })
      .catch((e) => { setError(e.message); setCanjeando(false) })
  }, [listo, alEntrar])

  return (
    <main className="pantalla-login">
      <section className="caja-login" aria-labelledby="titulo-registro">
        <Logotipo />
        <h1 id="titulo-registro">Registro de Observadores</h1>
        {canjeando ? (
          <p role="status">Abriendo tu sesión…</p>
        ) : (
          <>
            <p className="tenue">
              Como Observador puedes recorrer los edificios, áreas, inventario y servicios, y dejar avisos sobre ellos.
            </p>
            <ul className="lista-registro">
              <li>Te registras y entras con tu correo institucional <strong>@{DOMINIO_INSTITUCIONAL}</strong>.</li>
              <li>No necesitas crear una contraseña aquí: {nombre} confirma quién eres.</li>
              <li>La primera vez se crea tu cuenta; las siguientes, solo entras.</li>
            </ul>
            {error && <p className="aviso aviso-error" role="alert">{error}</p>}
            {intentoFallido && <AyudaCuenta proveedor={proveedor} />}
            <BotonCuentaInstitucional texto={intentoFallido ? `Intentar de nuevo con ${nombre}` : undefined} />
            <p className="nota-registro">
              ¿Tienes usuario y contraseña del sistema?{' '}
              <button type="button" className="boton-texto" onClick={alIrAlInicio}>Inicia sesión aquí</button>
            </p>
          </>
        )}
      </section>
    </main>
  )
}
