"""Régénère schemas/claim.schema.json depuis models.py : python -m app.export_schema"""
import json
from pathlib import Path

from .models import AnalyzeRequest, AnalyzeResponse, ExtractedClaim, PoliticianProfile, Verification

OUT = Path(__file__).resolve().parents[2] / "schemas" / "claim.schema.json"

schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "FactCheck Politique — contrat de données",
    "description": "Généré depuis backend/app/models.py. Ne pas éditer à la main.",
    "definitions": {m.__name__: m.model_json_schema() for m in
                    (ExtractedClaim, Verification, AnalyzeRequest, AnalyzeResponse, PoliticianProfile)},
}
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"→ {OUT}")
