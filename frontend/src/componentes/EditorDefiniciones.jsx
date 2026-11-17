// Editor de las propiedades que define un tipo de elemento (solo Administrador).
// Cada renglón es una propiedad: etiqueta, clave interna, clase de dato y sus límites u opciones.
export const CLASES_PROPIEDAD = [
  ['texto', 'Texto'], ['numero', 'Número'], ['opcion', 'Lista de opciones'], ['fecha', 'Fecha'], ['si_no', 'Sí o no'],
]

// "Capacidad (BTU)" -> "capacidad_btu": la clave interna sale de la etiqueta
export function claveDesdeEtiqueta(etiqueta) {
  return etiqueta.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^[0-9_]+/, '').slice(0, 50)
}

const nueva = () => ({ clave: '', etiqueta: '', tipo: 'texto', unidad: '', minimo: '', maximo: '', opciones: [], requerida: false, nueva: true })

// Del formato de la API al del editor (los números se editan como texto)
export function definicionesAControl(definiciones = []) {
  return definiciones.map((d) => ({
    ...d,
    unidad: d.unidad ?? '',
    minimo: d.minimo ?? '',
    maximo: d.maximo ?? '',
    opciones: d.opciones ?? [],
    requerida: Boolean(d.requerida),
  }))
}

// Del editor al formato de la API
export function definicionesAApi(filas = []) {
  return filas.map((d) => ({
    clave: d.clave.trim(),
    etiqueta: d.etiqueta.trim(),
    tipo: d.tipo,
    unidad: d.tipo === 'numero' && d.unidad.trim() ? d.unidad.trim() : null,
    minimo: d.tipo === 'numero' && d.minimo !== '' ? Number(d.minimo) : null,
    maximo: d.tipo === 'numero' && d.maximo !== '' ? Number(d.maximo) : null,
    opciones: d.tipo === 'opcion' ? d.opciones.map((o) => o.trim()).filter(Boolean) : null,
    requerida: d.requerida,
  }))
}

// Texto corto para la tabla y el detalle: "Capacidad (BTU) *, Refrigerante"
export function resumenDefiniciones(definiciones = []) {
  if (!definiciones.length) return 'Ninguna'
  return definiciones.map((d) => `${d.etiqueta}${d.unidad ? ` (${d.unidad})` : ''}${d.requerida ? ' *' : ''}`).join(', ')
}

export function EditorDefiniciones({ id, valor, alCambiar }) {
  const filas = valor || []
  const cambiar = (i, cambios) => alCambiar(filas.map((f, j) => (j === i ? { ...f, ...cambios } : f)))
  const mover = (i, paso) => {
    const otra = i + paso
    if (otra < 0 || otra >= filas.length) return
    const copia = [...filas]
    ;[copia[i], copia[otra]] = [copia[otra], copia[i]]
    alCambiar(copia)
  }

  return (
    <div className="editor-definiciones" id={id}>
      {filas.length === 0 && <p className="tenue">Este tipo todavía no tiene propiedades.</p>}
      {filas.map((f, i) => (
        <fieldset key={i} className="definicion">
          <legend>Propiedad {i + 1}{f.etiqueta ? `: ${f.etiqueta}` : ''}</legend>
          <div className="definicion-campos">
            <label>Etiqueta
              <input required maxLength={80} value={f.etiqueta}
                     onChange={(e) => cambiar(i, {
                       etiqueta: e.target.value,
                       // Mientras la propiedad es nueva, la clave se arma sola a partir de la etiqueta
                       ...(f.nueva ? { clave: claveDesdeEtiqueta(e.target.value) } : {}),
                     })} />
            </label>
            <label>Clave interna
              <input required pattern="[a-z][a-z0-9_]{0,49}" value={f.clave} disabled={!f.nueva}
                     title="Minúsculas, números y guion bajo; empieza con letra"
                     onChange={(e) => cambiar(i, { clave: e.target.value })} />
            </label>
            <label>Clase de dato
              <select value={f.tipo} onChange={(e) => cambiar(i, { tipo: e.target.value })}>
                {CLASES_PROPIEDAD.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
              </select>
            </label>
            {f.tipo === 'numero' && (
              <>
                <label>Unidad<input maxLength={20} placeholder="BTU, W, lm…" value={f.unidad}
                                    onChange={(e) => cambiar(i, { unidad: e.target.value })} /></label>
                <label>Mínimo<input type="number" step="any" value={f.minimo}
                                    onChange={(e) => cambiar(i, { minimo: e.target.value })} /></label>
                <label>Máximo<input type="number" step="any" value={f.maximo}
                                    onChange={(e) => cambiar(i, { maximo: e.target.value })} /></label>
              </>
            )}
            {f.tipo === 'opcion' && (
              <label className="definicion-ancha">Opciones, separadas por comas
                <input required value={f.opciones.join(', ')} placeholder="Minisplit, Ventana, Central"
                       onChange={(e) => cambiar(i, { opciones: e.target.value.split(',').map((o) => o.trimStart()) })} />
              </label>
            )}
          </div>
          <div className="definicion-pie">
            <label className="casilla-en-linea">
              <input type="checkbox" checked={f.requerida} onChange={(e) => cambiar(i, { requerida: e.target.checked })} />
              Obligatoria
            </label>
            <span className="acciones-definicion">
              <button type="button" className="boton-texto" onClick={() => mover(i, -1)} disabled={i === 0}
                      aria-label={`Subir ${f.etiqueta || 'la propiedad'}`}>Subir</button>
              <button type="button" className="boton-texto" onClick={() => mover(i, 1)} disabled={i === filas.length - 1}
                      aria-label={`Bajar ${f.etiqueta || 'la propiedad'}`}>Bajar</button>
              <button type="button" className="boton-texto" onClick={() => alCambiar(filas.filter((_, j) => j !== i))}
                      aria-label={`Quitar ${f.etiqueta || 'la propiedad'}`}>Quitar</button>
            </span>
          </div>
        </fieldset>
      ))}
      <button type="button" className="boton-secundario" onClick={() => alCambiar([...filas, nueva()])}>
        Agregar propiedad
      </button>
      <small>Clases: {CLASES_PROPIEDAD.map(([, t]) => t.toLowerCase()).join(', ')}. Las obligatorias se piden al capturar cada elemento.</small>
    </div>
  )
}
