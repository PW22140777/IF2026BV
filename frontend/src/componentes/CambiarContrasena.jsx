// Cambio de la propia contraseña. Si es obligatorio (contraseña temporal), es lo único que se puede hacer.
import { useState } from 'react'
import { cambiarContrasena, salir, sesionActual } from '../api'
import { problemaDeContrasena } from '../contrasenas'
import { MedidorContrasena } from './MedidorContrasena'

export function CambiarContrasena({ obligatorio = false, alSalir }) {
  const [campos, setCampos] = useState({ actual: '', nueva: '', confirmar: '' })
  const [error, setError] = useState('')
  const [aviso, setAviso] = useState('')
  const [enviando, setEnviando] = useState(false)
  const cambiar = (campo) => (e) => setCampos({ ...campos, [campo]: e.target.value })
  // Nombre y correo propios: la contraseña no debe contenerlos
  const { nombre = '', email = '' } = sesionActual()?.usuario || {}

  async function guardar(e) {
    e.preventDefault()
    setError('')
    setAviso('')
    const problema = problemaDeContrasena(campos.nueva, { nombre, email })
      || (campos.nueva !== campos.confirmar && 'La confirmación no coincide con la nueva contraseña.')
      || (campos.nueva === campos.actual && 'La nueva contraseña debe ser distinta de la actual.')
    if (problema) {
      setError(problema)
      return
    }
    setEnviando(true)
    try {
      // Al terminar, la sesión se actualiza y, si era obligatorio, la aplicación se abre sola
      await cambiarContrasena(campos.actual, campos.nueva)
      setCampos({ actual: '', nueva: '', confirmar: '' })
      setAviso('Tu contraseña se cambió. Las demás sesiones abiertas con tu cuenta se cerraron.')
    } catch (err) {
      setError(err.message)
    } finally {
      setEnviando(false)
    }
  }

  const formulario = (
    <form className={obligatorio ? 'caja-login' : 'formulario formulario-en-pagina'} onSubmit={guardar}>
      <h2>{obligatorio ? 'Cambia tu contraseña temporal' : 'Cambiar contraseña'}</h2>
      {obligatorio && (
        <p className="tenue">El Administrador te asignó una contraseña temporal. Elige una propia para continuar.</p>
      )}
      <div className="campo">
        <label htmlFor="c-actual">{obligatorio ? 'Contraseña temporal' : 'Contraseña actual'}</label>
        <input id="c-actual" type="password" autoComplete="current-password" required
               value={campos.actual} onChange={cambiar('actual')} />
      </div>
      <div className="campo">
        <label htmlFor="c-nueva">Nueva contraseña</label>
        <input id="c-nueva" type="password" autoComplete="new-password" required aria-describedby="c-medidor"
               value={campos.nueva} onChange={cambiar('nueva')} />
        <MedidorContrasena id="c-medidor" contrasena={campos.nueva} nombre={nombre} email={email} />
      </div>
      <div className="campo">
        <label htmlFor="c-confirmar">Repite la nueva contraseña</label>
        <input id="c-confirmar" type="password" autoComplete="new-password" required
               value={campos.confirmar} onChange={cambiar('confirmar')} />
        {campos.confirmar && (
          <small className={campos.confirmar === campos.nueva ? 'texto-bien' : 'texto-alerta'}>
            {campos.confirmar === campos.nueva ? '✓ Coincide con la nueva contraseña' : '✗ Todavía no coincide con la nueva contraseña'}
          </small>
        )}
      </div>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      {aviso && <p className="aviso aviso-bien" role="status">{aviso}</p>}
      <div className="acciones">
        <button type="submit" className="boton-principal" disabled={enviando}>
          {enviando ? 'Guardando…' : 'Cambiar contraseña'}
        </button>
        {obligatorio && (
          <button type="button" className="boton-secundario" onClick={() => { salir(); alSalir() }}>
            Cerrar sesión
          </button>
        )}
      </div>
    </form>
  )

  if (obligatorio) return <main className="pantalla-login">{formulario}</main>
  return <div className="pagina"><section className="contenido">{formulario}</section></div>
}
