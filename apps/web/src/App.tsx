import { useCallback, useEffect, useRef, useState } from 'react'
import MapView from './MapView'

const API: string = (import.meta as unknown as { env: Record<string, string | undefined> }).env
  .VITE_API_URL ?? 'http://localhost:8000'

type BBox = [number, number, number, number]

interface GeoPolygon { type: 'Polygon'; coordinates: number[][][] }

interface Site {
  id: number; name: string; backfill_status: string; created_at: string
  polygon_geojson: string
}

interface Progress {
  backfill_status: string; backfill_error: string | null
  milestone: number | null; milestone_label: string | null; pivot_confirme: boolean
  pv_sum_first: number; pv_sum_last: number; delta_pra: number | null
  progression: number; observations: number
}

interface Observation {
  id: number; obs_date: string; milestone: number | null; milestone_label: string | null
  pivot_confirme: boolean; confidence: number; image_url: string | null
  image_bbox: BBox | null
}

interface AlertItem { id: number; message: string; sent_at: string }

interface CompareResult {
  from: Observation; to: Observation
  delta: { progression: number; milestone_from: number | null; milestone_to: number | null; pivot_confirme: boolean }
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
    min_lon: 9.70, min_lat: 4.04, max_lon: 9.71, max_lat: 4.05, // bbox demo (Douala)
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
      <p className="hint">Astuce : recuperez la bbox de votre parcelle sur bboxfinder.com.</p>
      {error && <p role="alert" className="error">{error}</p>}
      <button disabled={busy}>{busy ? 'Creation…' : 'Creer le chantier'}</button>
    </form>
  )
}

function CompareSlider({ a, b }: { a: Observation; b: Observation }) {
  const [pos, setPos] = useState(50)
  if (!a.image_url || !b.image_url) return <p className="hint">Images indisponibles pour ces dates.</p>
  return (
    <div className="comparebox" role="group" aria-label="Comparaison avant apres">
      <img className="cmp imgA" src={`${API}${a.image_url}`} alt={`Avant — ${a.obs_date}`} />
      <img className="cmp imgB" src={`${API}${b.image_url}`} alt={`Apres — ${b.obs_date}`}
           style={{ clipPath: `inset(0 0 0 ${pos}%)` }} />
      <span className="tag tagA">Avant {a.obs_date}</span>
      <span className="tag tagB">Apres {b.obs_date}</span>
      <input type="range" min={0} max={100} value={pos} className="cmprange"
             aria-label="Curseur de comparaison avant apres"
             onChange={(e) => setPos(Number(e.target.value))} />
    </div>
  )
}

function ComparePanel({ siteId, polygon, obs }: {
  siteId: number; polygon: GeoPolygon; obs: Observation[]
}) {
  const chrono = [...obs].reverse()
  const [fromId, setFromId] = useState<number | ''>('')
  const [toId, setToId] = useState<number | ''>('')
  const [result, setResult] = useState<CompareResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [fadeFrom, setFadeFrom] = useState(0.9)
  const [fadeTo, setFadeTo] = useState(0.0)

  useEffect(() => {
    if (chrono.length >= 2) {
      setFromId((f) => (f === '' ? chrono[0].id : f))
      setToId((t) => (t === '' ? chrono[chrono.length - 1].id : t))
    }
  }, [obs.length])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (fromId === '' || toId === '' || fromId === toId) { setResult(null); return }
    api<CompareResult>(`/sites/${siteId}/compare?from=${fromId}&to=${toId}`)
      .then((r) => { setResult(r); setError(null) })
      .catch((e) => setError(e instanceof Error ? e.message : 'erreur'))
  }, [siteId, fromId, toId])

  if (chrono.length < 2) {
    return <p className="hint">La comparaison avant/apres sera disponible apres 2 observations.</p>
  }
  const overlays = result ? {
    from: result.from.image_url && result.from.image_bbox
      ? { url: `${API}${result.from.image_url}`, bbox: result.from.image_bbox, opacity: fadeFrom }
      : undefined,
    to: result.to.image_url && result.to.image_bbox
      ? { url: `${API}${result.to.image_url}`, bbox: result.to.image_bbox, opacity: fadeTo }
      : undefined,
  } : {}

  return (
    <section>
      <h3>Avant / Apres (periodes au choix)</h3>
      <div className="actions">
        <label>Avant
          <select value={fromId} onChange={(e) => setFromId(Number(e.target.value))}>
            {chrono.map(o => <option key={o.id} value={o.id}>{o.obs_date}</option>)}
          </select>
        </label>
        <label>Apres
          <select value={toId} onChange={(e) => setToId(Number(e.target.value))}>
            {chrono.map(o => <option key={o.id} value={o.id}>{o.obs_date}</option>)}
          </select>
        </label>
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      {result && (
        <>
          <MapView polygon={polygon} overlays={overlays} />
          <div className="actions">
            <label>Calque Avant
              <input type="range" min={0} max={1} step={0.05} value={fadeFrom}
                     aria-label="Opacite calque avant"
                     onChange={(e) => setFadeFrom(Number(e.target.value))} />
            </label>
            <label>Calque Apres
              <input type="range" min={0} max={1} step={0.05} value={fadeTo}
                     aria-label="Opacite calque apres"
                     onChange={(e) => setFadeTo(Number(e.target.value))} />
            </label>
          </div>
          <CompareSlider a={result.from} b={result.to} />
          <dl className="metrics">
            <dt>Jalon avant</dt><dd>{result.from.milestone_label ?? '—'}</dd>
            <dt>Jalon apres</dt><dd>{result.to.milestone_label ?? '—'}</dd>
            <dt>Progression periode</dt><dd>{result.delta.progression} %</dd>
            <dt>Pivot</dt><dd>{result.delta.pivot_confirme ? 'confirme' : 'non'}</dd>
          </dl>
        </>
      )}
    </section>
  )
}

