"""Lot C — Référentiel de séries officielles + comparaison DÉTERMINISTE.

Le LLM ne décide jamais d'un verdict chiffré : il normalise l'affirmation (indicateur,
valeur, unité, période) et c'est ce module qui compare aux données officielles.

Conventions de période (documentées dans docs/METHODOLOGIE.md) :
- "AAAA-Tn" / "AAAA-Qn" → le trimestre exact ;
- "AAAA-MM"            → le trimestre qui contient ce mois ;
- "AAAA"               → moyenne des observations de l'année ;
- None en fin de période → dernière observation disponible.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from statistics import mean

from .models import ClaimType, ExtractedClaim, Source, Unit, Verdict

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "referentiel"

# Tolérances. Taux (en points) / volumes (en écart relatif).
RATE_TOL = {"vrai": 0.15, "plutot_vrai": 0.5, "imprecis": 1.0}
VOLUME_TOL = {"vrai": 0.02, "plutot_vrai": 0.05, "imprecis": 0.10}


@dataclass
class Series:
    key: str
    label: str
    unit: str
    publisher: str
    url: str
    note: str
    obs: list[tuple[str, float]]  # trié par période croissante

    @property
    def is_rate(self) -> bool:
        return self.unit == "pourcent"

    def source(self, extra: str | None = None) -> Source:
        note = self.note + (f" — {extra}" if extra else "")
        return Source(title=self.label, url=self.url, publisher=self.publisher, note=note)


@dataclass
class CheckResult:
    verdict: Verdict
    official_value: float | None
    official_period: str | None
    facts: str                      # constat factuel en français, donné au LLM pour rédiger
    sources: list[Source] = field(default_factory=list)
    confidence: float = 0.9


# ---------------------------------------------------------------- chargement


@lru_cache
def load() -> dict[str, Series]:
    out: dict[str, Series] = {}
    for path in sorted(DATA_DIR.glob("*.json")):
        if path.name == "series.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, s in data.get("series", {}).items():
            obs = sorted(((p, float(v)) for p, v in s["observations"]), key=lambda o: _t(o[0]))
            out[key] = Series(key, s["label"], s["unit"], s["publisher"], s["url"], s.get("note", ""), obs)
    return out


def indicators_for_prompt() -> str:
    lines = []
    for s in load().values():
        last_p, last_v = s.obs[-1]
        lines.append(f"- {s.key} : {s.label} [{s.unit}] (dernier point {last_p} = {last_v})")
    return "\n".join(lines) or "(aucun indicateur chargé)"


# ---------------------------------------------------------------- périodes

_Q = re.compile(r"^(\d{4})-[QT]([1-4])$")
_M = re.compile(r"^(\d{4})-(\d{2})$")
_Y = re.compile(r"^(\d{4})$")


def _t(period: str) -> float:
    """Période → année décimale (début de période)."""
    if m := _Q.match(period):
        return int(m[1]) + (int(m[2]) - 1) / 4
    if m := _M.match(period):
        return int(m[1]) + (int(m[2]) - 1) / 12
    if m := _Y.match(period):
        return float(m[1])
    raise ValueError(f"période illisible : {period!r}")


def _norm(period: str) -> str:
    period = period.strip().upper().replace("T", "Q") if _Q.match(period.strip().upper().replace("T", "Q")) else period.strip()
    if m := _M.match(period):
        return f"{m[1]}-Q{(int(m[2]) - 1) // 3 + 1}"
    return period


def value_at(s: Series, period: str | None) -> tuple[float, str] | None:
    """Valeur de la série à une période (convention en tête de fichier)."""
    if not period:
        return s.obs[-1][1], s.obs[-1][0]
    period = _norm(period)
    if _Y.match(period):
        vals = [v for p, v in s.obs if p.startswith(period)]
        return (round(mean(vals), 2), f"moyenne {period}") if vals else None
    for p, v in s.obs:
        if p == period:
            return v, p
    # période absente (ex. trimestre pas encore publié) : dernier point antérieur
    before = [(p, v) for p, v in s.obs if _t(p) <= _t(period)]
    return (before[-1][1], before[-1][0]) if before else None


# ---------------------------------------------------------------- comparaison


def _gap(claimed: float, official: float, bound: str | None) -> float:
    """Écart entre l'affirmé et l'officiel. Avec « plus de X » (min) ou « moins de X » (max),
    il est nul dès que l'officiel respecte la borne ; sinon, c'est la distance à la borne."""
    if bound == "min":
        return max(0.0, claimed - official)
    if bound == "max":
        return max(0.0, official - claimed)
    return abs(claimed - official)


BOUND_LABEL = {"min": "plus de ", "max": "moins de ", None: ""}


def _grade(diff: float, tol: dict[str, float], worst: Verdict = Verdict.faux) -> Verdict:
    if diff <= tol["vrai"]:
        return Verdict.vrai
    if diff <= tol["plutot_vrai"]:
        return Verdict.plutot_vrai
    if diff <= tol["imprecis"]:
        return Verdict.imprecis
    return worst


def check(claim: ExtractedClaim) -> CheckResult | None:
    """Renvoie un verdict calculé, ou None si le référentiel ne couvre pas l'affirmation."""
    s = load().get(claim.indicator or "")
    if s is None:
        return None
    if claim.claim_type == ClaimType.niveau:
        return _check_level(claim, s)
    if claim.claim_type == ClaimType.evolution:
        return _check_evolution(claim, s)
    if claim.claim_type == ClaimType.record:
        return _check_record(claim, s)
    return None


