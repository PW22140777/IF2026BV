// «Recorrido»: el campus dibujado como una calle de edificios. Se entra a un edificio
// (corte por pisos, cada área es una puerta) y luego a un salón (su inventario y su tablero de avisos).
// Es la única vista del Observador; los demás roles la tienen como sección adicional.
// Solo muestra inmuebles y el ESTADO de los servicios: nada de consumos ni mantenimientos.
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useCatalogos } from '../catalogos'
import { legible } from '../recursos'
import { Adjuntos, FotoFachada } from './Adjuntos'
import { Comentarios } from './Comentarios'

// Color de cada estado: bien (verde), atención (ámbar), mal (rojo)
const TONO = {
  OPERATIVO: 'bien', BUENO: 'bien', OPERANDO: 'bien',
  EN_MANTENIMIENTO: 'medio', REGULAR: 'medio', SUSPENDIDO: 'medio',
  FUERA_DE_SERVICIO: 'mal', MALO: 'mal', CON_FALLA: 'mal',
}
const tono = (estado) => TONO[estado] || 'neutro'

const ICONO_SERVICIO = { AGUA: '💧', LUZ: '⚡', INTERNET: '📶', ALCANTARILLADO: '🚰' }
// Íconos de los tipos de elemento conocidos; un tipo nuevo usa la caja genérica
const ICONO_ELEMENTO = {
  AIRE_ACONDICIONADO: '❄️', BANCA: '🪑', CONTACTO: '🔌', LUMINARIA: '💡', MESA: '🟫',
  PARED: '🧱', PIZARRON: '📋', PUERTA: '🚪', VENTANA: '🪟',
}
const ORDEN_ESTADOS = ['BUENO', 'REGULAR', 'MALO', 'FUERA_DE_SERVICIO']

function nombrePiso(piso) {
  if (piso === null || piso === undefined) return 'Sin piso indicado'
  return piso === 0 ? 'Planta baja' : `Piso ${piso}`
}

// Directorio: «Campus Centro › Edificio A › Piso 1 › Lab 3»; cada parte lleva a ese lugar
function Directorio({ partes }) {
  return (
    <nav className="directorio" aria-label="Dónde estás">
      {partes.map((p, i) => (
        <span key={i}>
          {i > 0 && <span className="directorio-sep" aria-hidden="true">›</span>}
          {p.ir && i < partes.length - 1
            ? <button type="button" className="boton-texto" onClick={p.ir}>{p.texto}</button>
            : <strong aria-current={i === partes.length - 1 ? 'location' : undefined}>{p.texto}</strong>}
        </span>
      ))}
    </nav>
  )
}

// Estado de los servicios como medidores en la pared. Al tocar uno se abre su tablero de avisos.
function Medidores({ servicios, usuario }) {
  const [abierto, setAbierto] = useState(null)
  if (servicios.length === 0) return <p className="tenue">Sin servicios registrados aquí.</p>
  const elegido = servicios.find((s) => s.id === abierto)
  return (
    <>
      <ul className="medidores">
        {servicios.map((s) => (
          <li key={s.id}>
            <button type="button" className={`medidor tono-${tono(s.estado)}`} aria-expanded={abierto === s.id}
                    onClick={() => setAbierto(abierto === s.id ? null : s.id)}>
              <span aria-hidden="true">{ICONO_SERVICIO[s.tipo] || '•'}</span>
              <span>{s.nombre}</span>
              <span className="medidor-estado">{legible(s.estado, 'estado')}</span>
            </button>
          </li>
        ))}
      </ul>
      {elegido && <Comentarios key={elegido.id} recurso="SERVICIO" id={elegido.id} usuario={usuario}
                               titulo={`Avisos de ${elegido.nombre}`} />}
    </>
  )
}

