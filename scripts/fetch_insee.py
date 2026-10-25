"""Régénère data/referentiel/<thème>.json depuis l'API BDM de l'INSEE et, pour les séries annuelles de
finances publiques absentes de la BDM en base 2020, depuis Eurostat (données notifiées par l'INSEE). Gratuit, sans clé.

Usage : python scripts/fetch_insee.py [thème]      (défaut : tous les thèmes de series.json)

Pour ajouter une série : ajouter une entrée dans data/referentiel/series.json (idbank trouvé sur
https://www.insee.fr/fr/statistiques/serie/<idbank>), relancer ce script, commiter le JSON généré.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from collections import defaultdict
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "referentiel"
API = "https://bdm.insee.fr/series/sdmx/data/SERIES_BDM/{}"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{}?{}"
EUROSTAT_PAGE = "https://ec.europa.eu/eurostat/databrowser/view/{}/default/table?lang=fr"
UNIT_POWER = {"milliers": 3, "milliards": 9}  # puissance de 10 de l'unité du référentiel


def fetch(idbank: str) -> tuple[dict, list[tuple[str, float]], int]:
    """Série INSEE → (attributs, observations triées, puissance de 10 des valeurs)."""
    with urllib.request.urlopen(API.format(idbank), timeout=60) as r:
        root = ET.fromstring(r.read())
    series = next(el for el in root.iter() if el.tag.endswith("Series"))
    obs = []
    for o in series:
        v = o.get("OBS_VALUE")
        if v not in (None, "", "NaN"):
            obs.append((o.get("TIME_PERIOD"), float(v)))
    obs.sort(key=lambda x: x[0])
    return dict(series.attrib), obs, int(series.get("UNIT_MULT", "0"))


def fetch_eurostat(dataset: str, filters: dict) -> tuple[dict, list[tuple[str, float]], int]:
    """Jeu Eurostat filtré sur une seule série (JSON-stat) → (attributs, observations, puissance de 10)."""
    url = EUROSTAT.format(dataset, urllib.parse.urlencode({"format": "JSON", "lang": "FR", **filters}))
    with urllib.request.urlopen(url, timeout=90) as r:
        d = json.load(r)
    if any(n > 1 for i, n in zip(d["id"], d["size"]) if i != "time"):
        raise ValueError(f"{dataset} : les filtres doivent désigner une seule série")
    times = sorted(d["dimension"]["time"]["category"]["index"].items(), key=lambda t: t[1])
    obs = [(p, float(d["value"][str(i)])) for p, i in times if str(i) in d["value"]]
    power = 6 if filters.get("unit") == "MIO_EUR" else 0
    return {"TITLE_FR": d.get("label"), "LAST_UPDATE": (d.get("updated") or "")[:10]}, obs, power


_csv_cache: dict[str, list[dict]] = {}


def fetch_datagouv(resource: str, filters: dict) -> tuple[dict, list[tuple[str, float]], int]:
    """CSV data.gouv (séparateur « ; ») : lignes filtrées, colonne `nombre` additionnée par `annee`."""
    if resource not in _csv_cache:
        with urllib.request.urlopen(f"https://www.data.gouv.fr/fr/datasets/r/{resource}", timeout=120) as r:
            _csv_cache[resource] = list(csv.DictReader(io.StringIO(r.read().decode("utf-8-sig")), delimiter=";"))
    sums: dict[str, float] = defaultdict(float)
    for row in _csv_cache[resource]:
        if all(row.get(k) == v for k, v in filters.items()) and row.get("nombre") not in (None, "", "NA"):
            sums[row["annee"]] += float(row["nombre"].replace(",", "."))
    if not sums:
        raise ValueError(f"{resource} : aucune ligne pour {filters}")
    return {"TITLE_FR": " / ".join(filters.values()), "LAST_UPDATE": date.today().isoformat()}, sorted(sums.items()), 0


def build(theme: str, conf: dict) -> dict:
    out = {"generated_at": date.today().isoformat(), "source": "INSEE BDM (bdm.insee.fr), Eurostat, data.gouv.fr (SSMSI)", "series": {}}
    for key, c in conf.items():
        if c.get("source") == "eurostat":
            attrs, obs, power = fetch_eurostat(c["dataset"], c["filters"])
            ref, url = {"eurostat": c["dataset"]}, EUROSTAT_PAGE.format(c["dataset"])
        elif c.get("source") == "datagouv":
            attrs, obs, power = fetch_datagouv(c["resource"], c["filters"])
            ref, url = {"datagouv_resource": c["resource"]}, c["page"]
        else:
            attrs, obs, power = fetch(c["idbank"])
            ref, url = {"idbank": c["idbank"]}, f"https://www.insee.fr/fr/statistiques/serie/{c['idbank']}"
        scale = c.get("factor", 1) * 10 ** (power - UNIT_POWER.get(c["unit"], power))
        if scale != 1:
            obs = [(p, round(v * scale, 2) + 0.0) for p, v in obs]  # + 0.0 : pas de « -0.0 »
        out["series"][key] = {
            "label": c["label"],
            **ref,
            "insee_title": attrs.get("TITLE_FR"),
            "unit": c["unit"],
            "publisher": c.get("publisher", "INSEE"),
            "url": url,
            "note": c.get("note", ""),
            "last_update": attrs.get("LAST_UPDATE"),
            "observations": obs,
        }
        print(f"  {key:28s} {len(obs):4d} obs  {obs[0][0]} → {obs[-1][0]} = {obs[-1][1]}")
        time.sleep(0.3)
    return out


def main() -> None:
    config = json.loads((REF / "series.json").read_text(encoding="utf-8"))
    themes = sys.argv[1:] or [k for k in config if not k.startswith("_")]
    for theme in themes:
        print(f"[{theme}]")
        data = build(theme, config[theme])
        (REF / f"{theme}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  → data/referentiel/{theme}.json")


if __name__ == "__main__":
    main()
