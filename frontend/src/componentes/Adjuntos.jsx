// Archivos adjuntos de un recurso (fotos, planos, PDF) o evidencias de una orden.
// Los enlaces vienen firmados y caducan (1 h): se piden de nuevo cada vez que se abre el panel.
import { useCallback, useEffect, useState } from 'react'
import { api, apiFormulario } from '../api'
import { formatoFecha } from './Historial'

const TIPOS = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf']
const MAXIMO_MB = 10
const CATEGORIAS = [['FOTO', 'Foto'], ['PLANO', 'Plano'], ['DOCUMENTO', 'Documento'], ['EVIDENCIA', 'Evidencia'], ['OTRO', 'Otro']]
const NOMBRE_CATEGORIA = Object.fromEntries(CATEGORIAS)

function tamano(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// Nombre sugerido: el del archivo sin la extensión
const sinExtension = (nombre) => nombre.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim().slice(0, 120)

function Subir({ ruta, categoriaInicial, categorias, conCategoria, alSubir, alCancelar }) {
  const [archivo, setArchivo] = useState(null)
  const [nombre, setNombre] = useState('')
  const [categoria, setCategoria] = useState(categoriaInicial)
  const [descripcion, setDescripcion] = useState('')
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)

  function elegir(e) {
    const f = e.target.files?.[0] || null
    setError('')
    // Se revisa aquí para avisar rápido; el servidor revisa de nuevo el contenido real
    if (f && !TIPOS.includes(f.type)) setError('Solo se aceptan archivos JPG, PNG, WebP o PDF.')
    else if (f && f.size > MAXIMO_MB * 1024 * 1024) setError(`El archivo pesa más de ${MAXIMO_MB} MB; redúcelo e intenta de nuevo.`)
    setArchivo(f)
    if (f && !nombre) setNombre(sinExtension(f.name))
  }

  async function enviar(e) {
    e.preventDefault()
    if (!archivo || error) return
    setEnviando(true)
    const datos = new FormData()
    datos.append('archivo', archivo)
    datos.append('nombre', nombre.trim())
    datos.append('categoria', categoria)
    if (descripcion.trim()) datos.append('descripcion', descripcion.trim())
    try {
      await apiFormulario(ruta, datos)
      alSubir()
    } catch (err) {
      setError(err.message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <form className="formulario subir-adjunto" onSubmit={enviar}>
      <div className="campo">
        <label htmlFor="adj-archivo">Archivo (JPG, PNG, WebP o PDF, hasta {MAXIMO_MB} MB)</label>
        <input id="adj-archivo" type="file" accept={TIPOS.join(',')} required onChange={elegir} />
      </div>
      <div className="campo">
        <label htmlFor="adj-nombre">Nombre</label>
        <input id="adj-nombre" required maxLength={120} value={nombre} onChange={(e) => setNombre(e.target.value)}
               placeholder="Plano de planta baja" />
      </div>
      {conCategoria && (
        <div className="campo">
          <label htmlFor="adj-categoria">Tipo</label>
          <select id="adj-categoria" value={categoria} onChange={(e) => setCategoria(e.target.value)}>
            {categorias.map((c) => <option key={c} value={c}>{NOMBRE_CATEGORIA[c]}</option>)}
          </select>
        </div>
      )}
      <div className="campo">
        <label htmlFor="adj-descripcion">Descripción (opcional)</label>
        <input id="adj-descripcion" maxLength={500} value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
      </div>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      <div className="acciones">
        <button type="submit" className="boton-principal" disabled={!archivo || Boolean(error) || enviando}>
          {enviando ? 'Subiendo…' : 'Subir archivo'}
        </button>
        <button type="button" className="boton-secundario" onClick={alCancelar}>Cancelar</button>
      </div>
    </form>
  )
}

function Quitar({ alConfirmar, alCancelar }) {
  const [motivo, setMotivo] = useState('')
  return (
    <form className="quitar-adjunto" onSubmit={(e) => { e.preventDefault(); alConfirmar(motivo.trim()) }}>
      <label className="sr-only" htmlFor="adj-motivo">Motivo</label>
      <input id="adj-motivo" required minLength={5} maxLength={500} placeholder="Motivo (mínimo 5 caracteres)"
             value={motivo} onChange={(e) => setMotivo(e.target.value)} />
      <button type="submit" className="boton-secundario" disabled={motivo.trim().length < 5}>Quitar</button>
      <button type="button" className="boton-texto" onClick={alCancelar}>Cancelar</button>
    </form>
  )
}

export function Adjuntos({
  ruta,                       // p. ej. '/edificios/7/archivos' o '/mantenimientos/ordenes/3/evidencias'
  puedeEditar = false,
  titulo = 'Fotos y documentos',
  categoriaInicial = 'DOCUMENTO',
  categorias = ['FOTO', 'PLANO', 'DOCUMENTO', 'OTRO'],
  vacio = 'Todavía no hay archivos.',
  conCategoria = true,        // los archivos de un edificio solo llevan nombre y descripción (como en develop)
}) {
  const [archivos, setArchivos] = useState(null)   // null = cargando
  const [error, setError] = useState('')
  const [subiendo, setSubiendo] = useState(false)
  const [quitando, setQuitando] = useState(null)

  const cargar = useCallback(() => {
    api(ruta).then((datos) => { setArchivos(datos); setError('') }).catch((e) => setError(e.message))
  }, [ruta])
  useEffect(() => { cargar() }, [cargar])

  async function quitar(id, motivo) {
    try {
      await api(`${ruta}/${id}`, { metodo: 'DELETE', cuerpo: { motivo } })
      setQuitando(null)
      cargar()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <section className="seccion-detalle">
      <h4>{titulo}{archivos ? ` (${archivos.length})` : ''}</h4>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      {archivos === null && !error && <p className="tenue">Cargando archivos…</p>}
      {archivos?.length === 0 && <p className="tenue">{vacio}</p>}
      <ul className="adjuntos">
        {(archivos || []).map((a) => {
          const esImagen = a.tipo_mime.startsWith('image/')
          return (
            <li key={a.id}>
              <a className="adjunto-vista" href={a.url || undefined} target="_blank" rel="noreferrer"
                 aria-label={`Abrir ${a.nombre} en otra pestaña`}>
                {esImagen && a.url
                  ? <img src={a.url} alt="" loading="lazy" />
                  : <span className="adjunto-icono" aria-hidden="true">{esImagen ? 'IMG' : 'PDF'}</span>}
              </a>
              <div className="adjunto-datos">
                <strong>{a.nombre}</strong>
                <span className="tenue">
                  {conCategoria ? `${NOMBRE_CATEGORIA[a.categoria] || a.categoria} · ` : ''}{tamano(a.tamano_bytes)}
                  {a.creado_por_nombre ? ` · ${a.creado_por_nombre}` : ''} · {formatoFecha(a.creado_en)}
                </span>
                {a.descripcion && <span>{a.descripcion}</span>}
                {!a.url && <span className="tenue">El almacén de archivos no respondió; intenta más tarde.</span>}
                {puedeEditar && (quitando === a.id
                  ? <Quitar alConfirmar={(motivo) => quitar(a.id, motivo)} alCancelar={() => setQuitando(null)} />
                  : <button type="button" className="boton-texto" onClick={() => setQuitando(a.id)}>Quitar</button>)}
              </div>
            </li>
          )
        })}
      </ul>
      {puedeEditar && (subiendo
        ? <Subir ruta={ruta} categoriaInicial={categoriaInicial} categorias={categorias} conCategoria={conCategoria}
                 alSubir={() => { setSubiendo(false); cargar() }} alCancelar={() => setSubiendo(false)} />
        : <div className="acciones"><button type="button" className="boton-secundario" onClick={() => setSubiendo(true)}>Adjuntar archivo</button></div>)}
    </section>
  )
}

// Foto de fachada del edificio: una sola imagen; subir otra reemplaza a la anterior
export function FotoFachada({ url, puedeEditar = false, alSubir }) {
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)

  async function elegir(e) {
    const f = e.target.files?.[0]
    e.target.value = ''   // permite volver a elegir el mismo archivo
    if (!f) return
    setError('')
    if (!TIPOS.slice(0, 3).includes(f.type)) return setError('La fachada debe ser una imagen JPG, PNG o WebP.')
    if (f.size > MAXIMO_MB * 1024 * 1024) return setError(`La imagen pesa más de ${MAXIMO_MB} MB; redúcela e intenta de nuevo.`)
    const datos = new FormData()
    datos.append('archivo', f)
    setEnviando(true)
    try {
      await alSubir(datos)
    } catch (err) {
      setError(err.message)
    } finally {
      setEnviando(false)
    }
  }

  if (!url && !puedeEditar) return null
  return (
    <figure className="fachada-foto">
      {url ? <img src={url} alt="Foto de fachada del edificio" /> : <div className="fachada-vacia">Sin foto de fachada</div>}
      {puedeEditar && (
        <figcaption>
          <label className="boton-secundario boton-archivo">
            {enviando ? 'Subiendo…' : url ? 'Cambiar foto de fachada' : 'Agregar foto de fachada'}
            <input type="file" accept={TIPOS.slice(0, 3).join(',')} onChange={elegir} disabled={enviando} className="sr-only" />
          </label>
          {error && <p className="aviso aviso-error" role="alert">{error}</p>}
        </figcaption>
      )}
    </figure>
  )
}
