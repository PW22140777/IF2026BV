// Tablero para la toma de decisiones (visible para todos los roles).
// Va de lo general a lo particular: indicadores, estado de los espacios, inventario,
// edificios que requieren atención, servicios con problema y consumos.
// Las gráficas son barras hechas con CSS: no hace falta ninguna librería.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useCatalogos } from '../catalogos'
import { ESTADOS_ELEMENTO, ESTADOS_INMUEBLE, legible } from '../recursos'
import { Estado } from './PaginaRecurso'

const suma = (grupos) => Object.values(grupos || {}).reduce((a, b) => a + b, 0)
const numero = (n) => n.toLocaleString('es-MX')

// Clase de color de cada estado (definidas en estilos.css, sección resumen)
const COLOR_ESTADO = {
  OPERATIVO: 'bien', EN_MANTENIMIENTO: 'medio',
  BUENO: 'bien', REGULAR: 'medio', MALO: 'mal',
  FUERA_DE_SERVICIO: 'fuera',
  RESUELTO: 'bien', PARCIAL: 'medio', NO_RESUELTO: 'mal',   // resultado de un mantenimiento
}
const RESULTADOS = [['RESUELTO', 'Resuelto'], ['PARCIAL', 'Parcial'], ['NO_RESUELTO', 'No resuelto']]

// 45 -> «45 min»; 150 -> «2 h 30 min»
function duracionLegible(minutos) {
  if (minutos === null || minutos === undefined) return '—'
  return minutos < 60 ? `${minutos} min` : `${Math.floor(minutos / 60)} h${minutos % 60 ? ` ${minutos % 60} min` : ''}`
}

function Indicador({ titulo, valor, de, nota, alerta }) {
  return (
    <div className="indicador">
      <p className="indicador-titulo">{titulo}</p>
      <p className={alerta ? 'indicador-valor texto-alerta' : 'indicador-valor'}>
        {valor}{de !== undefined && <span className="indicador-de"> de {numero(de)}</span>}
      </p>
      {nota && <p className="indicador-nota">{nota}</p>}
    </div>
  )
}

function Leyenda({ estados }) {
  return (
    <ul className="leyenda">
      {estados.map(([clave, texto]) => (
        <li key={clave}><span className={`muestra color-${COLOR_ESTADO[clave]}`} aria-hidden="true" />{texto}</li>
      ))}
    </ul>
  )
}

// Una barra apilada: cada segmento mide lo que representa del total
function BarraApilada({ etiqueta, grupos, estados }) {
  const total = suma(grupos)
  const detalle = estados.filter(([c]) => grupos[c]).map(([c, t]) => `${grupos[c]} ${t.toLowerCase()}`).join(', ')
  return (
    <div className="fila-apilada">
      <span className="fila-etiqueta">{etiqueta}</span>
      <span className="pila" role="img" aria-label={`${etiqueta}: ${detalle || 'sin registros'}`}>
        {estados.filter(([c]) => grupos[c]).map(([c, t]) => (
          <span key={c} className={`segmento color-${COLOR_ESTADO[c]}`} style={{ flexGrow: grupos[c] }}
                title={`${t}: ${numero(grupos[c])}`} />
        ))}
      </span>
      <span className="fila-total">{numero(total)}</span>
    </div>
  )
}

function Columnas({ titulo, datos, unidad }) {
  const maximo = Math.max(1, ...datos.map((d) => d.cantidad))
  const mes = (p) => new Date(`${p}T12:00:00`).toLocaleDateString('es-MX', { month: 'short' })
  return (
    <figure className="tarjeta columnas">
      <figcaption>{titulo} <span className="tenue">({unidad})</span></figcaption>
      {datos.length === 0 ? <p className="tenue">Sin consumos registrados en los últimos 12 meses.</p> : (
        <div className="columnas-area">
          {datos.map((d) => (
            <div className="columna" key={d.periodo}
                 title={`${numero(d.cantidad)} ${unidad}${d.costo > 0 ? `, $${numero(d.costo)}` : ''}`}>
              <span className="columna-pista">
                <span className="columna-barra" style={{ height: `${(d.cantidad / maximo) * 100}%` }} />
              </span>
              <span className="columna-mes">{mes(d.periodo)}</span>
            </div>
          ))}
        </div>
      )}
    </figure>
  )
}

