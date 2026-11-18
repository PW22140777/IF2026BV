// Registro e inicio de sesión de los Observadores con su cuenta institucional (Microsoft).
//   /registro       -> explica y manda a /api/v1/auth/oauth/inicio (que redirige a Microsoft)
//   /registro/listo -> Microsoft ya regresó: cambia el código de un solo uso por la sesión
import { useEffect, useState } from 'react'
import { canjearCodigoOAuth } from '../api'

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

// Botón que inicia el flujo con Microsoft: es un enlace normal, el servidor hace la redirección
export function BotonCuentaInstitucional({ texto = 'Continuar con tu cuenta institucional' }) {
  return <a className="boton-principal boton-ancho boton-enlace" href="/api/v1/auth/oauth/inicio">{texto}</a>
}

export function Registro({ alEntrar, alIrAlInicio }) {
  const listo = window.location.pathname.startsWith('/registro/listo')
  const [error, setError] = useState(() => new URLSearchParams(window.location.search).get('error') || '')
  const [canjeando, setCanjeando] = useState(listo)

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
      .then(alEntrar)
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
              Como Observador puedes consultar edificios, áreas, inventario y servicios, y dejar comentarios sobre ellos.
            </p>
            <ul className="lista-registro">
              <li>Te registras y entras con tu cuenta institucional <strong>@{DOMINIO_INSTITUCIONAL}</strong>.</li>
              <li>No necesitas crear una contraseña: Microsoft confirma quién eres.</li>
              <li>La primera vez se crea tu cuenta; las siguientes, solo entras.</li>
            </ul>
            {error && <p className="aviso aviso-error" role="alert">{error}</p>}
            <BotonCuentaInstitucional />
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
