"""Lot C — Référentiel de séries officielles + comparaison DÉTERMINISTE.

Le LLM ne décide jamais d'un verdict chiffré : il normalise l'affirmation (indicateur,
valeur, unité, période) et c'est ce module qui compare aux données officielles.

Conventions de période (documentées dans docs/METHODOLOGIE.md), selon la fréquence de la série :
- "AAAA-Tn" / "AAAA-Qn" → le trimestre exact (série mensuelle : moyenne de ses mois ; annuelle : l'année) ;
- "AAAA-MM"            → le mois exact (série trimestrielle : le trimestre qui le contient ; annuelle : l'année) ;
- "AAAA"               → moyenne des observations de l'année (série annuelle : la valeur de l'année) ;
- None en fin de période → dernière observation disponible (à la date du discours si elle est connue : un propos
  de décembre 2025 se compare aux chiffres publiés à ce moment-là, pas à ceux d'aujourd'hui).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
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
    explanation: str                # explication affichée telle quelle (aucun LLM : le texte suit le calcul)
    sources: list[Source] = field(default_factory=list)
    confidence: float = 0.9
    correction: str | None = None   # formulation juste, None si le verdict est vrai


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


def _end(period: str) -> float:
    """Fin de la période, en année décimale."""
    return _t(period) + (1 / 12 if _M.match(period) else 0.25 if _Q.match(period) else 1.0)


def as_of(s: Series, date: str) -> Series | None:
    """La série telle qu'on pouvait la connaître à cette date : seulement les périodes terminées (valeurs révisées
    d'aujourd'hui ; le délai de publication de quelques semaines n'est pas modélisé)."""
    d = dt.date.fromisoformat(date[:10])
    now = d.year + (d.timetuple().tm_yday - 1) / (366 if d.year % 4 == 0 else 365)
    obs = [o for o in s.obs if _end(o[0]) <= now + 1e-9]
    return dataclasses.replace(s, obs=obs) if obs else None


def _norm(period: str) -> str:
    """« 2026-t2 » → « 2026-Q2 » ; le reste inchangé."""
    period = period.strip().upper()
    return period.replace("T", "Q") if _Q.match(period.replace("T", "Q")) else period


def _quarter(month_period: str) -> str:
    y, m = month_period.split("-")
    return f"{y}-Q{(int(m) - 1) // 3 + 1}"


def _mean(s: Series, prefix: str, months: set[str] | None = None) -> tuple[float, str] | None:
    vals = [v for p, v in s.obs if p.startswith(prefix) and (months is None or p in months)]
    return (round(mean(vals), 2), f"moyenne {prefix if months is None else _quarter(min(months))}") if vals else None


def value_at(s: Series, period: str | None) -> tuple[float, str] | None:
    """Valeur de la série à une période (convention en tête de fichier)."""
    if not period:
        return s.obs[-1][1], s.obs[-1][0]
    period = _norm(period)
    last = s.obs[-1][0]
    if int(period[:4]) > int(last[:4]):
        return None  # année pas encore publiée (souvent un objectif : « le déficit à 5 % en 2027 ») : pas de verdict calculé
    monthly, annual = bool(_M.match(last)), bool(_Y.match(last))
    if (q := _Q.match(period)) and monthly:
        y, n = q[1], int(q[2])
        return _mean(s, y, {f"{y}-{m:02d}" for m in range(3 * n - 2, 3 * n + 1)}) or _before(s, period)
    if _M.match(period) and not monthly:
        period = period[:4] if annual else _quarter(period)
    elif _Q.match(period) and annual:
        period = period[:4]
    if _Y.match(period):
        if annual:
            return next(((v, p) for p, v in s.obs if p == period), None) or _before(s, period)
        return _mean(s, period)
    for p, v in s.obs:
        if p == period:
            return v, p
    return _before(s, period)


def _before(s: Series, period: str) -> tuple[float, str] | None:
    """Période absente (ex. pas encore publiée) : dernier point antérieur."""
    before = [(p, v) for p, v in s.obs if _t(p) <= _t(period)]
    return (before[-1][1], before[-1][0]) if before else None


# ---------------------------------------------------------------- rédaction (français, sans LLM)

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]
UNIT_SUFFIXES = (" (milliers)", " (milliards d'euros)", " (euros)")


def _num(v: float, decimals: int = 2) -> str:
    """8.3 → « 8,3 », 3595.5 → « 3 595,5 » (espace fine insécable entre les milliers)."""
    text = f"{abs(v):,.{decimals}f}".replace(",", "\u202f").replace(".", ",")
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    return ("−" if v < 0 else "") + text


def _value(v: float, s: Series) -> str:
    if s.is_rate:
        return f"{_num(v)} %"
    if s.unit == "milliers":
        return f"{_num(v / 1000)} million{'s' if abs(v) >= 2000 else ''}" if abs(v) >= 1000 else f"{_num(v * 1000, 0)}"
    if s.unit == "milliards":
        return f"{_num(v, 1)} milliards d'euros"
    if s.unit == "euros":
        return f"{_num(v)} €"
    return _num(v)


