"""Imagerie haute resolution DATEE (Esri World Imagery Wayback) — la voie « voir sa maison ».
Dated high-resolution imagery (Esri World Imagery Wayback) — the "see your house" track.

Pourquoi : Sentinel-2 (10 m) ne montrera JAMAIS une maison individuelle (1-2 px). Wayback fournit
des prises **sub-metriques DATEES** (couverture ~mensuelle depuis 2018 sur de nombreuses zones),
gratuites et sans cle — donc un VRAI avant/apres lisible. Ex. Douala : 121 dates de 2018-03 a 2026-08.

Licence : Esri World Imagery Wayback — visualisation autorisee, attribution requise ; la
redistribution/cache est restreinte (a valider avant embarquement en rapport vendu).

Le fournisseur est injectable (`fetcher`) -> testable sans reseau.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from housat.imagery.basemap import (
    BBox,
    Fetcher,
    _http_get,
    choose_zoom,
    lonlat_to_global_px,
    lonlat_to_tile,
    stitch_xyz,
    validate_bbox,
)

CONFIG_URL = "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
ATTRIBUTION = "Esri, Maxar, Earthstar Geographics — World Imagery Wayback"
LICENCE = ("Esri World Imagery Wayback : visualisation autorisee (attribution requise) ; "
           "redistribution/cache restreints — a valider avant embarquement en rapport vendu.")

# Seuil de taille de tuile : une tuile plus petite est un placeholder vide (« no imagery »).
_MIN_TILE_BYTES = 1500

_releases_cache: list["Release"] | None = None
_dates_cache: dict[tuple, list[str]] = {}  # (bbox, zoom) -> dates disponibles (sonde couteuse)


@dataclass(frozen=True)
class Release:
    date: str          # YYYY-MM-DD
    release_id: str    # identifiant interne Wayback (ex. "32246")
    template: str      # gabarit de tuiles avec {z}/{y}/{x}

    def url(self, z: int, x: int, y: int) -> str:
        return self.template.format(z=z, y=y, x=x)


def _parse_releases(raw: dict) -> list[Release]:
    """Extrait les releases datees du JSON Wayback (tri croissant par date)."""
    out: list[Release] = []
    for entry in raw.values():
        title = str(entry.get("itemTitle", ""))
        url = str(entry.get("itemURL", ""))
        m = re.search(r"Wayback (\d{4}-\d{2}-\d{2})", title)
        rid = re.search(r"/tile/(\d+)/", url)
        if not m or not rid:
            continue
        tmpl = (url.replace("{level}", "{z}").replace("{row}", "{y}").replace("{col}", "{x}"))
        out.append(Release(date=m.group(1), release_id=rid.group(1), template=tmpl))
    out.sort(key=lambda r: r.date)
    return out


def load_releases(*, fetcher: Fetcher | None = None, refresh: bool = False) -> list[Release]:
    """Charge (et memoise) les releases Wayback datees."""
    global _releases_cache
    if _releases_cache is None or refresh:
        import json

        data = (fetcher or _http_get)(CONFIG_URL)
        _releases_cache = _parse_releases(json.loads(data))
    return _releases_cache


def release_for(date: str, *, fetcher: Fetcher | None = None) -> Release | None:
    """Release Wayback correspondant a une date YYYY-MM-DD (ou None)."""
    return next((r for r in load_releases(fetcher=fetcher) if r.date == date), None)


def latest_date_at_or_before(bbox: BBox, until: str, *, zoom: int = 16, max_probes: int = 4,
                             fetcher: Fetcher | None = None) -> str | None:
    """Date Wayback la plus recente <= `until` (YYYY-MM-DD) ayant une couverture REELLE.

    Sonde **ciblee et BORNEE** : parcours du plus recent au plus ancien, arret au premier hit, et
    au plus `max_probes` essais. Un fournisseur lent ne doit jamais bloquer la generation d'un
    rapport (au-dela, on rend le rapport SANS vue HR plutot que d'attendre).
    """
    b = validate_bbox(bbox)
    candidates = [r for r in load_releases(fetcher=fetcher) if r.date <= until]
    fetch = fetcher or _http_get
    cx, cy = lonlat_to_tile((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, zoom)
    for rel in sorted(candidates, key=lambda r: r.date, reverse=True)[:max_probes]:
        try:
            if len(fetch(rel.url(zoom, cx, cy))) > _MIN_TILE_BYTES:
                return rel.date
        except Exception:  # noqa: BLE001 — pas de couverture a cette date : on continue
            continue
    return None


def available_dates(bbox: BBox, *, zoom: int = 18, max_workers: int = 16,
                    fetcher: Fetcher | None = None) -> list[str]:
    """Dates (YYYY-MM-DD) ou une tuile REELLE existe au centre de `bbox`, au zoom de DETAIL.

    `zoom=18` (et non 16) : on ne propose que les dates dont la couverture est fine — sinon la
    carte affiche des trous/du flou des qu'on zoome. Resultat **memoise par emprise** (la sonde
    coute ~196 requetes : on ne la refait pas a chaque affichage de page).
    """
    b = validate_bbox(bbox)
    key = (b, zoom)
    if key in _dates_cache:
        return _dates_cache[key]
    releases = load_releases(fetcher=fetcher)
    fetch = fetcher or _http_get
    cx, cy = lonlat_to_tile((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, zoom)

    def probe(r: Release) -> str | None:
        try:
            return r.date if len(fetch(r.url(zoom, cx, cy))) > _MIN_TILE_BYTES else None
        except Exception:  # noqa: BLE001 — absence de couverture = resultat, pas une panne
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        found = list(ex.map(probe, releases))
    dates = [d for d in found if d]
    _dates_cache[key] = dates
    return dates


def _native_size(bbox: BBox, zoom: int) -> int:
    """Pixels NATIFS couvrant la bbox — zone **recadree** (pas la tuile entiere), sinon on
    re-suréchantillonne. Borne l'upsampling = nettete maximale gratuite."""
    gx0, gy0 = lonlat_to_global_px(bbox[0], bbox[3], zoom)
    gx1, gy1 = lonlat_to_global_px(bbox[2], bbox[1], zoom)
    return max(1, int(round(max(gx1 - gx0, gy1 - gy0))))


