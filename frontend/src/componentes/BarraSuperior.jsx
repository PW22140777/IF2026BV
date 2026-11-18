// Barra superior: campus con el que se trabaja y menú del usuario (perfil, contraseña, cerrar sesión).
// Antes estaban al fondo del menú lateral y se perdían debajo de todas las secciones.
import { useEffect, useRef, useState } from 'react'

export const NOMBRES_ROL = { ADMINISTRADOR: 'Administrador', TECNICO: 'Técnico', CONSULTA: 'Consulta', OBSERVADOR: 'Observador' }

// «Ana María López» -> «AL»
function iniciales(nombre = '') {
  const partes = nombre.trim().split(/\s+/).filter(Boolean)
  return ((partes[0]?.[0] || '') + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase() || '?'
}

function MenuUsuario({ usuario, alIr, alSalir }) {
  const [abierto, setAbierto] = useState(false)
  const caja = useRef(null)
  const boton = useRef(null)

  // Se cierra al hacer clic fuera o con Escape (y el foco regresa al botón)
  useEffect(() => {
    if (!abierto) return undefined
    const alClic = (e) => { if (!caja.current?.contains(e.target)) setAbierto(false) }
    const alTecla = (e) => { if (e.key === 'Escape') { setAbierto(false); boton.current?.focus() } }
    document.addEventListener('mousedown', alClic)
    document.addEventListener('keydown', alTecla)
    return () => {
      document.removeEventListener('mousedown', alClic)
      document.removeEventListener('keydown', alTecla)
    }
  }, [abierto])

  function elegir(accion) {
    setAbierto(false)
    accion()
  }

  return (
    <div className="menu-usuario" ref={caja}>
      <button type="button" ref={boton} className="boton-usuario" aria-haspopup="menu" aria-expanded={abierto}
              aria-controls="opciones-usuario" onClick={() => setAbierto(!abierto)}>
        <span className="avatar" aria-hidden="true">{iniciales(usuario.nombre)}</span>
        <span className="usuario-texto">
          <strong>{usuario.nombre}</strong>
          <span>{NOMBRES_ROL[usuario.rol]}</span>
        </span>
        <span className="grupo-flecha" aria-hidden="true">▾</span>
      </button>
      {abierto && (
        <div className="opciones-usuario" id="opciones-usuario" role="menu" aria-label="Opciones de tu cuenta">
          <div className="opciones-cabecera">
            <strong>{usuario.nombre}</strong>
            <span>{usuario.email}</span>
          </div>
          <button type="button" role="menuitem" onClick={() => elegir(() => alIr('perfil'))}>Mi perfil</button>
          {/* Un Observador entra con Microsoft: no tiene contraseña que cambiar */}
          {usuario.rol !== 'OBSERVADOR' && (
            <button type="button" role="menuitem" onClick={() => elegir(() => alIr('contrasena'))}>Cambiar contraseña</button>
          )}
          <button type="button" role="menuitem" className="opcion-salir" onClick={() => elegir(alSalir)}>Cerrar sesión</button>
        </div>
      )}
    </div>
  )
}

export function BarraSuperior({ usuario, selectorCampus, alIr, alSalir }) {
  return (
    <header className="barra-superior">
      {selectorCampus}
      <MenuUsuario usuario={usuario} alIr={alIr} alSalir={alSalir} />
    </header>
  )
}
