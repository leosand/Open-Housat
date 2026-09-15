import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

// Fond OSM raster (0$, sans cle) + polygone chantier + overlays image georeferences
// (scenes super-resolues posees aux coins exacts de leur fenetre de clip, image_bbox).

type BBox = [number, number, number, number]  // [minLon, minLat, maxLon, maxLat]

export interface MapOverlay {
  url: string
  bbox: BBox
  opacity: number
}

interface Props {
  polygon: { type: 'Polygon'; coordinates: number[][][] }
  overlays: { from?: MapOverlay; to?: MapOverlay }
  height?: number
}

function corners(b: BBox): [number, number][] {
  const [minx, miny, maxx, maxy] = b
  return [[minx, maxy], [maxx, maxy], [maxx, miny], [minx, miny]]  // MapLibre : TL, TR, BR, BL
}

function setOverlay(map: maplibregl.Map, id: string, o: MapOverlay | undefined) {
  if (map.getLayer(id)) map.removeLayer(id)
  if (map.getSource(id)) map.removeSource(id)
  if (!o) return
  map.addSource(id, { type: 'image', url: o.url, coordinates: corners(o.bbox) })
  map.addLayer({
    id, type: 'raster', source: id,
    paint: { 'raster-opacity': o.opacity, 'raster-fade-duration': 0 },
  })
}

export default function MapView({ polygon, overlays, height = 380 }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)

  useEffect(() => {
    if (!ref.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: ref.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors',
          },
        },
        layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
      },
      center: [polygon.coordinates[0][0][0], polygon.coordinates[0][0][1]],
      zoom: 15,
    })
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.on('load', () => {
      map.addSource('site-poly', { type: 'geojson', data: { type: 'Feature', geometry: polygon, properties: {} } })
      map.addLayer({ id: 'site-fill', type: 'fill', source: 'site-poly',
        paint: { 'fill-color': '#2563eb', 'fill-opacity': 0.08 } })
      map.addLayer({ id: 'site-line', type: 'line', source: 'site-poly',
        paint: { 'line-color': '#2563eb', 'line-width': 2 } })
      const b = polygon.coordinates[0]
      const xs = b.map(c => c[0]); const ys = b.map(c => c[1])
      map.fitBounds([[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]],
        { padding: 40 })
    })
    mapRef.current = map
    return () => { map.remove(); mapRef.current = null }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      setOverlay(map, 'ov-from', overlays.from)
      setOverlay(map, 'ov-to', overlays.to)
    }
    if (map.isStyleLoaded()) apply()
    else map.once('load', apply)
  }, [overlays.from?.url, overlays.to?.url, overlays.from?.opacity, overlays.to?.opacity])

  return <div ref={ref} className="mapbox" style={{ height }} role="application"
              aria-label="Carte du chantier avec calques avant apres" />
}