// -------------------------------------------------------------- 1. el campus
function Fachada({ edificio, areas, servicios, alEntrar }) {
  const niveles = Math.max(edificio.niveles || 1, 1)
  // Del piso más alto a la planta baja, como se ve un edificio desde la calle
  const pisos = Array.from({ length: niveles }, (_, i) => niveles - 1 - i)
  const atencion = areas.filter((a) => tono(a.estado) !== 'bien').length
  return (
    <li className="lote">
      <button type="button" className={`fachada tono-${tono(edificio.estado)}`} onClick={alEntrar}
              aria-label={`${edificio.nombre}: ${legible(edificio.estado, 'estado')}, ${niveles} niveles, ${areas.length} áreas${atencion ? `, ${atencion} requieren atención` : ''}. Entrar`}>
        <span className="letrero">
          <span className={`foco tono-${tono(edificio.estado)}`} aria-hidden="true" />
          <strong>{edificio.clave}</strong> {edificio.nombre}
        </span>
        <span className="muro" aria-hidden="true">
          {pisos.map((piso) => {
            const delPiso = areas.filter((a) => a.piso === piso)
            return (
              <span key={piso} className="hilera">
                {delPiso.length === 0
                  ? <span className="ventana apagada" />
                  : delPiso.map((a) => <span key={a.id} className={`ventana tono-${tono(a.estado)}`} title={a.nombre} />)}
              </span>
            )
          })}
          <span className="puerta-principal" />
        </span>
      </button>
      <span className="banqueta">
        {servicios.length === 0
          ? <span className="tenue">Sin servicios</span>
          : servicios.map((s) => (
            <span key={s.id} className={`chip-servicio tono-${tono(s.estado)}`} title={`${s.nombre}: ${legible(s.estado, 'estado')}`}>
              <span aria-hidden="true">{ICONO_SERVICIO[s.tipo]}</span> {legible(s.tipo, 'tipo')}
            </span>
          ))}
      </span>
    </li>
  )
}

function Campus({ campus, alIr }) {
  const { edificios, areas, servicios } = useCatalogos()
  const suyos = edificios.filter((e) => e.campus_id === campus.id)
  const independientes = areas.filter((a) => a.campus_id === campus.id && a.edificio_id === null)
  const delCampus = servicios.filter((s) => s.campus_id === campus.id)
  const todosLosServicios = servicios.filter((s) => s.campus_id === campus.id
    || suyos.some((e) => e.id === s.edificio_id)
    || areas.some((a) => a.id === s.area_id && a.campus_id === campus.id))
  const atencion = suyos.filter((e) => tono(e.estado) !== 'bien').length
  const operando = todosLosServicios.filter((s) => s.estado === 'OPERANDO').length

  return (
    <section className="campus-recorrido" aria-labelledby={`campus-${campus.id}`}>
      <div className="campus-encabezado">
        <h2 id={`campus-${campus.id}`}>{campus.nombre}</h2>
        <p className="tenue">
          {suyos.length} {suyos.length === 1 ? 'edificio' : 'edificios'}
          {atencion > 0 ? ` · ${atencion} ${atencion === 1 ? 'requiere' : 'requieren'} atención` : ' · todos operan con normalidad'}
          {todosLosServicios.length > 0 && ` · servicios: ${operando} de ${todosLosServicios.length} operando`}
        </p>
      </div>
      {delCampus.length > 0 && (
        <p className="servicios-campus">
          Todo el campus:{' '}
          {delCampus.map((s) => (
            <span key={s.id} className={`chip-servicio tono-${tono(s.estado)}`}>
              <span aria-hidden="true">{ICONO_SERVICIO[s.tipo]}</span> {s.nombre} · {legible(s.estado, 'estado')}
            </span>
          ))}
        </p>
      )}
      {suyos.length === 0 && independientes.length === 0
        ? <p className="tenue">Este campus todavía no tiene edificios ni áreas registrados.</p>
        : (
          <ul className="calle">
            {suyos.map((e) => (
              <Fachada key={e.id} edificio={e} alEntrar={() => alIr({ tipo: 'edificio', id: e.id })}
                       areas={areas.filter((a) => a.edificio_id === e.id)}
                       servicios={servicios.filter((s) => s.edificio_id === e.id)} />
            ))}
            {independientes.map((a) => (
              <li key={a.id} className="lote">
                <button type="button" className={`terreno tono-${tono(a.estado)}`} onClick={() => alIr({ tipo: 'area', id: a.id })}
                        aria-label={`${a.nombre}, área al aire libre: ${legible(a.estado, 'estado')}. Entrar`}>
                  <strong>{a.nombre}</strong>
                  <span>{legible(a.tipo, 'tipo')} · {legible(a.estado, 'estado')}</span>
                </button>
                <span className="banqueta" />
              </li>
            ))}
          </ul>
        )}
    </section>
  )
}

