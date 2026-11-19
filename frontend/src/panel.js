// El panel lateral de detalle es parte de la página (no tiene su propio desplazamiento).
// Si se abre un registro desde abajo de una lista larga, la página sube hasta el panel
// para que se vea su inicio. En tableta y teléfono el panel flota encima: no hace falta.
import { useEffect, useRef } from 'react'

const ESCRITORIO = '(min-width: 1101px)'
const ALTO_BARRA = 56   // barra superior fija (--alto-barra)

export function usePanelVisible(clave) {
  const panel = useRef(null)
  useEffect(() => {
    const el = panel.current
    if (!el || !window.matchMedia(ESCRITORIO).matches) return
    const arriba = el.getBoundingClientRect().top
    // Solo se mueve si el inicio del panel quedó fuera de la vista
    if (arriba < ALTO_BARRA || arriba > window.innerHeight * 0.6) {
      const reducir = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      window.scrollTo({ top: window.scrollY + arriba - ALTO_BARRA - 16, behavior: reducir ? 'auto' : 'smooth' })
    }
  }, [clave])
  return panel
}
