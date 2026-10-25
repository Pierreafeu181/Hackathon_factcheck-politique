"""Autotest sans clé API : référentiel, comparaisons, transcript, base de données.
Lancer depuis backend/ : python -m app.selftest
"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "selftest.db"))
# Jamais la base de backend/.env : SQLite jetable, sauf SELFTEST_DATABASE_URL (Postgres vide et jetable).
os.environ["DATABASE_URL"] = os.environ.get("SELFTEST_DATABASE_URL", "")

from . import db, referentiel  # noqa: E402
from .models import (ClaimResult, ClaimType, ExtractedClaim, Method, Speaker, Speech, TranscriptSegment,  # noqa: E402
                     Unit, Verdict, Verification)
from .transcript import to_prompt_text, video_id_from_url  # noqa: E402


def claim(**kw) -> ExtractedClaim:
    base = dict(quote="…", claim="…", timestamp_start=0.0, category="emploi", checkable=True,
                claim_type="niveau", indicator="taux_chomage_bit", value=None, unit=None, direction=None,
                period_start=None, period_end=None, geo="France")
    base.update(kw)
    return ExtractedClaim(**base)


def main() -> None:
    series = referentiel.load()
    assert "taux_chomage_bit" in series, "data/referentiel/emploi.json manquant : lancer scripts/fetch_insee.py"
    s = series["taux_chomage_bit"]
    last_p, last_v = s.obs[-1]
    print(f"référentiel : {len(series)} séries, taux_chomage_bit dernier point {last_p} = {last_v}")

    # niveau
    r = referentiel.check(claim(value=last_v, unit=Unit.pourcent))
    assert r.verdict == Verdict.vrai, r
    r = referentiel.check(claim(value=last_v + 3, unit=Unit.pourcent))
    assert r.verdict == Verdict.faux, r
    r = referentiel.check(claim(value=last_v + 0.4, unit=Unit.pourcent))
    assert r.verdict == Verdict.plutot_vrai, r

    # évolution depuis 2017 : sens inverse → faux
    v2017, _ = referentiel.value_at(s, "2017")
    real_dir = "baisse" if last_v < v2017 else "hausse"
    wrong_dir = "hausse" if real_dir == "baisse" else "baisse"
    r = referentiel.check(claim(claim_type=ClaimType.evolution, direction=wrong_dir, period_start="2017",
                                value=1.0, unit=Unit.points))
    assert r.verdict == Verdict.faux, r
    r = referentiel.check(claim(claim_type=ClaimType.evolution, direction=real_dir, period_start="2017",
                                value=round(abs(last_v - v2017), 1), unit=Unit.points))
    assert r.verdict in {Verdict.vrai, Verdict.plutot_vrai}, r
    print(f"évolution 2017→{last_p} : {v2017} → {last_v} ({real_dir}) OK")

    # record « au plus bas depuis 60 ans » : la série commence en 1975 → au mieux imprécis
    r = referentiel.check(claim(claim_type=ClaimType.record, direction="baisse", value=60, unit=Unit.annees))
    assert r.verdict in {Verdict.faux, Verdict.imprecis}, r
    print("record :", r.verdict.value, "—", r.explanation)

    # séries mensuelles et annuelles (inflation, déficit) : périodes selon la fréquence
    inf, dfc = series["inflation"], series["deficit_public_pib"]
    sept = next(v for p, v in inf.obs if p == "2026-09")
    assert referentiel.value_at(inf, "2026-09") == (sept, "2026-09")
    assert referentiel.value_at(inf, "2026-T2")[1] == "moyenne 2026-Q2"
    assert referentiel.value_at(dfc, "2024") == (next(v for p, v in dfc.obs if p == "2024"), "2024")
    assert referentiel.value_at(dfc, "2024-T3")[1] == "2024"
    assert referentiel.value_at(series["taux_chomage_bit"], "2026-05")[1] == "2026-Q2"
    r = referentiel.check(claim(indicator="inflation", category="economie", value=sept, unit=Unit.pourcent, period_end="2026-09"))
    assert r.verdict == Verdict.vrai, r
    r = referentiel.check(claim(indicator="deficit_public_pib", category="finances_publiques", value=dfc.obs[-1][1] + 2, unit=Unit.pourcent))
    assert r.verdict == Verdict.faux, r
    # évolution d'un volume en unités : « +X milliards de dette depuis 2017 »
    debt = series["dette_publique_milliards"]
    d2017, _ = referentiel.value_at(debt, "2017")
    r = referentiel.check(claim(indicator="dette_publique_milliards", category="finances_publiques", claim_type=ClaimType.evolution,
                                direction="hausse", period_start="2017", value=round(debt.obs[-1][1] - d2017), unit=Unit.milliards))
    assert r.verdict == Verdict.vrai, r
    r = referentiel.check(claim(indicator="dette_publique_milliards", category="finances_publiques", claim_type=ClaimType.evolution,
                                direction="hausse", period_start="2017", value=round((debt.obs[-1][1] - d2017) / 2), unit=Unit.milliards))
    assert r.verdict == Verdict.trompeur, r
    print(f"inflation {sept} % (2026-09), déficit {dfc.obs[-1][1]} % ({dfc.obs[-1][0]}), dette 2017→ OK")

    # date du discours : comparaison aux chiffres disponibles à cette date
    old_inf = referentiel.check(claim(indicator="inflation", category="economie", value=0.9, unit=Unit.pourcent), "2025-12-17")
    nov = next(v for p, v in series["inflation"].obs if p == "2025-11")
    assert old_inf.official_period == "2025-11" and old_inf.official_value == nov, old_inf
    assert referentiel.check(claim(value=8.0, unit=Unit.pourcent), "1970-01-01") is None  # avant le début de la série
    assert referentiel.check(claim(value=8.0, unit=Unit.pourcent), "pas une date").official_period == last_p

    # immigration et sécurité (nombres bruts) : chiffres officiels 2025 vérifiés contre la DGEF et le bilan SSMSI
    assert series["demandes_asile_total"].obs[-1] == ("2025", 151665.0)
    assert series["homicides"].obs[-1] == ("2025", 975.0) and series["cambriolages_logement"].obs[-1] == ("2025", 211596.0)
    r = referentiel.check(claim(indicator="homicides", category="securite", value=1000, unit=Unit.personnes, bound="min"), "2026-10-25")
    assert r.verdict == Verdict.imprecis and "975" in r.explanation and "SSMSI" in r.explanation, r
    r = referentiel.check(claim(indicator="demandes_asile_total", category="immigration", value=150000, unit=Unit.personnes))
    assert r.verdict == Verdict.vrai, r

    # évolution sans date de départ : sur un an ; record sans durée : sur toute la série
    r = referentiel.check(claim(indicator="cambriolages_logement", category="securite", claim_type=ClaimType.evolution,
                                direction="baisse"), "2026-10-25")
    assert r.verdict == Verdict.plutot_vrai and "2024" in r.explanation and "2025" in r.explanation, r
    r = referentiel.check(claim(indicator="premiers_titres_sejour", category="immigration", claim_type=ClaimType.record,
                                direction="hausse", period_start="2025"), "2026-10-25")
    assert r.verdict == Verdict.vrai and "d'un record" in r.explanation, r

    # confusion d'indicateurs : 69 % cité comme taux d'activité, c'est le taux d'emploi → imprécis, pas faux
    emp = series["taux_emploi_15_64"].obs[-1][1]
    r = referentiel.check(claim(indicator="taux_activite_15_64", value=emp, unit=Unit.pourcent))
    assert r.verdict == Verdict.imprecis and "taux d'emploi" in r.explanation and len(r.sources) == 2, r
    r = referentiel.check(claim(indicator="taux_activite_15_64", value=50.0, unit=Unit.pourcent))
    assert r.verdict == Verdict.faux, r  # aucun indicateur voisin ne colle : reste faux
    assert referentiel.check(claim(indicator="deficit_public_pib", quote="le Sénat a remis le déficit à 5,3 %",
                                   value=5.3, unit=Unit.pourcent)) is None

    # objectif ou prévision dans la citation : pas de verdict calculé
    for quote in ("la copie initiale à 4,7 % de déficit", "on vise 5 % de déficit", "ramener le déficit à 4,7 %"):
        assert referentiel.check(claim(indicator="deficit_public_pib", quote=quote, value=4.7, unit=Unit.pourcent)) is None, quote
    assert referentiel.check(claim(indicator="deficit_public_pib", quote="le déficit est de 5,1 %", value=5.1, unit=Unit.pourcent))

    # année pas encore publiée (objectif) : pas de verdict calculé
    assert referentiel.check(claim(indicator="deficit_public_pib", category="finances_publiques", value=5.0,
                                   unit=Unit.pourcent, period_start="2027", period_end="2027")) is None

    # verdict web durci en code quand le modèle trouve un taux officiel (« un sur cinq » = 20 % contre 15,4 %)
    from .verify import rate_verdict
    poor = claim(indicator=None, category="autre", value=20.0, unit=Unit.pourcent)
    assert rate_verdict(poor, 15.4)[0] == Verdict.faux and rate_verdict(poor, 19.9)[0] == Verdict.vrai
    assert rate_verdict(claim(indicator=None, value=20.0, unit=Unit.milliers), 15.4) is None

    assert referentiel.check(claim(value=8.0, unit=Unit.pourcent, period_end="2026-S1")) is None  # période illisible

    # mémoire des vérifications web : reformulation normalisée, chiffre et date dans la clé
    from . import verify as verify_mod
    a = claim(indicator=None, claim="Un Français sur cinq vit sous le seuil de pauvreté.", value=20.0, unit=Unit.pourcent)
    b = claim(indicator=None, claim="un francais sur cinq vit sous le seuil de pauvrete", value=20.0, unit=Unit.pourcent)
    assert verify_mod.cache_key(a, "2026-10-25") == verify_mod.cache_key(b, "2026-10-25T10:00")
    assert verify_mod.cache_key(a, "2026-10-25") != verify_mod.cache_key(b.model_copy(update={"value": 25.0}), "2026-10-25")
    assert verify_mod.cache_key(a, "2026-10-25") != verify_mod.cache_key(a.model_copy(update={"quote": "autre citation"}), "2026-10-25")
    assert verify_mod.cache_key(a, "2026-10-25") != verify_mod.cache_key(a.model_copy(update={"claim_type": "comparaison"}), "2026-10-25")
    assert verify_mod._canon("Дефицит 5 %") == "дефицит 5"  # lettres non latines gardées
    assert verify_mod.cache_key(a.model_copy(update={"claim": "Дефицит"}), None) != verify_mod.cache_key(a.model_copy(update={"claim": "Долг"}), None)
    calls = []
    def fake_web(c, d):
        calls.append(c)
        return Verification(verdict=Verdict.faux, method=Method.web, explanation="x", confidence=0.7,
                            sources=[{"title": "INSEE", "url": "https://www.insee.fr/fr/statistiques/5759045", "publisher": "INSEE"}])
    real_web, verify_mod._from_web = verify_mod._from_web, fake_web
    try:
        verify_mod.verify(a, "2026-10-25"); verify_mod.verify(b, "2026-10-25")
    finally:
        verify_mod._from_web = real_web
        verify_mod._web_cache.clear()
    assert len(calls) == 1, calls

    # indicateur inconnu → None (part en recherche web)
    assert referentiel.check(claim(indicator="taux_pauvrete", value=14.0)) is None

    # transcript
    assert video_id_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10") == "dQw4w9WgXcQ"
    assert video_id_from_url("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    txt = to_prompt_text([TranscriptSegment(start=0, text="a"), TranscriptSegment(start=25, text="b")])
    assert txt == "[0s] a\n[25s] b", txt

    # bornes : « plus de X » / « moins de X »
    young = referentiel.load()["taux_chomage_moins_25"].obs[-1][1]
    assert referentiel.check(claim(indicator="taux_chomage_moins_25", value=young - 1.5, unit=Unit.pourcent, bound="min")).verdict == Verdict.vrai
    assert referentiel.check(claim(indicator="taux_chomage_moins_25", value=young - 1.5, unit=Unit.pourcent)).verdict != Verdict.vrai
    assert referentiel.check(claim(indicator="taux_chomage_moins_25", value=young - 1.5, unit=Unit.pourcent, bound="max")).verdict == Verdict.faux
    assert referentiel.check(claim(indicator="taux_chomage_moins_25", value=young - 0.2, unit=Unit.pourcent, bound="max")).verdict == Verdict.imprecis
    print("bornes : « plus de » / « moins de » OK")

    # API INSEE en direct : lecture du XML SDMX (sans réseau)
    from . import insee_api
    xml = (b'<m:Data xmlns:m="urn:x"><m:DataSet><Series IDBANK="010777608" TITLE_FR="Dette - en point de PIB" '
           b'UNIT_MEASURE="POURCENT" UNIT_MULT="0" FREQ="T"><Obs TIME_PERIOD="2026-Q2" OBS_VALUE="119.0"/>'
           b'<Obs TIME_PERIOD="2026-Q1" OBS_VALUE="117.5"/><Obs TIME_PERIOD="2025-Q4" OBS_VALUE="NaN"/></Series>'
           b'</m:DataSet></m:Data>')
    s = insee_api.parse_series(xml)[0]
    assert s["idbank"] == "010777608" and s["observations"] == [["2026-Q1", 117.5], ["2026-Q2", 119.0]], s
    assert insee_api.run_tool("insee_lire_serie", {"idbank": "abc"})[2]  # idbank invalide → erreur, sans appel réseau
    assert {t["name"] for t in insee_api.TOOLS} == insee_api.TOOL_NAMES
    print("insee_api : parse SDMX OK")

    # registre d'outils et recherche par pertinence (sans réseau)
    from . import open_data, tools
    names = {t["name"] for t in tools.available()}
    assert {"insee_lire_serie", "eurostat_lire", "datagouv_chercher", "assemblee_votes"} <= names, names
    assert "wikipedia" not in names  # source modifiable par tous : exclue
    assert open_data._certified_public({"badges": [{"kind": "certified"}, {"kind": "public-service"}]})
    assert not open_data._certified_public({"badges": [{"kind": "certified"}]})  # certifiée mais pas publique (entreprise…)
    assert not open_data._certified_public(None)  # particulier
    from .verify import unreliable
    assert unreliable("https://fr.wikipedia.org/wiki/Dette") and unreliable("https://x.com/a/status/1")
    assert not unreliable("https://www.insee.fr/fr/statistiques/serie/001688527")
    assert ("legifrance_chercher" in names) == bool(os.getenv("PISTE_CLIENT_ID"))
    assert {"insee_publications", "page_officielle_lire"} <= names
    assert open_data.official_url("https://www.insee.fr/fr/statistiques/5759045")
    assert open_data.official_url("https://www.economie.gouv.fr/x")
    for bad in ("http://www.insee.fr/", "https://insee.fr.exemple.com/", "https://faux-insee.fr/", "https://www.insee.fr:8443/",
                "https://fr.wikipedia.org/wiki/Insee"):
        assert not open_data.official_url(bad), bad
    assert tools.run_tool("page_officielle_lire", {"url": "https://blog.exemple.com/chiffres"})[2]  # refusé sans appel réseau
    title, lines = open_data.page_text("<html><head><title>Pauvreté | Insee</title><script>x=1</script></head><body>"
                                       "<nav>Menu</nav><h1>Taux</h1><p>En 2024, le taux de pauvreté est de 15,4 %.</p>"
                                       "<table><tr><th>Année</th><th>Taux</th></tr><tr><td>2024</td><td>15,4</td></tr></table></body></html>")
    assert title == "Pauvreté | Insee" and "Menu" not in lines and "x=1" not in " ".join(lines), lines
    assert "Année | Taux" in lines and "2024 | 15,4" in lines, lines
    assert open_data._passages(lines, "taux pauvreté 2024")[0] == "Taux", open_data._passages(lines, "taux pauvreté 2024")
    ranked = open_data._rank([("a", "Impôts et cotisations sociales"), ("b", "Population"), ("c", "Impôt sur le revenu")],
                             "impôts cotisations", key=lambda x: x[1])
    assert [c for c, _ in ranked][0] == "a" and "b" not in [c for c, _ in ranked], ranked
    assert tools.run_tool("outil_inexistant", {})[2]
    print("outils :", len(names), "disponibles")

    # Mistral : schéma Pydantic sans $ref (sans réseau)
    from . import llm
    from .models import ExtractionResult
    inlined = json.dumps(llm._inline_refs(ExtractionResult.model_json_schema()))
    assert "$ref" not in inlined and "$defs" not in inlined and "timestamp_start" in inlined
    assert llm._text([{"type": "thinking", "thinking": "…"}, {"type": "text", "text": "ok"}]) == "ok"
    print("llm : fournisseur", llm.PROVIDER, "/", llm.MODEL)

    # quota du jour épuisé : 503 avec un message lisible (relayé jusqu'au panneau)
    from fastapi.testclient import TestClient
    from . import main as main_mod
    real_check, main_mod.check_api.check = main_mod.check_api.check, lambda req: (_ for _ in ()).throw(llm.QuotaExhausted("test"))
    try:
        r = TestClient(main_mod.app).post("/check", json={"source": {"kind": "selection", "url": "https://x.fr/q"}, "segments": [{"text": "x"}]})
        assert r.status_code == 503 and "quota du jour" in r.json()["detail"], r.text
    finally:
        main_mod.check_api.check = real_check

    # base de données
    db.init()
    sp = Speech(id="yt:TEST", video_id="TEST", url=None, title="t", date="2026-10-01",
                speaker=Speaker(name="Personne Démo", party=None))
    db.save_speech(sp, "[]")
    for i, v in enumerate(["vrai", "faux", "vrai", "imprecis", "plutot_vrai"]):
        db.save_result(ClaimResult(id=f"yt:TEST#{i}", speech_id="yt:TEST", claim=claim(value=8.0),
                                   verification=Verification(verdict=v, method=Method.referentiel,
                                                             explanation="x", confidence=0.9)), sp.speaker)
    p = db.profile("personne-demo")
    assert p.n_claims == 5 and p.reliability_score == 65.0, p
    assert db.get_speech("yt:TEST")[1][0].verification.verdict == Verdict.vrai
    print("db : profil", p.reliability_score, p.verdicts)

    # POST /check (contrat Node) : LLM remplacé par des fonctions factices
    from . import check_api
    from .models import CheckRequest

    fake_claims = [claim(quote="le chômage est à 8,3 %", value=last_v, unit=Unit.pourcent, timestamp_start=12.0),
                   claim(quote="le chômage a baissé", claim_type=ClaimType.evolution, direction="baisse",
                         period_start="2017", value=3, unit=Unit.points, timestamp_start=40.0)]
    check_api.extract_claims = lambda *a, **k: fake_claims
    check_api.verify = lambda c, *a, **k: Verification(
        verdict=referentiel.check(c).verdict, method=Method.referentiel, explanation="x", confidence=0.9,
        correction=None if referentiel.check(c).verdict == Verdict.vrai else "corrigé",
        sources=referentiel.check(c).sources)
    resp = check_api.check(CheckRequest.model_validate({
        "source": {"kind": "youtube", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "t"},
        "segments": [{"text": "…", "start": 10, "speaker": "1"}],
        "politician": {"name": "Personne Démo"},
    }))
    assert [c.verdict for c in resp.claims] == ["vrai", "trompeur"], resp
    assert resp.claims[0].start == 12.0 and resp.claims[0].sources[0].official
    assert "Correction : corrigé" in resp.claims[1].explanation
    assert db.get_speech("yt:dQw4w9WgXcQ") is not None  # stocké car politician fourni
    print("/check :", [(c.verdict, c.start) for c in resp.claims])

    # article : faits de l'article et des autres personnes citées vérifiés, mais hors du profil de la personnalité
    assert check_api.same_person("le ministre Jean-Pierre Farandou", "Jean-Pierre Farandou")
    assert check_api.same_person("Farandou", "Jean-Pierre Farandou") and not check_api.same_person("article", "Jean-Pierre Farandou")
    article_claims = [claim(quote="le chômage est à 8,3 %", value=last_v, unit=Unit.pourcent, author="Personne Article"),
                      claim(quote="8,3 % selon l'INSEE", value=last_v, unit=Unit.pourcent, author="article"),
                      claim(quote="8,3 %", value=last_v, unit=Unit.pourcent, author="Autre Personne")]
    check_api.extract_claims = lambda *a, **k: article_claims if k.get("article") else []
    resp = check_api.check(CheckRequest.model_validate({
        "source": {"kind": "article", "url": "https://www.exemple-presse.fr/article", "title": "t"},
        "segments": [{"text": "…"}], "politician": {"name": "Personne Article"}}))
    assert len(resp.claims) == 3 and resp.claims[1].explanation.startswith("Affirmé par l'article.")
    assert resp.claims[2].explanation.startswith("Affirmé par Autre Personne.")
    assert db.profile("personne-article").n_claims == 1  # seule sa propre affirmation compte
    print("/check article : 3 affirmations, 1 dans le profil")

    # délai global : ce qui n'est pas prêt revient « en cours », hors du profil
    import time as _time
    slow = [claim(quote="rapide", value=last_v, unit=Unit.pourcent), claim(quote="lente", indicator=None, value=1.0)]
    check_api.extract_claims = lambda *a, **k: slow
    check_api.verify = lambda c, *a, **k: (_time.sleep(3) if c.quote == "lente" else None) or Verification(
        verdict=Verdict.vrai, method=Method.referentiel, explanation="ok", confidence=0.9, sources=referentiel.check(slow[0]).sources)
    check_api.DEADLINE_S, t0 = 0.5, _time.time()
    resp = check_api.check(CheckRequest.model_validate({
        "source": {"kind": "youtube", "url": "https://www.youtube.com/watch?v=deadline001", "title": "t"},
        "segments": [{"text": "…", "start": 0}], "politician": {"name": "Personne Délai"}}))
    assert _time.time() - t0 < 2 and [c.verdict for c in resp.claims] == ["vrai", "invérifiable"], resp
    assert "encore en cours" in resp.claims[1].explanation and db.profile("personne-delai").n_claims == 1
    print("/check délai : réponse partielle en", round(_time.time() - t0, 1), "s")
    # file pleine : réponse immédiate « serveur très sollicité », jamais d'attente
    real_backlog, check_api._backlog = check_api._backlog, __import__("threading").BoundedSemaphore(1)
    check_api._backlog.acquire()
    try:
        resp = check_api.check(CheckRequest.model_validate({
            "source": {"kind": "youtube", "url": "https://www.youtube.com/watch?v=backlog0001", "title": "t"},
            "segments": [{"text": "…", "start": 0}]}))
        assert all("très sollicité" in c.explanation for c in resp.claims), resp
    finally:
        check_api._backlog = real_backlog

    print("\nOK — tous les autotests passent")


if __name__ == "__main__":
    main()
