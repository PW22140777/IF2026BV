// «Mi perfil»: quién eres en el sistema, qué puede hacer tu rol y qué sesiones tienes abiertas.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { NOMBRES_ROL } from './BarraSuperior'
import { formatoFecha } from './Historial'

// Lo que puede hacer cada rol (la misma tabla del README, en palabras de la interfaz)
const PERMISOS = {
  ADMINISTRADOR: [
    'Todo lo que hace un Técnico',
    'Administrar usuarios, tipos de elemento y plantillas de mantenimiento',
    'Ver la auditoría completa y verificar la integridad del historial',
    'Restaurar registros eliminados y ocultar comentarios',
  ],
  TECNICO: [
    'Crear, modificar y eliminar recursos y sus propiedades',
    'Registrar consumos de agua y luz',
    'Programar, iniciar y terminar mantenimientos',
    'Responder comentarios',
  ],
  CONSULTA: ['Ver recursos, historial y resumen (solo lectura)'],
  OBSERVADOR: ['Ver recursos y su historial', 'Dejar comentarios en los recursos'],
}

export function Perfil({ alCambiarContrasena }) {
  const [perfil, setPerfil] = useState(null)
  const [error, setError] = useState('')
  const [aviso, setAviso] = useState('')
  const [cerrando, setCerrando] = useState(false)

  const cargar = useCallback(() => {
    api('/auth/perfil').then(setPerfil).catch((e) => setError(e.message))
  }, [])
  useEffect(() => { cargar() }, [cargar])

  async function cerrarOtras() {
    setCerrando(true)
    setError('')
    setAviso('')
    try {
      const { cerradas } = await api('/auth/cerrar-otras-sesiones', { metodo: 'POST' })
      setAviso(cerradas === 1 ? 'Se cerró 1 sesión.' : `Se cerraron ${cerradas} sesiones.`)
      cargar()
    } catch (e) {
      setError(e.message)
    } finally {
      setCerrando(false)
    }
  }

  if (error && !perfil) return <div className="pagina"><section className="contenido"><p className="aviso aviso-error">{error}</p></section></div>
  if (!perfil) return <div className="pagina"><section className="contenido"><p className="tenue">Cargando tu perfil…</p></section></div>

  const otras = perfil.sesiones.filter((s) => !s.actual).length
  const proveedores = { google: 'Google', microsoft: 'Microsoft' }
  const conProveedor = proveedores[perfil.acceso]   // entra con Google o Microsoft, sin contraseña aquí

  return (
    <div className="pagina">
      <section className="contenido perfil">
        <h1>Mi perfil</h1>

        <div className="tarjeta-perfil">
          <h2>Tus datos</h2>
          <dl className="ficha">
            <dt>Nombre</dt><dd>{perfil.nombre}</dd>
            <dt>Correo</dt><dd>{perfil.email}</dd>
            <dt>Rol</dt><dd>{NOMBRES_ROL[perfil.rol]}</dd>
            <dt>Cuenta creada</dt><dd>{formatoFecha(perfil.creado_en)}</dd>
          </dl>
          <p className="tenue">
            {perfil.rol === 'ADMINISTRADOR'
              ? 'Tu nombre y tu rol se cambian en «Usuarios».'
              : 'Para cambiar tu nombre o tu rol, pídeselo al Administrador.'}
          </p>
        </div>

        <div className="tarjeta-perfil">
          <h2>Lo que puedes hacer</h2>
          <ul className="lista-permisos">
            {(PERMISOS[perfil.rol] || []).map((p) => <li key={p}>{p}</li>)}
          </ul>
        </div>

        <div className="tarjeta-perfil">
          <h2>Cómo entras</h2>
          {conProveedor ? (
            <p>Con tu cuenta institucional de {conProveedor}. Tu contraseña se administra en {conProveedor}, no aquí.</p>
          ) : (
            <>
              <p>Con tu correo y tu contraseña.</p>
              <div className="acciones">
                <button type="button" className="boton-secundario" onClick={alCambiarContrasena}>Cambiar contraseña</button>
              </div>
            </>
          )}
        </div>

        <div className="tarjeta-perfil">
          <h2>Sesiones abiertas</h2>
          <ul className="lista-sesiones">
            {perfil.sesiones.map((s) => (
              <li key={s.creada_en}>
                <span>Desde {formatoFecha(s.creada_en)}{s.ip ? ` · ${s.ip}` : ''}</span>
                {s.actual && <span className="etiqueta">Esta sesión</span>}
              </li>
            ))}
          </ul>
          <p className="tenue">
            Si dejaste tu cuenta abierta en otra computadora, cierra las demás sesiones; esta sigue abierta.
          </p>
          {error && <p className="aviso aviso-error" role="alert">{error}</p>}
          {aviso && <p className="aviso aviso-bien" role="status">{aviso}</p>}
          <div className="acciones">
            <button type="button" className="boton-secundario" disabled={cerrando || otras === 0} onClick={cerrarOtras}>
              {cerrando ? 'Cerrando…' : `Cerrar las demás sesiones (${otras})`}
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
