"""Registre des outils de vérification exposés au modèle (Gemini ou Claude).

Chaque outil : nom, description, schéma JSON des arguments, et une fonction qui renvoie un dict.
`run_tool` exécute, sérialise le résultat et liste les sources consultées (titre + URL), qui servent à
vérifier que les sources citées par le modèle existent vraiment. Les outils à clé n'apparaissent que si
la clé est définie dans backend/.env.
"""
from __future__ import annotations

import json
import os
from typing import Callable

from . import assemblee, insee_api, open_data


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


S = {"type": "string"}
FILTERS = {"type": "object", "description": "dimension ou colonne → valeur (ex. {\"na_item\": \"TAX_NSC\"})",
           "additionalProperties": {"type": "string"}}
COUNTRIES = {"type": "array", "items": S}


def _source(title: str, url: str | None) -> list[dict]:
    return [{"title": title, "url": url}] if url else []


# (définition, fonction, sources consultées à partir du résultat, variable d'env requise)
_TOOLS: list[tuple[dict, Callable[[dict], object], Callable[[dict, object], list[dict]], str | None]] = [
    ({"name": "eurostat_chercher",
      "description": "Cherche des jeux de données Eurostat (statistiques européennes, comparaisons entre pays de l'UE) par "
                     "mots-clés en français. Renvoie aussi une liste de jeux fréquents (prélèvements obligatoires, dette, chômage…).",
      "input_schema": _obj({"mots_cles": S}, ["mots_cles"])},
     lambda a: open_data.eurostat_search(a["mots_cles"]), lambda a, r: [], None),
    ({"name": "eurostat_lire",
      "description": "Lit un jeu Eurostat pour plusieurs pays (codes Eurostat : FR, DE, IT, ES, EU27_2020…). Fixer les autres "
                     "dimensions avec `filtres` ; la réponse liste les dimensions encore ouvertes dans `a_preciser`. `depuis` : année.",
      "input_schema": _obj({"jeu": S, "filtres": FILTERS, "pays": COUNTRIES, "depuis": S}, ["jeu"])},
     lambda a: open_data.eurostat_read(a["jeu"], a.get("filtres"), a.get("pays"), a.get("depuis", "")),
     lambda a, r: _source(f"Eurostat – {r.get('titre')}", r.get("url")), None),
    ({"name": "datagouv_chercher",
      "description": "Cherche des jeux de données publics sur data.gouv.fr, publiés par des organismes publics certifiés "
                     "seulement (ministères, opérateurs, collectivités) : délinquance SSMSI, immigration, éducation, santé, "
                     "énergie, budgets… Renvoie les jeux et leurs ressources (id, format).",
      "input_schema": _obj({"mots_cles": S}, ["mots_cles"])},
     lambda a: open_data.datagouv_search(a["mots_cles"]), lambda a, r: [], None),
    ({"name": "datagouv_lire_ressource",
      "description": "Lit les lignes d'une ressource tabulaire (CSV/XLSX) de data.gouv.fr par son id, avec filtres exacts par colonne.",
      "input_schema": _obj({"ressource_id": S, "filtres": FILTERS}, ["ressource_id"])},
     lambda a: open_data.datagouv_read(a["ressource_id"], a.get("filtres")),
     lambda a, r: _source("data.gouv.fr – ressource " + a["ressource_id"], r.get("url")), None),
    ({"name": "banquemondiale_chercher",
      "description": "Cherche un indicateur de la Banque mondiale (noms en anglais). Renvoie aussi des indicateurs fréquents.",
      "input_schema": _obj({"mots_cles": S}, ["mots_cles"])},
     lambda a: open_data.worldbank_search(a["mots_cles"]), lambda a, r: [], None),
    ({"name": "banquemondiale_lire",
      "description": "Lit un indicateur de la Banque mondiale pour plusieurs pays (codes ISO3 : FRA, DEU, USA, EUU…), depuis une année.",
      "input_schema": _obj({"indicateur": S, "pays": COUNTRIES, "depuis": S}, ["indicateur"])},
     lambda a: open_data.worldbank_read(a["indicateur"], a.get("pays"), a.get("depuis", "2015")),
     lambda a, r: _source(f"Banque mondiale – {r.get('indicateur')}", r.get("url")), None),
    ({"name": "assemblee_votes",
      "description": "Votes de l'Assemblée nationale (17e législature, données officielles du jour) : scrutins dont le titre "
                     "contient les mots-clés, résultat, position de chaque groupe, et le vote d'un député si `depute` est donné.",
      "input_schema": _obj({"mots_cles": S, "depute": S}, ["mots_cles"])},
     lambda a: assemblee.search(a["mots_cles"], a.get("depute", "")),
     lambda a, r: [{"title": f"Assemblée nationale – scrutin n° {s['numero']}", "url": s["url"]} for s in r.get("scrutins", [])[:5]], None),
    ({"name": "insee_publications",
      "description": "Cherche dans les publications de l'INSEE (Insee Première, Insee Focus, chiffres clés, tableaux de "
                     "l'économie française) par mots-clés en français : pauvreté, immigration, population, logement, revenus, "
                     "inégalités… Renvoie titres, dates et URL à lire avec page_officielle_lire.",
      "input_schema": _obj({"mots_cles": S}, ["mots_cles"])},
     lambda a: open_data.insee_publications_search(a["mots_cles"]), lambda a, r: [], None),
    ({"name": "page_officielle_lire",
      "description": "Lit le texte d'une page HTML d'un site officiel (insee.fr, *.gouv.fr, vie-publique.fr, ccomptes.fr, "
                     "assemblee-nationale.fr, senat.fr, banque-france.fr, europa.eu, oecd.org…). `recherche` : mots-clés ou "
                     "nombres pour ne renvoyer que les passages utiles. Les autres sites et les PDF sont refusés.",
      "input_schema": _obj({"url": S, "recherche": S}, ["url"])},
     lambda a: open_data.official_page_read(a["url"], a.get("recherche", "")),
     lambda a, r: _source(f"{r.get('editeur')} – {r.get('titre')}", r.get("url")), None),
    ({"name": "factchecks_publies",
      "description": "Cherche si l'affirmation a déjà été vérifiée par des médias (AFP Factuel, Libération, Le Monde, franceinfo…).",
      "input_schema": _obj({"affirmation": S}, ["affirmation"])},
     lambda a: open_data.factcheck_search(a["affirmation"]),
     lambda a, r: [{"title": f"{f['media']} – {f['titre']}", "url": f["url"]} for f in r.get("fact_checks", []) if f.get("url")],
     "GOOGLE_FACTCHECK_API_KEY"),
    ({"name": "legifrance_chercher",
      "description": "Cherche dans les textes de loi et codes en vigueur (Légifrance) : ce que dit vraiment la loi.",
      "input_schema": _obj({"recherche": S}, ["recherche"])},
     lambda a: open_data.legifrance_search(a["recherche"]), lambda a, r: [], "PISTE_CLIENT_ID"),
    ({"name": "legifrance_article",
      "description": "Lit le texte exact d'un article de loi ou de code par son id Légifrance (LEGIARTI…).",
      "input_schema": _obj({"id": S}, ["id"])},
     lambda a: open_data.legifrance_article(a["id"]),
     lambda a, r: _source(f"Légifrance – article {r.get('numero')}", r.get("url")), "PISTE_CLIENT_ID"),
]


def available() -> list[dict]:
    """Définitions (format Anthropic : name, description, input_schema) des outils utilisables."""
    own = [d for d, _, _, env in _TOOLS if not env or os.getenv(env)]
    return [*insee_api.TOOLS, *own]


def run_tool(name: str, args: dict) -> tuple[str, list[dict], bool]:
    """Exécute un outil. Renvoie (résultat JSON, sources consultées, erreur ?)."""
    if name in insee_api.TOOL_NAMES:
        return insee_api.run_tool(name, args)
    for definition, fn, sources, env in _TOOLS:
        if definition["name"] != name or (env and not os.getenv(env)):
            continue
        try:
            result = fn(args)
        except (open_data.SourceError, KeyError, ValueError, TypeError, OSError) as e:
            return f"Erreur : {e}", [], True
        if isinstance(result, dict) and result.get("erreur"):
            return json.dumps(result, ensure_ascii=False), [], True
        return json.dumps(result, ensure_ascii=False, default=str)[:30_000], sources(args, result), False
    return f"outil inconnu : {name}", [], True