export function Resumen({ campusActivo = '', alAbrir }) {
  const { nombreCampus, nombreTipo, servicios: catalogoServicios, campusDeServicio } = useCatalogos()
  const [inmuebles, setInmuebles] = useState(null)
  const [consumos, setConsumos] = useState([])
  const [fallas, setFallas] = useState([])
  const [mantenimiento, setMantenimiento] = useState(null)   // null si el servicio no responde: el resto sigue
  const [error, setError] = useState('')

  useEffect(() => {
    const consulta = { campus_id: campusActivo || undefined }
    Promise.all([
      api('/resumen/inmuebles', { consulta }),
      api('/resumen/consumos', { consulta }),
      api('/resumen/servicios', { consulta }),
      api('/resumen/mantenimientos', { consulta }).catch(() => null),
    ])
      .then(([i, c, s, m]) => { setInmuebles(i); setConsumos(c); setFallas(s); setMantenimiento(m) })
      .catch((e) => setError(e.message))
  }, [campusActivo])

  if (error) return <div className="pagina"><section className="contenido"><p className="aviso aviso-error">{error}</p></section></div>
  if (!inmuebles) return <div className="pagina"><section className="contenido"><p className="tenue">Cargando resumen…</p></section></div>

  const edificiosOperativos = inmuebles.edificios_por_estado.OPERATIVO || 0
  const areasOperativas = inmuebles.areas_por_estado.OPERATIVO || 0
  const totalPiezas = suma(inmuebles.inventario_por_estado)
  const piezasBuenas = inmuebles.inventario_por_estado.BUENO || 0
  const piezasDanadas = (inmuebles.inventario_por_estado.MALO || 0) + (inmuebles.inventario_por_estado.FUERA_DE_SERVICIO || 0)
  const serviciosActivos = catalogoServicios.filter((s) => s.activo && !s.eliminado_en
    && (!campusActivo || String(campusDeServicio(s)) === String(campusActivo))).length

  // Tipos de inventario de mayor a menor cantidad
  const tiposInventario = Object.entries(inmuebles.inventario_por_tipo_y_estado)
    .sort((a, b) => suma(b[1]) - suma(a[1]))
  const areasPorTipo = Object.entries(inmuebles.areas_por_tipo).sort((a, b) => b[1] - a[1])

  return (
    <div className="pagina">
      <section className="contenido">
        <header className="encabezado-pagina">
          <h1>{campusActivo ? `Resumen de ${nombreCampus(Number(campusActivo))}` : 'Resumen de la escuela'}</h1>
        </header>

        <div className="rejilla-indicadores">
          <Indicador titulo="Edificios operativos" valor={numero(edificiosOperativos)} de={inmuebles.edificios}
                     nota={inmuebles.edificios - edificiosOperativos > 0
                       ? `${inmuebles.edificios - edificiosOperativos} requieren atención` : 'Todos operan con normalidad'} />
          <Indicador titulo="Áreas operativas" valor={numero(areasOperativas)} de={inmuebles.areas}
                     nota={`${inmuebles.areas_independientes} sin edificio, como canchas o bancas`} />
          <Indicador titulo="Inventario en buen estado"
                     valor={totalPiezas ? `${Math.round((piezasBuenas / totalPiezas) * 100)} %` : '—'}
                     nota={piezasDanadas > 0 ? `${numero(piezasDanadas)} piezas en mal estado o fuera de servicio` : `${numero(totalPiezas)} piezas, ninguna dañada`}
                     alerta={piezasDanadas > 0} />
          <Indicador titulo="Servicios con problema" valor={numero(fallas.length)} de={serviciosActivos}
                     nota={fallas.length ? 'Con falla, suspendidos o en mantenimiento' : 'Todos operando'}
                     alerta={fallas.length > 0} />
          {mantenimiento && (
            <Indicador titulo="Mantenimientos abiertos" valor={numero(mantenimiento.programadas + mantenimiento.en_curso)}
                       nota={mantenimiento.vencidas || mantenimiento.sin_asignar
                         ? `${mantenimiento.vencidas} vencidos · ${mantenimiento.sin_asignar} sin técnico`
                         : `${mantenimiento.en_curso} en curso; ninguno vencido`}
                       alerta={mantenimiento.vencidas > 0} />
          )}
        </div>

        <div className="rejilla-tarjetas">
          <section className="tarjeta">
            <h2>Estado de edificios y áreas</h2>
            <Leyenda estados={ESTADOS_INMUEBLE} />
            <BarraApilada etiqueta="Edificios" grupos={inmuebles.edificios_por_estado} estados={ESTADOS_INMUEBLE} />
            <BarraApilada etiqueta="Áreas" grupos={inmuebles.areas_por_estado} estados={ESTADOS_INMUEBLE} />
            {areasPorTipo.length > 0 && (
              <p className="nota-tarjeta">
                Áreas por tipo: {areasPorTipo.map(([t, n]) => `${n} ${legible(t, 'tipo').toLowerCase()}`).join(' · ')}
              </p>
            )}
          </section>

          <section className="tarjeta">
            <h2>Estado del inventario por tipo</h2>
            <Leyenda estados={ESTADOS_ELEMENTO} />
            {tiposInventario.length === 0 && <p className="tenue">Sin inventario registrado.</p>}
            {tiposInventario.map(([tipo, grupos]) => (
              <BarraApilada key={tipo} etiqueta={nombreTipo(tipo)} grupos={grupos} estados={ESTADOS_ELEMENTO} />
            ))}
          </section>
        </div>

        <section className="tarjeta">
          <h2>Edificios: estado y salud del inventario</h2>
          {inmuebles.edificios_detalle.length === 0 ? <p className="tenue">No hay edificios registrados.</p> : (
            <>
              <div className="tabla-contenedor">
              <table className="tabla tabla-resumen">
                <thead>
                  <tr>
                    <th scope="col">Edificio</th>
                    {!campusActivo && <th scope="col">Campus</th>}
                    <th scope="col">Estado</th>
                    <th scope="col" className="numero">Áreas operativas</th>
                    <th scope="col" className="numero">Inventario dañado</th>
                  </tr>
                </thead>
                <tbody>
                  {inmuebles.edificios_detalle.map((e) => (
                    <tr key={e.id} onClick={() => alAbrir?.('edificios', e.id)}>
                      <td data-etiqueta="Edificio">
                        <button type="button" className="boton-texto" onClick={(ev) => { ev.stopPropagation(); alAbrir?.('edificios', e.id) }}>
                          {e.nombre}
                        </button>
                      </td>
                      {!campusActivo && <td data-etiqueta="Campus">{nombreCampus(e.campus_id)}</td>}
                      <td data-etiqueta="Estado"><Estado valor={e.estado} /></td>
                      <td data-etiqueta="Áreas operativas" className="numero">{e.areas_operativas} / {e.areas}</td>
                      <td data-etiqueta="Inventario dañado" className={e.inventario_danado > 0 ? 'numero texto-alerta' : 'numero'}>{numero(e.inventario_danado)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
              <p className="nota-tarjeta">Del más urgente al menos urgente. Abre un edificio para ver sus áreas e historial.</p>
            </>
          )}
        </section>

        {mantenimiento && (
          <section className="tarjeta">
            <h2>Mantenimientos</h2>
            <div className="rejilla-mantenimiento">
              <dl className="cifras">
                <div><dt>Programados</dt><dd>{numero(mantenimiento.programadas)}</dd></div>
                <div><dt>En curso</dt><dd>{numero(mantenimiento.en_curso)}</dd></div>
                <div><dt>Vencidos</dt><dd className={mantenimiento.vencidas ? 'texto-alerta' : undefined}>{numero(mantenimiento.vencidas)}</dd></div>
                <div><dt>Sin técnico asignado</dt><dd>{numero(mantenimiento.sin_asignar)}</dd></div>
                <div><dt>Tiempo promedio de atención</dt>
                  <dd>{duracionLegible(mantenimiento.minutos_promedio)}</dd></div>
              </dl>
              <div>
                <p className="nota-tarjeta">Terminados en los últimos {mantenimiento.dias} días, por resultado</p>
                <Leyenda estados={RESULTADOS} />
                <BarraApilada etiqueta="Terminados" grupos={mantenimiento.por_resultado} estados={RESULTADOS} />
              </div>
            </div>
            {mantenimiento.vencidas_detalle.length > 0 && (
              <>
                <h3 className="subtitulo-tarjeta">Vencidos</h3>
                <ul className="lista-fallas">
                  {mantenimiento.vencidas_detalle.map((v) => (
                    <li key={v.id}>
                      <button type="button" className="boton-texto" onClick={() => alAbrir?.('mantenimientos', v.id)}>
                        #{v.id} {v.plantilla_nombre}
                      </button>
                      <span className="tenue">{v.recurso_nombre} · hace {v.dias_vencida} {v.dias_vencida === 1 ? 'día' : 'días'}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        )}

        <div className="rejilla-tarjetas">
          <section className="tarjeta">
            <h2>Servicios que no operan con normalidad</h2>
            {fallas.length === 0 ? <p className="tenue">Todos los servicios están operando.</p> : (
              <ul className="lista-fallas">
                {fallas.map((s) => (
                  <li key={s.id}>
                    <span>
                      <strong>{legible(s.tipo, 'tipo')}</strong>, {s.nombre}
                      <span className="tenue"> · {s.area || s.edificio || `${s.campus} (todo el campus)`}</span>
                    </span>
                    <Estado valor={s.estado} />
                  </li>
                ))}
              </ul>
            )}
          </section>
          <Columnas titulo="Luz por mes" unidad="kWh" datos={consumos.filter((c) => c.tipo === 'LUZ')} />
          <Columnas titulo="Agua por mes" unidad="m³" datos={consumos.filter((c) => c.tipo === 'AGUA')} />
        </div>
      </section>
    </div>
  )
}
