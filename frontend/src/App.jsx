import { useCallback, useEffect, useState } from 'react'
import { alActualizarSesion, alCerrarSesion, iniciarSesion, salir, sesionActual } from './api'
import { ProveedorCatalogos, useCatalogos } from './catalogos'
import { Auditoria } from './componentes/Auditoria'
import { CambiarContrasena } from './componentes/CambiarContrasena'
import { PaginaRecurso } from './componentes/PaginaRecurso'
import { Resumen } from './componentes/Resumen'
import { Usuarios } from './componentes/Usuarios'
import { RECURSOS } from './recursos'

const NOMBRES_ROL = { ADMINISTRADOR: 'Administrador', TECNICO: 'Técnico', CONSULTA: 'Consulta' }

// Menú: qué ve cada rol
const SECCIONES = [
  { id: 'resumen', titulo: 'Resumen', roles: ['ADMINISTRADOR', 'TECNICO', 'CONSULTA'] },
  { id: 'edificios', titulo: 'Edificios', roles: ['ADMINISTRADOR', 'TECNICO', 'CONSULTA'], grupo: 'Inmuebles' },
  { id: 'areas', titulo: 'Áreas', roles: ['ADMINISTRADOR', 'TECNICO', 'CONSULTA'], grupo: 'Inmuebles' },
  { id: 'inventario', titulo: 'Inventario', roles: ['ADMINISTRADOR', 'TECNICO', 'CONSULTA'], grupo: 'Inmuebles' },
  { id: 'servicios', titulo: 'Agua y luz', roles: ['ADMINISTRADOR', 'TECNICO', 'CONSULTA'], grupo: 'Servicios básicos' },
  { id: 'consumos', titulo: 'Consumos', roles: ['ADMINISTRADOR', 'TECNICO', 'CONSULTA'], grupo: 'Servicios básicos' },
  { id: 'tipos_elemento', titulo: 'Tipos de elemento', roles: ['ADMINISTRADOR'], grupo: 'Administración' },
  { id: 'auditoria', titulo: 'Auditoría', roles: ['ADMINISTRADOR'], grupo: 'Administración' },
  { id: 'usuarios', titulo: 'Usuarios', roles: ['ADMINISTRADOR'], grupo: 'Administración' },
]

