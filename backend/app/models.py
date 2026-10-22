"""Contrat de données — SOURCE DE VÉRITÉ côté code.

Toute modification ici doit être répercutée dans docs/DATA_CONTRACT.md et
schemas/claim.schema.json (régénérer avec `python -m app.export_schema`).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- énumérations


class Category(str, Enum):
    emploi = "emploi"
    economie = "economie"        # croissance, inflation, pouvoir d'achat
    finances_publiques = "finances_publiques"  # dette, déficit, impôts
    immigration = "immigration"
    securite = "securite"
    sante = "sante"
    education = "education"
    energie_climat = "energie_climat"
    autre = "autre"


class ClaimType(str, Enum):
    niveau = "niveau"            # « le chômage est à 7,5 % »
    evolution = "evolution"      # « le chômage a baissé de 2 points depuis 2017 »
    record = "record"            # « le chômage est au plus bas depuis 40 ans »
    comparaison = "comparaison"  # « plus bas qu'en Allemagne »
    autre = "autre"


class Unit(str, Enum):
    pourcent = "pourcent"        # un taux (7,5 %)
    points = "points"            # écart de taux (−2 points)
    pourcent_variation = "pourcent_variation"  # variation relative (+10 %)
    milliers = "milliers"
    personnes = "personnes"
    euros = "euros"
    annees = "annees"            # pour les records : « depuis 40 ans »
    autre = "autre"


class Verdict(str, Enum):
    vrai = "vrai"
    plutot_vrai = "plutot_vrai"
    imprecis = "imprecis"
    trompeur = "trompeur"
    faux = "faux"
    inverifiable = "inverifiable"


class Method(str, Enum):
    referentiel = "referentiel"  # comparé à une série officielle figée (data/referentiel)
    web = "web"                  # recherche web par le LLM
    aucun = "aucun"


# ---------------------------------------------------------------- extraction (sortie LLM)


class ExtractedClaim(BaseModel):
    """Une affirmation telle qu'extraite du transcript par le LLM."""

    quote: str = Field(description="Citation exacte (ou quasi exacte) tirée du transcript")
    claim: str = Field(description="Reformulation neutre, autonome et vérifiable de l'affirmation")
    timestamp_start: Optional[float] = Field(description="Début en secondes dans la vidéo, si connu")
    category: Category
    checkable: bool = Field(description="True si l'affirmation est factuelle et vérifiable (pas une opinion ni une promesse)")
    claim_type: ClaimType
    indicator: Optional[str] = Field(description="Clé d'indicateur du référentiel (ex: taux_chomage_bit) ou null")
    value: Optional[float] = Field(description="Valeur chiffrée affirmée, normalisée (7,5 % → 7.5)")
    unit: Optional[Unit]
    direction: Optional[str] = Field(description="'hausse' | 'baisse' | null, pour les évolutions et records")
    period_start: Optional[str] = Field(description="Début de période, format AAAA ou AAAA-Tn, ou null")
    period_end: Optional[str] = Field(description="Fin de période, format AAAA ou AAAA-Tn, ou null (= aujourd'hui)")
    geo: str = Field(description="Périmètre géographique, 'France' par défaut")


class ExtractionResult(BaseModel):
    claims: list[ExtractedClaim]


# ---------------------------------------------------------------- vérification


class Source(BaseModel):
    title: str
    url: str
    publisher: str = Field(description="INSEE, DARES, France Travail, Eurostat, média…")
    note: Optional[str] = Field(default=None, description="Précision : CVS, France hors Mayotte, période…")


class Verification(BaseModel):
    verdict: Verdict
    method: Method
    official_value: Optional[float] = None
    official_period: Optional[str] = None
    correction: Optional[str] = Field(default=None, description="Formulation corrigée de l'affirmation, si besoin")
    explanation: str = Field(description="2-4 phrases neutres, sourcées")
    sources: list[Source] = []
    confidence: float = Field(description="0 à 1")


class WebVerification(BaseModel):
    """Format demandé au LLM quand il vérifie via recherche web."""

    verdict: Verdict
    official_value: Optional[float]
    official_period: Optional[str]
    correction: Optional[str]
    explanation: str
    sources: list[Source]
    confidence: float


class ExplanationText(BaseModel):
    """Format demandé au LLM pour rédiger l'explication d'un verdict calculé en code."""

    explanation: str
    correction: Optional[str]


# ---------------------------------------------------------------- objets stockés / API


class Speaker(BaseModel):
    name: str
    party: Optional[str] = None


class TranscriptSegment(BaseModel):
    start: float
    duration: float = 0.0
    text: str


class AnalyzeRequest(BaseModel):
    """Au moins un de video_id / url / transcript doit être fourni."""

    video_id: Optional[str] = None
    url: Optional[str] = None
    transcript: Optional[list[TranscriptSegment] | str] = None
    speaker: Speaker
    title: Optional[str] = None
    date: Optional[str] = Field(default=None, description="Date du discours AAAA-MM-JJ")
    categories: list[Category] = [Category.emploi]
    use_web: bool = True
    force: bool = Field(default=False, description="Ré-analyser même si déjà en base")


class ClaimResult(BaseModel):
    id: str
    speech_id: str
    claim: ExtractedClaim
    verification: Verification


class Speech(BaseModel):
    id: str
    video_id: Optional[str]
    url: Optional[str]
    title: Optional[str]
    date: Optional[str]
    speaker: Speaker


class AnalyzeResponse(BaseModel):
    speech: Speech
    results: list[ClaimResult]
    stats: dict[str, int]


class PoliticianProfile(BaseModel):
    id: str
    name: str
    party: Optional[str]
    n_speeches: int
    n_claims: int
    verdicts: dict[str, int]
    reliability_score: Optional[float] = Field(description="0-100, null si < 5 affirmations vérifiées")
    by_category: dict[str, dict[str, int]]
