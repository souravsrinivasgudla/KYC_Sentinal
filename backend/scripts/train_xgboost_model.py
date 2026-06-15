"""
KYC Risk XGBoost Training Script
=================================
Downloads KYC datasets from Kaggle, preprocesses them,
trains an XGBoost classifier for risk scoring, and saves
the model + feature metadata to disk.

Run: venv\Scripts\python scripts/train_xgboost_model.py
"""

import os
import sys
import json
import pickle
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
    accuracy_score,
)
from xgboost import XGBClassifier

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "kaggle_raw"
MODEL_DIR = ROOT / "models"
MODEL_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("train")

# ── 1. Download datasets from Kaggle ──────────────────────────────────────────
def download_datasets():
    """Download KYC dataset from Kaggle if not already present."""
    clients_path = RAW_DIR / "clients_with_fatf_ofac.csv"
    tx_path = RAW_DIR / "transactions_with_fatf_ofac.csv"

    if clients_path.exists() and tx_path.exists():
        log.info("Kaggle datasets already present — skipping download")
        return

    log.info("Downloading KYC dataset from Kaggle...")
    RAW_DIR.mkdir(exist_ok=True)

    # Set Kaggle credentials from .env
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    username = os.getenv("KAGGLE_USERNAME") or os.getenv("kaggle_username")
    key = os.getenv("KAGGLE_KEY") or os.getenv("kaggle_api_key")
    if not username or not key:
        raise RuntimeError("KAGGLE_USERNAME / KAGGLE_KEY not set in .env")

    os.environ["KAGGLE_USERNAME"] = username
    os.environ["KAGGLE_KEY"] = key

    from kaggle import KaggleApi
    api = KaggleApi()
    api.authenticate()
    api.dataset_download_files(
        "chaitalithakkar/synthetic-kyc-and-transaction-risk-dataset",
        path=str(RAW_DIR),
        unzip=True,
    )
    log.info("Download complete")


# ── 2. Load & merge data ──────────────────────────────────────────────────────
def load_and_merge() -> pd.DataFrame:
    """Load client + transaction data, aggregate transactions per client, merge."""
    log.info("Loading client data...")
    clients = pd.read_csv(RAW_DIR / "clients_with_fatf_ofac.csv")

    log.info("Loading transaction data...")
    tx = pd.read_csv(RAW_DIR / "transactions_with_fatf_ofac.csv")

    log.info(f"Clients: {len(clients)} rows | Transactions: {len(tx)} rows")

    # ── Aggregate transaction features per client ──────────────────────────
    tx_agg = tx.groupby("client_id").agg(
        tx_count=("transaction_id", "count"),
        tx_total_amount=("amount", "sum"),
        tx_avg_amount=("amount", "mean"),
        tx_max_amount=("amount", "max"),
        tx_std_amount=("amount", "std"),
        ofac_hit_count=("ofac_match_flag", "sum"),
        fatf_tx_count=("fatf_country_flag", "sum"),
        structuring_count=("structuring_pattern_flag", "sum"),
        rapid_movement_count=("rapid_movement_flag", "sum"),
        trade_mispricing_count=("trade_mispricing_flag", "sum"),
        unique_counterparties=("counterparty_country", "nunique"),
    ).reset_index()

    # Derived ratios
    tx_agg["ofac_hit_ratio"] = tx_agg["ofac_hit_count"] / tx_agg["tx_count"].clip(lower=1)
    tx_agg["suspicious_tx_ratio"] = (
        (tx_agg["structuring_count"] + tx_agg["rapid_movement_count"] + tx_agg["trade_mispricing_count"])
        / tx_agg["tx_count"].clip(lower=1)
    )
    tx_agg["tx_std_amount"] = tx_agg["tx_std_amount"].fillna(0)

    # ── Merge ─────────────────────────────────────────────────────────────
    df = clients.merge(tx_agg, on="client_id", how="left")

    # Fill NaN for clients with no transactions
    tx_cols = [c for c in tx_agg.columns if c != "client_id"]
    df[tx_cols] = df[tx_cols].fillna(0)

    log.info(f"Merged dataset: {df.shape}")
    return df