def _period(p: str) -> str:
    """« 2026-Q2 » → « au 2e trimestre 2026 », « 2026-09 » → « en septembre 2026 », « moyenne 2017 » → « en moyenne en 2017 »."""
    if p.startswith("moyenne "):
        return "en moyenne " + _period(p[8:])
    if m := _Q.match(p):
        n = int(m[2])
        return f"au {'1er' if n == 1 else f'{n}e'} trimestre {m[1]}"
    if m := _M.match(p):
        return f"en {MONTHS[int(m[2]) - 1]} {m[1]}"
    return f"en {p}"


def _since(p: str) -> str:
    """« 2026-Q1 » → « depuis le 1er trimestre 2026 », « 2017 » → « depuis 2017 »."""
    text = _period(p)
    return "depuis le " + text[3:] if text.startswith("au ") else "depuis " + text[3:]


def _publisher(s: Series) -> str:
    if s.publisher.startswith("INSEE"):
        return "l'INSEE"
    if s.publisher.startswith("DARES"):
        return "la DARES"
    return s.publisher


def _label(s: Series) -> str:
    label = s.label
    for suffix in UNIT_SUFFIXES:
        label = label.removesuffix(suffix)
    return label


def _inline(s: Series) -> str:
    """Libellé en milieu de phrase : minuscule initiale, sauf nom propre (Smic)."""
    label = _label(s)
    return label if label.startswith("Smic") else label[0].lower() + label[1:]


def _points(v: float) -> str:
    return f"{_num(v, 1)} point{'s' if abs(v) >= 2 else ''}"


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


# Objectif ou prévision (« on vise 4,7 % de déficit », « la copie initiale à 4,7 % ») : jamais comparé à un chiffre
# publié. Garde-fou en plus de la consigne d'extraction, que les petits modèles ne suivent pas toujours.
TARGET = re.compile(r"\b(vis(e|ons|ent|er|é|ait)|objectifs?|cibles?|ramener|prévoi[ts]?|prévu[es]*|copie|devrai(t|ent)|"
                    r"d'ici|projet de (loi|budget)|PLF|PLFSS|trajectoire)\b", re.IGNORECASE)


def check(claim: ExtractedClaim, speech_date: str | None = None) -> CheckResult | None:
    """Renvoie un verdict calculé, ou None si le référentiel ne couvre pas l'affirmation."""
    s = load().get(claim.indicator or "")
    if s is None or TARGET.search(claim.quote or ""):
        return None
    if speech_date:
        try:
            s = as_of(s, speech_date)
        except ValueError:
            pass  # date illisible : on garde toute la série
        if s is None:
            return None  # discours antérieur à la série
    try:
        if claim.claim_type == ClaimType.niveau:
            return _check_level(claim, s)
        if claim.claim_type == ClaimType.evolution:
            return _check_evolution(claim, s)
        if claim.claim_type == ClaimType.record:
            return _check_record(claim, s)
    except ValueError:  # période illisible renvoyée par le modèle (« 2026-S1 ») : on passe à la recherche
        return None
    return None


