// Formulario genérico de alta y edición a partir de la descripción del recurso
import { useState } from 'react'
import { useCatalogos } from '../catalogos'
import { ESTADOS_POR_RECURSO, legible } from '../recursos'
import { EditorDefiniciones, definicionesAApi, definicionesAControl } from './EditorDefiniciones'

// Valor del registro -> texto del control
function aControl(campo, registro, campusActivo) {
  if (campo.tipo === 'destino') {
    if (registro?.campus_id) return `c:${registro.campus_id}`
    if (registro?.edificio_id) return `e:${registro.edificio_id}`
    if (registro?.area_id) return `a:${registro.area_id}`
    return ''
  }
  if (campo.tipo === 'campus' && !registro) return campusActivo || ''
  if (campo.tipo === 'definiciones') return definicionesAControl(registro?.[campo.nombre])
  if (campo.tipo === 'estados') return [...(registro?.[campo.nombre] || [])]
  const valor = registro ? registro[campo.nombre] : campo.inicial
  if (campo.tipo === 'casilla') return Boolean(valor ?? campo.inicial ?? false)
  if (campo.tipo === 'mes') return valor ? String(valor).slice(0, 7) : ''
  return valor === null || valor === undefined ? '' : String(valor)
}

// Texto del control -> valor(es) que espera la API
function aApi(campo, texto) {
  switch (campo.tipo) {
    case 'casilla': return { [campo.nombre]: Boolean(texto) }
    case 'numero': return { [campo.nombre]: texto === '' ? null : Number(texto) }
    case 'piso':
    case 'campus':
    case 'edificio':
    case 'area':
    case 'servicio': return { [campo.nombre]: texto === '' ? null : Number(texto) }
    case 'mes': return { [campo.nombre]: texto ? `${texto}-01` : null }
    case 'fecha': return { [campo.nombre]: texto || null }
    case 'definiciones': return { [campo.nombre]: definicionesAApi(texto) }
    case 'estados': return { [campo.nombre]: texto }
    case 'destino': {
      const [tipo, id] = texto.split(':')
      return {
        campus_id: tipo === 'c' ? Number(id) : null,
        edificio_id: tipo === 'e' ? Number(id) : null,
        area_id: tipo === 'a' ? Number(id) : null,
      }
    }
    default: return { [campo.nombre]: texto === '' ? null : texto.trim() }
  }
}

// Propiedades del elemento -> texto de cada control (los números y sí/no se editan como texto)
function propiedadesAControl(propiedades = {}) {
  return Object.fromEntries(Object.entries(propiedades).map(([k, v]) => [k, typeof v === 'boolean' || typeof v === 'number' ? String(v) : v]))
}

// Texto de un control -> valor JSON según la clase de dato de la propiedad
export function propiedadAApi(definicion, texto) {
  if (definicion.tipo === 'numero') return Number(texto)
  if (definicion.tipo === 'si_no') return texto === 'true'
  return texto.trim()
}

// Compara valores de cualquier forma (texto, lista, objeto) para saber si un campo cambió
const igual = (a, b) => JSON.stringify(a) === JSON.stringify(b)

