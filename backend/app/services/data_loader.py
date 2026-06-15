import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load_dataset_manifest() -> dict:
    path = DATA_DIR / "dataset_manifest.json"
    if not path.exists():
        return {"sources": ["synthetic"], "watchlist_count": 0}
    import json
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_country_risk() -> dict[str, int]:
    df = pd.read_csv(DATA_DIR / "country_risk.csv", keep_default_na=False)
    return dict(zip(df["country"], df["risk_score"]))


def load_occupation_risk() -> dict[str, int]:
    df = pd.read_csv(DATA_DIR / "occupation_risk.csv")
    return dict(zip(df["occupation"], df["risk_score"]))


def load_customers() -> list[dict]:
    df = pd.read_csv(DATA_DIR / "customers.csv")
    df = df.fillna("")
    return df.to_dict(orient="records")


def load_watchlist() -> list[dict]:
    with open(DATA_DIR / "sanctions_watchlist.json", encoding="utf-8") as f:
        return json.load(f)


def load_adverse_media() -> list[dict]:
    with open(DATA_DIR / "adverse_media.json", encoding="utf-8") as f:
        return json.load(f)
