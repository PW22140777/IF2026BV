// Administración de usuarios y roles: solo el Administrador
import { useEffect, useState } from 'react'
import { api } from '../api'
import { problemaDeContrasena } from '../contrasenas'
import { MedidorContrasena } from './MedidorContrasena'

const ROLES = [['ADMINISTRADOR', 'Administrador'], ['TECNICO', 'Técnico'], ['CONSULTA', 'Consulta']]

export function Usuarios({ usuario: yo }) {
  const [usuarios, setUsuarios] = useState([])
  const [nuevo, setNuevo] = useState({ nombre: '', email: '', contrasena: '', rol: 'TECNICO' })
  const [restablecer, setRestablecer] = useState(null)   // usuario al que se le asigna una contraseña temporal
  const [temporal, setTemporal] = useState('')
  const [error, setError] = useState('')
  const [aviso, setAviso] = useState('')

  const cargar = () => api('/usuarios').then(setUsuarios).catch((e) => setError(e.message))
  useEffect(() => { cargar() }, [])

  async function crear(e) {
    e.preventDefault()
    setError('')
    const problema = problemaDeContrasena(nuevo.contrasena, nuevo)
    if (problema) {
      setError(problema)
      return
    }
    try {
      const u = await api('/usuarios', { metodo: 'POST', cuerpo: nuevo })
      setAviso(`Se creó la cuenta de ${u.nombre}. Deberá cambiar la contraseña inicial al entrar por primera vez.`)
      setNuevo({ nombre: '', email: '', contrasena: '', rol: 'TECNICO' })
      cargar()
    } catch (err) {
      setError(err.message)
    }
  }

  async function modificar(id, cambios, mensaje) {
    setError('')
    try {
      await api(`/usuarios/${id}`, { metodo: 'PATCH', cuerpo: cambios })
      setAviso(mensaje)
      cargar()
      return true
    } catch (err) {
      setError(err.message)
      return false
    }
  }

  async function guardarTemporal(e) {
    e.preventDefault()
    const problema = problemaDeContrasena(temporal, restablecer)
    if (problema) {
      setError(problema)
      return
    }
    const listo = await modificar(restablecer.id, { contrasena: temporal },
      `${restablecer.nombre} tiene una contraseña temporal. Sus sesiones se cerraron y deberá cambiarla al entrar.`)
    if (listo) {
      setRestablecer(null)
      setTemporal('')
    }
  }

  return (
    <div className="pagina">
      <section className="contenido">
        <header className="encabezado-pagina"><h1>Usuarios</h1></header>
        {aviso && <p className="aviso aviso-bien" role="status">{aviso}</p>}
        {error && <p className="aviso aviso-error" role="alert">{error}</p>}

        <div className="tabla-contenedor">

        <table className="tabla">
          <thead><tr><th scope="col">Nombre</th><th scope="col">Correo</th><th scope="col">Rol</th><th scope="col">Acceso</th><th scope="col">Cuenta</th></tr></thead>
          <tbody>
            {usuarios.map((u) => (
              <tr key={u.id} className={u.activo ? '' : 'eliminada'}>
                <td data-etiqueta="Nombre">
                  {u.nombre}
                  {u.debe_cambiar_contrasena && <><br /><small className="tenue">Contraseña temporal pendiente de cambiar</small></>}
                </td>
                <td data-etiqueta="Correo">{u.email}</td>
                <td data-etiqueta="Rol">
                  {/* El rol Observador solo se obtiene registrándose con la cuenta institucional */}
                  {u.rol === 'OBSERVADOR' ? 'Observador' : (
                    <select aria-label={`Rol de ${u.nombre}`} value={u.rol} disabled={u.id === yo.id}
                            onChange={(e) => modificar(u.id, { rol: e.target.value }, `${u.nombre} ahora tiene el rol ${e.target.value.toLowerCase()}.`)}>
                      {ROLES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                    </select>
                  )}
                </td>
                <td data-etiqueta="Acceso">{u.proveedor_oauth ? 'Cuenta institucional' : 'Contraseña'}</td>
                <td data-etiqueta="Cuenta">
                  {u.id === yo.id ? <span className="tenue">Tu cuenta</span> : (
                    <div className="acciones">
                      <button type="button" className="boton-secundario"
                              onClick={() => modificar(u.id, { activo: !u.activo }, `${u.nombre} ${u.activo ? 'ya no puede' : 'puede'} iniciar sesión.`)}>
                        {u.activo ? 'Desactivar' : 'Activar'}
                      </button>
                      {!u.proveedor_oauth && <button type="button" className="boton-secundario"
                              onClick={() => { setRestablecer(u); setTemporal(''); setError('') }}>
                        Restablecer contraseña
                      </button>}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>

        {restablecer && (
          <form className="formulario formulario-en-pagina" onSubmit={guardarTemporal}>
            <h3>Restablecer la contraseña de {restablecer.nombre}</h3>
            <p className="tenue">
              Asigna una contraseña temporal y compártela por un medio privado. Sus sesiones abiertas se cierran y,
              al entrar, solo podrá cambiarla por una propia.
            </p>
            <div className="campo"><label htmlFor="u-temporal">Contraseña temporal</label>
              <input id="u-temporal" type="password" autoComplete="new-password" required value={temporal}
                     aria-describedby="u-medidor-temporal" onChange={(e) => setTemporal(e.target.value)} />
              <MedidorContrasena id="u-medidor-temporal" contrasena={temporal}
                                 nombre={restablecer.nombre} email={restablecer.email} /></div>
            <div className="acciones">
              <button type="submit" className="boton-principal">Asignar contraseña temporal</button>
              <button type="button" className="boton-secundario" onClick={() => setRestablecer(null)}>Cancelar</button>
            </div>
          </form>
        )}

        <form className="formulario formulario-en-pagina" onSubmit={crear}>
          <h3>Crear usuario</h3>
          <div className="campo"><label htmlFor="u-nombre">Nombre</label>
            <input id="u-nombre" required minLength={2} value={nuevo.nombre} onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })} /></div>
          <div className="campo"><label htmlFor="u-email">Correo</label>
            <input id="u-email" type="email" required value={nuevo.email} onChange={(e) => setNuevo({ ...nuevo, email: e.target.value })} /></div>
          <div className="campo"><label htmlFor="u-pass">Contraseña inicial</label>
            <input id="u-pass" type="password" autoComplete="new-password" required value={nuevo.contrasena}
                   aria-describedby="u-medidor" onChange={(e) => setNuevo({ ...nuevo, contrasena: e.target.value })} />
            <small>Es temporal: el usuario deberá cambiarla al entrar.</small>
            <MedidorContrasena id="u-medidor" contrasena={nuevo.contrasena} nombre={nuevo.nombre} email={nuevo.email} /></div>
          <div className="campo"><label htmlFor="u-rol">Rol</label>
            <select id="u-rol" value={nuevo.rol} onChange={(e) => setNuevo({ ...nuevo, rol: e.target.value })}>
              {ROLES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select></div>
          <div className="acciones"><button type="submit" className="boton-principal">Crear usuario</button></div>
        </form>
      </section>
    </div>
  )
}
