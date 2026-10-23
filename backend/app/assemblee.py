"""Votes de l'Assemblée nationale (17e législature), depuis les données ouvertes officielles.

data.assemblee-nationale.fr publie chaque nuit tous les scrutins (~28 Mo) et les députés en exercice (~5 Mo).
On les télécharge une fois par jour dans backend/data/assemblee/ (ignoré par git), puis on garde en mémoire
un index compact : titre, date, résultat, position de chaque groupe, et la liste des votants par position.
Le chargement démarre en arrière-plan au lancement du serveur (prewarm), car le premier téléchargement est long.
"""
from __future__ import annotations

import json
import threading
import time
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://data.assemblee-nationale.fr/static/openData/repository/17"
FILES = {
    "scrutins.zip": f"{BASE}/loi/scrutins/Scrutins.json.zip",
    "deputes.zip": f"{BASE}/amo/deputes_actifs_mandats_actifs_organes/AMO10_deputes_actifs_mandats_actifs_organes.json.zip",
}
DIR = Path(__file__).resolve().parents[1] / "data" / "assemblee"
MAX_AGE = 24 * 3600
POSITIONS = {"pours": "pour", "contres": "contre", "abstentions": "abstention", "nonVotants": "non-votant"}

_lock = threading.Lock()
_index: dict | None = None


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _download() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        path = DIR / name
        if path.exists() and time.time() - path.stat().st_mtime < MAX_AGE:
            continue
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=600) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        tmp.replace(path)


def _voters(block) -> list[str]:
    if not block:
        return []
    v = block.get("votant") if isinstance(block, dict) else None
    v = v if isinstance(v, list) else [v] if v else []
    return [x["acteurRef"] for x in v if isinstance(x, dict) and "acteurRef" in x]


def _build() -> dict:
    _download()
    groups, deputies = {}, {}
    with zipfile.ZipFile(DIR / "deputes.zip") as z:
        for n in z.namelist():
            if "/organe/" in n:
                o = json.loads(z.read(n))["organe"]
                if o.get("codeType") == "GP":
                    groups[o["uid"]] = o.get("libelleAbrev") or o.get("libelle")
            elif "/acteur/" in n:
                a = json.loads(z.read(n))["acteur"]
                ident = a["etatCivil"]["ident"]
                deputies[a["uid"]["#text"]] = f"{ident['prenom']} {ident['nom']}"
    scrutins = []
    with zipfile.ZipFile(DIR / "scrutins.zip") as z:
        for n in z.namelist():
            if not n.endswith(".json"):
                continue
            s = json.loads(z.read(n))["scrutin"]
            positions, votes = {}, {p: [] for p in POSITIONS.values()}
            g = ((s.get("ventilationVotes") or {}).get("organe") or {}).get("groupes", {}).get("groupe") or []
            for grp in g if isinstance(g, list) else [g]:
                vote = grp.get("vote") or {}
                positions[groups.get(grp.get("organeRef"), grp.get("organeRef"))] = vote.get("positionMajoritaire")
                for key, label in POSITIONS.items():
                    votes[label] += _voters((vote.get("decompteNominatif") or {}).get(key))
            scrutins.append({
                "numero": int(s["numero"]), "date": s["dateScrutin"], "titre": s["titre"],
                "sort": (s.get("sort") or {}).get("code"), "decompte": (s.get("syntheseVote") or {}).get("decompte"),
                "groupes": positions, "votes": {k: ",".join(v) for k, v in votes.items()},
                "_n": _norm(s["titre"]),
            })
    scrutins.sort(key=lambda x: (x["date"], x["numero"]), reverse=True)
    return {"scrutins": scrutins, "deputes": deputies}


def index() -> dict:
    global _index
    with _lock:
        if _index is None:
            _index = _build()
        return _index


def prewarm() -> None:
    """Télécharge et indexe en arrière-plan (appelé au démarrage du serveur)."""
    threading.Thread(target=lambda: _safe(index), daemon=True).start()


def _safe(fn) -> None:
    try:
        fn()
    except Exception as e:  # noqa: BLE001 — l'outil renverra l'erreur au moment de la question
        print(f"[assemblee] préchargement impossible : {e}")


def find_deputy(name: str) -> list[tuple[str, str]]:
    words = [w for w in _norm(name).split() if len(w) > 1]
    return [(uid, full) for uid, full in index()["deputes"].items() if all(w in _norm(full) for w in words)]


def search(keywords: str, deputy: str = "", limit: int = 12) -> dict:
    idx = index()
    words = [w for w in _norm(keywords).split() if len(w) > 2]
    found = [s for s in idx["scrutins"] if all(w in s["_n"] for w in words)] if words else idx["scrutins"]
    who: list[tuple[str, str]] = find_deputy(deputy) if deputy else []
    if deputy and not who:
        return {"erreur": f"aucun député en exercice ne correspond à « {deputy} »", "nb_scrutins": len(found)}
    if deputy and len(who) > 1:
        return {"erreur": "plusieurs députés correspondent, précisez", "candidats": [n for _, n in who[:10]]}
    out = []
    for s in found[:limit]:
        row = {k: s[k] for k in ("numero", "date", "titre", "sort", "decompte", "groupes")}
        row["url"] = f"https://www.assemblee-nationale.fr/dyn/17/scrutins/{s['numero']}"
        if who:
            uid = who[0][0]
            row["vote_du_depute"] = next((p for p, refs in s["votes"].items() if uid in refs.split(",")), "absent ou pas de vote enregistré")
        out.append(row)
    return {"nb_scrutins": len(found), **({"depute": who[0][1]} if who else {}), "scrutins": out}
