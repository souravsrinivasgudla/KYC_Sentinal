"""
Fetch KYC-relevant datasets:
  1. OpenSanctions sanctions + PEP (public bulk download, no API key)
  2. Kaggle Synthetic KYC dataset (requires ~/.kaggle/kaggle.json)

Run: python -m scripts.fetch_datasets
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.country_mapper import ISO2_TO_NAME, country_risk_from_iso, normalize_country

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
KAGGLE_DIR = DATA / "kaggle"

OPENSANCTIONS_SOURCES = {
    "sanctions": "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv",
    "peps": "https://data.opensanctions.org/datasets/latest/peps/targets.simple.csv",
}

KAGGLE_DATASETS = [
    "chaitalithakkar/synthetic-kyc-and-transaction-risk-dataset",
    "berkanoztas/synthetic-transaction-monitoring-dataset-aml",
]

MAX_SANCTIONS_ROWS = 3000
MAX_PEP_ROWS = 2000


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {url} ...")
    with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(65536):
                f.write(chunk)
    print(f"  Saved {dest.name} ({dest.stat().st_size / 1_048_576:.1f} MB)")


def fetch_opensanctions() -> None:
    print("\n=== OpenSanctions (sanctions + PEP) ===")
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in OPENSANCTIONS_SOURCES.items():
        dest = RAW / f"opensanctions_{name}.csv"
        if not dest.exists():
            try:
                download_file(url, dest)
            except Exception as e:
                print(f"  WARN: Could not download {name}: {e}")
                continue
        else:
            print(f"  Using cached {dest.name}")


def fetch_kaggle() -> bool:
    print("\n=== Kaggle datasets ===")
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if not kaggle_json.exists():
        print("  SKIP: No Kaggle credentials at ~/.kaggle/kaggle.json")
        print("  Create API token at https://www.kaggle.com/settings")
        return False

    KAGGLE_DIR.mkdir(parents=True, exist_ok=True)
    ok = False
    for slug in KAGGLE_DATASETS:
        out = KAGGLE_DIR / slug.split("/")[-1]
        out.mkdir(parents=True, exist_ok=True)
        print(f"  Downloading {slug} ...")
        try:
            subprocess.run(
                [sys.executable, "-m", "kaggle", "datasets", "download", "-d", slug, "-p", str(out), "--unzip"],
                check=True,
                capture_output=True,
                text=True,
            )
            ok = True
            print(f"  OK: {slug}")
        except subprocess.CalledProcessError as e:
            print(f"  FAIL: {slug} — {e.stderr[:200] if e.stderr else e}")
    return ok


def _safe_str(val) -> str:
    if pd.isna(val) or val is None:
        return ""
    return str(val).strip()


def transform_opensanctions_to_watchlist() -> list[dict]:
    watchlist: list[dict] = []
    sanctions_path = RAW / "opensanctions_sanctions.csv"
    peps_path = RAW / "opensanctions_peps.csv"

    if sanctions_path.exists():
        df = pd.read_csv(sanctions_path, low_memory=False, nrows=MAX_SANCTIONS_ROWS)
        for i, row in df.iterrows():
            name = _safe_str(row.get("name") or row.get("caption") or row.get("id"))
            if not name:
                continue
            aliases = _safe_str(row.get("aliases", ""))
            alias_list = [a.strip() for a in aliases.split(";") if a.strip()][:5]
            watchlist.append(
                {
                    "id": f"SAN-OS-{i:05d}",
                    "name": name,
                    "aliases": alias_list,
                    "dob": _safe_str(row.get("birth_date", "")),
                    "nationality": normalize_country(_safe_str(row.get("countries", "")).split(";")[0]),
                    "nationality_iso": _safe_str(row.get("countries", "")).split(";")[0].lower()[:2],
                    "type": "sanctions",
                    "list": _safe_str(row.get("dataset", "OpenSanctions")),
                    "reason": _safe_str(row.get("sanctions", "") or "Sanctioned entity"),
                    "source": "opensanctions",
                }
            )

    if peps_path.exists():
        df = pd.read_csv(peps_path, low_memory=False, nrows=MAX_PEP_ROWS)
        for i, row in df.iterrows():
            name = _safe_str(row.get("name") or row.get("caption") or row.get("id"))
            if not name:
                continue
            aliases = _safe_str(row.get("aliases", ""))
            alias_list = [a.strip() for a in aliases.split(";") if a.strip()][:5]
            watchlist.append(
                {
                    "id": f"PEP-OS-{i:05d}",
                    "name": name,
                    "aliases": alias_list,
                    "dob": _safe_str(row.get("birth_date", "")),
                    "nationality": normalize_country(_safe_str(row.get("countries", "")).split(";")[0]),
                    "nationality_iso": _safe_str(row.get("countries", "")).split(";")[0].lower()[:2],
                    "type": "pep",
                    "list": "OpenSanctions PEP",
                    "reason": _safe_str(row.get("dataset", "") or "Politically exposed person"),
                    "source": "opensanctions",
                }
            )

    return watchlist


def transform_kaggle_kyc() -> tuple[list[dict], pd.DataFrame | None]:
    """Extract watchlist hints and country risk from Kaggle KYC dataset."""
    extra_watchlist: list[dict] = []
    kyc_df = None

    for subdir in KAGGLE_DIR.iterdir() if KAGGLE_DIR.exists() else []:
        for csv in subdir.glob("**/*.csv"):
            try:
                df = pd.read_csv(csv, nrows=5000, low_memory=False)
            except Exception:
                continue
            cols = {c.lower(): c for c in df.columns}

            if any(k in cols for k in ("pep_status", "sanctions", "risk", "kyc")):
                kyc_df = df
                print(f"  Found Kaggle KYC file: {csv.name} ({len(df)} rows)")

                name_col = next((cols[k] for k in ("full_name", "name", "customer_name", "client_name") if k in cols), None)
                pep_col = next((cols[k] for k in ("pep_status", "is_pep", "pep") if k in cols), None)
                sanc_col = next((cols[k] for k in ("sanctions_screening_result", "sanctions", "sanction_hit") if k in cols), None)

                if name_col:
                    for i, row in df.head(500).iterrows():
                        name = _safe_str(row.get(name_col))
                        if not name:
                            continue
                        is_pep = str(row.get(pep_col, "")).lower() in ("true", "1", "yes", "pep") if pep_col else False
                        is_sanc = str(row.get(sanc_col, "")).lower() in ("true", "1", "yes", "hit", "match") if sanc_col else False
                        if is_pep:
                            extra_watchlist.append(
                                {
                                    "id": f"PEP-KG-{i:05d}",
                                    "name": name,
                                    "aliases": [],
                                    "dob": "",
                                    "nationality": "",
                                    "type": "pep",
                                    "list": "Kaggle Synthetic KYC",
                                    "reason": "PEP flag in synthetic KYC dataset",
                                    "source": "kaggle",
                                }
                            )
                        if is_sanc:
                            extra_watchlist.append(
                                {
                                    "id": f"SAN-KG-{i:05d}",
                                    "name": name,
                                    "aliases": [],
                                    "dob": "",
                                    "nationality": "",
                                    "type": "sanctions",
                                    "list": "Kaggle Synthetic KYC",
                                    "reason": "Sanctions hit in synthetic KYC dataset",
                                    "source": "kaggle",
                                }
                            )
    return extra_watchlist, kyc_df


def build_country_risk_from_kaggle(kyc_df: pd.DataFrame | None) -> dict[str, int]:
    base = {
        "India": 5, "Singapore": 5, "United States": 5, "United Kingdom": 5,
        "Iran": 25, "North Korea": 30, "Syria": 25, "Russia": 20,
    }
    if kyc_df is None:
        return base

    cols = {c.lower(): c for c in kyc_df.columns}
    country_col = next(
        (cols[k] for k in ("nationality", "country", "residence_country", "tax_domicile", "country_code") if k in cols),
        None,
    )
    risk_col = next(
        (cols[k] for k in ("kyc_risk_rating", "risk_score", "risk_rating", "risk_level", "aml_risk_score") if k in cols),
        None,
    )
    if not country_col:
        return base

    for _, row in kyc_df.iterrows():
        country = _safe_str(row.get(country_col))
        if not country or len(country) < 2:
            continue
        if risk_col:
            try:
                risk_val = float(row.get(risk_col, 10))
                score = min(30, max(5, int(risk_val / 3) if risk_val > 10 else int(risk_val)))
            except (TypeError, ValueError):
                score = 10
        else:
            score = 10
        if country not in base:
            base[country] = score
    return base


def build_adverse_media_from_kaggle(kyc_df: pd.DataFrame | None) -> list[dict]:
    media = []
    if kyc_df is None:
        return media

    cols = {c.lower(): c for c in kyc_df.columns}
    name_col = next((cols[k] for k in ("full_name", "name", "customer_name") if k in cols), None)
    am_col = next((cols[k] for k in ("adverse_media_flag", "adverse_media", "has_adverse_media") if k in cols), None)
    if not name_col or not am_col:
        return media

    for i, row in kyc_df.iterrows():
        if str(row.get(am_col, "")).lower() not in ("true", "1", "yes"):
            continue
        name = _safe_str(row.get(name_col))
        if not name:
            continue
        media.append(
            {
                "id": f"AM-KG-{i:05d}",
                "subject": name,
                "aliases": [],
                "title": f"Adverse media flag — {name}",
                "source": "Kaggle Synthetic KYC Dataset",
                "date": "2024-01-01",
                "severity": "Medium",
                "categories": ["adverse media", "compliance flag"],
                "summary": "Flagged in synthetic KYC/AML training dataset for adverse media screening.",
                "url": "",
            }
        )
        if len(media) >= 200:
            break
    return media


def main():
    print("KYC Sentinel — Dataset Fetcher")
    DATA.mkdir(parents=True, exist_ok=True)

    fetch_opensanctions()
    kaggle_ok = fetch_kaggle()

    print("\n=== Transforming to project format ===")
    watchlist = transform_opensanctions_to_watchlist()
    print(f"  OpenSanctions watchlist entries: {len(watchlist)}")

    kaggle_wl, kyc_df = transform_kaggle_kyc()
    if kaggle_wl:
        watchlist.extend(kaggle_wl)
        print(f"  Kaggle watchlist entries: {len(kaggle_wl)}")

    if not watchlist:
        print("  ERROR: No watchlist data. Keeping existing files.")
        return 1

    out_watchlist = DATA / "sanctions_watchlist.json"
    backup = DATA / "sanctions_watchlist.backup.json"
    if out_watchlist.exists():
        shutil.copy(out_watchlist, backup)

    with open(out_watchlist, "w", encoding="utf-8") as f:
        json.dump(watchlist, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {out_watchlist} ({len(watchlist)} entries)")

    country_risk = build_country_risk_from_kaggle(kyc_df)
    for iso, name in ISO2_TO_NAME.items():
        if name not in country_risk:
            country_risk[name] = country_risk_from_iso(iso)
    sanctions_csv = RAW / "opensanctions_sanctions.csv"
    if sanctions_csv.exists():
        sanc_df = pd.read_csv(sanctions_csv, usecols=["countries"], low_memory=False)
        for c in sanc_df["countries"].dropna().astype(str):
            for iso in c.split(";"):
                iso = iso.strip().lower()[:2]
                name = ISO2_TO_NAME.get(iso, iso.upper())
                if name not in country_risk:
                    country_risk[name] = country_risk_from_iso(iso)
    pd.DataFrame([{"country": k, "risk_score": v} for k, v in sorted(country_risk.items())]).to_csv(
        DATA / "country_risk.csv", index=False
    )
    print(f"  Wrote country_risk.csv ({len(country_risk)} countries)")

    adverse = build_adverse_media_from_kaggle(kyc_df)
    if adverse:
        existing = []
        am_path = DATA / "adverse_media.json"
        if am_path.exists():
            with open(am_path, encoding="utf-8") as f:
                existing = json.load(f)
        combined = existing + adverse
        with open(am_path, "w", encoding="utf-8") as f:
            json.dump(combined, f, indent=2, ensure_ascii=False)
        print(f"  Appended {len(adverse)} Kaggle adverse media entries")

    sources = ["opensanctions"]
    if kaggle_ok:
        sources.append("kaggle")
    meta = {
        "sources": sources,
        "watchlist_count": len(watchlist),
        "sanctions_entries": sum(1 for w in watchlist if w["type"] == "sanctions"),
        "pep_entries": sum(1 for w in watchlist if w["type"] == "pep"),
        "opensanctions_sanctions_rows": MAX_SANCTIONS_ROWS,
        "opensanctions_pep_rows": MAX_PEP_ROWS,
        "kaggle_available": kaggle_ok,
        "kaggle_datasets": KAGGLE_DATASETS if kaggle_ok else [],
    }
    with open(DATA / "dataset_manifest.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print("\n=== Rebuild vector index ===")
    idx = DATA.parent / "vector_db" / "tfidf_index.pkl"
    if idx.exists():
        idx.unlink()
        print("  Cleared vector index (will rebuild on next server start)")

    print("\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
