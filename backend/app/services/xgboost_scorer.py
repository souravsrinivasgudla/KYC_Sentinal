"""
XGBoost Risk Scorer Service
============================
Loads the trained XGBoost model and provides risk score
predictions for KYC state objects.

The model classifies into 3 risk levels:
  0 = Low    → approximate score 25
  1 = Medium → approximate score 55
  2 = High   → approximate score 80

Scores are blended with rule-based signals so existing
risk breakdowns remain explainable.
"""

import json
import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
_model = None
_encoders = None
_metadata = None


def _load_artifacts():
    """Lazy-load model artifacts once."""
    global _model, _encoders, _metadata

    if _model is not None:
        return True

    model_path = MODEL_DIR / "xgboost_risk_model.pkl"
    enc_path = MODEL_DIR / "xgboost_encoders.pkl"
    meta_path = MODEL_DIR / "xgboost_metadata.json"

    if not model_path.exists():
        log.warning("XGBoost model not found at %s — falling back to rule-based scoring", model_path)
        return False

    try:
        with open(model_path, "rb") as f:
            _model = pickle.load(f)
        with open(enc_path, "rb") as f:
            _encoders = pickle.load(f)
        with open(meta_path) as f:
            _metadata = json.load(f)
        log.info("XGBoost model loaded (acc=%.3f)", _metadata.get("metrics", {}).get("accuracy", 0))
        return True
    except Exception as exc:
        log.warning("Failed to load XGBoost model: %s — falling back to rule-based scoring", exc)
        return False


def _country_risk_score(country: str) -> int:
    """Map country code to 1/2/3 risk score matching training scheme."""
    if not _metadata:
        return 1
    c = (country or "").upper()
    if c in _metadata.get("high_risk_countries", []):
        return 3
    if c in _metadata.get("medium_risk_countries", []):
        return 2
    return 1


def _encode_safe(le, value: str, fallback: int = 0) -> int:
    """Encode a label using a pre-trained LabelEncoder with fallback."""
    try:
        return int(le.transform([value])[0])
    except Exception:
        return fallback


def predict_risk(
    screening_results: dict[str, Any],
    financial_profile: dict[str, Any],
    customer_profile: dict[str, Any],
    adverse_media: dict[str, Any],
    evidence_validation: dict[str, Any],
    uploaded_evidence: list[dict[str, Any]],
    groq_verification: dict[str, Any],
) -> dict[str, Any]:
    """
    Run the XGBoost model to predict risk class + probability.

    Returns a dict with:
      ml_risk_class:  0/1/2
      ml_risk_level:  'Low'/'Medium'/'High'
      ml_risk_score:  0-100 blended numeric score
      ml_confidence:  probability for predicted class
      ml_used:        bool
      ml_probabilities: {Low: p, Medium: p, High: p}
    """
    if not _load_artifacts():
        return {"ml_used": False}

    try:
        # ── Build feature vector matching training columns ─────────────────
        nationality = customer_profile.get("nationality_normalized", customer_profile.get("nationality", ""))
        occupation = customer_profile.get("occupation_normalized", customer_profile.get("occupation", ""))
        sector = occupation  # occupation maps to sector in this dataset

        sector_risk_map = _metadata.get("sector_risk_map", {"Low": 0, "Medium": 1, "High": 2})
        fin = financial_profile

        # Map known occupation risk score to sector_risk_enc
        occ_score = fin.get("occupation_risk_score", 15)
        if occ_score >= 25:
            sector_risk_enc = 2  # High
        elif occ_score >= 15:
            sector_risk_enc = 1  # Medium
        else:
            sector_risk_enc = 0  # Low

        client_type_le = _encoders["client_type_le"]
        sector_le = _encoders["sector_le"]

        # client_type: individual → 'Individual', else map to closest known
        client_type_enc = _encode_safe(client_type_le, "Individual", fallback=0)
        sector_enc = _encode_safe(sector_le, sector, fallback=0)

        country_risk = _country_risk_score(nationality)

        # Transaction-based features (we use proxy values from KYC signals)
        tx_count = 1.0  # single customer profile check
        amount_proxy = fin.get("financial_risk_score", 30) * 100
        suspicious_count = (
            (1 if screening_results.get("sanctions") else 0)
            + (1 if adverse_media.get("match") else 0)
        )
        ofac_hit_ratio = 1.0 if screening_results.get("sanctions") else 0.0
        suspicious_tx_ratio = min(suspicious_count / 5.0, 1.0)

        features = [
            # Client-level flags
            int(bool(screening_results.get("pep"))),            # pep_flag
            int(bool(screening_results.get("sanctions"))),      # sanctions_flag
            1 if country_risk == 3 else 0,                      # fatf_country_flag
            1 if country_risk >= 2 else 0,                      # ofac_country_flag
            1 if screening_results.get("sanctions") else 0,     # sectoral_sanctions_flag
            fin.get("missing_source_of_funds", False) * 1.0,    # ownership_opacity_score proxy
            # Encoded categoricals
            sector_risk_enc,
            client_type_enc,
            sector_enc,
            country_risk,
            # Transaction aggregates
            float(tx_count),
            float(amount_proxy),
            float(amount_proxy),
            float(amount_proxy * 1.5),
            0.0,                                                 # tx_std_amount
            float(suspicious_count),                            # ofac_hit_count
            1 if country_risk == 3 else 0,                      # fatf_tx_count
            1 if adverse_media.get("match") else 0,             # structuring_count
            1 if screening_results.get("pep") else 0,           # rapid_movement_count
            0,                                                   # trade_mispricing_count
            1,                                                   # unique_counterparties
            # Ratios
            float(ofac_hit_ratio),
            float(suspicious_tx_ratio),
        ]

        X = np.array([features], dtype=float)

        # Predict
        proba = _model.predict_proba(X)[0]  # [p_low, p_medium, p_high]
        pred_class = int(np.argmax(proba))
        label_map = _metadata.get("label_map", {0: "Low", 1: "Medium", 2: "High"})
        risk_level = label_map[str(pred_class)]
        confidence = float(proba[pred_class])

        # Map class to numeric score range: Low=15-39, Med=40-69, High=70-95
        base_scores = {0: 25, 1: 55, 2: 80}
        # Blend base score with confidence
        ml_score = int(
            base_scores[pred_class]
            + (confidence - 0.5) * 20  # ±10 based on confidence
        )
        ml_score = max(0, min(100, ml_score))

        return {
            "ml_used": True,
            "ml_risk_class": pred_class,
            "ml_risk_level": risk_level,
            "ml_risk_score": ml_score,
            "ml_confidence": round(confidence, 4),
            "ml_probabilities": {
                "Low": round(float(proba[0]), 4),
                "Medium": round(float(proba[1]), 4),
                "High": round(float(proba[2]), 4),
            },
        }

    except Exception as exc:
        log.warning("XGBoost prediction failed: %s — falling back to rule-based", exc)
        return {"ml_used": False}