def _check_level(c: ExtractedClaim, s: Series) -> CheckResult | None:
    if c.value is None:
        return None
    got = value_at(s, c.period_end or c.period_start)
    if got is None:
        return None
    official, period = got
    said = BOUND_LABEL[c.bound] + _value(c.value, s)
    if s.is_rate:
        diff = _gap(c.value, official, c.bound)
        verdict = _grade(diff, RATE_TOL)
        gap = _points(diff)
    else:
        diff = _gap(c.value, official, c.bound) / abs(official)
        verdict = _grade(diff, VOLUME_TOL)
        gap = f"{_num(diff * 100, 1)} %"
    crossed = bool(c.bound) and diff > 0
    if crossed and verdict in (Verdict.vrai, Verdict.plutot_vrai):
        verdict = Verdict.imprecis  # « moins de 8 % » alors que c'est 8,3 % : seuil franchi, jamais « vrai »
    official_text = f"{_value(official, s)} {_period(period)}"
    text = f"Selon {_publisher(s)}, {_inline(s)} : {official_text}. "
    if verdict == Verdict.vrai:
        text += f"Le seuil annoncé ({said}) est bien respecté." if c.bound else f"Le chiffre avancé ({said}) correspond à la donnée officielle."
    elif verdict == Verdict.plutot_vrai:
        text += f"Le chiffre avancé ({said}) en est proche, à {gap} près."
    elif crossed:
        text += f"Le seuil annoncé ({said}) n'est pas respecté : écart de {gap}."
    else:
        text += f"Le chiffre avancé ({said}) s'en écarte de {gap}."
    correction = None if verdict == Verdict.vrai else f"{_label(s)} : {official_text}."
    return CheckResult(verdict, official, period, text, [s.source(period)], correction=correction)


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
    sign = "+" if delta > 0 else "−" if delta < 0 else ""
    change = f"{sign}{_points(abs(delta)) if s.is_rate else _value(abs(delta), s)} ({sign}{_num(abs(rel), 1)} %)"
    path = f"de {_value(va, s)} {_period(pa)} à {_value(vb, s)} {_period(pb)}, soit {change}"
    text = f"Selon {_publisher(s)}, {_inline(s)} : {path}. "
    correction = f"{_label(s)} : {path}."
    srcs = [s.source(f"{pa} → {pb}")]
    period = f"{pa} → {pb}"

    if c.direction and c.direction != official_dir and official_dir != "stable":
        return CheckResult(Verdict.faux, round(delta, 2), period,
                           text + f"L'affirmation annonce une {c.direction}, alors que la série est en {official_dir}.",
                           srcs, correction=correction)
    if c.value is None:
        return CheckResult(Verdict.plutot_vrai, round(delta, 2), period,
                           text + "Le sens de l'évolution est juste ; son ampleur n'est pas chiffrée.", srcs, 0.7,
                           correction=correction)

    claimed, bound = abs(c.value), BOUND_LABEL[c.bound]
    note = ""
    if c.unit == Unit.pourcent_variation or (not s.is_rate and c.unit == Unit.pourcent):
        official_mag = abs(rel)
        verdict = _grade(_gap(claimed, official_mag, c.bound) / max(official_mag, 1e-9), VOLUME_TOL, Verdict.trompeur)
        said, official_said = f"{bound}{_num(claimed, 1)} %", f"{_num(official_mag, 1)} %"
    elif not s.is_rate:
        # « 2 millions d'emplois créés », « 1 000 milliards de dette en plus » : écart absolu, dans l'unité de la série
        official_mag = abs(delta)
        verdict = _grade(_gap(claimed, official_mag, c.bound) / max(official_mag, 1e-9), VOLUME_TOL, Verdict.trompeur)
        said, official_said = f"{bound}{_value(claimed, s)}", _value(official_mag, s)
    else:
        official_mag = abs(delta)
        verdict = _grade(_gap(claimed, official_mag, c.bound), RATE_TOL, Verdict.trompeur)
        said, official_said = f"{bound}{_points(claimed)}", _points(official_mag)
        if c.unit == Unit.pourcent:
            note = " Un écart entre deux taux se mesure en points, pas en pourcentage."
    if verdict == Verdict.vrai:
        text += f"L'ampleur annoncée ({said}) correspond à l'évolution officielle."
    elif verdict == Verdict.plutot_vrai:
        text += f"L'ampleur annoncée ({said}) est proche de l'évolution officielle ({official_said})."
    else:
        text += f"L'ampleur annoncée ({said}) ne correspond pas à l'évolution officielle ({official_said})."
    return CheckResult(verdict, round(delta, 2), period, text + note, srcs,
                       correction=None if verdict == Verdict.vrai else correction)


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

    level = "bas" if lowest else "haut"

    def grade(idx: int) -> tuple[Verdict, str]:
        actual, p_prev = years_since_comparable(idx)
        p_ref, v_ref = s.obs[idx]
        years = "moins d'un an" if actual < 1 else f"environ {round(actual)} an{'s' if round(actual) >= 2 else ''}"
        where = (f"il faut remonter {_period(p_prev)} pour trouver un niveau aussi {level}, soit {years}" if p_prev
                 else f"c'est le niveau le plus {level} depuis le début de la série ({_period(s.obs[0][0])[3:]})")
        text = (f"Selon {_publisher(s)}, {_inline(s)} : {_value(v_ref, s)} {_period(p_ref)} ; "
                f"{where}. L'affirmation parle d'environ {round(claimed_years)} ans.")
        if claimed_years <= actual + 1:
            return Verdict.vrai, text
        if claimed_years <= actual * 1.5:
            return Verdict.imprecis, text
        return Verdict.faux, text

    def fix(idx: int) -> str:
        actual, p_prev = years_since_comparable(idx)
        p_ref, v_ref = s.obs[idx]
        since = _since(p_prev) if p_prev else "depuis le début de la série"
        return f"{_label(s)} : {_value(v_ref, s)} {_period(p_ref)}, niveau le plus {level} {since}."

    last = len(s.obs) - 1
    verdict, text = grade(last)
    if verdict == Verdict.faux:
        # C'était peut-être vrai récemment (ex. le chômage est remonté depuis) : on cherche sur 2 ans.
        recent = range(max(0, len(s.obs) - 9), last)
        for i in sorted(recent, key=lambda i: s.obs[i][1], reverse=not lowest):
            v2, t2 = grade(i)
            if v2 == Verdict.vrai:
                return CheckResult(Verdict.imprecis, s.obs[i][1], s.obs[i][0],
                                   f"{t2} C'était vrai {_period(s.obs[i][0])}, mais plus au dernier point publié "
                                   f"({_value(s.obs[-1][1], s)} {_period(s.obs[-1][0])}).",
                                   [s.source()], 0.8, correction=fix(last))
            break
    return CheckResult(verdict, s.obs[-1][1], s.obs[-1][0], text, [s.source()],
                       correction=None if verdict == Verdict.vrai else fix(last))
