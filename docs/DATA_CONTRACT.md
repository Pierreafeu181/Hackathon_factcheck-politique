# Contrat de données (GELÉ)

Source de vérité : `backend/app/models.py`. JSON Schema généré : `schemas/claim.schema.json` (`python -m app.export_schema`).
Toute modification doit changer les deux fichiers et ce document dans le même commit, avec une ligne dans le changelog en bas.

## ExtractedClaim : une affirmation

```json
{
  "quote": "depuis 2017 le chômage a baissé de plus de trois points",
  "claim": "Le taux de chômage en France a baissé de plus de 3 points entre 2017 et aujourd'hui.",
  "timestamp_start": 22,
  "category": "emploi",
  "checkable": true,
  "claim_type": "evolution",
  "indicator": "taux_chomage_bit",
  "value": 3,
  "unit": "points",
  "direction": "baisse",
  "period_start": "2017",
  "period_end": null,
  "geo": "France"
}
```

| Champ | Valeurs |
|---|---|
| `category` | `emploi`, `economie`, `finances_publiques`, `immigration`, `securite`, `sante`, `education`, `energie_climat`, `autre` |
| `claim_type` | `niveau`, `evolution`, `record`, `comparaison`, `autre` |
| `indicator` | clé de `data/referentiel/*.json` (voir `GET /indicators`) ou `null` |
| `unit` | `pourcent`, `points`, `pourcent_variation`, `milliers`, `personnes`, `euros`, `annees`, `autre` |
| `value` | exprimée **dans l'unité de l'indicateur** (volumes en milliers : 3,3 M → 3300) |
| `direction` | `hausse`, `baisse`, `null`. Pour un record : `baisse` = « plus bas » |
| `period_*` | `AAAA`, `AAAA-Tn` (ou `AAAA-Qn`), `AAAA-MM` ; `period_end: null` = dernier point disponible |

## Verification : un verdict

```json
{
  "verdict": "trompeur",
  "method": "referentiel",
  "official_value": -1.1,
  "official_period": "moyenne 2017 → 2026-Q2",
  "correction": "Le taux de chômage a baissé d'environ 1 point entre 2017 (9,4 %) et mi-2026 (8,3 %).",
  "explanation": "Selon l'INSEE, …",
  "sources": [{"title": "Taux de chômage au sens du BIT (ensemble)", "url": "https://www.insee.fr/fr/statistiques/serie/001688527", "publisher": "INSEE", "note": "France hors Mayotte, CVS"}],
  "confidence": 0.9
}
```

| Champ | Valeurs |
|---|---|
| `verdict` | `vrai`, `plutot_vrai`, `imprecis`, `trompeur`, `faux`, `inverifiable` |
| `method` | `referentiel`, `web`, `aucun` |
| `official_value` | niveau officiel, ou écart officiel pour une évolution |
| `confidence` | 0–1 ; le référentiel donne 0,7–0,9, le web est plafonné à 0,7 |

Invariant : si `verdict != inverifiable`, alors `sources` n'est pas vide.

## API

- `AnalyzeRequest` : `{video_id?, url?, transcript?: string | [{start, duration, text}], speaker: {name, party?}, title?, date?, categories?: ["emploi"], use_web?: true, force?: false}`
- `AnalyzeResponse` : `{speech: Speech, results: [{id, speech_id, claim: ExtractedClaim, verification: Verification}], stats: {verdict: count}}`
- `PoliticianProfile` : `{id, name, party, n_speeches, n_claims, verdicts, reliability_score (0-100 ou null), by_category}`

Identifiants : speech `yt:<video_id>` (ou `txt:<hash>`), claim `<speech_id>#<n>`, politicien = slug du nom.

## Changelog

- 2026-10-22 : v0.1, contrat initial.
