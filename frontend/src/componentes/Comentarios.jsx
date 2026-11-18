// Comentarios de un recurso, en el panel de detalle.
// El Observador abre comentarios; el Observador, el Técnico y el Administrador responden;
// solo el Administrador oculta (con motivo, queda en el historial). Consulta solo lee.
import { useCallback, useEffect, useId, useState } from 'react'
import { api } from '../api'

const NOMBRES_ROL = { ADMINISTRADOR: 'Administrador', TECNICO: 'Técnico', CONSULTA: 'Consulta', OBSERVADOR: 'Observador' }
const fecha = (iso) => new Date(iso).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' })

function Escribir({ etiqueta, boton, alEnviar, alCancelar }) {
  const [texto, setTexto] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState('')
  const idCampo = useId()

  async function enviar(e) {
    e.preventDefault()
    setEnviando(true)
    setError('')
    try {
      await alEnviar(texto.trim())
      setTexto('')
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

export function Comentarios({ recurso, id, usuario }) {
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

  async function publicar(texto, respuestaA = null) {
    await api('/comentarios', { metodo: 'POST', cuerpo: { recurso, recurso_id: id, texto, respuesta_a: respuestaA } })
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
      <h4>Comentarios{comentarios ? ` (${comentarios.length})` : ''}</h4>
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
              <Escribir etiqueta={`Respuesta a ${c.autor_nombre}`} boton="Responder"
                        alEnviar={(texto) => publicar(texto, c.id)} alCancelar={() => setRespondiendo(null)} />
            )}
          </li>
        ))}
      </ol>
      {abreComentarios && <Escribir etiqueta="Escribe un comentario" boton="Comentar" alEnviar={(texto) => publicar(texto)} />}
    </section>
  )
}
