import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

const API: string = (import.meta as unknown as { env: Record<string, string | undefined> }).env
  .VITE_API_URL ?? 'http://localhost:8000'

type BBox = [number, number, number, number]

interface GeoPolygon { type: 'Polygon'; coordinates: number[][][] }

interface Site {
  id: number; name: string; backfill_status: string; created_at: string
  polygon_geojson: string; obs_count?: number
}

interface Progress {
  backfill_status: string; backfill_error: string | null
  milestone: number | null; milestone_label: string | null; pivot_confirme: boolean
  milestone_date?: string | null; milestone_emprise?: number | null; milestone_built_ratio?: number | null
  milestone_pv?: number | null; anchor_date?: string | null
  pv_sum_first: number; pv_sum_last: number; delta_pra: number | null
  progression: number; observations: number
}

interface Observation {
  id: number; obs_date: string; milestone: number | null; milestone_label: string | null
  pivot_confirme: boolean; confidence: number; emprise?: number | null; pv_sum?: number | null
  image_url: string | null
  image_bbox: BBox | null; sr_method?: string | null; display_sr?: string | null
}

interface AlertItem { id: number; message: string; sent_at: string }

interface ReportMeta {
  id: number; week_start: string; week_end: string
  observations: number; sha256: string; pdf_url: string
}

// Etapes du chantier — vocabulaire CLIENT (« ou en est ma maison ? »), pas celui de l'ingenieur
// (M0..M4 et libelles API restent dans « Details techniques »).
const MILESTONES = ['Terrain nu', 'Fondations', 'Structure', 'Toiture', 'Finition']

function stepLabel(m: number | null): string {
  return m === null ? 'inconnue' : MILESTONES[m] ?? `etape ${m + 1}`
}

// Statuts d'API -> messages lisibles (au lieu de "cloud_pending" brut).
const STATUS_FR: Record<string, string> = {
  cloud_pending: 'aucune scene recente sous le seuil de nuages — reessayez plus tard',
  duplicate: 'scene deja analysee (aucun cout reseau)',
  baseline: "scene d'ancrage enregistree (baseline)",
  ok: 'observation mise a jour',
}

// Statut de backfill -> mot du client (« done » / « idle » ne veulent rien dire pour lui).
const BACKFILL_FR: Record<string, string> = {
  idle: 'jamais analyse', running: 'recherche en cours', done: 'a jour', error: 'erreur',
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!r.ok) {
    let title = `HTTP ${r.status}`
    try { title = (await r.json()).title ?? title } catch { /* ignore */ }
    throw new Error(title)
  }
  return r.json() as Promise<T>
}

function SiteForm({ onCreated }: { onCreated: (s: Site) => void }) {
  const [form, setForm] = useState({
    name: 'Ma maison', owner_email: '',
    // Parcelle INDIVIDUELLE (~22 m de cote, soit ~0,0002 deg) : c'est la taille d'une concession/
    // maison. Un carre de 0,0016 deg (178 m) couvre un ILOT ENTIER — l'ancien defaut, qui faisait
    // dire « votre maison » a un produit qui mesurait un paté de maisons. Centre : Douala (demo).
    // Valeurs multiples du pas 0,0001 des champs, sinon le navigateur refuse la soumission.
    min_lon: 9.7049, min_lat: 4.0449, max_lon: 9.7051, max_lat: 4.0451,
  })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onCreated(await api<Site>('/sites', { method: 'POST', body: JSON.stringify(form) }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'erreur inconnue')
    } finally {
      setBusy(false)
    }
  }

  const num = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.type === 'number' ? Number(e.target.value) : e.target.value })

  return (
    <form onSubmit={submit} className="card">
      <h2>Nouveau chantier</h2>
      <label>Nom
        <input value={form.name} onChange={num('name')} required minLength={2} />
      </label>
      <div className="grid4">
        <label>Lon min<input type="number" step="0.0001" value={form.min_lon} onChange={num('min_lon')} /></label>
        <label>Lat min<input type="number" step="0.0001" value={form.min_lat} onChange={num('min_lat')} /></label>
        <label>Lon max<input type="number" step="0.0001" value={form.max_lon} onChange={num('max_lon')} /></label>
        <label>Lat max<input type="number" step="0.0001" value={form.max_lat} onChange={num('max_lat')} /></label>
      </div>
      <p className="hint">
        <b>Taille de l&apos;emprise</b> : une parcelle / maison individuelle fait <b>20 a 40 m de
        cote</b> (0,0002 a 0,0004 deg). Un carre de 200 m de cote (0,0018 deg) couvre un <b>ilot
        entier</b> : le suivi porterait alors sur l&apos;ensemble du carre, pas sur votre maison.
        Coordonnees sur bboxfinder.com.
      </p>
      {error && <p role="alert" className="error">{error}</p>}
      <button disabled={busy}>{busy ? 'Creation…' : 'Creer le chantier'}</button>
    </form>
  )
}

// Dates en calendrier LOCAL (l'API valide selon le calendrier local — cf. DTZ011 assume).
function isoDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

// Lundi de la semaine ISO contenant `iso`.
function mondayOf(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7))
  return isoDate(d)
}