# ── 3. Feature engineering ────────────────────────────────────────────────────
def engineer_features(df: pd.DataFrame):
    """Build features and composite risk label for XGBoost."""

    # ── Encode sector risk ─────────────────────────────────────────────────
    sector_risk_map = {"Low": 0, "Medium": 1, "High": 2}
    df["sector_risk_enc"] = df["sector_risk"].map(sector_risk_map).fillna(1)

    # ── Encode client type ─────────────────────────────────────────────────
    client_type_le = LabelEncoder()
    df["client_type_enc"] = client_type_le.fit_transform(df["client_type"].fillna("Unknown"))

    # ── Encode sector ──────────────────────────────────────────────────────
    sector_le = LabelEncoder()
    df["sector_enc"] = sector_le.fit_transform(df["sector"].fillna("Unknown"))

    # ── Country risk mapping (high-risk countries) ─────────────────────────
    HIGH_RISK_COUNTRIES = {
        "AF", "IR", "KP", "MM", "SS", "SY", "YE", "LY", "SO", "SD",
        "VE", "HT", "NI", "BI", "CF", "CD", "MZ", "PG", "PH", "LB",
        "RU", "BY", "CU", "ZW",
    }
    MEDIUM_RISK_COUNTRIES = {
        "PK", "BD", "NG", "GH", "KE", "TZ", "MX", "CO", "PE", "GT",
        "HN", "SV", "TH", "VN", "ID", "TR", "UA", "KZ", "AZ", "GE",
        "MA", "TN", "DZ", "EG", "ET",
    }
    def country_risk_score(c):
        if c in HIGH_RISK_COUNTRIES:
            return 3
        if c in MEDIUM_RISK_COUNTRIES:
            return 2
        return 1

    df["country_risk_score"] = df["country"].fillna("XX").apply(country_risk_score)

    # ── Composite risk label ───────────────────────────────────────────────
    # Score: weight different risk signals to create a 3-class label
    # 0=Low, 1=Medium, 2=High
    df["risk_signal_score"] = (
        df["sanctions_flag"] * 3
        + df["pep_flag"] * 2
        + df["fatf_country_flag"] * 1
        + df["ofac_country_flag"] * 1
        + df["sectoral_sanctions_flag"] * 1
        + df["ownership_opacity_score"] * 1
        + df["sector_risk_enc"] * 0.5
        + df["country_risk_score"] * 0.5
        + df["ofac_hit_ratio"] * 2
        + df["suspicious_tx_ratio"] * 2
    )

    # Bin into 3 risk levels: Low=0, Medium=1, High=2
    low_thresh = df["risk_signal_score"].quantile(0.45)
    high_thresh = df["risk_signal_score"].quantile(0.75)

    def label_risk(s):
        if s >= high_thresh:
            return 2  # High
        if s >= low_thresh:
            return 1  # Medium
        return 0  # Low

    df["risk_label"] = df["risk_signal_score"].apply(label_risk)

    log.info(f"Risk label distribution: {df['risk_label'].value_counts().to_dict()}")

    # ── Feature columns ────────────────────────────────────────────────────
    FEATURES = [
        # Client-level flags
        "pep_flag",
        "sanctions_flag",
        "fatf_country_flag",
        "ofac_country_flag",
        "sectoral_sanctions_flag",
        "ownership_opacity_score",
        # Encoded categoricals
        "sector_risk_enc",
        "client_type_enc",
        "sector_enc",
        "country_risk_score",
        # Transaction aggregates
        "tx_count",
        "tx_total_amount",
        "tx_avg_amount",
        "tx_max_amount",
        "tx_std_amount",
        "ofac_hit_count",
        "fatf_tx_count",
        "structuring_count",
        "rapid_movement_count",
        "trade_mispricing_count",
        "unique_counterparties",
        # Derived ratios
        "ofac_hit_ratio",
        "suspicious_tx_ratio",
    ]

    X = df[FEATURES].copy()
    y = df["risk_label"].copy()

    # Store metadata for inference
    metadata = {
        "features": FEATURES,
        "client_type_classes": client_type_le.classes_.tolist(),
        "sector_classes": sector_le.classes_.tolist(),
        "sector_risk_map": sector_risk_map,
        "high_risk_countries": list(HIGH_RISK_COUNTRIES),
        "medium_risk_countries": list(MEDIUM_RISK_COUNTRIES),
        "risk_thresholds": {
            "low_max": float(low_thresh),
            "high_min": float(high_thresh),
        },
        "label_map": {0: "Low", 1: "Medium", 2: "High"},
        "score_map": {0: 25, 1: 55, 2: 80},  # numeric risk scores for KYC
    }

    return X, y, metadata, client_type_le, sector_le


