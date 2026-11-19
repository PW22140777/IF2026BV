// Comentarios de un recurso, en el panel de detalle.
// El Observador abre comentarios; el Observador, el Técnico y el Administrador responden;
// solo el Administrador oculta (con motivo, queda en el historial). Consulta solo lee.
// El Observador puede adjuntar hasta 4 fotos a cada comentario o respuesta.
import { useCallback, useEffect, useId, useState } from 'react'
import { api, apiFormulario } from '../api'

const MAXIMO_FOTOS = 4
const TIPOS_FOTO = ['image/jpeg', 'image/png', 'image/webp']
const MAXIMO_MB = 10

// Fotos elegidas antes de enviar: miniatura local (sin subir nada todavía) y botón para quitarla
function FotosElegidas({ fotos, alQuitar }) {
  const [vistas, setVistas] = useState([])
  useEffect(() => {
    const urls = fotos.map((f) => URL.createObjectURL(f))
    setVistas(urls)
    return () => urls.forEach((u) => URL.revokeObjectURL(u))   // libera la memoria del navegador
  }, [fotos])
  if (!fotos.length) return null
  return (
    <ul className="fotos-comentario elegidas">
      {fotos.map((f, i) => (
        <li key={`${f.name}-${i}`}>
          {vistas[i] && <img src={vistas[i]} alt={`Foto ${i + 1}: ${f.name}`} />}
          <button type="button" className="quitar-foto" onClick={() => alQuitar(i)} aria-label={`Quitar ${f.name}`}>×</button>
        </li>
      ))}
    </ul>
  )
}

const NOMBRES_ROL = { ADMINISTRADOR: 'Administrador', TECNICO: 'Técnico', CONSULTA: 'Consulta', OBSERVADOR: 'Observador' }
const fecha = (iso) => new Date(iso).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' })

