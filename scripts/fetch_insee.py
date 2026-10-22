"""Régénère data/referentiel/<thème>.json depuis l'API BDM de l'INSEE (gratuite, sans clé).

Usage : python scripts/fetch_insee.py [thème]      (défaut : tous les thèmes de series.json)

Pour ajouter une série : ajouter une entrée dans data/referentiel/series.json (idbank trouvé sur
https://www.insee.fr/fr/statistiques/serie/<idbank>), relancer ce script, commiter le JSON généré.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "referentiel"
API = "https://bdm.insee.fr/series/sdmx/data/SERIES_BDM/{}"


def fetch(idbank: str) -> tuple[dict, list[tuple[str, float]]]:
    with urllib.request.urlopen(API.format(idbank), timeout=60) as r:
        root = ET.fromstring(r.read())
    series = next(el for el in root.iter() if el.tag.endswith("Series"))
    mult = int(series.get("UNIT_MULT", "0"))
    obs = []
    for o in series:
        v = o.get("OBS_VALUE")
        if v not in (None, "", "NaN"):
            obs.append((o.get("TIME_PERIOD"), float(v), mult))
    obs.sort(key=lambda x: x[0])
    return dict(series.attrib), [(p, v) for p, v, _ in obs]


def build(theme: str, conf: dict) -> dict:
    out = {"generated_at": date.today().isoformat(), "source": "INSEE BDM (bdm.insee.fr), API SDMX", "series": {}}
    for key, c in conf.items():
        attrs, obs = fetch(c["idbank"])
        mult = int(attrs.get("UNIT_MULT", "0"))
        if c["unit"] == "milliers" and mult == 0:
            obs = [(p, round(v / 1000, 1)) for p, v in obs]
        out["series"][key] = {
            "label": c["label"],
            "idbank": c["idbank"],
            "insee_title": attrs.get("TITLE_FR"),
            "unit": c["unit"],
            "publisher": c.get("publisher", "INSEE"),
            "url": f"https://www.insee.fr/fr/statistiques/serie/{c['idbank']}",
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