// ---------------------------------------------------------- 2. un edificio
function Edificio({ edificio, usuario, alIr, directorio }) {
  const { areas, servicios } = useCatalogos()
  const suyas = areas.filter((a) => a.edificio_id === edificio.id)
  const niveles = Math.max(edificio.niveles || 1, 1)
  const pisos = Array.from({ length: niveles }, (_, i) => niveles - 1 - i)
  const sinPiso = suyas.filter((a) => a.piso === null || a.piso === undefined || a.piso >= niveles)

  return (
    <div className="contenido recorrido">
      <Directorio partes={directorio} />
      <div className="encabezado-lugar">
        <h1>{edificio.nombre}</h1>
        <span className={`estado-lugar tono-${tono(edificio.estado)}`}>{legible(edificio.estado, 'estado')}</span>
      </div>
      <p className="tenue">
        Clave {edificio.clave} · {niveles} {niveles === 1 ? 'nivel' : 'niveles'}
        {edificio.anio_construccion ? ` · construido en ${edificio.anio_construccion}` : ''}
        {edificio.superficie_m2 ? ` · ${edificio.superficie_m2} m²` : ''}
        {/^https?:\/\//i.test(edificio.carpeta_planos || '') && (
          <> · <a href={edificio.carpeta_planos} target="_blank" rel="noreferrer">Carpeta de planos</a></>
        )}
      </p>
      {/* La URL de la foto viene firmada en la lista de edificios y caduca en una hora */}
      {edificio.fachada_url && <FotoFachada url={edificio.fachada_url} />}

      <div className="corte" role="list" aria-label="Pisos del edificio">
        {pisos.map((piso) => {
          const delPiso = suyas.filter((a) => a.piso === piso)
          return (
            <div key={piso} className="piso" role="listitem">
              <span className="piso-nombre">{nombrePiso(piso)}</span>
              <div className="pasillo">
                {delPiso.length === 0
                  ? <span className="tenue">Sin áreas registradas en este piso</span>
                  : delPiso.map((a) => (
                    <button key={a.id} type="button" className={`salon tono-${tono(a.estado)}`}
                            onClick={() => alIr({ tipo: 'area', id: a.id })}>
                      <strong>{a.nombre}</strong>
                      <span>{legible(a.tipo, 'tipo')}{tono(a.estado) !== 'bien' ? ` · ${legible(a.estado, 'estado')}` : ''}</span>
                    </button>
                  ))}
              </div>
            </div>
          )
        })}
        {sinPiso.length > 0 && (
          <div className="piso" role="listitem">
            <span className="piso-nombre">Sin piso indicado</span>
            <div className="pasillo">
              {sinPiso.map((a) => (
                <button key={a.id} type="button" className={`salon tono-${tono(a.estado)}`} onClick={() => alIr({ tipo: 'area', id: a.id })}>
                  <strong>{a.nombre}</strong><span>{legible(a.tipo, 'tipo')}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <section className="seccion-detalle">
        <h4>Servicios del edificio</h4>
        <Medidores servicios={servicios.filter((s) => s.edificio_id === edificio.id)} usuario={usuario} />
      </section>
      {/* Fotos y planos: el Observador solo los ve; en la sección «Edificios» se suben */}
      <Adjuntos key={edificio.id} ruta={`/edificios/${edificio.id}/archivos`} titulo="Archivos del edificio"
                vacio="Este edificio todavía no tiene archivos." conCategoria={false} />
      <div className="tablero-avisos">
        <Comentarios recurso="EDIFICIO" id={edificio.id} usuario={usuario} titulo="Tablero de avisos del edificio" />
      </div>
    </div>
  )
}

// -------------------------------------------------------------- 3. un salón
function Salon({ area, usuario, directorio }) {
  const { servicios, nombreTipo } = useCatalogos()
  const [inventario, setInventario] = useState(null)
  const [error, setError] = useState('')
  const [tipoAbierto, setTipoAbierto] = useState(null)
  const [elementoAbierto, setElementoAbierto] = useState(null)

  useEffect(() => {
    let vigente = true
    setInventario(null)
    api('/inventario', { consulta: { area_id: area.id, limite: 1000 } })
      .then((datos) => vigente && setInventario(datos))
      .catch((e) => vigente && setError(e.message))
    return () => { vigente = false }
  }, [area.id])

  // Agrupa por tipo y suma la cantidad de piezas en cada estado
  const grupos = useMemo(() => {
    const mapa = new Map()
    for (const el of inventario || []) {
      const g = mapa.get(el.tipo) || { tipo: el.tipo, elementos: [], porEstado: {} }
      g.elementos.push(el)
      g.porEstado[el.estado] = (g.porEstado[el.estado] || 0) + (el.cantidad || 1)
      mapa.set(el.tipo, g)
    }
    return [...mapa.values()].sort((a, b) => nombreTipo(a.tipo).localeCompare(nombreTipo(b.tipo)))
  }, [inventario, nombreTipo])

  const grupo = grupos.find((g) => g.tipo === tipoAbierto)
  const datos = [
    legible(area.tipo, 'tipo'),
    area.edificio_id !== null ? nombrePiso(area.piso) : (area.exterior ? 'Al aire libre' : 'Área independiente'),
    area.superficie_m2 ? `${area.superficie_m2} m²` : null,
    area.capacidad ? `${area.capacidad} lugares` : null,
  ].filter(Boolean)

  return (
    <div className="contenido recorrido">
      <Directorio partes={directorio} />
      <div className="encabezado-lugar">
        <h1>{area.nombre}</h1>
        <span className={`estado-lugar tono-${tono(area.estado)}`}>{legible(area.estado, 'estado')}</span>
      </div>
      <p className="tenue">{datos.join(' · ')}</p>

      <div className="interior">
        <section aria-labelledby="lo-que-hay">
          <h2 id="lo-que-hay" className="subtitulo">Lo que hay aquí</h2>
          {error && <p className="aviso aviso-error">{error}</p>}
          {inventario === null && !error && <p className="tenue">Cargando inventario…</p>}
          {inventario && inventario.length === 0 && <p className="tenue">No hay inventario registrado en esta área.</p>}
          <ul className="objetos">
            {grupos.map((g) => (
              <li key={g.tipo}>
                <button type="button" className="objeto" aria-expanded={tipoAbierto === g.tipo}
                        onClick={() => { setTipoAbierto(tipoAbierto === g.tipo ? null : g.tipo); setElementoAbierto(null) }}>
                  <span className="objeto-icono" aria-hidden="true">{ICONO_ELEMENTO[g.tipo] || '📦'}</span>
                  <strong>{nombreTipo(g.tipo)}</strong>
                  <span className="objeto-estados">
                    {ORDEN_ESTADOS.filter((e) => g.porEstado[e]).map((e) => (
                      <span key={e} className={`texto-tono tono-${tono(e)}`}>{g.porEstado[e]} {legible(e, 'estado').toLowerCase()}</span>
                    ))}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {grupo && (
            <div className="detalle-objetos">
              <h3>{nombreTipo(grupo.tipo)}: cada registro</h3>
              <ul className="lista-servicios">
                {grupo.elementos.map((el) => (
                  <li key={el.id}>
                    <span>
                      {el.cantidad} {el.cantidad === 1 ? 'pieza' : 'piezas'}
                      {[el.marca, el.modelo, el.eje && `eje ${el.eje}`, el.descripcion].filter(Boolean).map((t) => ` · ${t}`)}
                    </span>
                    <span className="acciones-fila">
                      <span className={`texto-tono tono-${tono(el.estado)}`}>{legible(el.estado, 'estado')}</span>
                      <button type="button" className="boton-texto" aria-expanded={elementoAbierto === el.id}
                              onClick={() => setElementoAbierto(elementoAbierto === el.id ? null : el.id)}>Avisos</button>
                    </span>
                  </li>
                ))}
              </ul>
              {elementoAbierto && (
                <Comentarios key={elementoAbierto} recurso="INVENTARIO" id={elementoAbierto} usuario={usuario}
                             titulo="Avisos de este registro" />
              )}
            </div>
          )}

          <h2 className="subtitulo">Servicios del área</h2>
          <Medidores servicios={servicios.filter((s) => s.area_id === area.id)} usuario={usuario} />
          <Adjuntos key={area.id} ruta={`/areas/${area.id}/archivos`} titulo="Fotos y planos del área"
                    vacio="Esta área todavía no tiene fotos ni planos." />
        </section>

        <div className="tablero-avisos">
          <Comentarios recurso="AREA" id={area.id} usuario={usuario} titulo="Tablero de avisos" />
        </div>
      </div>
    </div>
  )
}

// --------------------------------------------------------------- la sección
export function Recorrido({ usuario, campusActivo }) {
  const catalogos = useCatalogos()
  const { campus, edificios, areas } = catalogos
  const [lugar, setLugar] = useState({ tipo: 'campus' })

  // Al cambiar de campus en la barra superior se vuelve a la calle
  useEffect(() => { setLugar({ tipo: 'campus' }) }, [campusActivo])

  const visibles = campusActivo ? campus.filter((c) => String(c.id) === String(campusActivo)) : campus
  const alCampus = (id) => ({ texto: catalogos.nombreCampus(id), ir: () => setLugar({ tipo: 'campus' }) })

  if (lugar.tipo === 'edificio') {
    const e = edificios.find((x) => x.id === lugar.id)
    if (e) {
      return <Edificio edificio={e} usuario={usuario} alIr={setLugar}
                       directorio={[alCampus(e.campus_id), { texto: e.nombre }]} />
    }
  }
  if (lugar.tipo === 'area') {
    const a = areas.find((x) => x.id === lugar.id)
    if (a) {
      const e = edificios.find((x) => x.id === a.edificio_id)
      const partes = [alCampus(a.campus_id)]
      if (e) {
        partes.push({ texto: e.nombre, ir: () => setLugar({ tipo: 'edificio', id: e.id }) })
        partes.push({ texto: nombrePiso(a.piso), ir: () => setLugar({ tipo: 'edificio', id: e.id }) })
      }
      partes.push({ texto: a.nombre })
      return <Salon key={a.id} area={a} usuario={usuario} directorio={partes} />
    }
  }

  return (
    <div className="contenido recorrido">
      <h1>Recorrido</h1>
      <p className="tenue">
        Cada edificio tiene la altura de sus niveles y cada ventana es un área, con el color de su estado.
        Toca un edificio o un terreno para entrar.
      </p>
      <ul className="leyenda" aria-label="Colores">
        <li><span className="muestra tono-bien" /> Operativo / bueno</li>
        <li><span className="muestra tono-medio" /> En mantenimiento / regular</li>
        <li><span className="muestra tono-mal" /> Fuera de servicio / malo</li>
      </ul>
      {campus.length === 0 && <p className="tenue">Cargando el campus…</p>}
      {visibles.map((c) => <Campus key={c.id} campus={c} alIr={setLugar} />)}
    </div>
  )
}
