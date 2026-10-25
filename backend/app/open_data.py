"""Outils de vérification sur les données ouvertes, en plus de l'INSEE (insee_api.py) et de l'Assemblée (assemblee.py).

Sans clé : Eurostat (comparaisons européennes), data.gouv.fr (producteurs publics certifiés uniquement :
délinquance, immigration, éducation, santé…), Banque mondiale (comparaisons internationales), publications de
l'INSEE (recherche du site insee.fr) et lecture des pages de sites officiels (liste fermée OFFICIAL_HOSTS).
Pas de Wikipédia ni de source modifiable par tous : seulement des producteurs officiels ou des fact-checks publiés.
Avec clé (activés seulement si la variable est définie dans backend/.env) :
Google Fact Check Tools (GOOGLE_FACTCHECK_API_KEY), Légifrance via PISTE (PISTE_CLIENT_ID / PISTE_CLIENT_SECRET).

Chaque fonction renvoie un dict JSON compact ; tools.py les expose au modèle.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import OrderedDict
from html.parser import HTMLParser

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


# ---------------------------------------------------------------- Sites officiels (sans clé)

# Seuls sites lisibles par page_officielle_lire : producteurs de statistiques publiques, administrations,
# institutions de contrôle, Parlement, institutions européennes et internationales.
OFFICIAL_HOSTS = ("insee.fr", "gouv.fr", "vie-publique.fr", "service-public.fr", "ccomptes.fr", "assemblee-nationale.fr",
                  "senat.fr", "banque-france.fr", "conseil-constitutionnel.fr", "conseil-etat.fr", "francetravail.org",
                  "europa.eu", "oecd.org")
PAGE_MAX_BYTES = 3_000_000
PAGE_MAX_CHARS = 8_000


def official_url(url: str) -> bool:
    parts = urllib.parse.urlparse(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and parts.port in (None, 443) and any(host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS)


class _OfficialRedirect(urllib.request.HTTPRedirectHandler):
    """Une redirection ne doit jamais faire sortir de la liste des sites officiels."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not official_url(newurl):
            raise SourceError("redirection vers un site hors de la liste officielle, page non lue")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_official_opener = urllib.request.build_opener(_OfficialRedirect)


class _PageText(HTMLParser):
    """HTML → texte : garde titres, paragraphes et tableaux (cellules séparées par « | »), saute menus et scripts."""
    SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "form", "button", "select", "iframe", "template"}
    BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "br", "table", "ul", "ol",
             "dd", "dt", "caption", "figcaption", "blockquote", "main"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip, self.in_title, self.title, self.parts = 0, False, "", []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self.in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def page_text(html: str) -> tuple[str, list[str]]:
    """Titre et lignes de texte d'une page HTML (testé dans selftest)."""
    parser = _PageText()
    parser.feed(html)
    lines, out = "".join(parser.parts).split("\n"), []
    for line in lines:
        line = re.sub(r"\s+", " ", line).strip(" |")
        if line and (not out or out[-1] != line):
            out.append(line)
    return re.sub(r"\s+", " ", parser.title).strip(), out


def _passages(lines: list[str], keywords: str) -> list[str]:
    """Lignes qui contiennent les mots-clés (racines de 5 lettres) ou les nombres cherchés, avec leur voisine."""
    words = {w[:5] for w in _norm(keywords).split() if len(w) > 2 or w.isdigit()}
    scores = [sum(w in _norm(line) for w in words) for line in lines]
    best = max(scores, default=0)
    if not best:
        return []
    keep: set[int] = set()
    for i, n in enumerate(scores):
        if n >= max(1, best - 1):
            keep.update({i - 1, i, i + 1})
    return [lines[i] for i in sorted(keep) if 0 <= i < len(lines)]


def official_page_read(url: str, keywords: str = "") -> dict:
    if not official_url(url):
        raise SourceError("site hors de la liste des sources officielles : " + ", ".join(OFFICIAL_HOSTS))
    key = "page|" + url
    with _cache_lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        title, lines = hit[1]
    else:
        req = urllib.request.Request(url, headers={**UA, "Accept": "text/html,text/plain"})
        try:
            with _official_opener.open(req, timeout=40) as r:
                ctype = r.headers.get("Content-Type", "")
                if "pdf" in ctype:
                    raise SourceError("document PDF, non lu par cet outil : chercher la page HTML de la publication")
                if "html" not in ctype and "text" not in ctype:
                    raise SourceError(f"format non lisible ({ctype or 'inconnu'})")
                body = r.read(PAGE_MAX_BYTES + 1)
                charset = r.headers.get_content_charset() or "utf-8"
        except urllib.error.HTTPError as e:
            raise SourceError(f"HTTP {e.code} sur {urllib.parse.urlparse(url).hostname}")
        except (urllib.error.URLError, TimeoutError) as e:
            raise SourceError(f"{urllib.parse.urlparse(url).hostname} injoignable ({getattr(e, 'reason', e)})")
        if len(body) > PAGE_MAX_BYTES:
            raise SourceError("page trop volumineuse")
        title, lines = page_text(body.decode(charset, "replace"))
        with _cache_lock:
            _cache[key] = (time.time(), (title, lines))
            while len(_cache) > CACHE_MAX:
                _cache.popitem(last=False)
    found = _passages(lines, keywords) if keywords.strip() else []
    text = "\n".join(found or lines)
    return {"titre": title or url, "url": url, "editeur": urllib.parse.urlparse(url).hostname,
            ("extraits" if found else "texte"): text[:PAGE_MAX_CHARS],
            **({"note": "texte tronqué : préciser `recherche` pour cibler un passage"} if len(text) > PAGE_MAX_CHARS else {}),
            **({"note_recherche": "aucun passage ne contient ces mots : début de la page"} if keywords.strip() and not found else {})}


def insee_publications_search(keywords: str) -> dict:
    """Recherche du site insee.fr : Insee Première, Insee Focus, chiffres clés, tableaux de l'économie française…"""
    payload = {"q": keywords, "start": 0, "rows": 10, "sortFields": [{"field": "score", "order": "desc"}],
               "filters": [], "facetsQuery": []}
    d = _get("https://www.insee.fr/fr/solr/consultation", headers={"Content-Type": "application/json"},
             data=json.dumps(payload).encode())
    docs = [x for x in d.get("documents", []) if x.get("type") == "statistiques" and x.get("id")]
    return {"publications": [{
        "titre": x.get("titre"), "sous_titre": (x.get("sousTitre") or "")[:200],
        "collection": (x.get("famille") or {}).get("libelleFr"), "date": (x.get("dateDiffusion") or "")[:10],
        "url": f"https://www.insee.fr/fr/statistiques/{x['id']}"} for x in docs[:8]],
        "conseil": "Lire une publication avec page_officielle_lire (url + recherche) ; préférer la plus récente."}


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