// Campus con el que se trabaja: filtra todas las pantallas
function SelectorCampus({ valor, alCambiar }) {
  const { campus } = useCatalogos()
  return (
    <div className="selector-campus">
      <label htmlFor="campus-activo">Campus con el que trabajas</label>
      <select id="campus-activo" value={valor} onChange={(e) => alCambiar(e.target.value)}>
        <option value="">Todos los campus</option>
        {campus.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
      </select>
    </div>
  )
}

function leerCampusGuardado() {
  try { return sessionStorage.getItem('campus-activo') || '' } catch { return '' }
}

function Login({ alEntrar, mensaje }) {
  const [email, setEmail] = useState('')
  const [contrasena, setContrasena] = useState('')
  const [error, setError] = useState(mensaje || '')
  const [enviando, setEnviando] = useState(false)

  async function entrar(e) {
    e.preventDefault()
    setEnviando(true)
    setError('')
    try {
      alEntrar(await iniciarSesion(email, contrasena))
    } catch (err) {
      setError(err.message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <main className="pantalla-login">
      <form className="caja-login" onSubmit={entrar}>
        <svg className="logotipo" viewBox="0 0 48 48" aria-hidden="true">
          <path d="M6 42V20L24 8l18 12v22" fill="none" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" />
          <path d="M18 42V30h12v12" fill="none" stroke="currentColor" strokeWidth="3" />
          <rect x="21" y="16" width="6" height="6" fill="var(--senal)" />
        </svg>
        <h1>Infraestructura Física</h1>
        <p className="tenue">Recursos inmobiliarios de la escuela: edificios, áreas, inventario y servicios básicos.</p>
        <div className="campo">
          <label htmlFor="email">Correo</label>
          <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="campo">
          <label htmlFor="contrasena">Contraseña</label>
          <input id="contrasena" type="password" autoComplete="current-password" required value={contrasena}
                 onChange={(e) => setContrasena(e.target.value)} />
        </div>
        {error && <p className="aviso aviso-error" role="alert">{error}</p>}
        <button type="submit" className="boton-principal boton-ancho" disabled={enviando}>
          {enviando ? 'Entrando…' : 'Iniciar sesión'}
        </button>
      </form>
    </main>
  )
}

export default function App() {
  const [sesion, setSesion] = useState(sesionActual)
  const [seccion, setSeccion] = useState('resumen')
  const [menuAbierto, setMenuAbierto] = useState(false)
  const [mensajeLogin, setMensajeLogin] = useState('')
  const [campusActivo, setCampusActivo] = useState(leerCampusGuardado)
  const [idInicial, setIdInicial] = useState(null)   // registro a abrir al cambiar de sección
  const usarIdInicial = useCallback(() => setIdInicial(null), [])

  // Desde el Resumen: ir a una sección con un registro ya abierto
  function abrir(destino, id) {
    setIdInicial(id)
    setSeccion(destino)
  }

  function elegirCampus(valor) {
    setCampusActivo(valor)
    try { sessionStorage.setItem('campus-activo', valor) } catch { /* sin almacenamiento */ }
  }

  useEffect(() => {
    alCerrarSesion((mensaje) => {
      setMensajeLogin(mensaje || 'Tu sesión expiró. Vuelve a iniciar sesión.')
      setSesion(null)
    })
    // Al renovar, el servidor devuelve el rol actual: el menú se ajusta si cambió
    alActualizarSesion(setSesion)
  }, [])

  if (!sesion) {
    return <Login mensaje={mensajeLogin} alEntrar={(s) => { setMensajeLogin(''); setSeccion('resumen'); setSesion(s) }} />
  }

  const usuario = sesion.usuario
  // Con una contraseña temporal el servidor rechaza todo lo demás: solo se muestra el cambio
  if (usuario.debe_cambiar_contrasena) {
    return <CambiarContrasena obligatorio alSalir={() => setSesion(null)} />
  }
  const visibles = SECCIONES.filter((s) => s.roles.includes(usuario.rol))
  const grupos = [...new Set(visibles.map((s) => s.grupo || ''))]

  function pagina() {
    if (seccion === 'resumen') return <Resumen campusActivo={campusActivo} alAbrir={abrir} />
    if (seccion === 'auditoria') return <Auditoria />
    if (seccion === 'usuarios') return <Usuarios usuario={usuario} />
    if (seccion === 'contrasena') return <CambiarContrasena />
    return <PaginaRecurso config={RECURSOS[seccion]} usuario={usuario} campusActivo={campusActivo}
                          idInicial={idInicial} alUsarIdInicial={usarIdInicial} />
  }

  return (
    <ProveedorCatalogos>
      <div className="aplicacion">
        <nav className={menuAbierto ? 'menu abierto' : 'menu'} aria-label="Secciones">
          <div className="marca">
            <svg className="logotipo-chico" viewBox="0 0 48 48" aria-hidden="true">
              <path d="M6 42V20L24 8l18 12v22" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinejoin="round" />
              <rect x="20" y="16" width="8" height="8" fill="var(--senal)" />
            </svg>
            <span>Infraestructura Física</span>
            <button type="button" className="boton-menu" aria-expanded={menuAbierto} onClick={() => setMenuAbierto(!menuAbierto)}>
              Menú
            </button>
          </div>
          <SelectorCampus valor={campusActivo} alCambiar={elegirCampus} />
          {grupos.map((g) => (
            <div key={g} className="grupo-menu">
              {g && <p className="titulo-grupo">{g}</p>}
              <ul>
                {visibles.filter((s) => (s.grupo || '') === g).map((s) => (
                  <li key={s.id}>
                    <button type="button" aria-current={seccion === s.id ? 'page' : undefined}
                            onClick={() => { setIdInicial(null); setSeccion(s.id); setMenuAbierto(false) }}>
                      {s.titulo}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <div className="sesion">
            <p><strong>{usuario.nombre}</strong><br /><span className="tenue">{NOMBRES_ROL[usuario.rol]}</span></p>
            {usuario.rol === 'CONSULTA' && <p className="tenue nota-rol">Tu rol es de solo lectura.</p>}
            <button type="button" className="boton-secundario" aria-current={seccion === 'contrasena' ? 'page' : undefined}
                    onClick={() => { setSeccion('contrasena'); setMenuAbierto(false) }}>
              Cambiar contraseña
            </button>
            <button type="button" className="boton-secundario" onClick={() => { salir(); setSesion(null) }}>
              Cerrar sesión
            </button>
          </div>
        </nav>
        <main className="principal">{pagina()}</main>
      </div>
    </ProveedorCatalogos>
  )
}
