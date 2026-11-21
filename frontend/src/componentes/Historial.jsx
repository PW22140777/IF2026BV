// Línea de tiempo de un recurso: quién hizo qué, cuándo y qué cambió
import { useEffect, useState } from 'react'
import { api } from '../api'
import { legible } from '../recursos'

const VERBOS = {
  CREAR: 'creó el registro',
  MODIFICAR: 'modificó',
  ELIMINAR: 'eliminó el registro',
  RESTAURAR: 'restauró el registro',
}

const ROLES = { ADMINISTRADOR: 'Administrador', TECNICO: 'Técnico', CONSULTA: 'Consulta', OBSERVADOR: 'Observador', SISTEMA: 'Automático' }

export function formatoFecha(iso) {
  return new Date(iso).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' })
}

function nombreCampo(campo) {
  if (campo.startsWith('propiedades.')) return `propiedad «${campo.slice(12)}»`
  return campo.replace(/_/g, ' ').replace(/ id$/, '')
}

export function ListaCambios({ cambios }) {
  if (!cambios?.length) return null
  return (
    <ul className="cambios">
      {cambios.map((c) => (
        <li key={c.campo}>
          <span className="cambio-campo">{nombreCampo(c.campo)}</span>
          <del>{legible(c.antes, c.campo)}</del>
          <span aria-label="cambió a"> → </span>
          <ins>{legible(c.despues, c.campo)}</ins>
        </li>
      ))}
    </ul>
  )
}

export function Historial({ recurso, id, version }) {
  const [entradas, setEntradas] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let vigente = true
    api(`/historial/${recurso}/${id}`)
      .then((datos) => vigente && setEntradas(datos.slice().reverse()))
      .catch((e) => vigente && setError(e.message))
    return () => { vigente = false }
  }, [recurso, id, version])

  if (error) return <p className="aviso aviso-error">{error}</p>
  if (entradas === null) return <p className="tenue">Cargando historial…</p>
  if (entradas.length === 0) {
    return <p className="tenue">El historial se actualiza en unos segundos, cuando audit-service registra el cambio.</p>
  }

  return (
    <ol className="linea-tiempo">
      {entradas.map((e) => (
        <li key={e.evento_id} className={`hito hito-${e.accion.toLowerCase()}`}>
          <p className="hito-quien">
            <strong>{e.usuario_nombre || 'Sistema'}</strong>
            <span className="rol">{ROLES[e.rol] || e.rol}</span>
            {' '}{VERBOS[e.accion] || e.accion.toLowerCase()}
          </p>
          <time dateTime={e.fecha}>{formatoFecha(e.fecha)}</time>
          {e.accion !== 'CREAR' && <ListaCambios cambios={e.cambios.filter((c) => !c.campo.startsWith('eliminado') && c.campo !== 'motivo_eliminacion')} />}
          {e.motivo && <p className="motivo">Motivo: {e.motivo}</p>}
        </li>
      ))}
    </ol>
  )
}