def _check_level(c: ExtractedClaim, s: Series) -> CheckResult | None:
    if c.value is None:
        return None
    got = value_at(s, c.period_end or c.period_start)
    if got is None:
        return None
    official, period = got
    said = BOUND_LABEL[c.bound]
    if s.is_rate:
        diff = _gap(c.value, official, c.bound)
        verdict = _grade(diff, RATE_TOL)
        facts = f"Affirmé : {said}{c.value} %. Officiel ({period}) : {official} %. Écart : {diff:.2f} point."
    else:
        diff = _gap(c.value, official, c.bound) / abs(official)
        verdict = _grade(diff, VOLUME_TOL)
        facts = f"Affirmé : {said}{c.value} {s.unit}. Officiel ({period}) : {official} {s.unit}. Écart relatif : {diff:.1%}."
    if c.bound and diff > 0 and verdict in (Verdict.vrai, Verdict.plutot_vrai):
        verdict = Verdict.imprecis  # « moins de 8 % » alors que c'est 8,3 % : seuil franchi, jamais « vrai »
    return CheckResult(verdict, official, period, facts, [s.source(period)])


def _check_evolution(c: ExtractedClaim, s: Series) -> CheckResult | None:
    if not c.period_start:
        return None
    a, b = value_at(s, c.period_start), value_at(s, c.period_end)
    if a is None or b is None:
        return None
    (va, pa), (vb, pb) = a, b
    delta = vb - va
    official_dir = "hausse" if delta > 0 else "baisse" if delta < 0 else "stable"
    rel = delta / abs(va) * 100 if va else 0.0
    facts = (f"{s.label} : {va} ({pa}) → {vb} ({pb}), soit {delta:+.2f} "
             f"{'point' if s.is_rate else s.unit} ({rel:+.1f} %).")
    srcs = [s.source(f"{pa} → {pb}")]

    if c.direction and c.direction != official_dir and official_dir != "stable":
        return CheckResult(Verdict.faux, round(delta, 2), f"{pa} → {pb}", facts + f" Sens affirmé : {c.direction}.", srcs)
    if c.value is None:
        return CheckResult(Verdict.plutot_vrai, round(delta, 2), f"{pa} → {pb}",
                           facts + " Le sens est correct, l'ampleur n'est pas chiffrée.", srcs, 0.7)

    claimed = abs(c.value)
    if c.unit == Unit.pourcent_variation or not s.is_rate:
        official_mag = abs(rel)
        verdict = _grade(_gap(claimed, official_mag, c.bound) / max(official_mag, 1e-9), VOLUME_TOL, Verdict.trompeur)
        facts += f" Affirmé : {BOUND_LABEL[c.bound]}{claimed} % de variation."
    else:
        official_mag = abs(delta)
        verdict = _grade(_gap(claimed, official_mag, c.bound), RATE_TOL, Verdict.trompeur)
        facts += f" Affirmé : {BOUND_LABEL[c.bound]}{claimed} point(s)."
        if c.unit == Unit.pourcent:
            facts += " Attention : l'orateur dit « % » pour un écart de taux (ce sont des points)."
    return CheckResult(verdict, round(delta, 2), f"{pa} → {pb}", facts, srcs)


def _check_record(c: ExtractedClaim, s: Series) -> CheckResult | None:
    """« au plus bas / plus haut depuis N ans (ou depuis AAAA) »."""
    if c.direction not in {"hausse", "baisse"}:
        return None
    lowest = c.direction == "baisse"  # « plus bas » = record à la baisse

    def years_since_comparable(idx: int) -> tuple[float, str | None]:
        p_ref, v_ref = s.obs[idx]
        for p, v in reversed(s.obs[:idx]):
            if (v <= v_ref) if lowest else (v >= v_ref):
                return _t(p_ref) - _t(p), p
        return _t(p_ref) - _t(s.obs[0][0]), None  # record sur toute la série

    if c.unit == Unit.annees and c.value:
        claimed_years = c.value
    elif c.period_start and _Y.match(c.period_start[:4]):
        claimed_years = _t(s.obs[-1][0]) - _t(c.period_start[:4])
    else:
        return None

    def grade(idx: int) -> tuple[Verdict, str]:
        actual, p_prev = years_since_comparable(idx)
        p_ref, v_ref = s.obs[idx]
        where = f"il faut remonter à {p_prev} pour trouver un niveau aussi {'bas' if lowest else 'haut'}" if p_prev \
            else f"c'est un record depuis le début de la série ({s.obs[0][0]})"
        facts = f"{s.label} = {v_ref} en {p_ref} ; {where} (≈ {actual:.1f} ans). Affirmé : ≈ {claimed_years:.0f} ans."
        if claimed_years <= actual + 1:
            return Verdict.vrai, facts
        if claimed_years <= actual * 1.5:
            return Verdict.imprecis, facts
        return Verdict.faux, facts

    verdict, facts = grade(len(s.obs) - 1)
    if verdict == Verdict.faux:
        # C'était peut-être vrai récemment (ex. le chômage est remonté depuis) : on cherche sur 2 ans.
        recent = range(max(0, len(s.obs) - 9), len(s.obs) - 1)
        for i in sorted(recent, key=lambda i: s.obs[i][1], reverse=not lowest):
            v2, f2 = grade(i)
            if v2 == Verdict.vrai:
                return CheckResult(Verdict.imprecis, s.obs[i][1], s.obs[i][0],
                                   f"Vrai en {s.obs[i][0]} mais plus au dernier point. {f2} Dernier point : {s.obs[-1][0]} = {s.obs[-1][1]}.",
                                   [s.source()], 0.8)
            break
    return CheckResult(verdict, s.obs[-1][1], s.obs[-1][0], facts, [s.source()])
