"""Autotest sans clé API : référentiel, comparaisons, transcript, base de données.
Lancer depuis backend/ : python -m app.selftest
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "selftest.db"))

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
    print("record :", r.verdict.value, "—", r.facts)

    # indicateur inconnu → None (part en recherche web)
    assert referentiel.check(claim(indicator="taux_pauvrete", value=14.0)) is None

    # transcript
    assert video_id_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10") == "dQw4w9WgXcQ"
    assert video_id_from_url("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    txt = to_prompt_text([TranscriptSegment(start=0, text="a"), TranscriptSegment(start=25, text="b")])
    assert txt == "[0s] a\n[25s] b", txt

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

    # Google Fact Check : réponse de l'API remplacée par une réponse factice
    from . import factcheck

    for rating, expected in [("Faux", Verdict.faux), ("Inexact", Verdict.faux), ("Plutôt vrai", Verdict.plutot_vrai),
                             ("Partiellement faux", Verdict.trompeur), ("Manque de contexte", Verdict.trompeur),
                             ("Imprécis", Verdict.imprecis), ("Vrai", Verdict.vrai), ("Satire", None)]:
        assert factcheck.rating_to_verdict(rating) == expected, (rating, factcheck.rating_to_verdict(rating))
    fake_fc = [{"text": "Le chômage a baissé de deux points depuis 2017", "claimant": "Personne Démo",
                "claimReview": [{"publisher": {"name": "AFP Factuel", "site": "factuel.afp.com"},
                                 "url": "https://factuel.afp.com/demo", "title": "Chômage depuis 2017",
                                 "reviewDate": "2024-05-02T00:00:00Z", "textualRating": "Partiellement faux",
                                 "languageCode": "fr"}]}]
    v = factcheck.check(claim(claim="Le chômage a baissé de 2 points depuis 2017", quote="le chômage a baissé"),
                        fetch=lambda q: fake_fc)
    assert v is not None and v.verdict == Verdict.trompeur and v.method == Method.factcheck, v
    assert v.sources[0].url == "https://factuel.afp.com/demo" and "AFP Factuel" in v.explanation, v
    assert factcheck.check(claim(claim="La dette publique dépasse 3 000 milliards d'euros"),
                           fetch=lambda q: fake_fc) is None
    print("fact check :", v.verdict.value, "—", v.explanation)

    print("\nOK — tous les autotests passent")


if __name__ == "__main__":
    main()
