"""Tests du socle dataset bati (masque OSM rasterise + tuilage) — sans reseau."""

import numpy as np
import pytest
from housat.built_dataset import BBox, built_fraction, built_mask, tiles

BBOX: BBox = (9.7000, 4.0400, 9.7100, 4.0500)   # ~1,1 x 1,1 km
SHAPE = (110, 110)                              # ~10 m/px


def test_masque_couvre_la_part_attendue() -> None:
    """Un carre occupant la moitie de l'emprise doit donner ~50 % de pixels batis."""
    minlon, minlat, maxlon, maxlat = BBOX
    moitie = [(minlon, minlat), ((minlon + maxlon) / 2, minlat),
              ((minlon + maxlon) / 2, (minlat + maxlat) / 2), (minlon, (minlat + maxlat) / 2)]
    m = built_mask([moitie], BBOX, SHAPE)
    assert m.shape == SHAPE and m.dtype == np.uint8
    assert built_fraction(m) == pytest.approx(0.25, abs=0.02)   # quart sud-ouest
    # Grille nord-en-haut : la ligne 0 est au NORD -> le quart sud-ouest est en bas a gauche.
    assert m[-1, 0] == 1 and m[0, -1] == 0


def test_masque_vide_si_aucune_empreinte() -> None:
    m = built_mask([], BBOX, SHAPE)
    assert m.sum() == 0 and built_fraction(m) == 0.0


def test_tuilage_couvre_tout_et_rejette_les_tailles_invalides() -> None:
    """Emprise de 110 px : patches de 64 avec recouvrement 32 -> bords atteints (derniere
    fenetre alignee), et aucun pixel de bord perdu."""
    fen: list[tuple[int, int, int, int]] = list(tiles((110, 110), size=64, overlap=32))
    assert fen, "au moins une fenetre"
    assert fen[0][:2] == (0, 64)
    assert max(r1 for _, r1, _, _ in fen) == 110 and max(c1 for _, _, _, c1 in fen) == 110
    assert min(r0 for r0, *_ in fen) == 0 and min(c0 for *_, c0, _ in fen) == 0
    with pytest.raises(ValueError):
        list(tiles((110, 110), size=32, overlap=32))


def test_emprise_plus_petite_qu_un_patch() -> None:
    """Ilot Housat : 178 m a 10 m = 18 px -> une seule fenetre de la taille de l'emprise."""
    assert list(tiles((18, 18), size=64)) == [(0, 18, 0, 18)]