# ── 4. Train XGBoost ──────────────────────────────────────────────────────────
def train_model(X: pd.DataFrame, y: pd.Series):
    """Train XGBoost classifier with cross-validation."""
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    log.info(f"Train: {len(X_train)} | Test: {len(X_test)}")

    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        gamma=0.1,
        reg_alpha=0.1,
        reg_lambda=1.0,
        use_label_encoder=False,
        eval_metric="mlogloss",
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )

    log.info("Training XGBoost...")
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # ── Evaluate ────────────────────────────────────────────────────────────
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)

    acc = accuracy_score(y_test, y_pred)
    log.info(f"Accuracy: {acc:.4f}")

    try:
        roc = roc_auc_score(y_test, y_proba, multi_class="ovr", average="weighted")
        log.info(f"ROC-AUC (weighted OvR): {roc:.4f}")
    except Exception:
        pass

    log.info("\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=["Low", "Medium", "High"]))

    log.info("\nConfusion Matrix:")
    print(confusion_matrix(y_test, y_pred))

    # ── Cross-validation ────────────────────────────────────────────────────
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X, y, cv=cv, scoring="accuracy")
    log.info(f"\nCV Accuracy: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

    # ── Feature importance ──────────────────────────────────────────────────
    importances = dict(zip(X.columns, model.feature_importances_))
    top_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:10]
    log.info("\nTop 10 features by importance:")
    for feat, imp in top_features:
        log.info(f"  {feat}: {imp:.4f}")

    return model, {
        "accuracy": float(acc),
        "cv_mean": float(cv_scores.mean()),
        "cv_std": float(cv_scores.std()),
        "feature_importances": {k: float(v) for k, v in importances.items()},
        "top_features": [{"feature": f, "importance": float(i)} for f, i in top_features],
    }


# ── 5. Save artifacts ─────────────────────────────────────────────────────────
def save_artifacts(model, metadata: dict, metrics: dict, client_type_le, sector_le):
    """Persist model, encoders, and metadata."""
    # Model
    model_path = MODEL_DIR / "xgboost_risk_model.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    log.info(f"Model saved → {model_path}")

    # Encoders
    enc_path = MODEL_DIR / "xgboost_encoders.pkl"
    with open(enc_path, "wb") as f:
        pickle.dump({"client_type_le": client_type_le, "sector_le": sector_le}, f)
    log.info(f"Encoders saved → {enc_path}")

    # Metadata + metrics
    full_meta = {**metadata, "metrics": metrics}
    meta_path = MODEL_DIR / "xgboost_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(full_meta, f, indent=2)
    log.info(f"Metadata saved → {meta_path}")

    return model_path


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    download_datasets()
    df = load_and_merge()
    X, y, metadata, client_type_le, sector_le = engineer_features(df)
    model, metrics = train_model(X, y)
    save_artifacts(model, metadata, metrics, client_type_le, sector_le)
    log.info("\n✓ XGBoost KYC risk model training complete!")
