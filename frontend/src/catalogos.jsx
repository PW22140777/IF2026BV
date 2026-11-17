// Listas que varias pantallas necesitan (para selects y para mostrar nombres en tablas)
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from './api'
import { legible } from './recursos'

const Contexto = createContext(null)

export function ProveedorCatalogos({ children }) {
  const [catalogos, setCatalogos] = useState({ campus: [], edificios: [], areas: [], servicios: [], tiposElemento: [] })

  const recargar = useCallback(async () => {
    try {
      const [campus, edificios, areas, servicios, tiposElemento] = await Promise.all([
        api('/campus', { consulta: { limite: 1000 } }),
        api('/edificios', { consulta: { limite: 1000 } }),
        api('/areas', { consulta: { limite: 1000 } }),
        api('/servicios', { consulta: { limite: 1000 } }),
        api('/tipos-elemento', { consulta: { limite: 1000 } }),
      ])
      setCatalogos({ campus, edificios, areas, servicios, tiposElemento })
    } catch {
      /* si falla, las pantallas muestran los identificadores */
    }
  }, [])

  useEffect(() => { recargar() }, [recargar])

  const nombreCampus = (id) => {
    const c = catalogos.campus.find((x) => x.id === id)
    return c ? c.nombre : `Campus ${id}`
  }
  const nombreEdificio = (id) => {
    if (id === null || id === undefined) return 'Independiente'
    const e = catalogos.edificios.find((x) => x.id === id)
    return e ? e.nombre : `Edificio ${id}`
  }
  const nombreArea = (id) => {
    const a = catalogos.areas.find((x) => x.id === id)
    return a ? a.nombre : `Área ${id}`
  }
  // Campus al que pertenece un servicio (directo, por su edificio o por su área)
  const campusDeServicio = (s) => {
    if (s.campus_id) return s.campus_id
    if (s.edificio_id) return catalogos.edificios.find((e) => e.id === s.edificio_id)?.campus_id
    return catalogos.areas.find((a) => a.id === s.area_id)?.campus_id
  }
  const destinoServicio = (s) => {
    if (s.campus_id) return `${nombreCampus(s.campus_id)} (todo el campus)`
    if (s.edificio_id) return nombreEdificio(s.edificio_id)
    return nombreArea(s.area_id)
  }
  // Tipo de elemento de inventario por su clave (PARED, AIRE_ACONDICIONADO...)
  const tipoElemento = (clave) => catalogos.tiposElemento.find((t) => t.clave === clave)
  const nombreTipo = (clave) => tipoElemento(clave)?.nombre || legible(clave, 'tipo')
  const nombreServicio = (id) => {
    const s = catalogos.servicios.find((x) => x.id === id)
    return s ? s.nombre : `Servicio ${id}`
  }

  return (
    <Contexto.Provider value={{
      ...catalogos, recargar, nombreCampus, nombreEdificio, nombreArea, nombreServicio, campusDeServicio, destinoServicio,
      tipoElemento, nombreTipo,
    }}>
      {children}
    </Contexto.Provider>
  )
}

export function useCatalogos() {
  return useContext(Contexto)
}
