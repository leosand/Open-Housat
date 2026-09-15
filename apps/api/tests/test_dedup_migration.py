"""Migration defensive au demarrage : dedup observations + index unique (bases heritees)."""

import os

os.environ["HOUSAT_DATABASE_URL"] = "sqlite:///./test-housat.db"

from sqlalchemy import text  # noqa: E402

import main  # noqa: E402

_INSERT = ("INSERT INTO observations (site_id, obs_date, milestone, pivot_confirme,"
           " confidence, payload, created_at) VALUES"
           " (424242, '2026-09-10', 0, 0, 0.0, '{}', '2026-09-10 08:00:00')")


def test_startup_dedup_puis_index_unique() -> None:
    engine = main.engine
    with engine.begin() as c:
        # Simule une base heritee sans index unique + doublons (meme site, meme date)
        c.execute(text("DROP INDEX IF EXISTS uq_obs_site_date"))
        c.execute(text("DELETE FROM observations WHERE site_id=424242"))
        c.execute(text(_INSERT))
        c.execute(text(_INSERT))
    main.on_startup()  # relance la migration : purge le doublon et recree l'index
    with engine.begin() as c:
        n = c.execute(text("SELECT COUNT(*) FROM observations"
                           " WHERE site_id=424242 AND obs_date='2026-09-10'")).scalar()
    assert n == 1
    with engine.connect() as c:
        import pytest
        with pytest.raises(Exception):
            with c.begin():  # l'index unique recree doit refuser ce doublon
                c.execute(text(_INSERT))
