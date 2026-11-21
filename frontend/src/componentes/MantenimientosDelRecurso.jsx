// Sección «Mantenimientos» del panel de un recurso: sus órdenes y el botón para programar una.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { EstadoOrden } from './Mantenimientos'

export function MantenimientosDelRecurso({ recurso, registro, usuario, alAbrirOrden }) {
  const [ordenes, setOrdenes] = useState(null)   // null = cargando
  const [plantillas, setPlantillas] = useState([])
  const [programando, setProgramando] = useState(false)
  const [plantillaId, setPlantillaId] = useState('')
  const [fecha, setFecha] = useState(() => new Date().toLocaleDateString('en-CA'))
  const [tecnicos, setTecnicos] = useState([])        // solo el Administrador elige
  const [elegidos, setElegidos] = useState([])
  const [error, setError] = useState('')
  const esAdmin = usuario.rol === 'ADMINISTRADOR'
  const programa = ['ADMINISTRADOR', 'TECNICO'].includes(usuario.rol)

  const cargar = useCallback(() => {
    api('/mantenimientos/ordenes', { consulta: { recurso, recurso_id: registro.id, limite: 20 } })
      .then(setOrdenes).catch((e) => setError(e.message))
  }, [recurso, registro.id])
  useEffect(() => { cargar() }, [cargar])

  function abrirFormulario() {
    setProgramando(true)
    setError('')
    // Plantillas activas de este recurso; en inventario, solo las de su tipo (o de cualquier tipo)
    api('/mantenimientos/plantillas', { consulta: { recurso } })
      .then((ps) => setPlantillas(ps.filter((p) => p.activa && (!p.tipo_elemento || p.tipo_elemento === registro.tipo))))
      .catch((e) => setError(e.message))
    if (esAdmin) {
      api('/usuarios').then((us) => setTecnicos(us.filter((u) => u.activo && ['TECNICO', 'ADMINISTRADOR'].includes(u.rol))))
        .catch(() => {})
    }
  }

  async function programar(e) {
    e.preventDefault()
    setError('')
    try {
      const orden = await api('/mantenimientos/ordenes', {
        metodo: 'POST',
        cuerpo: { plantilla_id: Number(plantillaId), recurso_id: registro.id, fecha_programada: fecha, tecnicos: elegidos },
      })
      setProgramando(false)
      setPlantillaId('')
      setElegidos([])
      cargar()
      alAbrirOrden?.(orden.id)
    } catch (err) {
      setError(err.message)
    }
  }

  const abiertas = (ordenes || []).filter((o) => ['PROGRAMADA', 'EN_CURSO'].includes(o.estado))
  const cerradas = (ordenes || []).filter((o) => !['PROGRAMADA', 'EN_CURSO'].includes(o.estado)).slice(0, 5)

  return (
    <section className="seccion-detalle">
      <h4>Mantenimientos</h4>
      {ordenes === null && !error && <p className="tenue">Cargando…</p>}
      {ordenes && ordenes.length === 0 && <p className="tenue">Sin mantenimientos registrados.</p>}
      <ul className="lista-servicios">
        {[...abiertas, ...cerradas].map((o) => (
          <li key={o.id}>
            <button type="button" className="boton-texto" onClick={() => alAbrirOrden?.(o.id)}>#{o.id} {o.plantilla_nombre}</button>
            <EstadoOrden valor={o.estado} />
          </li>
        ))}
      </ul>
      {programa && !programando && !registro.eliminado_en && (
        <div className="acciones">
          <button type="button" className="boton-secundario" onClick={abrirFormulario}>Programar mantenimiento</button>
        </div>
      )}
      {programando && (
        <form className="formulario" onSubmit={programar}>
          <div className="campo">
            <label htmlFor="mant-plantilla">Mantenimiento</label>
            <select id="mant-plantilla" required value={plantillaId} onChange={(e) => setPlantillaId(e.target.value)}>
              <option value="">Elige una plantilla</option>
              {plantillas.map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
            </select>
            {plantillas.length === 0 && <small>No hay plantillas para este recurso; el Administrador las crea en «Plantillas de mantenimiento».</small>}
          </div>
          <div className="campo">
            <label htmlFor="mant-fecha">Fecha programada</label>
            <input id="mant-fecha" type="date" required value={fecha} onChange={(e) => setFecha(e.target.value)} />
          </div>
          {esAdmin ? (
            <fieldset className="campo">
              <legend>Técnicos asignados</legend>
              <div className="casillas">
                {tecnicos.map((u) => (
                  <label key={u.id} className="casilla-en-linea">
                    <input type="checkbox" checked={elegidos.includes(u.id)}
                           onChange={(ev) => setElegidos(ev.target.checked ? [...elegidos, u.id] : elegidos.filter((x) => x !== u.id))} />
                    {u.nombre}
                  </label>
                ))}
              </div>
            </fieldset>
          ) : (
            <p className="tenue">La orden queda asignada a ti.</p>
          )}
          {error && <p className="aviso aviso-error" role="alert">{error}</p>}
          <div className="acciones">
            <button type="submit" className="boton-principal" disabled={!plantillaId || (esAdmin && elegidos.length === 0)}>Programar</button>
            <button type="button" className="boton-secundario" onClick={() => setProgramando(false)}>Cancelar</button>
          </div>
        </form>
      )}
      {error && !programando && <p className="aviso aviso-error" role="alert">{error}</p>}
    </section>
  )
}