def fetch_wayback(bbox: BBox, date: str, *, size: int | None = None, zoom: int | None = None,
                  fetcher: Fetcher | None = None) -> bytes:
    """Image HR (PNG) de l'emprise pour la date Wayback donnee.

    `size=None` -> taille **NATIVE** (1 px image = 1 px source, AUCUN sur-echantillonnage : c'est la
    nettete maximale gratuite). Une `size` fournie est **bornee au natif** (jamais d'upsampling, qui
    ne fait que flouter). Un zoom trop profond sans couverture retombe automatiquement au zoom inferieur.
    """
    b = validate_bbox(bbox)
    releases = load_releases(fetcher=fetcher)
    match = next((r for r in releases if r.date == date), None)
    if match is None:
        raise ValueError(f"date Wayback inconnue: {date!r}")
    # max_zoom=19 = profondeur NATIVE Esri Wayback (~0,3 m/px). Le defaut de `choose_zoom` (17)
    # plafonnait a ~1,2 m/px — c'etait LA cause du flou residuel malgre le rendu « natif ».
    start = zoom if zoom is not None else choose_zoom(b, max_tiles=9, max_zoom=19)
    last: Exception | None = None
    for zz in range(start, 11, -1):
        native = _native_size(b, zz)
        eff = native if size is None else min(size, native)  # JAMAIS au-dessus du natif
        try:
            return stitch_xyz(b, eff, match.template, fetcher=fetcher, zoom=zz)
        except Exception as exc:  # noqa: BLE001 — trou de couverture : on redescend de zoom
            last = exc
    raise RuntimeError(f"aucune tuile disponible pour {date} sur cette emprise ({last})")
