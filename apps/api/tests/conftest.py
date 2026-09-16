"""Isolation des tests API : base SQLite NEUVE a chaque execution de pytest.

Sans cela, `test-housat.db` (fichier du depot) **accumulait** les chantiers d'une execution a
l'autre ; le garde-fou anti-doublon de `POST /sites` rejetait alors en **409** des creations que
les tests attendent en **201** (6 faux echecs). Un test doit partir d'un etat vierge.

pytest importe ce fichier AVANT les modules de test : la variable d'environnement est donc posee
avant que `main` ne lise la configuration.
"""

from __future__ import annotations

import os
import pathlib
import tempfile

_DB = pathlib.Path(tempfile.gettempdir()) / f"housat-api-tests-{os.getpid()}.db"
_DB.unlink(missing_ok=True)
os.environ["HOUSAT_DATABASE_URL"] = f"sqlite:///{_DB.as_posix()}"

# Les tests API doivent rester SANS RESEAU : la vue HR du rapport (imagerie d'archive) est
# desactivee ici. Elle est couverte par des tests dedies a fetcher injecte.
os.environ["HOUSAT_REPORT_HR_IMAGE"] = "0"
