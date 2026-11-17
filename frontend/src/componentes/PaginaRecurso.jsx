// Página genérica: tabla del recurso + panel de detalle con propiedades e historial
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { useCatalogos } from '../catalogos'
import { legible } from '../recursos'
import { resumenDefiniciones } from './EditorDefiniciones'
import { Formulario } from './Formulario'
import { Historial } from './Historial'

export function Estado({ valor }) {
  const tono = {
    OPERATIVO: 'bien', BUENO: 'bien', OPERANDO: 'bien',
    REGULAR: 'medio', EN_MANTENIMIENTO: 'medio', SUSPENDIDO: 'medio',
    MALO: 'mal', FUERA_DE_SERVICIO: 'mal', CON_FALLA: 'mal',
  }[valor] || 'neutro'
  return <span className={`estado estado-${tono}`}>{legible(valor)}</span>
}

// definiciones: propiedades que define el tipo del elemento (inventario); dan etiqueta y unidad
function Propiedades({ registro, puedeEditar, alCambiar, reservadas = [], definiciones = [] }) {
  const [clave, setClave] = useState('')
  const [valor, setValor] = useState('')
  const [error, setError] = useState('')
  const entradas = Object.entries(registro.propiedades || {})
  const definicion = (k) => definiciones.find((d) => d.clave === k)
  const mostrarValor = (k, v) => {
    if (typeof v === 'boolean') return v ? 'Sí' : 'No'
    const unidad = definicion(k)?.unidad
    return `${legible(v, 'propiedad')}${unidad ? ` ${unidad}` : ''}`
  }

  // Si el valor es JSON válido (número, booleano, lista...) se guarda con ese tipo
  const interpretar = (texto) => {
    try { return JSON.parse(texto) } catch { return texto }
  }

  async function poner(e) {
    e.preventDefault()
    setError('')
    if (reservadas.some((nombre) => nombre.toLowerCase() === clave.trim().toLowerCase())) {
      setError(`La propiedad «${clave.trim()}» está reservada por el sistema.`)
      return
    }
    try {
      await alCambiar('PUT', clave.trim(), { valor: interpretar(valor) })
      setClave('')
      setValor('')
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section className="seccion-detalle">
      <h4>{definiciones.length ? 'Propiedades' : 'Propiedades adicionales'}</h4>
      {entradas.length === 0 && <p className="tenue">Sin propiedades registradas.</p>}
      {entradas.length > 0 && (
        <dl className="propiedades">
          {entradas.map(([k, v]) => (
            <div key={k}>
              <dt>{definicion(k)?.etiqueta || k}</dt>
              <dd>
                {mostrarValor(k, v)}
                {puedeEditar && (
                  <button type="button" className="boton-texto" onClick={() => alCambiar('DELETE', k).catch((err) => setError(err.message))}
                          aria-label={`Quitar la propiedad ${k}`}>Quitar</button>
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {puedeEditar && (
        <form className="fila-propiedad" onSubmit={poner}>
          <input aria-label="Nombre de la propiedad" placeholder="Nombre, p. ej. btu" value={clave}
                 onChange={(e) => setClave(e.target.value)} pattern="[A-Za-z0-9_]{1,50}" required />
          <input aria-label="Valor" placeholder="Valor, p. ej. 12000" value={valor}
                 onChange={(e) => setValor(e.target.value)} required />
          <button type="submit" className="boton-secundario">Agregar o cambiar</button>
        </form>
      )}
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
    </section>
  )
}

function ServiciosDelRecurso({ filtro, id }) {
  const [servicios, setServicios] = useState(null)   // null = cargando
  const [error, setError] = useState('')

  useEffect(() => {
    setServicios(null)
    api('/servicios', { consulta: { [filtro]: id } })
      .then(setServicios)
      .catch((e) => setError(e.message))
  }, [filtro, id])

  return (
    <section className="seccion-detalle">
      <h4>Servicios básicos</h4>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      {!error && servicios === null && <p className="tenue">Cargando…</p>}
      {servicios?.length === 0 && <p className="tenue">No tiene servicios básicos asignados.</p>}
      {servicios?.length > 0 && (
        <ul className="lista-servicios">
          {servicios.map((s) => (
            <li key={s.id}>
              {legible(s.tipo)} — {s.nombre} <Estado valor={s.estado} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Detalle({ config, registro, usuario, campusActivo, alActualizar, alCerrar }) {
  const catalogos = useCatalogos()
  const [modo, setModo] = useState('ver')         // ver | editar | eliminar
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)        // fuerza recargar el historial
  const puedeEditar = usuario.rol !== 'CONSULTA' && !registro.eliminado_en
  const esAdmin = usuario.rol === 'ADMINISTRADOR'
  const ruta = `${config.ruta}/${registro.id}`

  async function ejecutar(promesa) {
    setError('')
    try {
      const nuevo = await promesa
      alActualizar(nuevo)
      setModo('ver')
      setMotivo('')
      // El historial se escribe de forma asíncrona (RabbitMQ): se recarga en un momento
      setTimeout(() => setVersion((v) => v + 1), 1500)
      return nuevo
    } catch (err) {
      setError(err.message)
      throw err
    }
  }

  const valorCampo = (campo) => {
    const v = registro[campo.nombre]
    if (campo.tipo === 'campus') return catalogos.nombreCampus(v)
    if (campo.tipo === 'edificio') return catalogos.nombreEdificio(v)
    if (campo.tipo === 'area') return catalogos.nombreArea(v)
    if (campo.tipo === 'servicio') return catalogos.nombreServicio(v)
    if (campo.tipo === 'tipoElemento') return catalogos.nombreTipo(v)
    if (campo.tipo === 'definiciones') return resumenDefiniciones(v)
    if (campo.tipo === 'destino') return catalogos.destinoServicio(registro)
    if (campo.tipo === 'mes') return v?.slice(0, 7)
    if (campo.tipo === 'fecha') return v ? new Date(`${v}T00:00:00`).toLocaleDateString('es-MX') : '—'
    if (campo.tipo === 'total_lineal') return v === null || v === undefined ? '—' : `${v}${registro.unidad ? ` ${registro.unidad}` : ''}`
    if (campo.tipo === 'total_area') return v === null || v === undefined ? '—' : `${v}${registro.unidad ? ` ${registro.unidad}²` : ''}`
    if (campo.tipo === 'total_volumen') return v === null || v === undefined ? '—' : `${v}${registro.unidad ? ` ${registro.unidad}³` : ''}`
    return legible(v, campo.nombre)
  }

  if (modo === 'editar') {
    return (
      <aside className="panel-detalle" aria-label="Editar">
        <Formulario config={config} registro={registro} campusActivo={campusActivo} alCancelar={() => setModo('ver')}
                    alGuardar={(datos) => ejecutar(api(ruta, { metodo: 'PATCH', cuerpo: datos }))} />
      </aside>
    )
  }

  return (
    <aside className="panel-detalle" aria-label={`Detalle de ${config.singular}`}>
      <header className="detalle-encabezado">
        <h2>{config.nombre(registro)}</h2>
        <button type="button" className="boton-texto" onClick={alCerrar}>Cerrar</button>
      </header>

      {registro.eliminado_en && (
        <p className="aviso aviso-eliminado">
          Eliminado el {new Date(registro.eliminado_en).toLocaleDateString('es-MX')}. Motivo: {registro.motivo_eliminacion}
        </p>
      )}

      <dl className="ficha">
        {config.campos.map((c) => (
          <div key={c.nombre}>
            <dt>{c.etiqueta}</dt>
            <dd>{c.tipo === 'opciones' && c.nombre === 'estado' ? <Estado valor={registro.estado} /> : valorCampo(c)}</dd>
          </div>
        ))}
        {(config.camposSoloLectura || []).map((c) => (
          <div key={c.nombre}>
            <dt>{c.etiqueta}</dt>
            <dd>{valorCampo(c)}</dd>
          </div>
        ))}
        {registro.unidad && !config.campos.some((c) => c.nombre === 'unidad') &&
          <div><dt>Unidad</dt><dd>{registro.unidad}</dd></div>}
      </dl>

      {error && <p className="aviso aviso-error" role="alert">{error}</p>}

      {modo === 'eliminar' ? (
        <form className="confirmar-eliminar" onSubmit={(e) => {
          e.preventDefault()
          ejecutar(api(ruta, { metodo: 'DELETE', cuerpo: { motivo } })).catch(() => {})
        }}>
          <label htmlFor="motivo">¿Por qué se elimina? Queda registrado en el historial.</label>
          <textarea id="motivo" rows={2} minLength={5} required value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          <div className="acciones">
            <button type="submit" className="boton-peligro">Eliminar {config.singular}</button>
            <button type="button" className="boton-secundario" onClick={() => setModo('ver')}>Cancelar</button>
          </div>
        </form>
      ) : (
        <div className="acciones">
          {puedeEditar && <button type="button" className="boton-principal" onClick={() => setModo('editar')}>Editar</button>}
          {puedeEditar && <button type="button" className="boton-secundario" onClick={() => setModo('eliminar')}>Eliminar</button>}
          {esAdmin && registro.eliminado_en && (
            <button type="button" className="boton-principal"
                    onClick={() => ejecutar(api(`${ruta}/restaurar`, { metodo: 'POST', cuerpo: { motivo: 'Restaurado desde la interfaz' } })).catch(() => {})}>
              Restaurar
            </button>
          )}
        </div>
      )}

      {!config.sinPropiedadesLibres && (
        <Propiedades registro={registro} puedeEditar={puedeEditar} reservadas={config.propiedadesReservadas}
                     definiciones={config.propiedadesPorTipo ? catalogos.tipoElemento(registro.tipo)?.propiedades_definidas : undefined}
                     alCambiar={(metodo, clave, cuerpo) => ejecutar(api(`${ruta}/propiedades/${encodeURIComponent(clave)}`, { metodo, cuerpo }))} />
      )}

      {config.serviciosFiltro && <ServiciosDelRecurso filtro={config.serviciosFiltro} id={registro.id} />}

      <section className="seccion-detalle">
        <h4>Historial</h4>
        <Historial recurso={config.historial} id={registro.id} version={version} />
      </section>
    </aside>
  )
}

// idInicial: registro que se abre al llegar desde otra pantalla (p. ej. un edificio del Resumen)
export function PaginaRecurso({ config, usuario, campusActivo = '', idInicial = null, alUsarIdInicial }) {
  const catalogos = useCatalogos()
  const [filas, setFilas] = useState([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')
  const [seleccion, setSeleccion] = useState(null)
  const [creando, setCreando] = useState(false)
  const [filtros, setFiltros] = useState({})
  const [verEliminados, setVerEliminados] = useState(false)
  const puedeCrear = usuario.rol !== 'CONSULTA'
  const esAdmin = usuario.rol === 'ADMINISTRADOR'

  const cargar = useCallback(async () => {
    setCargando(true)
    setError('')
    const consulta = { incluir_eliminados: verEliminados || undefined }
    if (campusActivo && !config.sinFiltroCampus) consulta.campus_id = campusActivo
    for (const f of config.filtros || []) {
      const valor = filtros[f.nombre]
      if (!valor) continue
      if (f.tipo === 'edificio' && valor === 'independientes') consulta.independientes = true
      else if (f.tipo === 'edificio') consulta.edificio_id = valor
      else consulta[f.nombre] = valor
    }
    try {
      setFilas(await api(config.ruta, { consulta }))
    } catch (e) {
      setError(e.message)
    } finally {
      setCargando(false)
    }
  }, [config.ruta, config.sinFiltroCampus, config.filtros, filtros, verEliminados, campusActivo])

  useEffect(() => { cargar() }, [cargar])
  useEffect(() => { setSeleccion(null); setCreando(false); setFiltros({}) }, [config, campusActivo])

  // En teléfonos y tabletas el panel cubre la pantalla: Escape o tocar el fondo lo cierra
  const panelAbierto = Boolean(seleccion || creando)
  const cerrarPanel = useCallback(() => { setSeleccion(null); setCreando(false) }, [])
  useEffect(() => {
    if (!panelAbierto) return undefined
    const alTeclear = (e) => { if (e.key === 'Escape') cerrarPanel() }
    window.addEventListener('keydown', alTeclear)
    return () => window.removeEventListener('keydown', alTeclear)
  }, [panelAbierto, cerrarPanel])
  // Abre el registro pedido en cuanto llega la lista, y avisa para no volver a abrirlo
  useEffect(() => {
    if (!idInicial) return
    const fila = filas.find((f) => f.id === idInicial)
    if (fila) { setSeleccion(fila); alUsarIdInicial?.() }
  }, [filas, idInicial, alUsarIdInicial])

  function actualizarFila(nuevo) {
    setFilas((fs) => fs.map((f) => (f.id === nuevo.id ? nuevo : f)))
    setSeleccion(nuevo)
    catalogos.recargar()
  }

  const celda = (fila, columna) => {
    const v = fila[columna]
    switch (columna) {
      case 'estado': return <Estado valor={v} />
      case 'campus_id': return catalogos.nombreCampus(v)
      case 'edificio_id': return catalogos.nombreEdificio(v)
      case 'area_id': return catalogos.nombreArea(v)
      case 'servicio_id': return catalogos.nombreServicio(v)
      case 'tipo': return config.propiedadesPorTipo ? catalogos.nombreTipo(v) : legible(v, 'tipo')
      case 'propiedades_definidas': return resumenDefiniciones(v)
      case 'periodo': return v?.slice(0, 7)
      case 'cantidad': return config.cantidadConUnidad && fila.unidad ? `${v} ${fila.unidad}` : v
      case 'total_lineal': return v === null || v === undefined ? '—' : fila.unidad ? `${v} ${fila.unidad}` : v
      case 'total_area': return v === null || v === undefined ? '—' : fila.unidad ? `${v} ${fila.unidad}²` : v
      case 'total_volumen':
      case 'total_volumen_espesor': return v === null || v === undefined ? '—' : fila.unidad ? `${v} ${fila.unidad}³` : v
      case 'destino': return catalogos.destinoServicio(fila)
      default: return legible(v, columna)
    }
  }

  const esVacio = (v) => v === null || v === undefined || v === '' || v === '—'
  const delCampus = (campusId) => !campusActivo || String(campusId) === String(campusActivo)
  const opcionesFiltro = (cfg) => {
    if (cfg.tipo === 'opciones') {
      return cfg.opciones.map(([v, t]) => <option key={v} value={v}>{t}</option>)
    }
    if (cfg.tipo === 'edificio') {
      return [
        ...(cfg.sinIndependientes ? [] : [<option key="i" value="independientes">Solo áreas independientes</option>]),
        ...catalogos.edificios.filter((e) => delCampus(e.campus_id))
          .map((e) => <option key={e.id} value={e.id}>{e.nombre}</option>),
      ]
    }
    const lista = cfg.tipo === 'area'
      ? catalogos.areas.filter((a) => delCampus(a.campus_id))
      : catalogos.servicios.filter((x) => delCampus(catalogos.campusDeServicio(x)))
    return lista.map((x) => <option key={x.id} value={x.id}>{x.nombre}</option>)
  }

  return (
    <div className={seleccion || creando ? 'pagina con-panel' : 'pagina'}>
      <section className="contenido">
        <header className="encabezado-pagina">
          <h1>{config.titulo}</h1>
          {puedeCrear && (
            <button type="button" className="boton-principal" onClick={() => { setSeleccion(null); setCreando(true) }}>
              Agregar {config.singular}
            </button>
          )}
        </header>

        <div className="barra-filtros">
          {config.filtros?.map((f) => (
            <label key={f.nombre}>
              {f.etiqueta}
              <select value={filtros[f.nombre] || ''}
                      onChange={(e) => setFiltros((anteriores) => ({ ...anteriores, [f.nombre]: e.target.value }))}>
                <option value="">Todos</option>
                {opcionesFiltro(f)}
              </select>
            </label>
          ))}
          {esAdmin && (
            <label className="casilla-en-linea">
              <input type="checkbox" checked={verEliminados} onChange={(e) => setVerEliminados(e.target.checked)} />
              Mostrar eliminados
            </label>
          )}
          <span className="tenue">{cargando ? 'Cargando…' : `${filas.length} registro${filas.length === 1 ? '' : 's'}`}</span>
        </div>

        {error && <p className="aviso aviso-error" role="alert">{error}</p>}

        {!cargando && filas.length === 0 && !error ? (
          <div className="vacio">
            <p>Todavía no hay {config.titulo.toLowerCase()} registrados.</p>
            {puedeCrear && <p>Usa «Agregar {config.singular}» para dar de alta el primero.</p>}
          </div>
        ) : (
          <div className="tabla-contenedor">
          <table className="tabla">
            <thead>
              <tr>{config.columnas.map(([c, t]) => <th key={c} scope="col">{t}</th>)}</tr>
            </thead>
            <tbody>
              {filas.map((fila) => (
                <tr key={fila.id}
                    className={[seleccion?.id === fila.id ? 'seleccionada' : '', fila.eliminado_en ? 'eliminada' : ''].join(' ')}
                    onClick={() => { setCreando(false); setSeleccion(fila) }}>
                  {config.columnas.map(([c, titulo], i) => (
                    <td key={c} data-etiqueta={titulo} className={i > 0 && esVacio(celda(fila, c)) ? 'celda-vacia' : undefined}>
                      {i === 0
                        ? <button type="button" className="enlace-fila" onClick={(e) => { e.stopPropagation(); setCreando(false); setSeleccion(fila) }}>{celda(fila, c)}</button>
                        : celda(fila, c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </section>

      {/* Fondo oscuro detrás del panel; solo se ve cuando el panel flota (pantallas angostas) */}
      {panelAbierto && <div className="fondo-panel" aria-hidden="true" onClick={cerrarPanel} />}
      {creando && (
        <aside className="panel-detalle" aria-label={`Nuevo ${config.singular}`}>
          <Formulario config={config} campusActivo={campusActivo} alCancelar={() => setCreando(false)}
                      alGuardar={async (datos) => {
                        const nuevo = await api(config.ruta, { metodo: 'POST', cuerpo: datos })
                        setFilas((fs) => [...fs, nuevo])
                        setCreando(false)
                        setSeleccion(nuevo)
                        catalogos.recargar()
                      }} />
        </aside>
      )}
      {seleccion && !creando && (
        <Detalle key={seleccion.id} config={config} registro={seleccion} usuario={usuario} campusActivo={campusActivo}
                 alActualizar={(nuevo) => { actualizarFila(nuevo); if (nuevo.eliminado_en && !verEliminados) cargar() }}
                 alCerrar={() => setSeleccion(null)} />
      )}
    </div>
  )
}
