"""Emprises de batiments (OpenStreetMap / Overpass) — superposition d'identification.
Building footprints (OSM/Overpass) — identification overlay.

Complement **licence-propre** a l'imagerie Esri : les emprises OSM sont sous **ODbL** (redistribuables
avec attribution), donc utilisables dans un rapport livre — a la difference des tuiles Esri. Gratuit,
sans cle. Servi en **GeoJSON** et dessine par le moteur de carte (aucune rasterisation serveur).

`footprint_stats` tire de ces emprises la **caracterisation formelle** de l'emprise analysee
(nombre de batiments, part batie, emprise moyenne) : c'est ce qui permet de dire si le carre
suit UNE maison ou un paté de maisons, au lieu de le supposer.

Fournisseur injectable (`fetcher`) -> testable sans reseau.
"""

from __future__ import annotations

import json
import math

import httpx

from housat.imagery.basemap import USER_AGENT, BBox, Fetcher, validate_bbox

OVERPASS_URL = "https://overpass-api.de/api/interpreter"  # conserve pour compat (miroir primaire)
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",  # miroir de repli (mesure : 200 en 0,8 s)
)
ATTRIBUTION = "Emprises : © OpenStreetMap contributors (ODbL)"


def _overpass_query(query: str, *, rotate: int = 0) -> bytes:
    """Interroge Overpass, endpoints essays dans l'ordre (permutation possible via `rotate`).

    Overpass est **intermittent** : mesures du 2026-09-16 sur le meme endpoint et la meme requete —
    GET 200 en 1,4 s (65 batiments) puis POST 504 en 8,5 s, puis l'inverse, et un quartier de 1 km
    qui repond 200 avec **zero element** avant de renvoyer du HTML. L'API transformait cet echec en
    collection vide, donc la superposition OSM etait **silencieusement vide** (la case « Emprises »
    semblait morte) : ici l'echec **remonte** pour etre dit a l'utilisateur.
    """
    last: Exception | None = None
    urls = OVERPASS_URLS[rotate:] + OVERPASS_URLS[:rotate]
    for url in urls:
        try:
            with httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT},
                              follow_redirects=True) as c:
                r = c.get(url, params={"data": query})
                r.raise_for_status()
                return r.content
        except Exception as exc:  # noqa: BLE001 — on tente l'endpoint suivant
            last = exc
    raise RuntimeError(f"Overpass indisponible : {last}")


def fetch_buildings(bbox: BBox, *, fetcher: Fetcher | None = None) -> list[list[tuple[float, float]]]:
    """Emprises (polygones lon/lat) des batiments tagges `building` dans l'emprise (OSM Overpass).

    Une reponse **vide** est reessayee (miroir suivant) : Overpass sature renvoie `200` avec zero
    element, ce qui est indistinguishable d'une zone sans bati. Mesure du 2026-09-16 : le carre de
    178 m de Douala a renvoye 0 polygone alors qu'il en contient **65** (49,8 % de surface batie),
    et un quartier de 1 km a renvoye 0 deux fois de suite avant d'echouer sur du HTML — une
    conclusion « aucun batiment » tiree de la premiere reponse etait FAUSSE.
    """
    minlon, minlat, maxlon, maxlat = validate_bbox(bbox)
    query = (f'[out:json][timeout:25];way["building"]({minlat},{minlon},{maxlat},{maxlon});'
             "out geom;")
    if fetcher is not None:  # fetcher injecte (tests hors ligne) : une seule tentative
        return _polys_from(json.loads(fetcher(query)))
    polys: list[list[tuple[float, float]]] = []
    for essai in range(2):   # 1re tentative, puis miroir si la reponse est vide
        polys = _polys_from(json.loads(_overpass_query(query, rotate=essai)))
        if polys:
            break
    return polys


def _polys_from(data: dict) -> list[list[tuple[float, float]]]:
    """Elements Overpass -> anneaux lon/lat (les ways de moins de 3 sommets sont ignores)."""
    out: list[list[tuple[float, float]]] = []
    for el in data.get("elements", []):
        geom = el.get("geometry") or []
        if len(geom) >= 3:
            out.append([(float(g["lon"]), float(g["lat"])) for g in geom])
    return out


def footprint_stats(polys: list[list[tuple[float, float]]], bbox: BBox) -> dict[str, float]:
    """Caracterisation formelle de l'emprise a partir des emprises OSM.

    Les emprises sont **coupees a l'emprise analysee** (shapely) : Overpass renvoie la geometrie
    COMPLETE des ways qui touchent la zone, donc un immeuble voisin apporterait des m2 hors du
    carre et la part batie pourrait depasser 100 %. Projection equirectangulaire locale (lon x
    cos(lat), lat) : suffisant a l'echelle d'un chantier, sans dependance de reprojection.
    """
    from shapely.geometry import Polygon, box

    minlon, minlat, maxlon, maxlat = bbox
    kx = 111320.0 * math.cos(math.radians((minlat + maxlat) / 2))
    ky = 111320.0
    clip = box(minlon * kx, minlat * ky, maxlon * kx, maxlat * ky)

    aires: list[float] = []
    for pts in polys:
        g = Polygon([(x * kx, y * ky) for x, y in pts])
        if not g.is_valid:
            g = g.buffer(0)  # anneaux auto-intersectants (saisie OSM) : on repare au lieu d'echouer
        inter = g.intersection(clip)
        if not inter.is_empty and inter.area > 20.0:  # ignore un simple coin qui touche la zone
            aires.append(inter.area)

    total = sum(aires)
    emprise = clip.area
    return {
        "count": len(aires),
        "built_m2": round(total),
        "built_frac": round(min(total / emprise, 1.0), 3) if emprise else 0.0,
        "mean_m2": round(total / len(aires)) if aires else 0,
        "area_m2": round(emprise),
    }