function Escribir({ etiqueta, boton, alEnviar, alCancelar, conFotos = false }) {
  const [texto, setTexto] = useState('')
  const [fotos, setFotos] = useState([])
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState('')
  const idCampo = useId()
  const idFotos = useId()

  function agregarFotos(e) {
    const nuevas = [...(e.target.files || [])]
    e.target.value = ''   // permite elegir otra vez el mismo archivo
    setError('')
    const malas = nuevas.filter((f) => !TIPOS_FOTO.includes(f.type))
    const pesadas = nuevas.filter((f) => f.size > MAXIMO_MB * 1024 * 1024)
    if (malas.length) return setError('Solo se aceptan fotos JPG, PNG o WebP.')
    if (pesadas.length) return setError(`Cada foto debe pesar ${MAXIMO_MB} MB o menos.`)
    if (fotos.length + nuevas.length > MAXIMO_FOTOS) {
      setError(`Puedes adjuntar hasta ${MAXIMO_FOTOS} fotos por comentario.`)
    }
    setFotos([...fotos, ...nuevas].slice(0, MAXIMO_FOTOS))
  }

  async function enviar(e) {
    e.preventDefault()
    setEnviando(true)
    setError('')
    try {
      await alEnviar(texto.trim(), fotos)
      setTexto('')
      setFotos([])
    } catch (err) {
      setError(err.message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <form className="escribir-comentario" onSubmit={enviar}>
      <label className="sr-only" htmlFor={idCampo}>{etiqueta}</label>
      <textarea id={idCampo} rows={3} maxLength={2000} required placeholder={etiqueta}
                value={texto} onChange={(e) => setTexto(e.target.value)} />
      {conFotos && (
        <>
          <FotosElegidas fotos={fotos} alQuitar={(i) => setFotos(fotos.filter((_, j) => j !== i))} />
          {fotos.length < MAXIMO_FOTOS && (
            <label className="boton-texto boton-archivo" htmlFor={idFotos}>
              Adjuntar fotos ({fotos.length} de {MAXIMO_FOTOS})
              <input id={idFotos} type="file" accept={TIPOS_FOTO.join(',')} multiple className="sr-only" onChange={agregarFotos} />
            </label>
          )}
        </>
      )}
      <div className="acciones">
        <button type="submit" className="boton-secundario" disabled={enviando || !texto.trim()}>
          {enviando ? 'Enviando…' : boton}
        </button>
        {alCancelar && <button type="button" className="boton-texto" onClick={alCancelar}>Cancelar</button>}
        <small className="tenue">{texto.length} / 2000</small>
      </div>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
    </form>
  )
}

function Comentario({ c, puedeOcultar, alOcultar }) {
  const [ocultando, setOcultando] = useState(false)
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  async function ocultar(e) {
    e.preventDefault()
    try {
      await alOcultar(c.id, motivo)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <article className="comentario">
      <header>
        <strong>{c.autor_nombre}</strong>
        <span className={`rol rol-${c.autor_rol.toLowerCase()}`}>{NOMBRES_ROL[c.autor_rol] || c.autor_rol}</span>
        <time dateTime={c.creado_en}>{fecha(c.creado_en)}</time>
      </header>
      <p className="comentario-texto">{c.texto}</p>
      {c.fotos?.length > 0 && (
        <ul className="fotos-comentario">
          {c.fotos.map((f, i) => (
            <li key={f.id}>
              {f.url
                ? <a href={f.url} target="_blank" rel="noreferrer"><img src={f.url} alt={`Foto ${i + 1} de ${c.autor_nombre}`} loading="lazy" /></a>
                : <span className="tenue">Foto no disponible</span>}
            </li>
          ))}
        </ul>
      )}
      {puedeOcultar && !ocultando && (
        <button type="button" className="boton-texto" onClick={() => setOcultando(true)}>Ocultar</button>
      )}
      {ocultando && (
        <form className="confirmar-eliminar" onSubmit={ocultar}>
          <label htmlFor={`motivo-ocultar-${c.id}`}>¿Por qué se oculta? Queda en el historial.</label>
          <input id={`motivo-ocultar-${c.id}`} minLength={5} required value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          <div className="acciones">
            <button type="submit" className="boton-peligro">Ocultar comentario</button>
            <button type="button" className="boton-secundario" onClick={() => setOcultando(false)}>Cancelar</button>
          </div>
          {error && <p className="aviso aviso-error" role="alert">{error}</p>}
        </form>
      )}
    </article>
  )
}

export function Comentarios({ recurso, id, usuario, titulo = 'Comentarios' }) {
  const [comentarios, setComentarios] = useState(null)   // null = cargando
  const [error, setError] = useState('')
  const [respondiendo, setRespondiendo] = useState(null)  // id del comentario al que se responde

  const rol = usuario.rol
  const abreComentarios = rol === 'OBSERVADOR'
  const responde = ['OBSERVADOR', 'TECNICO', 'ADMINISTRADOR'].includes(rol)
  const esAdmin = rol === 'ADMINISTRADOR'

  const cargar = useCallback(() => {
    api('/comentarios', { consulta: { recurso, recurso_id: id } })
      .then(setComentarios)
      .catch((e) => setError(e.message))
  }, [recurso, id])
  useEffect(() => { cargar() }, [cargar])

  async function publicar(texto, respuestaA = null, fotos = []) {
    if (fotos.length) {
      // Con fotos: un solo envío multipart; si una foto no pasa, no se guarda nada
      const datos = new FormData()
      datos.append('recurso', recurso)
      datos.append('recurso_id', id)
      datos.append('texto', texto)
      if (respuestaA) datos.append('respuesta_a', respuestaA)
      fotos.forEach((f) => datos.append('fotos', f))
      await apiFormulario('/comentarios/con-fotos', datos)
    } else {
      await api('/comentarios', { metodo: 'POST', cuerpo: { recurso, recurso_id: id, texto, respuesta_a: respuestaA } })
    }
    setRespondiendo(null)
    cargar()
  }

  async function ocultar(comentarioId, motivo) {
    await api(`/comentarios/${comentarioId}`, { metodo: 'DELETE', cuerpo: { motivo } })
    cargar()
  }

  const originales = (comentarios || []).filter((c) => c.respuesta_a === null)
  const respuestasDe = (cid) => (comentarios || []).filter((c) => c.respuesta_a === cid)

  return (
    <section className="seccion-detalle">
      <h4>{titulo}{comentarios ? ` (${comentarios.length})` : ''}</h4>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      {comentarios === null && !error && <p className="tenue">Cargando comentarios…</p>}
      {comentarios && originales.length === 0 && (
        <p className="tenue">
          {abreComentarios ? 'Todavía no hay comentarios; escribe el primero.' : 'Todavía no hay comentarios de Observadores.'}
        </p>
      )}
      <ol className="lista-comentarios">
        {originales.map((c) => (
          <li key={c.id}>
            <Comentario c={c} puedeOcultar={esAdmin} alOcultar={ocultar} />
            {respuestasDe(c.id).length > 0 && (
              <ol className="respuestas">
                {respuestasDe(c.id).map((r) => (
                  <li key={r.id}><Comentario c={r} puedeOcultar={esAdmin} alOcultar={ocultar} /></li>
                ))}
              </ol>
            )}
            {responde && respondiendo !== c.id && (
              <button type="button" className="boton-texto" onClick={() => setRespondiendo(c.id)}>Responder</button>
            )}
            {respondiendo === c.id && (
              <Escribir etiqueta={`Respuesta a ${c.autor_nombre}`} boton="Responder" conFotos={abreComentarios}
                        alEnviar={(texto, fotos) => publicar(texto, c.id, fotos)} alCancelar={() => setRespondiendo(null)} />
            )}
          </li>
        ))}
      </ol>
      {abreComentarios && <Escribir etiqueta="Escribe un comentario" boton="Comentar" conFotos
                                    alEnviar={(texto, fotos) => publicar(texto, null, fotos)} />}
    </section>
  )
}
