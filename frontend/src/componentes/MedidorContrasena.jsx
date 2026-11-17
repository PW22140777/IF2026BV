// Medidor visual de la seguridad de una contraseña: barra de nivel y lista de requisitos.
// Se actualiza mientras se escribe; el servidor vuelve a revisar las mismas reglas.
import { NOMBRES_NIVEL, nivelContrasena, requisitosContrasena } from '../contrasenas'

export function MedidorContrasena({ contrasena, nombre, email, id }) {
  const datos = { nombre, email }
  const nivel = nivelContrasena(contrasena, datos)
  // El requisito de bytes solo se muestra si se rebasa: casi nunca pasa y distrae
  const requisitos = requisitosContrasena(contrasena, datos).filter((r) => r.id !== 'bytes' || !r.cumple)

  return (
    <div className="medidor-contrasena" id={id}>
      <div className="medidor-barra" aria-hidden="true">
        {[1, 2, 3, 4].map((n) => (
          <span key={n} className={n <= nivel ? `medidor-tramo nivel-${nivel}` : 'medidor-tramo'} />
        ))}
      </div>
      <p className={`medidor-nivel nivel-texto-${nivel}`} aria-live="polite">
        {contrasena ? `Seguridad: ${NOMBRES_NIVEL[nivel]}` : 'Escribe una contraseña para ver qué tan segura es'}
      </p>
      <ul className="medidor-requisitos">
        {requisitos.map((r) => (
          <li key={r.id} className={r.cumple ? 'cumple' : 'falta'}>
            <span aria-hidden="true">{r.cumple ? '✓' : '✗'}</span>
            <span className="sr-only">{r.cumple ? 'Cumple: ' : 'Falta: '}</span>
            {r.texto}
          </li>
        ))}
      </ul>
    </div>
  )
}
