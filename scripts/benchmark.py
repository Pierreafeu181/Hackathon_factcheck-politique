"""Benchmark : Vérif'Pol contre une base naïve (le même modèle Claude, sans données ni outils).

10 affirmations datées du 22/10/2026, dont la réponse est connue d'après les séries officielles
(INSEE / DARES, dernier point publié). Chaque affirmation passe :
  - par le pipeline complet (POST /check : extraction, référentiel figé, INSEE en direct, web) ;
  - par Claude seul, sans outil, à qui on demande vrai / faux / invérifiable.

Lancer depuis backend/ :  .venv/bin/python ../scripts/benchmark.py   (clé Anthropic requise, ~2 min)
Écrit docs/EVIDENCE.md.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pydantic import BaseModel  # noqa: E402

from app import check_api, llm  # noqa: E402
from app.models import CheckRequest  # noqa: E402

DATE = "2026-10-22"
# (affirmation, vérité, valeur officielle qui tranche)
CASES = [
    ("Aujourd'hui, le taux de chômage est de 8,3 %.", "vrai", "8,3 % (INSEE, T2 2026)"),
    ("Le chômage est tombé à 6,5 %, son plus bas niveau.", "faux", "8,3 % (INSEE, T2 2026)"),
    ("Depuis 2017, le chômage a baissé de plus de trois points.", "faux", "9,4 % en 2017 → 8,3 % : −1,1 point"),
    ("Le chômage des moins de 25 ans dépasse 20 %.", "vrai", "21,6 % (INSEE, T2 2026)"),
    ("Le taux d'emploi des 15-64 ans atteint 69 %.", "vrai", "69,0 % (INSEE, T2 2026)"),
    ("Il y a moins de deux millions de demandeurs d'emploi en catégorie A.", "faux", "3 323 000 (DARES, T2 2026)"),
    ("L'inflation sur un an dépasse aujourd'hui 4 %.", "faux", "3,1 % (INSEE, sept. 2026)"),
    ("L'inflation est repassée au-dessus de 3 % sur un an.", "vrai", "3,1 % (INSEE, sept. 2026)"),
    ("La dette publique atteint 119 % du PIB.", "vrai", "119,0 % (INSEE, T2 2026)"),
    ("La dette publique est d'environ 2 000 milliards d'euros.", "faux", "3 595,5 Md€ (INSEE, T2 2026)"),
]


class Naive(BaseModel):
    verdict: Literal["vrai", "faux", "inverifiable"]
    valeur_citee: str | None


NAIVE_SYSTEM = (f"Tu es un·e fact-checker. L'affirmation a été prononcée le {DATE} par un responsable politique "
                "français. Dis si elle est vraie, fausse, ou invérifiable, et cite la valeur officielle que tu connais.")


def ours(text: str) -> tuple[str, bool, float]:
    t = time.time()
    req = CheckRequest.model_validate({"source": {"kind": "selection", "url": "https://bench.local/claim", "title": "benchmark"},
                                       "segments": [{"text": text}], "date": DATE})
    claims = check_api.check(req).claims
    if not claims:
        return "aucune affirmation", False, time.time() - t
    c = claims[0]
    return c.verdict, any(s.official for s in c.sources), time.time() - t


def naive(text: str) -> tuple[str, float]:
    t = time.time()
    r = llm.parse(NAIVE_SYSTEM, text, Naive, effort="medium", max_tokens=2000)
    return ("invérifiable" if r.verdict == "inverifiable" else r.verdict), time.time() - t


def correct(verdict: str, truth: str) -> bool:
    return verdict == "vrai" if truth == "vrai" else verdict in ("faux", "trompeur")


def main() -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        a = list(pool.map(lambda c: ours(c[0]), CASES))
        b = list(pool.map(lambda c: naive(c[0]), CASES))
    rows, ok_a, ok_b, src = [], 0, 0, 0
    for (text, truth, ref), (va, official, ta), (vb, tb) in zip(CASES, a, b):
        ok_a += correct(va, truth)
        ok_b += correct(vb, truth)
        src += official
        rows.append(f"| {text} | **{truth}** · {ref} | {va} {'✅' if correct(va, truth) else '❌'} | {vb} {'✅' if correct(vb, truth) else '❌'} |")
    n = len(CASES)
    out = f"""# Evidence it works

Benchmark run on {time.strftime('%Y-%m-%d')} with `{llm.MODEL}`: {n} claims dated {DATE} whose answer is set by the latest official INSEE / DARES figures. **Baseline** = the same model with no data and no tools. Script: `scripts/benchmark.py`.

| | Vérif'Pol | Naive baseline |
|---|---|---|
| Correct verdicts | **{ok_a}/{n}** | {ok_b}/{n} |
| Verdicts backed by an official source | **{src}/{n}** | 0/{n} |
| Average time per claim | {sum(x[2] for x in a) / n:.0f} s | {sum(x[1] for x in b) / n:.0f} s |

| Claim | Truth (official figure) | Vérif'Pol | Baseline |
|---|---|---|---|
""" + "\n".join(rows) + "\n"
    (ROOT / "docs" / "EVIDENCE.md").write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
