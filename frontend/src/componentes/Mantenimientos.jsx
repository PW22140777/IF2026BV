// Órdenes de mantenimiento: lista y panel para atender cada una.
// El técnico asignado pulsa «Iniciar», llena la lista de verificación y pulsa «Terminar»;
// el sistema registra quién, cuándo y el resultado, y deja el recurso en el estado que toca.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { legible } from '../recursos'

const FILTROS = [
  ['abiertas', 'Abiertas', { estado: 'PROGRAMADA,EN_CURSO' }],
  ['terminadas', 'Terminadas', { estado: 'TERMINADA' }],
  ['canceladas', 'Canceladas', { estado: 'CANCELADA' }],
  ['todas', 'Todas', {}],
]
const TONO = { PROGRAMADA: 'neutro', EN_CURSO: 'medio', TERMINADA: 'bien', CANCELADA: 'mal' }
const ORIGENES = { ESTADO: 'Por estado del recurso', PERIODICO: 'Periódica', MANUAL: 'Programada a mano' }
const fecha = (iso) => (iso ? new Date(iso).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' }) : '—')
const dia = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('es-MX', { dateStyle: 'medium' })

export function EstadoOrden({ valor }) {
  return <span className={`estado estado-${TONO[valor] || 'neutro'}`}>{legible(valor)}</span>
}

function DetalleOrden({ orden, usuario, alActualizar, alCerrar }) {
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)
  const esAdmin = usuario.rol === 'ADMINISTRADOR'
  // Atienden los técnicos asignados; el Administrador siempre puede
  const atiende = esAdmin || (usuario.rol === 'TECNICO' && orden.tecnicos.includes(usuario.id))
  const abierta = ['PROGRAMADA', 'EN_CURSO'].includes(orden.estado)

  async function ejecutar(ruta, metodo, cuerpo) {
    setError('')
    try {
      const nueva = await api(`/mantenimientos/ordenes/${orden.id}${ruta}`, { metodo, cuerpo })
      alActualizar(nueva)
      setTimeout(() => setVersion((v) => v + 1), 1500)   // el historial llega por RabbitMQ en un momento
    } catch (err) {
      setError(err.message)
      throw err
    }
  }

  return (
    <aside className="panel-detalle" aria-label={`Orden de mantenimiento ${orden.id}`}>
      <header className="detalle-encabezado">
        <h2>#{orden.id} {orden.plantilla_nombre}</h2>
        <button type="button" className="boton-texto" onClick={alCerrar}>Cerrar</button>
      </header>
      <dl className="ficha">
        <div><dt>Recurso</dt><dd>{orden.recurso_nombre}</dd></div>
        <div><dt>Estado</dt><dd><EstadoOrden valor={orden.estado} /></dd></div>
        <div><dt>Programada para</dt><dd>{dia(orden.fecha_programada)}</dd></div>
        <div><dt>Origen</dt><dd>{ORIGENES[orden.origen] || orden.origen}</dd></div>
        <div><dt>Técnicos</dt><dd>{orden.asignados.map((a) => a.nombre).join(', ') || 'Sin asignar'}</dd></div>
      </dl>

      {error && <p className="aviso aviso-error" role="alert">{error}</p>}

    </aside>
  )
}

export function Mantenimientos({ usuario, idInicial = null, alUsarIdInicial }) {
  const [filtro, setFiltro] = useState('abiertas')
  const [ordenes, setOrdenes] = useState([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')
  const [aviso, setAviso] = useState('')
  const [seleccion, setSeleccion] = useState(null)

  const cargar = useCallback(async () => {
    setCargando(true)
    setError('')
    const consulta = FILTROS.find(([id]) => id === filtro)[2]
    try {
      setOrdenes(await api('/mantenimientos/ordenes', { consulta }))
    } catch (e) {
      setError(e.message)
    } finally {
      setCargando(false)
    }
  }, [filtro])
  useEffect(() => { cargar() }, [cargar])

  // Llegada desde un recurso: abre esa orden
  useEffect(() => {
    if (!idInicial) return
    api(`/mantenimientos/ordenes/${idInicial}`).then(setSeleccion).catch(() => {}).finally(() => alUsarIdInicial?.())
  }, [idInicial, alUsarIdInicial])

  function actualizar(nueva) {
    setSeleccion(nueva)
    setOrdenes((os) => os.map((o) => (o.id === nueva.id ? nueva : o)))
  }

  return (
    <div className={seleccion ? 'pagina con-panel' : 'pagina'}>
      <section className="contenido">
        <header className="encabezado-pagina">
          <h1>Mantenimientos</h1>
        </header>
        <div className="barra-filtros" role="group" aria-label="Filtrar órdenes">
          {FILTROS.filter(([id]) => id !== 'mias' || ['TECNICO', 'ADMINISTRADOR'].includes(usuario.rol)).map(([id, texto]) => (
            <button key={id} type="button" className={filtro === id ? 'boton-principal' : 'boton-secundario'}
                    aria-pressed={filtro === id} onClick={() => { setFiltro(id); setSeleccion(null) }}>{texto}</button>
          ))}
          <span className="tenue">{cargando ? 'Cargando…' : `${ordenes.length} orden${ordenes.length === 1 ? '' : 'es'}`}</span>
        </div>
        {aviso && <p className="aviso aviso-bien" role="status">{aviso}</p>}
        {error && <p className="aviso aviso-error" role="alert">{error}</p>}
        {!cargando && ordenes.length === 0 && !error ? (
          <div className="vacio"><p>No hay órdenes en esta vista.</p></div>
        ) : (
          <div className="tabla-contenedor">
            <table className="tabla">
              <thead>
                <tr><th scope="col">Orden</th><th scope="col">Recurso</th><th scope="col">Estado</th>
                  <th scope="col">Programada</th><th scope="col">Técnicos</th></tr>
              </thead>
              <tbody>
                {ordenes.map((o) => (
                  <tr key={o.id} className={seleccion?.id === o.id ? 'seleccionada' : ''} onClick={() => setSeleccion(o)}>
                    <td data-etiqueta="Orden">
                      <button type="button" className="enlace-fila" onClick={(e) => { e.stopPropagation(); setSeleccion(o) }}>
                        #{o.id} {o.plantilla_nombre}
                      </button>
                    </td>
                    <td data-etiqueta="Recurso">{o.recurso_nombre}</td>
                    <td data-etiqueta="Estado"><EstadoOrden valor={o.estado} /></td>
                    <td data-etiqueta="Programada">{dia(o.fecha_programada)}</td>
                    <td data-etiqueta="Técnicos">{o.asignados.map((a) => a.nombre).join(', ') || 'Sin asignar'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {seleccion && (
        <>
          <div className="fondo-panel" aria-hidden="true" onClick={() => setSeleccion(null)} />
          <DetalleOrden key={seleccion.id} orden={seleccion} usuario={usuario} alActualizar={actualizar} alCerrar={() => setSeleccion(null)} />
        </>
      )}
    </div>
  )
}
