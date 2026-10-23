"""Outils de vérification sur les données ouvertes, en plus de l'INSEE (insee_api.py) et de l'Assemblée (assemblee.py).

Sans clé : Eurostat (comparaisons européennes), data.gouv.fr (producteurs publics certifiés uniquement :
délinquance, immigration, éducation, santé…), Banque mondiale (comparaisons internationales).
Pas de Wikipédia ni de source modifiable par tous : seulement des producteurs officiels ou des fact-checks publiés.
Avec clé (activés seulement si la variable est définie dans backend/.env) :
Google Fact Check Tools (GOOGLE_FACTCHECK_API_KEY), Légifrance via PISTE (PISTE_CLIENT_ID / PISTE_CLIENT_SECRET).

Chaque fonction renvoie un dict JSON compact ; tools.py les expose au modèle.
"""
from __future__ import annotations

import json
import os
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import OrderedDict

UA = {"User-Agent": "VerifPol/0.1 (hackathon fact-checking; contact via GitHub bab6429/factcheck-politique)"}
_cache: OrderedDict[str, tuple[float, object]] = OrderedDict()
_cache_lock = threading.Lock()
CACHE_TTL, CACHE_MAX = 6 * 3600, 300


class SourceError(RuntimeError):
    pass


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _rank(items: list, keywords: str, key) -> list:
    """Classe par nombre de mots-clés présents (racines de 5 lettres, pour « impôts » / « impôt »)."""
    words = {w[:5] for w in _norm(keywords).split() if len(w) > 2}
    scored = [(sum(w in _norm(key(it)) for w in words), it) for it in items]
    best = max((n for n, _ in scored), default=0)
    return [it for n, it in sorted(scored, key=lambda x: -x[0]) if n and n >= max(1, best - 1)]


