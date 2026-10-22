# Contrats de données

Il y a deux niveaux :

1. **Le format d'échange** : `shared/contract.ts`. C'est le format entre l'extension, le serveur Node et le moteur Python. On ne le modifie **qu'en équipe**. Son miroir Python est dans `backend/app/models.py`, section « POST /check ».
2. **Le modèle interne du moteur Python** : `backend/app/models.py`, avec le JSON Schema généré dans `schemas/claim.schema.json` (`python -m app.export_schema`). Il est plus riche (6 verdicts, indicateur, valeur, période…) et sert au stockage et aux profils.

## Format d'échange : POST /check (`shared/contract.ts`)

```jsonc
// CheckRequest  (extension → serveur Node /api/check → moteur Python /check)
{ "source": { "kind": "youtube", "url": "…", "title": "…" },          // kind : article | youtube | selection | podcast
  "segments": [{ "text": "Le chômage est à 7 %…", "start": 801, "speaker": "1" }],
  // facultatif, accepté par le Python mais pas encore dans contract.ts :
  "politician": { "name": "…", "party": "…" }, "date": "AAAA-MM-JJ" }

// CheckResponse
{ "claims": [{ "id": "yt:abc#0", "quote": "Le chômage est à 7 %", "verdict": "faux",
               "explanation": "… Correction : …", "start": 801,
               "sources": [{ "label": "INSEE – Taux de chômage…", "url": "https://…", "official": true }] }],
  "demo": false }
```

Correspondance des verdicts (`backend/app/check_api.py`) :

| Moteur Python | Contrat | Ajout dans `explanation` |
|---|---|---|
| `vrai` | `vrai` | — |
| `plutot_vrai` | `vrai` | préfixe « Plutôt vrai : » |
| `imprecis` | `trompeur` | préfixe « Imprécis : » |
| `trompeur` | `trompeur` | — |
| `faux` | `faux` | — |
| `inverifiable` | `invérifiable` | — |

`official` vaut `true` pour une source du référentiel, ou pour un domaine public (insee.fr, gouv.fr, assemblee-nationale.fr, senat.fr, ec.europa.eu…).

---

# Modèle interne du moteur Python

Toute modification doit changer `models.py`, le schéma généré et ce document dans le même commit, avec une ligne dans le changelog en bas.

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
- 2026-10-22 : fusion avec la branche de Sébastien. `shared/contract.ts` devient le format d'échange ; ajout de `POST /check` et de son miroir Pydantic.