export function Formulario({ config, registro, alGuardar, alCancelar, campusActivo = '' }) {
  const catalogos = useCatalogos()
  const editando = Boolean(registro)
  const [valores, setValores] = useState(() =>
    Object.fromEntries(config.campos.map((c) => [c.nombre, aControl(c, registro, campusActivo)])))
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)
  // Propiedades del tipo de elemento (solo inventario)
  const [propiedades, setPropiedades] = useState(() => propiedadesAControl(registro?.propiedades))

  // Tipo de elemento elegido: define qué propiedades se piden y si se muestran las medidas
  const tipoElegido = config.propiedadesPorTipo ? catalogos.tipoElemento(valores.tipo) : null
  const definiciones = tipoElegido?.propiedades_definidas || []
  const sinMedidas = Boolean(tipoElegido && !tipoElegido.usa_medidas)
  const visible = (campo) => !(campo.medida && sinMedidas)

  // Campus que limita las opciones: el del propio formulario o el elegido en el menú
  const campusFiltro = String(valores.campus_id ?? campusActivo ?? '')
  const enCampus = (campusId) => !campusFiltro || String(campusId) === campusFiltro
  const edificios = catalogos.edificios.filter((e) => enCampus(e.campus_id))
  const areas = catalogos.areas.filter((a) => enCampus(a.campus_id))
  const servicios = catalogos.servicios.filter((x) => enCampus(catalogos.campusDeServicio(x)))
  const listaCampus = catalogos.campus

  // Pisos que existen en un edificio: de 0 (planta baja) a niveles - 1
  function pisosDe(edificioId) {
    const edificio = catalogos.edificios.find((e) => String(e.id) === String(edificioId))
    return edificio?.niveles ? Array.from({ length: edificio.niveles }, (_, i) => i) : []
  }
  const limite = (l) => (typeof l === 'function' ? l() : l)

  const cambiar = (nombre, valor) => setValores((v) => {
    const nuevo = { ...v, [nombre]: valor }
    // Si cambia el campus, el edificio elegido debe pertenecer a él
    if (nombre === 'campus_id' && 'edificio_id' in v && v.edificio_id) {
      const edificio = catalogos.edificios.find((e) => String(e.id) === String(v.edificio_id))
      if (!edificio || String(edificio.campus_id) !== String(valor)) nuevo.edificio_id = ''
    }
    // Si cambia el edificio, el piso elegido debe existir en el nuevo edificio
    if ('piso' in v && nuevo.piso !== '' && !pisosDe(nuevo.edificio_id).includes(Number(nuevo.piso))) {
      nuevo.piso = ''
    }
    return nuevo
  })

  async function enviar(e) {
    e.preventDefault()
    setError('')
    let datos = {}
    for (const campo of config.campos) {
      if (editando && campo.soloAlCrear) continue
      if (!visible(campo)) continue
      const original = aControl(campo, registro, campusActivo)
      if (editando && igual(valores[campo.nombre], original)) continue   // solo lo que cambió
      datos = { ...datos, ...aApi(campo, valores[campo.nombre]) }
    }
    if (config.propiedadesPorTipo) {
      // Se conservan las propiedades extra que no define el tipo; las vacías se quitan
      const nuevas = { ...(registro?.propiedades || {}) }
      for (const d of definiciones) {
        const texto = propiedades[d.clave] ?? ''
        if (texto === '') delete nuevas[d.clave]
        else nuevas[d.clave] = propiedadAApi(d, texto)
      }
      if (!igual(nuevas, registro?.propiedades || {})) datos.propiedades = nuevas
    }
    if (editando && Object.keys(datos).length === 0) {
      alCancelar()
      return
    }
    setEnviando(true)
    try {
      await alGuardar(datos)
    } catch (err) {
      setError(err.message)
    } finally {
      setEnviando(false)
    }
  }

  function control(campo) {
    const comun = {
      id: `campo-${campo.nombre}`,
      value: valores[campo.nombre],
      onChange: (e) => cambiar(campo.nombre, e.target.value),
      required: campo.requerido,
      disabled: editando && campo.soloAlCrear,
    }
    switch (campo.tipo) {
      case 'numero':
        return <input type="number" step={campo.paso || '1'} min={limite(campo.minimo)} max={limite(campo.maximo)} {...comun} />
      case 'parrafo':
        return <textarea rows={3} {...comun} />
      case 'mes':
        return <input type="month" {...comun} />
      case 'fecha':
        return <input type="date" max={limite(campo.maximo)} {...comun} />
      case 'casilla':
        return (
          <input type="checkbox" id={comun.id} checked={valores[campo.nombre]}
                 onChange={(e) => cambiar(campo.nombre, e.target.checked)} />
        )
      case 'opciones':
        return (
          <select {...comun}>
            {campo.opciones.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select>
        )
      case 'tipoElemento': {
        const tipos = catalogos.tiposElemento
        return (
          <select {...comun}>
            <option value="">Elige un tipo</option>
            {tipos.map((t) => <option key={t.clave} value={t.clave}>{t.nombre}</option>)}
            {/* Un registro anterior con un tipo que ya no está en el catálogo se muestra para poder cambiarlo */}
            {valores.tipo && !tipos.some((t) => t.clave === valores.tipo) && (
              <option value={valores.tipo}>{valores.tipo} (no está en el catálogo)</option>
            )}
          </select>
        )
      }
      case 'estado': {
        // Estados del tipo de recurso elegido en el mismo formulario (campo «recurso»)
        const estados = ESTADOS_POR_RECURSO[valores.recurso] || []
        return (
          <select {...comun}>
            <option value="">{campo.vacio || 'Elige un estado'}</option>
            {estados.map((e) => <option key={e} value={e}>{legible(e)}</option>)}
          </select>
        )
      }
      case 'estados': {
        const estados = ESTADOS_POR_RECURSO[valores.recurso] || []
        const elegidos = valores[campo.nombre] || []
        return (
          <div className="casillas" id={comun.id} role="group">
            {estados.map((e) => (
              <label key={e} className="casilla-en-linea">
                <input type="checkbox" checked={elegidos.includes(e)} disabled={comun.disabled}
                       onChange={(ev) => cambiar(campo.nombre, ev.target.checked ? [...elegidos, e] : elegidos.filter((x) => x !== e))} />
                {legible(e)}
              </label>
            ))}
          </div>
        )
      }
      case 'definiciones':
        return <EditorDefiniciones id={comun.id} valor={valores[campo.nombre]} alCambiar={(v) => cambiar(campo.nombre, v)} />
      case 'sugerencias':
        return (
          <>
            <input list={`lista-${campo.nombre}`} {...comun}
                   onChange={(e) => cambiar(campo.nombre, e.target.value.toUpperCase().replace(/\s+/g, '_'))} />
            <datalist id={`lista-${campo.nombre}`}>
              {campo.sugerencias.map((s) => <option key={s} value={s} />)}
            </datalist>
          </>
        )
      case 'campus':
        return (
          <select {...comun}>
            <option value="">Elige un campus</option>
            {listaCampus.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
          </select>
        )
      case 'edificio':
        return (
          <select {...comun}>
            <option value="">Sin edificio (área independiente)</option>
            {edificios.map((e) => <option key={e.id} value={e.id}>{e.nombre} ({e.clave})</option>)}
          </select>
        )
      case 'piso': {
        const edificio = catalogos.edificios.find((e) => String(e.id) === String(valores.edificio_id))
        const pisos = pisosDe(valores.edificio_id)
        const actual = valores.piso
        return (
          <>
            <select {...comun} disabled={!edificio || pisos.length === 0}>
              <option value="">{edificio ? 'Sin especificar' : 'Sin piso (área independiente)'}</option>
              {pisos.map((p) => <option key={p} value={p}>{p === 0 ? 'Planta baja (0)' : `Piso ${p}`}</option>)}
              {/* Un registro anterior con un piso que ya no existe se muestra para poder corregirlo */}
              {actual !== '' && !pisos.includes(Number(actual)) && (
                <option value={actual}>Piso {actual} (no existe en el edificio)</option>
              )}
            </select>
            {edificio && pisos.length === 0 && (
              <small className="texto-alerta">Este edificio no tiene registrado su número de niveles; regístralo para asignar un piso.</small>
            )}
          </>
        )
      }
      case 'area':
        return (
          <select {...comun}>
            <option value="">Elige un área</option>
            {areas.map((a) => <option key={a.id} value={a.id}>{a.nombre}</option>)}
          </select>
        )
      case 'servicio':
        return (
          <select {...comun}>
            <option value="">Elige un servicio</option>
            {servicios.map((s) => <option key={s.id} value={s.id}>{s.nombre}</option>)}
          </select>
        )
      case 'destino':
        return (
          <select {...comun}>
            <option value="">Elige un campus, edificio o área</option>
            <optgroup label="Campus completo">
              {catalogos.campus.filter((c) => enCampus(c.id)).map((c) => <option key={`c${c.id}`} value={`c:${c.id}`}>{c.nombre}</option>)}
            </optgroup>
            <optgroup label="Edificios">
              {edificios.map((e) => <option key={`e${e.id}`} value={`e:${e.id}`}>{e.nombre}</option>)}
            </optgroup>
            <optgroup label="Áreas">
              {areas.map((a) => <option key={`a${a.id}`} value={`a:${a.id}`}>{a.nombre}</option>)}
            </optgroup>
          </select>
        )
      default:
        return <input type="text" {...comun} />
    }
  }

  return (
    <form className="formulario" onSubmit={enviar}>
      <h3>{editando ? `Editar ${config.singular}` : `Nuevo ${config.singular}`}</h3>
      {config.campos.filter(visible).map((campo) => (
        <div key={campo.nombre} className={campo.tipo === 'casilla' ? 'campo campo-casilla' : 'campo'}>
          <label htmlFor={`campo-${campo.nombre}`}>
            {campo.etiqueta}{campo.requerido && <span className="requerido" aria-hidden="true"> *</span>}
          </label>
          {control(campo)}
          {campo.ayuda && <small>{campo.ayuda}</small>}
          {campo.tipo === 'tipoElemento' && tipoElegido && (
            <CamposDelTipo tipo={tipoElegido} definiciones={definiciones} valores={propiedades}
                           alCambiar={(clave, valor) => setPropiedades((p) => ({ ...p, [clave]: valor }))} />
          )}
        </div>
      ))}
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      <div className="acciones">
        <button type="submit" className="boton-principal" disabled={enviando}>
          {enviando ? 'Guardando…' : editando ? 'Guardar cambios' : `Crear ${config.singular}`}
        </button>
        <button type="button" className="boton-secundario" onClick={alCancelar}>Cancelar</button>
      </div>
    </form>
  )
}

// Controles de una lista de propiedades definidas: las de un tipo de elemento o
// la lista de verificación de un mantenimiento (mismo formato)
export function CamposDelTipo({ tipo, definiciones, valores, alCambiar, titulo }) {
  const hoy = new Date().toLocaleDateString('en-CA')
  return (
    <fieldset className="campos-del-tipo">
      <legend>{titulo || `Propiedades de ${tipo.nombre.toLowerCase()}`}</legend>
      {definiciones.length === 0 && <p className="tenue">Este tipo no define propiedades.</p>}
      {definiciones.map((d) => {
        const id = `propiedad-${d.clave}`
        const comun = { id, value: valores[d.clave] ?? '', required: d.requerida, onChange: (e) => alCambiar(d.clave, e.target.value) }
        let control
        if (d.tipo === 'numero') {
          control = <input type="number" step="any" min={d.minimo ?? undefined} max={d.maximo ?? undefined} {...comun} />
        } else if (d.tipo === 'opcion') {
          control = (
            <select {...comun}>
              <option value="">Sin especificar</option>
              {d.opciones.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          )
        } else if (d.tipo === 'si_no') {
          control = (
            <select {...comun}>
              <option value="">Sin especificar</option>
              <option value="true">Sí</option>
              <option value="false">No</option>
            </select>
          )
        } else if (d.tipo === 'fecha') {
          control = <input type="date" max={hoy} {...comun} />
        } else {
          control = <input type="text" maxLength={500} {...comun} />
        }
        return (
          <div className="campo" key={d.clave}>
            <label htmlFor={id}>
              {d.etiqueta}{d.unidad ? ` (${d.unidad})` : ''}
              {d.requerida && <span className="requerido" aria-hidden="true"> *</span>}
            </label>
            {control}
          </div>
        )
      })}
    </fieldset>
  )
}
