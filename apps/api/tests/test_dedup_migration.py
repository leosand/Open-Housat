"""Migration defensive au demarrage : dedup observations + index unique (bases heritees).

Le scenario teste est une base HERITEE : table `observations` creee AVANT que le
modele n'ajoute `UniqueConstraint(site_id, obs_date)` — donc sans contrainte de
table ni index unique — et contenant deja des doublons. La migration de demarrage
doit (1) purger les doublons et (2) recreer l'index unique qui les interdit ensuite.

Note V&V : supprimer le seul index nomme ne suffit pas a simuler cet heritage —
`create_all` materialise aussi la contrainte de table (index automatique SQLite
`sqlite_autoindex_observations_*`), qui rejette le doublon avant meme la migration.
D'ou la reconstruction explicite de la table dans sa forme historique.
"""

import os

os.environ["HOUSAT_DATABASE_URL"] = "sqlite:///./test-housat.db"

import main  # noqa: E402
from sqlalchemy import text  # noqa: E402

_INSERT = ("INSERT INTO observations (site_id, obs_date, milestone, pivot_confirme,"
           " confidence, payload, created_at) VALUES"
           " (424242, '2026-09-10', 0, 0, 0.0, '{}', '2026-09-10 08:00:00')")

# Forme historique : AUCUNE contrainte unique, aucun index uq_obs_site_date.
_LEGACY_TABLE = """
CREATE TABLE observations (
    id INTEGER NOT NULL,
    site_id INTEGER NOT NULL,
    obs_date VARCHAR NOT NULL,
    milestone INTEGER,
    pivot_confirme BOOLEAN NOT NULL,
    confidence FLOAT NOT NULL,
    payload VARCHAR NOT NULL,
    image_png BLOB,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id)
)
"""


def _unique_observations_objects(c) -> list:
    """Objets de schema portant l'unicite (site_id, obs_date) sur la table courante."""
    rows = c.execute(text("SELECT name, sql FROM sqlite_master"
                          " WHERE tbl_name='observations'")).fetchall()
    return [(name or "", (sql or "").lower())
            for name, sql in rows if "site_id, obs_date" in (sql or "").lower()]


def test_startup_dedup_puis_index_unique() -> None:
    engine = main.engine
    with engine.begin() as c:
        # Base heritee : table sans contrainte unique, avec deux doublons.
        c.execute(text("DROP TABLE IF EXISTS observations"))
        c.execute(text(_LEGACY_TABLE))
        assert _unique_observations_objects(c) == [], "l'heritage doit n'avoir aucune unicite"
        c.execute(text(_INSERT))
        c.execute(text(_INSERT))

    main.on_startup()  # migration : purge le doublon, puis (re)cree l'index unique

    with engine.begin() as c:
        n = c.execute(text("SELECT COUNT(*) FROM observations"
                           " WHERE site_id=424242 AND obs_date='2026-09-10'")).scalar()
        assert n == 1, f"la purge doit ne laisser qu'une ligne, obtenu {n}"
        # L'index unique doit exister ET couvrir exactement (site_id, obs_date).
        assert any("uq_obs_site_date" in name
                   for name, _ in _unique_observations_objects(c)), "index unique absent"

    import pytest
    from sqlalchemy.exc import IntegrityError

    # L'index unique recree doit refuser le doublon.
    with engine.connect() as c, pytest.raises(IntegrityError), c.begin():
        c.execute(text(_INSERT))