function lastWeekMonday(): string {
  // Lundi de la semaine ISO ECOULEE, calendrier LOCAL. En UTC, un dimanche soir (UTC deja lundi)
  // designait la semaine EN COURS -> 422 « semaine invalide ».
  const now = new Date()
  return mondayOf(isoDate(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 7)))
}

// Le rapport porte sur la semaine ECOULEE ; si le chantier n'a rien observe cette semaine-la, on
// propose la semaine de la derniere observation — sinon le bouton echoue TOUJOURS en 422 des que
// les donnees datent de plus d'une semaine, et l'utilisateur ne peut rien generer.
function reportWeek(lastObs: string | undefined): string {
  const last = lastWeekMonday()
  return lastObs && mondayOf(lastObs) !== last ? mondayOf(lastObs) : last
}

function ReportsPanel({ siteId, obsCount, lastObs }: {
  siteId: number; obsCount: number; lastObs?: string
}) {
  const [reports, setReports] = useState<ReportMeta[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const week = reportWeek(lastObs)

  const load = useCallback(() => {
    api<ReportMeta[]>(`/sites/${siteId}/reports`).then(setReports).catch(() => undefined)
  }, [siteId])
  useEffect(() => { load() }, [load])

  const generate = async () => {
    setBusy(true)
    setMsg(null)
    try {
      await api<ReportMeta>(`/sites/${siteId}/reports/${week}`, { method: 'POST' })
      load()
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'erreur')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <h3>Rapports PDF hebdomadaires</h3>
      <div className="actions">
        <button className="secondary" onClick={generate} disabled={busy || obsCount === 0}>
          {busy ? 'Generation…' : `Generer le rapport de la semaine du ${week}`}
        </button>
        {obsCount === 0 &&
          <span className="hint">
            Aucune observation : cliquez d&apos;abord « Chercher les images des derniers mois ».
          </span>}
      </div>
      {obsCount > 0 && week !== lastWeekMonday() && (
        <p className="hint">
          Aucune observation la semaine derniere : le rapport porte sur la semaine de votre
          derniere observation ({lastObs}).
        </p>
      )}
      {msg && <p role="alert" className="error">{msg}</p>}
      {reports.length > 0 && (
        <ul>
          {reports.map(r => (
            <li key={r.id}>
              <a href={`${API}${r.pdf_url}`} download>
                Semaine du {r.week_start} au {r.week_end}
              </a>
              <span className="hint"> ({r.observations} observation{r.observations > 1 ? 's' : ''})</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function bboxOf(polygon: GeoPolygon): string {
  const pts = polygon.coordinates[0]
  const xs = pts.map(p => p[0]); const ys = pts.map(p => p[1])
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)].join(',')
}

// Dimensions reelles (m) d'un anneau lon/lat — source unique pour la liste et la caracterisation.
function ringDims(pts: number[][]): { w: number; h: number } {
  const xs = pts.map(p => p[0]); const ys = pts.map(p => p[1])
  const lat = (Math.min(...ys) + Math.max(...ys)) / 2
  return {
    w: Math.round((Math.max(...xs) - Math.min(...xs)) * 111320 * Math.cos((lat * Math.PI) / 180)),
    h: Math.round((Math.max(...ys) - Math.min(...ys)) * 111320),
  }
}

// Emprise d'une parcelle en metres (distinguer deux chantiers homonymes).
function parcelSize(geojson: string): string {
  try {
    const { w, h } = ringDims((JSON.parse(geojson) as GeoPolygon).coordinates[0])
    return `${w} x ${h} m`
  } catch { return 'n/d' }
}

// Vue REELLE haute resolution (imagerie sub-metrique DATEE) — rendu par MOTEUR DE CARTE (MapLibre,
// deja dans le projet) : pan/zoom/clavier natifs, tuiles a la demande (rapproche + rapide), focus.
const WB_MAX_ZOOM = 19  // profondeur native Esri Wayback (~0,30 m/px)

type BBox4 = [number, number, number, number]
type Focus = { c: [number, number]; z: number }

function tileUrl(date: string): string {
  // Proxy same-origin : pas de CORS, URL Esri gardee cote serveur, cache immutable navigateur.
  return `${API}/parcel/wayback/tile?date=${date}&z={z}&x={x}&y={y}`
}

// MapLibre : `map.loaded()` est FAUX tant que des tuiles se chargent, et l'evenement 'load' ne se
// reproduit JAMAIS. Le motif `if (loaded()) fn(); else once('load', fn)` perdait donc silencieusement
// toute couche ajoutee pendant un chargement (cas normal ici : 1-3 s par tuile) — c'est ce qui
// empechait le rectangle de selection d'apparaitre. On s'appuie sur `isStyleLoaded()` (la vraie
// precondition pour addSource/addLayer) et on retombe sur 'idle', qui se reproduit.
function onStyleReady(m: maplibregl.Map, fn: () => void): void {
  if (m.isStyleLoaded()) fn()
  else m.once('idle', fn)
}

function SiteMap({ bbox, date, focus, maps, syncing, fitOnLoad, pick, square, onFocus, onRect }: {
  bbox: BBox4; date: string; focus: Focus | null
  maps: React.MutableRefObject<Set<maplibregl.Map>>
  syncing: React.MutableRefObject<boolean>
  fitOnLoad: boolean
  pick: boolean
  square: BBox4 | null
  onFocus: (c: [number, number]) => void
  onRect: (r: BBox4) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  // Une carte vide n'est pas une carte cassee : l'imagerie d'archive met 1-3 s par tuile (proxy
  // -> Esri, sans cache serveur). On le DIT au lieu de laisser un cadre blanc.
  const [loading, setLoading] = useState(true)
  // Les handlers sont enregistres UNE fois (deps vides) : on lit l'etat courant via des refs.
  const pickRef = useRef(pick)
  const onRectRef = useRef(onRect)
  const onFocusRef = useRef(onFocus)
  pickRef.current = pick
  onRectRef.current = onRect
  onFocusRef.current = onFocus

  useEffect(() => {
    if (!ref.current) return
    const m = new maplibregl.Map({
      container: ref.current,
      style: { version: 8, sources: {}, layers: [] },
      center: [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
      zoom: 15,
    })
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right')
    m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')
    m.on('idle', () => setLoading(false))  // toutes les tuiles demandees sont rendues
    m.on('move', () => {  // synchronise les deux cartes (Avant/Apres) SANS boucle
      if (syncing.current) return
      syncing.current = true
      const c = m.getCenter()
      for (const other of maps.current) if (other !== m) other.jumpTo({ center: c, zoom: m.getZoom() })
      syncing.current = false
    })
    // En mode dessin le clic ne deplace pas la camera : un clic sec ne doit pas faire sauter la vue
    // pendant qu'on trace l'emprise.
    m.on('click', (e) => {
      if (!pickRef.current) onFocusRef.current([e.lngLat.lng, e.lngLat.lat])
    })
    m.on('load', () => {
      m.addSource('parcel', { type: 'geojson', data: {
        type: 'Feature', properties: {},
        geometry: { type: 'Polygon', coordinates: [[[bbox[0], bbox[1]], [bbox[2], bbox[1]],
          [bbox[2], bbox[3]], [bbox[0], bbox[3]], [bbox[0], bbox[1]]]] } } })
      m.addLayer({ id: 'parcel-line', type: 'line', source: 'parcel',
        paint: { 'line-color': '#2563eb', 'line-width': 2 } })
      // Le conteneur n'a pas forcement sa taille DEFINITIVE au 'load' (grille/flex) : MapLibre
      // calcule alors un zoom trop large. On resize au frame suivant, et une SEULE carte (la
      // primaire) applique le cadrage a TOUTES -> les deux vues sont identiques a l'arrivee
      // (sinon chaque carte cadre a un instant different et les zooms divergent).
      requestAnimationFrame(() => {
        if (!fitOnLoad) return
        const bounds: [[number, number], [number, number]] =
          [[bbox[0], bbox[1]], [bbox[2], bbox[3]]]
        syncing.current = true
        for (const other of maps.current) {
          other.resize()
          other.fitBounds(bounds, { padding: 24, duration: 0 })
        }
        syncing.current = false
      })
    })
    const ro = new ResizeObserver(() => m.resize())
    ro.observe(ref.current)
    mapRef.current = m
    maps.current.add(m)
    return () => { ro.disconnect(); maps.current.delete(m); m.remove(); mapRef.current = null }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {  // date -> couche raster Wayback
    const m = mapRef.current
    if (!m) return
    const apply = () => {
      if (m.getLayer('wb')) m.removeLayer('wb')
      if (m.getSource('wb')) m.removeSource('wb')
      m.addSource('wb', { type: 'raster', tiles: [tileUrl(date)], tileSize: 256, maxzoom: WB_MAX_ZOOM })
      m.addLayer({ id: 'wb', type: 'raster', source: 'wb' },
        m.getLayer('parcel-line') ? 'parcel-line' : undefined)
    }
    onStyleReady(m, apply)
  }, [date])

  useEffect(() => {  // focus (clic carte / boutons) -> vol anime
    const m = mapRef.current
    if (m && focus) m.flyTo({ center: focus.c, zoom: Math.min(focus.z, WB_MAX_ZOOM), essential: true })
  }, [focus])

  useEffect(() => {  // mode « dessiner l'emprise » : GLISSER trace le rectangle (le deplacement de carte est coupe)
    const m = mapRef.current
    if (!m) return
    const canvas = m.getCanvas()
    if (!pick) {
      m.dragPan.enable()
      canvas.style.cursor = ''
      return
    }
    m.dragPan.disable()
    canvas.style.cursor = 'crosshair'
    let start: [number, number] | null = null

    const rectOf = (a: [number, number], b: [number, number]): BBox4 =>
      [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])]

    const show = (r: BBox4 | null) => {  // apercu vivant, sur la carte ou l'on dessine
      onStyleReady(m, () => {
        if (m.getLayer('pick-live')) m.removeLayer('pick-live')
        if (m.getSource('pick-live')) m.removeSource('pick-live')
        if (!r) return
        m.addSource('pick-live', { type: 'geojson', data: { type: 'Feature', properties: {},
          geometry: { type: 'Polygon', coordinates: [[[r[0], r[1]], [r[2], r[1]], [r[2], r[3]],
            [r[0], r[3]], [r[0], r[1]]]] } } })
        m.addLayer({ id: 'pick-live', type: 'line', source: 'pick-live',
          paint: { 'line-color': '#f97316', 'line-width': 3, 'line-dasharray': [2, 1] } })
      })
    }
    const down = (e: maplibregl.MapMouseEvent) => {
      start = [e.lngLat.lng, e.lngLat.lat]
      show(rectOf(start, start))
    }
    const move = (e: maplibregl.MapMouseEvent) => {
      if (start) show(rectOf(start, [e.lngLat.lng, e.lngLat.lat]))
    }
    const up = (e: maplibregl.MapMouseEvent) => {
      if (!start) return
      const r = rectOf(start, [e.lngLat.lng, e.lngLat.lat])
      start = null
      show(null)
      onRectRef.current(r)
    }
    m.on('mousedown', down)
    m.on('mousemove', move)
    m.on('mouseup', up)
    return () => {
      m.off('mousedown', down); m.off('mousemove', move); m.off('mouseup', up)
      show(null)
      m.dragPan.enable()
    }
  }, [pick])

  useEffect(() => {  // emprise DESSINEE (orange) : la meme sur les deux cartes synchronisees
    const m = mapRef.current
    if (!m) return
    const apply = () => {
      if (m.getLayer('pick')) m.removeLayer('pick')
      if (m.getSource('pick')) m.removeSource('pick')
      if (!square) return
      m.addSource('pick', { type: 'geojson', data: { type: 'Feature', properties: {},
        geometry: { type: 'Polygon', coordinates: [[[square[0], square[1]], [square[2], square[1]],
          [square[2], square[3]], [square[0], square[3]], [square[0], square[1]]]] } } })
      m.addLayer({ id: 'pick', type: 'line', source: 'pick',
        paint: { 'line-color': '#f97316', 'line-width': 3, 'line-dasharray': [2, 1] } })
    }
    onStyleReady(m, apply)
  }, [square])

  return (
    <>
      <div ref={ref} className="wbmap" role="application" aria-label="Carte imagerie datee" />
      {loading && <p className="hint">Chargement de l&apos;imagerie d&apos;archive…</p>}
    </>
  )
}

// Emprise « fine » (m) : sous ce cote, chaque point de mesure Sentinel-2 (10 m) melange le batiment
// et ses voisins. Ce n'est PAS un blocage : un batiment individuel fait 10 a 20 m de cote.
const FINE_SIDE_M = 30

function ParcelHR({ polygon, onCreateSite }: {
  polygon: GeoPolygon; onCreateSite: (s: Site) => void
}) {
  const siteBbox = bboxOf(polygon)
  const bbox = useMemo(() => siteBbox.split(',').map(Number) as BBox4, [siteBbox])
  const center = useMemo<[number, number]>(
    () => [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2], [bbox])
  const maps = useRef<Set<maplibregl.Map>>(new Set())
  const syncing = useRef(false)  // garde-fou anti-boucle de synchronisation
  const [dates, setDates] = useState<string[]>([])
  const [attribution, setAttribution] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [focus, setFocus] = useState<Focus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pick, setPick] = useState(false)
  const [rect, setRect] = useState<BBox4 | null>(null)  // emprise DESSINEE a la souris
  const [busy, setBusy] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const dims = useMemo(() => (rect
    ? ringDims([[rect[0], rect[1]], [rect[2], rect[1]], [rect[2], rect[3]], [rect[0], rect[3]]])
    : null), [rect])
  // Un batiment individuel fait 10 a 20 m de cote : on ne BLOQUE plus ces emprises. On dit ce que
  // la mesure peut en dire (pixels mixtes : chaque point de 10 m couvre la maison ET ses voisines),
  // et c'est l'utilisateur qui decide.
  const pixels = dims
    ? { w: Math.max(1, Math.round(dims.w / 10)), h: Math.max(1, Math.round(dims.h / 10)) }
    : null
  const fine = !!dims && Math.min(dims.w, dims.h) < FINE_SIDE_M

  const createSite = async () => {
    if (!rect) return
    setBusy(true)
    setCreateError(null)
    const [minLon, minLat, maxLon, maxLat] = rect.map((v) => Number(v.toFixed(6)))
    try {
      onCreateSite(await api<Site>('/sites', { method: 'POST', body: JSON.stringify({
        name: `Ma maison (${dims?.w} x ${dims?.h} m)`, owner_email: '',
        min_lon: minLon, min_lat: minLat, max_lon: maxLon, max_lat: maxLat }) }))
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : 'erreur')
    } finally { setBusy(false) }
  }

  useEffect(() => {
    setError(null)
    api<{ dates: string[]; attribution: string }>(`/parcel/wayback/dates?bbox=${siteBbox}`)
      .then((r) => {
        setDates(r.dates); setAttribution(r.attribution)
        if (r.dates.length) { setFrom(r.dates[0]); setTo(r.dates[r.dates.length - 1]) }
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'erreur'))
  }, [siteBbox])

  return (
    <section>
      <h3>Vue reelle haute resolution (imagerie datee)</h3>
      <p className="hint">
        <b>Lecture</b> — imagerie d&apos;archive : les dates ci-dessous sont <i>independantes</i> des
        dates d&apos;observations Sentinel-2 affichees plus bas. Glisser = deplacer, molette/pinch = zoom,
        clavier = defiler, <b>clic = centrer</b>. Le Sentinel-2 (10 m) sert la <b>mesure</b>, pas la lecture.
      </p>
      {dates.length > 0 && (
        <p className="hint">
          Archive la plus recente pour cette emprise : <b>{dates[dates.length - 1]}</b>
          {' '}— l&apos;archive Esri n&apos;est <b>pas quotidienne</b> (cadence ~mensuelle). Les dates
          recentes sont dans « Passages Sentinel-2 », plus bas.
        </p>
      )}
      {error && <p role="alert" className="error">{error}</p>}
      {dates.length === 0 && !error && <p className="hint">Recherche des dates disponibles…</p>}
      {dates.length > 0 && (
        <>
          <div className="actions">
            <label>Avant
              <select value={from} onChange={(e) => setFrom(e.target.value)}>
                {dates.map(d => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <label>Apres
              <select value={to} onChange={(e) => setTo(e.target.value)}>
                {dates.map(d => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <button className="secondary" type="button"
                    onClick={() => setFocus({ c: center, z: 15 })}>Recentrer chantier</button>
            <button className="secondary" type="button"
                    onClick={() => setFocus({ c: center, z: WB_MAX_ZOOM - 0.4 })}>Focus bati (zoom max)</button>
            <button className="secondary" type="button"
                    onClick={() => { setPick(!pick); setRect(null) }}>
              {pick ? 'Annuler le dessin d\'emprise' : 'Dessiner une emprise a analyser'}
            </button>
            {pick && (
              <button type="button" disabled={!rect || busy} onClick={createSite}>
                {busy ? 'Creation…' : 'Creer un chantier sur cette emprise'}
              </button>
            )}
          </div>
          {pick && (
            <p className="hint">
              <b>Maintenez le clic (ou le doigt) et glissez sur la carte</b> pour dessiner
              l&apos;emprise a analyser : le rectangle <b>orange</b> suit votre geste, relachez pour le
              fixer (le deplacement de la carte est suspendu pendant le dessin). Housat mesurera
              <b> ce rectangle</b> et rien d&apos;autre : les etapes M0-M4 qualifient l&apos;ensemble de
              l&apos;emprise, jamais un batiment isole.
              {dims && <> Emprise dessinee : <b>{dims.w} x {dims.h} m</b>{' '}
                ({(dims.w * dims.h / 10000).toFixed(2)} ha), soit{' '}
                <b>{pixels?.w} x {pixels?.h} points</b> Sentinel-2.</>}
              {fine && <> <b>Emprise fine</b> : a 10 m par point, chaque point de mesure couvre votre
                batiment <i>et</i> ses voisins (pixels mixtes) — l&apos;etape peut rester « terrain nu »
                meme si le chantier avance. La lecture fiable reste l&apos;imagerie haute resolution
                ci-dessus ; la mesure devient discriminante vers <b>30 m de cote</b> et plus.</>}
            </p>
          )}
          {createError && <p role="alert" className="error">{createError}</p>}
          {dates.length < 2 && (
            <p className="hint">Une seule date disponible sur cette emprise : comparaison impossible.</p>
          )}
          <div className="hcompare">
            <figure>
              <SiteMap bbox={bbox} date={from} focus={focus} maps={maps} pick={pick} square={rect}
                       syncing={syncing} fitOnLoad onFocus={(c) => setFocus({ c, z: 17 })}
                       onRect={setRect} />
              <figcaption>Avant — {from}</figcaption>
            </figure>
            <figure>
              <SiteMap bbox={bbox} date={to} focus={focus} maps={maps} pick={pick} square={rect}
                       syncing={syncing} fitOnLoad={false} onFocus={(c) => setFocus({ c, z: 17 })}
                       onRect={setRect} />
              <figcaption>Apres — {to}</figcaption>
            </figure>
          </div>
          <p className="hint">
            Contour <b>bleu</b> = la <b>zone analysee</b> : c&apos;est CE carre que Housat mesure
            (Sentinel-2, 10 m) — pas un batiment precis.
            {pick && <> Contour <b>orange</b> = l&apos;emprise que vous dessinez.</>}
          </p>
          <p className="hint">
            {attribution} · glisser/molette pour naviguer{pick ? '' : ' · clic = centrer'}
          </p>
        </>
      )}
    </section>
  )
}

interface Overpass {
  date: string; cloud_cover: number; analysed: boolean; usable: boolean
  parcel_cloud_pct?: number | null
}

interface OverpassData {
  overpasses: Overpass[]; median_gap_days: number | null; max_cloud: number
  parcel_clear_count: number | null; parcel_computed: number | null
}

// Cadence REELLE de la constellation + nuage **PAR PARCELLE** (ADR 0010) : « exploitable » se juge
// sur la parcelle, jamais sur la tuile (~110 km) — sinon le panneau annonce « 0 exploitable » alors
// que des dates passent. Le calcul parcelle est borne (1 telechargement SCL par date).
function OverpassPanel({ siteId }: { siteId: number }) {
  const [data, setData] = useState<OverpassData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<OverpassData>(`/sites/${siteId}/overpasses?parcel=true`)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'erreur'))
  }, [siteId])

  if (error) {
    return <section><h3>Passages Sentinel-2</h3>
      <p role="alert" className="error">{error}</p></section>
  }
  if (!data) {
    return <section><h3>Passages Sentinel-2</h3>
      <p className="hint">Interrogation du catalogue…</p></section>
  }
  const clear = data.parcel_clear_count
  // Une puce par passage (rendu reutilise pour la liste visible et la liste repliee).
  const chip = (o: Overpass) => {
    const pct = o.parcel_cloud_pct ?? null
    const val = pct ?? o.cloud_cover
    const ok = val <= data.max_cloud
    return (
      <li key={o.date} className={o.analysed ? 'ok' : (ok ? 'mid' : 'ko')}
          title={`${pct !== null ? 'parcelle' : 'tuile'} : ${val} %` +
                 (o.analysed ? ' · analyse' : (ok ? ' · exploitable' : ' · nuageux'))}>
        {o.date} · {val} %{pct !== null ? ' parc.' : ''}
      </li>
    )
  }

  return (
    <section>
      <h3>Passages Sentinel-2 (mesure)</h3>
      <p className="hint">
        {data.overpasses.length} passage(s) · <b>ecart median {data.median_gap_days ?? '—'} j</b>
        {clear !== null && data.parcel_computed
          ? <> · <b>{clear} exploitable(s)</b> sur {data.parcel_computed} mesurees
            {' '}(nuages <b>par parcelle</b> &le; {data.max_cloud} %)</>
          : <> · nuages &le; {data.max_cloud} %</>}
      </p>
      {clear === 0 && data.parcel_computed ? (
        <p className="hint">
          Aucun des {data.parcel_computed} passages les plus recents n&apos;est assez degage
          au-dessus de votre parcelle (seuil {data.max_cloud} %) : le suivi enregistrera la
          prochaine image <b>exploitable</b>. En attendant, la « Vue reelle haute resolution »
          ci-dessus reste disponible pour lire votre parcelle.
        </p>
      ) : null}
      <ul className="ovp">{data.overpasses.slice(0, 12).map(chip)}</ul>
      {data.overpasses.length > 12 && (
        <details className="tech">
          <summary>Voir les {data.overpasses.length - 12} passages plus anciens</summary>
          <ul className="ovp">{data.overpasses.slice(12).map(chip)}</ul>
        </details>
      )}
    </section>
  )
}

// Repond a la question du CLIENT (« ou en est ma maison ? »), pas a celle de l'ingenieur.
// Le jargon (PV cumulee, progression) part dans « Details techniques » : un proprietaire au
// Cameroun ne sait pas ce qu'est un indice de changement, et un tiret ne lui dit rien a faire.
// La caracterisation de l'emprise est FORMELLE (dimensions et pas de mesure reels) : on ne dit
// « votre maison » que si le carre a la taille d'une parcelle, sinon on decrit ce qu'il est.
function SiteStatus({ progress, obs, polygon }: {
  progress: Progress | null; obs: Observation[]; polygon: GeoPolygon
}) {
  if (!progress) return null
  const { w, h } = ringDims(polygon.coordinates[0])
  const maison = Math.max(w, h) <= 45
  const titre = maison ? 'Ou en est votre maison ?' : 'Ou en est ce chantier ?'
  const facts = (
    <>
      <p className="hint">
        La mesure porte sur <b>toute l&apos;emprise</b> : <b>{w} x {h} m</b>{' '}
        ({(w * h / 10000).toFixed(2)} ha). L&apos;etape ci-dessus est celle de l&apos;<b>ensemble du
        carre</b>, pas d&apos;un batiment designe.
      </p>
      <p className="hint">
        Pas de suivi batiment par batiment : Sentinel-2 mesure <b>1 point par 10 m</b>, ce carre fait
        donc <b>{Math.round(w / 10)} x {Math.round(h / 10)} points</b>, et une maison individuelle
        n&apos;en occupe que 1 a 3. {maison
          ? 'Votre emprise est deja a l\'echelle d\'une parcelle : la mesure porte sur votre terrain.'
          : <>Votre emprise couvre <b>plusieurs batiments</b> (un ilot, pas une maison) : utilisez
            « <b>Choisir une emprise a analyser</b> » ci-dessous pour ne mesurer qu&apos;une parcelle
            (~30 m de cote).</>}
      </p>
    </>
  )
  if (progress.observations === 0) {
    return (
      <section className="status">
        <h3>{titre}</h3>
        {facts}
        <p className="hint">Aucune donnee pour ce chantier pour l&apos;instant.</p>
        <p>
          Cliquez <b>« Chercher les images des derniers mois »</b> ci-dessus : Housat va chercher
          les images satellite des derniers mois et etablir le point de depart de votre chantier.
        </p>
      </section>
    )
  }
  const step = progress.milestone ?? 0
  const last = obs[0]
  return (
    <section className="status">
      <h3>{titre}</h3>
      <ol className="steps">
        {MILESTONES.map((label, i) => (
          <li key={label} className={i < step ? 'done' : (i === step ? 'current' : 'todo')}>
            <span className="dot" aria-hidden="true" />{label}
          </li>
        ))}
      </ol>
      <p>
        Etape <b>{step + 1} sur {MILESTONES.length}</b> — <b>{progress.milestone_label ?? 'n/d'}</b>
        {/* L'etape est une MESURE datee : on nomme la date qui l'a etablie, pas la derniere image. */}
        {progress.milestone_date && <> (mesuree le <b>{progress.milestone_date}</b>)</>}
        {last && <> · derniere image analysee : <b>{last.obs_date}</b></>}
      </p>
      <p className="hint">
        <b>Sur quoi repose cette etape</b> — indices NDVI/NDBI/BSI de chaque date, compares a
        l&apos;image d&apos;ancrage
        {progress.anchor_date && <> du <b>{progress.anchor_date}</b></>} (Sentinel-2, 10 m) : ce
        n&apos;est pas une lecture d&apos;image.
        {progress.milestone_emprise != null && progress.milestone_pv != null && (
          <> A la date retenue : <b>{Math.round(progress.milestone_emprise * 100)} %</b> de
            l&apos;emprise en changement robuste, indice de changement{' '}
            <b>{progress.milestone_pv.toFixed(1)}</b>.
            {progress.milestone_built_ratio != null && (
              <> Part batie de la parcelle :{' '}
                <b>{Math.round(progress.milestone_built_ratio * 100)} %</b> (c&apos;est ce chiffre,
                avec la tendance du bati, qui separe une dalle d&apos;une toiture : au-dela de 40 %
                avec une tendance plate, la toiture est en place).</>
            )}
          </>
        )}
      </p>
      {facts}
    </section>
  )
}

function Dashboard({ site, onCreateSite, autoStart }: {
  site: Site; onCreateSite: (s: Site) => void; autoStart?: boolean
}) {
  const [progress, setProgress] = useState<Progress | null>(null)
  const [obs, setObs] = useState<Observation[]>([])
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const [zoom, setZoom] = useState<Observation | null>(null)  // observation agrandie (lightbox)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setZoom(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  const polygon = JSON.parse(site.polygon_geojson) as GeoPolygon

  const refresh = useCallback(async () => {
    const [p, o, a] = await Promise.all([
      api<Progress>(`/sites/${site.id}/progress`),
      api<Observation[]>(`/sites/${site.id}/observations`),
      api<AlertItem[]>(`/sites/${site.id}/alerts`),
    ])
    setProgress(p)
    setObs(o)
    setAlerts(a)
  }, [site.id])

  useEffect(() => { refresh().catch(() => undefined) }, [refresh])

  useEffect(() => {
    if (progress?.backfill_status === 'running') {
      timer.current = setInterval(() => refresh().catch(() => undefined), 5000)
    }
    return () => { if (timer.current) clearInterval(timer.current) }
  }, [progress?.backfill_status, refresh])

  const backfill = async () => {
    setMsg(null)
    try {
      await api(`/sites/${site.id}/backfill`, { method: 'POST' })
      setMsg('Recherche des images des derniers mois lancee — rafraichissement auto toutes les 5 s.')
      refresh()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'erreur') }
  }

  // Un chantier vient d'etre cree sur la carte : on lance la recherche d'images tout de suite.
  // Sinon on arrive sur une fiche vide (« aucune donnee ») et l'analyse M0-M4 ne demarre jamais.
  const autoDone = useRef(false)
  useEffect(() => {
    if (autoStart && !autoDone.current) { autoDone.current = true; backfill() }
  }, [autoStart])  // eslint-disable-line react-hooks/exhaustive-deps

  const check = async () => {
    setMsg('Verification en cours (30-90 s)…')
    try {
      const r = await api<Record<string, unknown>>(`/sites/${site.id}/check`, { method: 'POST' })
      const status = String(r.status ?? '')
      const label = r.milestone_label ? String(r.milestone_label) : (STATUS_FR[status] ?? status)
      setMsg(`Verification terminee : ${label}`)
      refresh()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'erreur') }
  }

  return (
    <div className="card">
      <h2>{site.name}</h2>
      <div className="actions">
        <button onClick={backfill} disabled={progress?.backfill_status === 'running'}>
          {progress?.backfill_status === 'running'
            ? 'Recherche en cours…' : 'Chercher les images des derniers mois'}
        </button>
        <button onClick={check} className="secondary">Verifier maintenant</button>
      </div>
      {msg && <p className="info">{msg}</p>}
      {progress?.backfill_status === 'error' &&
        <p role="alert" className="error">Erreur backfill : {progress.backfill_error}</p>}
      <SiteStatus progress={progress} obs={obs} polygon={polygon} />
      <ParcelHR polygon={polygon} onCreateSite={onCreateSite} />
      {progress && progress.observations > 0 && (
        <details className="tech">
          <summary>Details techniques (mesure satellite)</summary>
          <dl className="metrics">
            <dt>Indice de changement</dt><dd>{progress.pv_sum_last.toFixed(2)}</dd>
            <dt>Progression periode</dt><dd>{progress.progression} %</dd>
            <dt>Pivot confirme</dt><dd>{progress.pivot_confirme ? 'oui' : 'non'}</dd>
            <dt>Observations</dt><dd>{progress.observations}</dd>
            <dt>Image d&apos;ancrage</dt><dd>{progress.anchor_date ?? 'n/d'}</dd>
            <dt>Fiabilite de la mesure</dt>
            <dd>
              {obs[0]?.confidence != null ? obs[0].confidence.toFixed(2) : 'n/d'}
              {obs[0]?.sr_method && obs[0].sr_method !== 'sen2sr'
                ? ` — surresolution de repli (${obs[0].sr_method}) : le modele SEN2SR de la voie
                   detection n'est pas installe dans ce deploiement`
                : ''}
            </dd>
          </dl>
        </details>
      )}
      <OverpassPanel siteId={site.id} />
      <ReportsPanel siteId={site.id} obsCount={obs.length} lastObs={obs[0]?.obs_date} />
      {alerts.length > 0 && (
        <section>
          <h3>Alertes</h3>
          <ul>{alerts.map(a =>
            <li key={a.id}>{a.message} — <b>{String(a.sent_at).slice(0, 10)}</b></li>)}</ul>
        </section>
      )}
      {obs.length > 0 && (
        <details className="tech">
          <summary>
            Vignettes de mesure ({obs.length}) — Sentinel-2, 10 m : a cette resolution un batiment
            fait 1 a 3 pixels, ces images ne sont pas interpretables a l&apos;oeil
          </summary>
          <div className="obsgrid">
            {obs.map(o => (
              <figure key={o.id}>
                {o.image_url
                  ? <img className="zoomable" src={`${API}${o.image_url}`} alt={`scene ${o.obs_date}`}
                         loading="lazy" onClick={() => setZoom(o)} />
                  : <div className="noimg">sans image</div>}
                <figcaption
                  title={`mesure (indices) : ${o.sr_method ?? '—'} | affichage (image) : ${o.display_sr ?? '—'} | bbox image : ${o.image_bbox?.join(', ') ?? '—'}`}>
                  <b>{o.obs_date}</b> — etape : {stepLabel(o.milestone)}
                  {o.emprise != null && <> · <b>{Math.round(o.emprise * 100)} %</b> du carre modifie</>}
                  {o.pv_sum != null && <> · indice <b>{o.pv_sum.toFixed(1)}</b></>}
                  <span className="hint"> · mesure Sentinel-2 (10 m)</span>
                </figcaption>
              </figure>
            ))}
          </div>
        </details>
      )}
      {zoom && (
        <div className="lightbox" role="dialog" aria-modal="true"
             aria-label={`Observation du ${zoom.obs_date} agrandie`}
             onClick={() => setZoom(null)}>
          <img src={`${API}${zoom.image_url}`} alt={`Observation du ${zoom.obs_date}`} />
          <p className="lightbox-cap">
            {zoom.obs_date} — etape : {stepLabel(zoom.milestone)} · mesure Sentinel-2 (10 m)
            {zoom.display_sr ? ` · affichage : ${zoom.display_sr}` : ''}
          </p>
          <button className="lightbox-close" onClick={() => setZoom(null)} aria-label="Fermer">Fermer ✕</button>
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [sites, setSites] = useState<Site[]>([])
  const [selected, setSelected] = useState<Site | null>(null)
  // Chantier cree a l'instant (carte ou formulaire) : sa recherche d'images demarre toute seule.
  const [autoId, setAutoId] = useState<number | null>(null)

  useEffect(() => { api<Site[]>('/sites').then(setSites).catch(() => undefined) }, [])

  return (
    <main>
      <h1>Housat — MVP local</h1>
      <p className="hint">
        Suivez la construction de votre maison <b>a distance</b> : images satellite datees, etapes
        du chantier, rapport PDF hebdomadaire scelle.
      </p>
      {!selected ? (
        <>
          <SiteForm onCreated={(s) => {
            setSites([s, ...sites]); setSelected(s); setAutoId(s.id)
          }} />
          {sites.length > 0 && (
            <div className="card">
              <h2>Mes chantiers</h2>
              <ul>{sites.map(s => (
                <li key={s.id}>
                  <button className="link" onClick={() => { setSelected(s); setAutoId(null) }}>{s.name}</button>
                  <span className="hint"> — {parcelSize(s.polygon_geojson)} ·{' '}
                    {BACKFILL_FR[s.backfill_status] ?? s.backfill_status}
                    {' '}· {s.obs_count ?? 0} observation{(s.obs_count ?? 0) > 1 ? 's' : ''}
                    {' '}· cree le {String(s.created_at).slice(0, 10)}</span>
                </li>))}
              </ul>
            </div>
          )}
        </>
      ) : (
        <>
          <button className="link" onClick={() => { setSelected(null); setAutoId(null) }}>&larr; Retour</button>
          <Dashboard site={selected} autoStart={autoId === selected.id}
                     onCreateSite={(s) => {
                       setSites([s, ...sites]); setSelected(s); setAutoId(s.id)
                     }} />
        </>
      )}
    </main>
  )
}
