// Auditoría completa: solo el Administrador
import { Fragment, useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { legible } from '../recursos'
import { formatoFecha, ListaCambios } from './Historial'

const RECURSOS = ['', 'EDIFICIO', 'AREA', 'INVENTARIO', 'TIPO_ELEMENTO', 'SERVICIO', 'COMENTARIO', 'CONSUMO', 'USUARIO', 'SESION', 'AUDITORIA']
const ACCIONES = ['', 'CREAR', 'MODIFICAR', 'ELIMINAR', 'RESTAURAR', 'LOGIN', 'LOGIN_FALLIDO', 'VERIFICAR']
const POR_PAGINA = 25

export function Auditoria() {
  const [verificacion, setVerificacion] = useState(null)
  const [verificando, setVerificando] = useState(false)
  const [actividad, setActividad] = useState([])
  const [bitacora, setBitacora] = useState({ total: 0, registros: [] })
  const [filtros, setFiltros] = useState({ recurso: '', accion: '', usuario_id: '' })
  const [pagina, setPagina] = useState(0)
  const [abierto, setAbierto] = useState(null)
  const [error, setError] = useState('')

  const cargar = useCallback(async () => {
    try {
      const [b, a] = await Promise.all([
        api('/auditoria', { consulta: { ...filtros, limite: POR_PAGINA, desplazamiento: pagina * POR_PAGINA } }),
        api('/auditoria/usuarios'),
      ])
      setBitacora(b)
      setActividad(a)
    } catch (e) {
      setError(e.message)
    }
  }, [filtros, pagina])

  useEffect(() => { cargar() }, [cargar])

  async function verificar() {
    setVerificando(true)
    try {
      setVerificacion(await api('/auditoria/verificar'))
      cargar()
    } catch (e) {
      setError(e.message)
    } finally {
      setVerificando(false)
    }
  }

  const cambiarFiltro = (k, v) => { setPagina(0); setFiltros((f) => ({ ...f, [k]: v })) }
  const paginas = Math.max(1, Math.ceil(bitacora.total / POR_PAGINA))

  return (
    <div className="pagina">
      <section className="contenido">
        <header className="encabezado-pagina">
          <h1>Auditoría</h1>
          <button type="button" className="boton-principal" onClick={verificar} disabled={verificando}>
            {verificando ? 'Verificando…' : 'Verificar integridad'}
          </button>
        </header>
        <p className="tenue ancho-lectura">
          Cada registro guarda el hash del anterior y está firmado digitalmente. La verificación recalcula
          toda la cadena: si alguien modificó o borró un registro directamente en la base, aquí se detecta.
        </p>

        {verificacion && (
          <p className={`aviso ${verificacion.integra ? 'aviso-bien' : 'aviso-error'}`} role="status">
            {verificacion.integra
              ? `La bitácora está íntegra: se revisaron ${verificacion.registros_revisados} registros y todas las firmas son válidas.`
              : `Se detectó una alteración en el registro ${verificacion.error.id}: ${verificacion.error.problema}.`}
          </p>
        )}
        {error && <p className="aviso aviso-error" role="alert">{error}</p>}

        <h2>Actividad por usuario</h2>
        <div className="tabla-contenedor">
        <table className="tabla">
          <thead><tr><th scope="col">Usuario</th><th scope="col">Rol</th><th scope="col">Acciones</th><th scope="col">Última actividad</th></tr></thead>
          <tbody>
            {actividad.map((u) => (
              <tr key={u.usuario_id}>
                <td data-etiqueta="Usuario">
                  <button type="button" className="enlace-fila" onClick={() => cambiarFiltro('usuario_id', String(u.usuario_id))}>{u.nombre}</button>
                </td>
                <td data-etiqueta="Rol">{legible(u.rol, 'rol')}</td>
                <td data-etiqueta="Acciones">{Object.entries(u.acciones).map(([a, n]) => `${a.toLowerCase().replace('_', ' ')} ${n}`).join(', ')}</td>
                <td data-etiqueta="Última actividad">{formatoFecha(u.ultima_actividad)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>

        <h2>Bitácora</h2>
        <div className="barra-filtros">
          <label>Recurso
            <select value={filtros.recurso} onChange={(e) => cambiarFiltro('recurso', e.target.value)}>
              {RECURSOS.map((r) => <option key={r} value={r}>{r ? r.toLowerCase() : 'Todos'}</option>)}
            </select>
          </label>
          <label>Acción
            <select value={filtros.accion} onChange={(e) => cambiarFiltro('accion', e.target.value)}>
              {ACCIONES.map((a) => <option key={a} value={a}>{a ? a.toLowerCase().replace('_', ' ') : 'Todas'}</option>)}
            </select>
          </label>
          {filtros.usuario_id && (
            <button type="button" className="boton-secundario" onClick={() => cambiarFiltro('usuario_id', '')}>Quitar filtro de usuario</button>
          )}
          <span className="tenue">{bitacora.total} registros</span>
        </div>

        <div className="tabla-contenedor">

        <table className="tabla tabla-bitacora">
          <thead>
            <tr><th scope="col">#</th><th scope="col">Fecha</th><th scope="col">Usuario</th><th scope="col">Acción</th><th scope="col">Recurso</th><th scope="col">Motivo</th></tr>
          </thead>
          <tbody>
            {bitacora.registros.map((r) => (
              <Fragment key={r.id}>
                <tr onClick={() => setAbierto(abierto === r.id ? null : r.id)} className={abierto === r.id ? 'seleccionada' : ''}>
                  <td data-etiqueta="Registro">
                    <button type="button" className="enlace-fila" aria-expanded={abierto === r.id}>{r.id}</button>
                  </td>
                  <td data-etiqueta="Fecha">{formatoFecha(r.fecha)}</td>
                  <td data-etiqueta="Usuario">{r.usuario_nombre || 'Sistema'} <span className="tenue">{legible(r.rol, 'rol')}</span></td>
                  <td data-etiqueta="Acción">{r.accion.toLowerCase().replace('_', ' ')}</td>
                  <td data-etiqueta="Recurso">{r.recurso.toLowerCase()}{r.recurso_id ? ` ${r.recurso_id}` : ''}</td>
                  <td data-etiqueta="Motivo">{r.motivo || '—'}</td>
                </tr>
                {abierto === r.id && (
                  <tr className="fila-expandida">
                    <td colSpan={6}>
                      <ListaCambios cambios={r.cambios} />
                      <dl className="ficha ficha-tecnica">
                        <div><dt>IP</dt><dd>{r.ip || '—'}</dd></div>
                        <div><dt>Correlation id</dt><dd>{r.correlation_id}</dd></div>
                        <div><dt>Trace id</dt><dd>{r.trace_id || '—'}</dd></div>
                        <div><dt>Hash anterior</dt><dd className="hash">{r.hash_anterior}</dd></div>
                        <div><dt>Hash</dt><dd className="hash">{r.hash}</dd></div>
                        <div><dt>Firma ({r.llave_id})</dt><dd className="hash">{r.firma}</dd></div>
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        </div>
        <div className="paginacion">
          <button type="button" className="boton-secundario" disabled={pagina === 0} onClick={() => setPagina(pagina - 1)}>Anteriores</button>
          <span>Página {pagina + 1} de {paginas}</span>
          <button type="button" className="boton-secundario" disabled={pagina + 1 >= paginas} onClick={() => setPagina(pagina + 1)}>Siguientes</button>
        </div>
      </section>
    </div>
  )
}