def _get(url: str, headers: dict | None = None, data: bytes | None = None, timeout: int = 40, raw: bool = False):
    key = url if data is None else url + "|" + data.decode(errors="ignore")
    with _cache_lock:
        if (hit := _cache.get(key)) and time.time() - hit[0] < CACHE_TTL:
            _cache.move_to_end(key)
            return hit[1]
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        raise SourceError(f"HTTP {e.code} sur {urllib.parse.urlparse(url).hostname}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise SourceError(f"{urllib.parse.urlparse(url).hostname} injoignable ({getattr(e, 'reason', e)})")
    value = body.decode("utf-8", "replace") if raw else json.loads(body)
    with _cache_lock:
        _cache[key] = (time.time(), value)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return value


# ---------------------------------------------------------------- Eurostat

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination"
EUROSTAT_FREQUENT = {
    "gov_10a_taxag": "prélèvements obligatoires (impôts + cotisations) en % du PIB — « pays le plus taxé » "
                     "(na_item=D2_D5_D91_D61_M_D995, sector=S13_S212, unit=PC_GDP)",
    "gov_10dd_edpt1": "déficit et dette publics, notification de Maastricht (sector=S13, unit=PC_GDP ; na_item=B9 "
                      "déficit/excédent, GD dette brute)",
    "gov_10a_exp": "dépenses publiques par fonction (cofog99, unit=PC_GDP)",
    "une_rt_a": "taux de chômage annuel (age=Y15-74, sex=T, unit=PC_ACT)",
    "prc_hicp_manr": "inflation mensuelle sur un an, IPCH (coicop=CP00)",
    "nama_10_gdp": "PIB (na_item=B1GQ, unit=CP_MEUR ou CLV_PCH_PRE pour la croissance)",
    "migr_asyappctza": "demandes d'asile (applicant=FRST, age=TOTAL, sex=T)",
    "ilc_li02": "taux de risque de pauvreté (indic_il=LI_R_MD60, age=TOTAL, sex=T, unit=PC)",
}
_toc: list[tuple[str, str]] | None = None


def eurostat_search(keywords: str) -> dict:
    global _toc
    if _toc is None:
        text = _get(f"{EUROSTAT}/catalogue/toc/txt?lang=fr", raw=True, timeout=90)
        rows = [line.split("\t") for line in text.splitlines()[1:]]
        _toc = [(r[1].strip('"'), r[0].strip('"').strip()) for r in rows if len(r) > 2 and r[2].strip('"') in ("dataset", "table")]
    hits = _rank(_toc, keywords, key=lambda item: item[1])
    return {"nb": len(hits), "jeux": [{"code": c, "titre": t} for c, t in hits[:25]],
            "frequents": EUROSTAT_FREQUENT}


def eurostat_read(dataset: str, filters: dict | None = None, countries: list[str] | None = None, since: str = "") -> dict:
    params = [("format", "JSON"), ("lang", "FR")]
    for geo in countries or ["FR", "DE", "IT", "ES", "EU27_2020"]:
        params.append(("geo", geo))
    for k, v in (filters or {}).items():
        for item in v if isinstance(v, list) else [v]:
            params.append((k, str(item)))
    if since:
        params.append(("sinceTimePeriod", since))
    d = _get(f"{EUROSTAT}/statistics/1.0/data/{urllib.parse.quote(dataset)}?{urllib.parse.urlencode(params)}", timeout=90)
    ids, sizes, dims = d["id"], d["size"], d["dimension"]
    labels = {i: {code: dims[i]["category"].get("label", {}).get(code, code)
                  for code in sorted(dims[i]["category"]["index"], key=lambda c: dims[i]["category"]["index"][c])} for i in ids}
    rows = []
    for flat, value in list(d.get("value", {}).items())[:300]:
        flat, coords = int(flat), {}
        for i, size in zip(reversed(ids), reversed(sizes)):
            coords[i] = list(labels[i])[flat % size]
            flat //= size
        rows.append({**{i: coords[i] for i in ids if sizes[ids.index(i)] > 1 or i in ("geo", "time")}, "valeur": value})
    varying = {i: dict(list(labels[i].items())[:20]) for i in ids if len(labels[i]) > 1 and i not in ("geo", "time")}
    return {"titre": d.get("label"), "mis_a_jour": d.get("updated"),
            "fixes": {i: next(iter(labels[i].values())) for i in ids if len(labels[i]) == 1},
            "a_preciser": varying,  # dimensions encore ouvertes : les fixer avec `filtres` pour un résultat net
            "lignes": rows, "url": f"https://ec.europa.eu/eurostat/databrowser/view/{dataset}/default/table?lang=fr"}


# ---------------------------------------------------------------- data.gouv.fr

# Sur data.gouv.fr, n'importe qui peut publier. On ne garde que les producteurs publics certifiés :
# ministères, opérateurs, collectivités (badges « certified » + « public-service » ou « local-authority »).
PUBLIC_BADGES = {"public-service", "local-authority"}


def _certified_public(org: dict | None) -> bool:
    kinds = {b.get("kind") for b in (org or {}).get("badges", [])}
    return "certified" in kinds and bool(kinds & PUBLIC_BADGES)


def datagouv_search(keywords: str) -> dict:
    d = _get(f"https://www.data.gouv.fr/api/1/datasets/?{urllib.parse.urlencode({'q': keywords, 'page_size': 30})}")
    kept = [ds for ds in d.get("data", []) if _certified_public(ds.get("organization"))]
    out = [{
        "titre": ds["title"], "producteur": ds["organization"].get("name"),
        "mis_a_jour": (ds.get("last_update") or "")[:10], "url": ds.get("page"),
        "ressources": [{"id": r["id"], "titre": r["title"][:120], "format": r.get("format")} for r in ds.get("resources", [])[:8]],
    } for ds in kept[:6]]
    return {"jeux": out, "ecartes_non_officiels": len(d.get("data", [])) - len(kept),
            "conseil": "Lire une ressource CSV/XLSX avec datagouv_lire_ressource (id de ressource)."}


def datagouv_read(resource_id: str, filters: dict | None = None, page_size: int = 30) -> dict:
    rid = urllib.parse.quote(resource_id)
    # Même règle à la lecture : la ressource doit appartenir à un jeu d'un producteur public certifié.
    dataset_id = _get(f"https://www.data.gouv.fr/api/2/datasets/resources/{rid}/").get("dataset_id")
    dataset = _get(f"https://www.data.gouv.fr/api/1/datasets/{urllib.parse.quote(str(dataset_id))}/") if dataset_id else {}
    if not _certified_public(dataset.get("organization")):
        raise SourceError("ressource écartée : son producteur n'est pas un organisme public certifié")
    base = f"https://tabular-api.data.gouv.fr/api/resources/{rid}"
    params = {"page_size": str(min(int(page_size or 30), 50))}
    for col, val in (filters or {}).items():
        params[f"{col}__exact"] = str(val)
    try:
        profile = _get(f"{base}/profile/")
    except SourceError:
        raise SourceError("ressource absente de l'API tabulaire (seuls les CSV/XLSX récents y sont) ; essayez une autre ressource du jeu")
    data = _get(f"{base}/data/?{urllib.parse.urlencode(params)}")
    columns = list((profile.get("profile") or {}).get("header") or (data.get("data") or [{}])[0].keys())
    return {"colonnes": columns, "nb_lignes_total": (data.get("meta") or {}).get("total"),
            "lignes": data.get("data", [])[:50], "url": f"https://www.data.gouv.fr/fr/datasets/r/{resource_id}",
            "conseil": "Filtrer avec `filtres` {colonne: valeur exacte} pour cibler une année, un territoire…"}


# ---------------------------------------------------------------- Banque mondiale

WB = "https://api.worldbank.org/v2"
WB_FREQUENT = {
    "GC.TAX.TOTL.GD.ZS": "recettes fiscales de l'État, % du PIB", "GC.DOD.TOTL.GD.ZS": "dette de l'État, % du PIB",
    "NY.GDP.MKTP.KD.ZG": "croissance du PIB, %", "NY.GDP.PCAP.CD": "PIB par habitant, $",
    "SL.UEM.TOTL.ZS": "chômage (OIT), %", "FP.CPI.TOTL.ZG": "inflation, %", "SP.POP.TOTL": "population",
    "SE.XPD.TOTL.GD.ZS": "dépense d'éducation, % du PIB", "SH.XPD.CHEX.GD.ZS": "dépense de santé, % du PIB",
    "EN.GHG.CO2.PC.CE.AR5": "CO2 par habitant", "MS.MIL.XPND.GD.ZS": "dépense militaire, % du PIB",
}
_wb_indicators: list[tuple[str, str]] | None = None


def worldbank_search(keywords: str) -> dict:
    global _wb_indicators
    if _wb_indicators is None:
        d = _get(f"{WB}/sources/2/indicators?format=json&per_page=3000", timeout=90)
        _wb_indicators = [(i["id"], i["name"]) for i in (d[1] if isinstance(d, list) and len(d) > 1 else [])]
    hits = _rank(_wb_indicators, keywords, key=lambda item: item[1])
    return {"indicateurs": [{"id": i, "nom": n} for i, n in hits[:25]], "frequents": WB_FREQUENT,
            "conseil": "Les noms sont en anglais : chercher « tax revenue », « unemployment », « debt »…"}


def worldbank_read(indicator: str, countries: list[str] | None = None, since: str = "2015") -> dict:
    iso = ";".join(countries or ["FRA", "DEU", "ITA", "ESP", "GBR", "USA", "EUU"])
    d = _get(f"{WB}/country/{urllib.parse.quote(iso)}/indicator/{urllib.parse.quote(indicator)}"
             f"?format=json&per_page=500&date={urllib.parse.quote(since or '2015')}:2030")
    if not isinstance(d, list) or len(d) < 2 or not d[1]:
        raise SourceError(f"aucune donnée pour l'indicateur {indicator}")
    rows = [{"pays": r["country"]["value"], "annee": r["date"], "valeur": r["value"]} for r in d[1] if r["value"] is not None]
    return {"indicateur": d[1][0]["indicator"]["value"], "lignes": rows[:200],
            **({} if rows else {"note": "aucune valeur publiée pour ces pays et ces années : essayer un autre indicateur ou Eurostat"}),
            "url": f"https://donnees.banquemondiale.org/indicateur/{indicator}"}


# ---------------------------------------------------------------- Google Fact Check Tools (clé)

def factcheck_search(query: str) -> dict:
    key = os.getenv("GOOGLE_FACTCHECK_API_KEY")
    d = _get("https://factchecktools.googleapis.com/v1alpha1/claims:search?"
             + urllib.parse.urlencode({"query": query, "languageCode": "fr", "pageSize": 8, "key": key}))
    out = []
    for c in d.get("claims", []):
        for r in c.get("claimReview", [])[:2]:
            out.append({"affirmation": c.get("text"), "auteur": c.get("claimant"), "date": (c.get("claimDate") or "")[:10],
                        "verdict": r.get("textualRating"), "media": (r.get("publisher") or {}).get("name"),
                        "titre": r.get("title"), "url": r.get("url")})
    return {"fact_checks": out}


# ---------------------------------------------------------------- Légifrance via PISTE (clés)

_piste_token: tuple[float, str] | None = None


def _piste() -> str:
    global _piste_token
    if _piste_token and _piste_token[0] > time.time():
        return _piste_token[1]
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": os.getenv("PISTE_CLIENT_ID"),
                                   "client_secret": os.getenv("PISTE_CLIENT_SECRET"), "scope": "openid"}).encode()
    req = urllib.request.Request("https://oauth.piste.gouv.fr/api/oauth/token", data=body,
                                 headers={**UA, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        tok = json.loads(r.read())
    _piste_token = (time.time() + int(tok.get("expires_in", 3600)) - 60, tok["access_token"])
    return _piste_token[1]


def _legifrance(path: str, payload: dict) -> dict:
    url = f"https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/{path}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={
        **UA, "Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {_piste()}"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SourceError(f"Légifrance : HTTP {e.code}")


def legifrance_search(query: str, fond: str = "ALL") -> dict:
    d = _legifrance("search", {"fond": fond, "recherche": {
        "champs": [{"typeChamp": "ALL", "operateur": "ET",
                    "criteres": [{"typeRecherche": "TOUS_LES_MOTS_DANS_UN_CHAMP", "valeur": query, "operateur": "ET"}]}],
        "pageNumber": 1, "pageSize": 6, "operateur": "ET", "sort": "PERTINENCE", "typePagination": "DEFAUT"}})
    out = []
    for r in d.get("results", [])[:6]:
        titles = r.get("titles") or [{}]
        out.append({"titre": titles[0].get("title"), "id": titles[0].get("id") or titles[0].get("cid"),
                    "nature": r.get("nature"), "date": r.get("date"),
                    "extraits": [s.get("value", "")[:300] for s in (r.get("sections") or [])[:2]]})
    return {"resultats": out, "conseil": "Lire le texte exact d'un article avec legifrance_article (id LEGIARTI…)."}


def legifrance_article(article_id: str) -> dict:
    d = _legifrance("consult/getArticle", {"id": article_id})
    a = d.get("article") or {}
    return {"id": a.get("id"), "numero": a.get("num"), "etat": a.get("etat"), "texte": (a.get("texte") or "")[:4000],
            "url": f"https://www.legifrance.gouv.fr/codes/article_lc/{a.get('id')}"}