function Dashboard({ site }: { site: Site }) {
  const [progress, setProgress] = useState<Progress | null>(null)
  const [obs, setObs] = useState<Observation[]>([])
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
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
      setMsg('Backfill lance — rafraichissement auto toutes les 5 s.')
      refresh()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'erreur') }
  }

  const check = async () => {
    setMsg('Verification en cours (30-90 s)…')
    try {
      const r = await api<Record<string, unknown>>(`/sites/${site.id}/check`, { method: 'POST' })
      setMsg(`Verification terminee : ${String(r.milestone_label ?? r.status)}`)
      refresh()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'erreur') }
  }

  return (
    <div className="card">
      <h2>{site.name}</h2>
      <div className="actions">
        <button onClick={backfill} disabled={progress?.backfill_status === 'running'}>
          {progress?.backfill_status === 'running' ? 'Backfill en cours…' : 'Lancer le backfill archive'}
        </button>
        <button onClick={check} className="secondary">Verifier maintenant</button>
      </div>
      {msg && <p className="info">{msg}</p>}
      {progress?.backfill_status === 'error' &&
        <p role="alert" className="error">Erreur backfill : {progress.backfill_error}</p>}
      {progress && (
        <dl className="metrics">
          <dt>Jalon</dt><dd>{progress.milestone_label ?? '—'} {progress.pivot_confirme ? '(pivot confirme)' : ''}</dd>
          <dt>Progression</dt><dd>{progress.progression} %</dd>
          <dt>PV cumulee</dt><dd>{progress.pv_sum_last.toFixed(2)}</dd>
          <dt>Observations</dt><dd>{progress.observations}</dd>
        </dl>
      )}
      <ComparePanel siteId={site.id} polygon={polygon} obs={obs} />
      {alerts.length > 0 && (
        <section>
          <h3>Alertes</h3>
          <ul>{alerts.map(a => <li key={a.id}>{a.message} — {new Date(a.sent_at).toLocaleString('fr-CA')}</li>)}</ul>
        </section>
      )}
      <section>
        <h3>Observations ({obs.length})</h3>
        <div className="obsgrid">
          {obs.map(o => (
            <figure key={o.id}>
              {o.image_url
                ? <img src={`${API}${o.image_url}`} alt={`scene ${o.obs_date}`} loading="lazy" />
                : <div className="noimg">sans image</div>}
              <figcaption>{o.obs_date} — M{o.milestone ?? '?'} (conf. {o.confidence})</figcaption>
            </figure>
          ))}
        </div>
      </section>
    </div>
  )
}

export default function App() {
  const [sites, setSites] = useState<Site[]>([])
  const [selected, setSelected] = useState<Site | null>(null)

  useEffect(() => { api<Site[]>('/sites').then(setSites).catch(() => undefined) }, [])

  return (
    <main>
      <h1>Housat — MVP local</h1>
      <p className="hint">Verification satellite de chantiers : carte OSM, jalons M0-M4, avant/apres.</p>
      {!selected ? (
        <>
          <SiteForm onCreated={(s) => { setSites([s, ...sites]); setSelected(s) }} />
          {sites.length > 0 && (
            <div className="card">
              <h2>Mes chantiers</h2>
              <ul>{sites.map(s => (
                <li key={s.id}>
                  <button className="link" onClick={() => setSelected(s)}>{s.name}</button>
                  <span className="hint"> ({s.backfill_status})</span>
                </li>))}
              </ul>
            </div>
          )}
        </>
      ) : (
        <>
          <button className="link" onClick={() => setSelected(null)}>&larr; Retour</button>
          <Dashboard site={selected} />
        </>
      )}
    </main>
  )
}
