"""
Indian KYC Document Classifier — Training Script
==================================================
Generates a domain-accurate synthetic dataset for six
Indian proof-of-identity/address documents, then trains
an XGBoost classifier to:
  1. Identify the document TYPE
  2. Determine if the document is VALID for KYC purposes

Indian documents modelled:
  • Aadhaar Card       (POI + POA)
  • PAN Card           (POI)
  • Passport           (POI + POA)
  • Voter ID (EPIC)    (POI + POA)
  • Driving Licence    (POI + POA)
  • Bank Passbook      (POA only)

Each document type has specific required fields, format
rules, and validity criteria drawn from UIDAI/NSDL/MEA
and RBI KYC Master Directions.

Run: venv\\Scripts\\python scripts/train_document_classifier.py
"""

import json
import logging
import os
import pickle
import random
import re
import string
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"
MODEL_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("doc_train")

# ── Document type constants ────────────────────────────────────────────────────
DOC_TYPES = [
    "aadhaar_card",
    "pan_card",
    "passport",
    "voter_id",
    "driving_licence",
    "bank_passbook",
]

DOC_LABEL_MAP = {d: i for i, d in enumerate(DOC_TYPES)}

# KYC purpose mapping per UIDAI / RBI guidelines
DOC_KYC_PURPOSE = {
    "aadhaar_card":    {"poi": True,  "poa": True},
    "pan_card":        {"poi": True,  "poa": False},
    "passport":        {"poi": True,  "poa": True},
    "voter_id":        {"poi": True,  "poa": True},
    "driving_licence": {"poi": True,  "poa": True},
    "bank_passbook":   {"poi": False, "poa": True},
}

# Indian state codes used for region-specific logic
INDIAN_STATE_CODES = [
    "AP", "AR", "AS", "BR", "CG", "GA", "GJ", "HR", "HP", "JH",
    "KA", "KL", "MP", "MH", "MN", "ML", "MZ", "NL", "OD", "PB",
    "RJ", "SK", "TN", "TG", "TR", "UP", "UK", "WB", "AN", "CH",
    "DH", "DD", "DL", "JK", "LA", "LD", "PY",
]

RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)


# ─────────────────────────────────────────────────────────────────────────────
# Helper generators
# ─────────────────────────────────────────────────────────────────────────────

def rnd_str(chars: str, n: int) -> str:
    return "".join(random.choices(chars, k=n))


def valid_aadhaar() -> str:
    """12-digit numeric Aadhaar — never starts with 0 or 1."""
    first = str(random.randint(2, 9))
    rest = rnd_str(string.digits, 11)
    return first + rest


def valid_pan() -> str:
    """PAN: AAAAA9999A — 5 letters, 4 digits, 1 letter."""
    return (
        rnd_str(string.ascii_uppercase, 5)
        + rnd_str(string.digits, 4)
        + rnd_str(string.ascii_uppercase, 1)
    )


def valid_passport_no() -> str:
    """Indian passport: 1 letter + 7 digits (A1234567)."""
    return rnd_str(string.ascii_uppercase, 1) + rnd_str(string.digits, 7)


def valid_voter_id() -> str:
    """EPIC: 3 letters + 7 digits (ABC1234567)."""
    return rnd_str(string.ascii_uppercase, 3) + rnd_str(string.digits, 7)


def valid_dl_no() -> str:
    """DL: StateCode-YY-NNNNNNN  e.g. MH-12-20180012345."""
    state = random.choice(INDIAN_STATE_CODES)
    year = str(random.randint(10, 23))
    num = rnd_str(string.digits, 7)
    return f"{state}-{year}-{num}"


def valid_passbook_no() -> str:
    """Bank account / passbook number: 9-18 digits."""
    length = random.randint(9, 18)
    return rnd_str(string.digits, length)


def random_dob(min_age: int = 18, max_age: int = 80) -> str:
    """Return DOB as DD/MM/YYYY string."""
    age = random.randint(min_age, max_age)
    year = 2025 - age
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return f"{day:02d}/{month:02d}/{year}"


def random_expiry(years_from_now: int = 1, max_years: int = 10) -> str:
    base_year = random.randint(2025 + years_from_now, 2025 + max_years)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return f"{day:02d}/{month:02d}/{base_year}"


def expired_date() -> str:
    """Return a past date as expiry."""
    year = random.randint(2010, 2023)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return f"{day:02d}/{month:02d}/{year}"


def random_name() -> str:
    first = random.choice([
        "Rahul", "Priya", "Amit", "Sunita", "Ravi", "Anita", "Suresh",
        "Kavita", "Vijay", "Deepa", "Arjun", "Meena", "Ajay", "Sonal",
        "Nikhil", "Pooja", "Kiran", "Rekha", "Sanjay", "Lakshmi",
        "Arun", "Neha", "Vishal", "Asha", "Rajesh", "Geeta", "Mohan",
        "Shanti", "Prakash", "Usha", "Dinesh", "Sarla", "Manish",
        "Savita", "Anil", "Pushpa", "Rohit", "Kamla", "Sunil", "Rekha",
    ])
    last = random.choice([
        "Sharma", "Verma", "Gupta", "Patel", "Singh", "Kumar", "Yadav",
        "Joshi", "Nair", "Pillai", "Reddy", "Rao", "Iyer", "Menon",
        "Kapoor", "Malhotra", "Bose", "Das", "Chatterjee", "Mukherjee",
        "Shah", "Mehta", "Trivedi", "Desai", "Jain", "Agarwal", "Tiwari",
        "Mishra", "Pandey", "Dubey", "Chouhan", "Rajput", "Rathore",
    ])
    return f"{first} {last}"


def random_address() -> str:
    house = random.randint(1, 999)
    roads = ["MG Road", "Nehru Nagar", "Gandhi Colony", "Rajpur Road",
             "Station Road", "Shivaji Marg", "Civil Lines", "Sector 12",
             "Indira Nagar", "Lal Bagh Road", "Anna Salai", "Ring Road"]
    cities = ["Mumbai", "Delhi", "Bengaluru", "Chennai", "Hyderabad",
              "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Lucknow",
              "Chandigarh", "Bhopal", "Patna", "Kochi", "Nagpur"]
    state = random.choice(INDIAN_STATE_CODES)
    pincode = str(random.randint(100000, 999999))
    return f"{house}, {random.choice(roads)}, {random.choice(cities)}, {state} - {pincode}"


def random_gender() -> str:
    return random.choice(["M", "F", "M", "M", "F"])


# ─────────────────────────────────────────────────────────────────────────────
# Document record generators — one per doc type
# ─────────────────────────────────────────────────────────────────────────────

def _corrupt(value: str, corruption_type: str = "truncate") -> str:
    """Introduce a realistic corruption into a field value."""
    if not value:
        return value
    if corruption_type == "truncate":
        cut = max(1, len(value) // 2)
        return value[:cut]
    if corruption_type == "wrong_format":
        return rnd_str(string.ascii_letters, len(value))
    if corruption_type == "extra_chars":
        return value + rnd_str(string.punctuation, 3)
    return value


def gen_aadhaar(is_valid: bool) -> dict:
    """Generate Aadhaar card feature record."""
    has_number = True
    has_name = True
    has_dob = True
    has_address = True
    has_gender = True
    has_photo = random.random() > 0.05
    has_qr_code = random.random() > 0.1
    has_enrolment_no = random.random() > 0.15

    number = valid_aadhaar()
    number_format_ok = True
    name_matches_profile = random.random() > 0.05
    dob_format_ok = True
    address_complete = random.random() > 0.1
    issuer_present = True                   # UIDAI
    language_secondary = random.random() > 0.2  # regional language on card

    if not is_valid:
        fault = random.choice([
            "bad_number", "no_name", "no_dob", "bad_format",
            "no_address", "name_mismatch", "no_photo",
        ])
        if fault == "bad_number":
            number_format_ok = False
            number = "0" + rnd_str(string.digits, 11)  # starts with 0 — invalid
        elif fault == "no_name":
            has_name = False
        elif fault == "no_dob":
            has_dob = False
        elif fault == "bad_format":
            number = rnd_str(string.ascii_letters, 12)
            number_format_ok = False
        elif fault == "no_address":
            has_address = False
            address_complete = False
        elif fault == "name_mismatch":
            name_matches_profile = False
        elif fault == "no_photo":
            has_photo = False

    return {
        "doc_type_label": DOC_LABEL_MAP["aadhaar_card"],
        "doc_type": "aadhaar_card",
        "has_doc_number": has_number,
        "doc_number_length": len(number),
        "doc_number_format_ok": number_format_ok,
        "has_name": has_name,
        "has_dob": has_dob,
        "has_address": has_address,
        "has_gender": has_gender,
        "has_photo": has_photo,
        "has_expiry": False,         # Aadhaar does not expire
        "expiry_valid": True,        # N/A
        "has_issuer": issuer_present,
        "has_signature": False,      # Aadhaar has no signature field
        "has_qr_or_barcode": has_qr_code,
        "has_enrolment_no": has_enrolment_no,
        "name_matches_profile": name_matches_profile,
        "address_complete": address_complete,
        "language_secondary_present": language_secondary,
        "is_poi": True,
        "is_poa": True,
        "is_valid": is_valid,
    }


def gen_pan(is_valid: bool) -> dict:
    """Generate PAN card feature record."""
    has_number = True
    number = valid_pan()
    number_format_ok = True
    has_name = True
    has_dob = True
    has_father_name = random.random() > 0.05
    has_photo = random.random() > 0.05
    has_signature = random.random() > 0.08
    has_issuer = True                       # Income Tax Department of India
    name_matches_profile = random.random() > 0.05

    if not is_valid:
        fault = random.choice([
            "bad_number", "no_name", "bad_format",
            "no_dob", "no_photo", "name_mismatch",
        ])
        if fault == "bad_number":
            number_format_ok = False
            number = rnd_str(string.digits, 10)  # all digits — invalid
        elif fault == "no_name":
            has_name = False
        elif fault == "bad_format":
            number = rnd_str(string.digits, 5) + rnd_str(string.ascii_uppercase, 5)
            number_format_ok = False
        elif fault == "no_dob":
            has_dob = False
        elif fault == "no_photo":
            has_photo = False
        elif fault == "name_mismatch":
            name_matches_profile = False

    return {
        "doc_type_label": DOC_LABEL_MAP["pan_card"],
        "doc_type": "pan_card",
        "has_doc_number": has_number,
        "doc_number_length": len(number),
        "doc_number_format_ok": number_format_ok,
        "has_name": has_name,
        "has_dob": has_dob,
        "has_address": False,        # PAN does not have address
        "has_gender": False,         # PAN does not have gender
        "has_photo": has_photo,
        "has_expiry": False,
        "expiry_valid": True,
        "has_issuer": has_issuer,
        "has_signature": has_signature,
        "has_qr_or_barcode": random.random() > 0.4,
        "has_enrolment_no": False,
        "name_matches_profile": name_matches_profile,
        "address_complete": False,
        "language_secondary_present": False,
        "is_poi": True,
        "is_poa": False,
        "is_valid": is_valid,
    }


def gen_passport(is_valid: bool) -> dict:
    """Generate Passport feature record."""
    has_number = True
    number = valid_passport_no()
    number_format_ok = True
    has_name = True
    has_dob = True
    has_address = True
    has_gender = True
    has_photo = True
    has_signature = random.random() > 0.04
    has_expiry = True
    is_expired = False
    has_nationality = True
    has_mrz = True
    has_place_of_birth = random.random() > 0.1
    name_matches_profile = random.random() > 0.04

    if not is_valid:
        fault = random.choice([
            "expired", "bad_number", "no_mrz", "no_signature",
            "name_mismatch", "no_photo", "bad_format",
        ])
        if fault == "expired":
            is_expired = True
        elif fault == "bad_number":
            number = rnd_str(string.digits, 8)
            number_format_ok = False
        elif fault == "no_mrz":
            has_mrz = False
        elif fault == "no_signature":
            has_signature = False
        elif fault == "name_mismatch":
            name_matches_profile = False
        elif fault == "no_photo":
            has_photo = False
        elif fault == "bad_format":
            number = rnd_str(string.ascii_lowercase, 8)
            number_format_ok = False

    return {
        "doc_type_label": DOC_LABEL_MAP["passport"],
        "doc_type": "passport",
        "has_doc_number": has_number,
        "doc_number_length": len(number),
        "doc_number_format_ok": number_format_ok,
        "has_name": has_name,
        "has_dob": has_dob,
        "has_address": has_address,
        "has_gender": has_gender,
        "has_photo": has_photo,
        "has_expiry": has_expiry,
        "expiry_valid": not is_expired,
        "has_issuer": True,          # Ministry of External Affairs, India
        "has_signature": has_signature,
        "has_qr_or_barcode": has_mrz,    # MRZ strip = machine-readable zone
        "has_enrolment_no": False,
        "name_matches_profile": name_matches_profile,
        "address_complete": True,
        "language_secondary_present": False,
        "is_poi": True,
        "is_poa": True,
        "is_valid": is_valid,
    }


def gen_voter_id(is_valid: bool) -> dict:
    """Generate Voter ID (EPIC) feature record."""
    has_number = True
    number = valid_voter_id()
    number_format_ok = True
    has_name = True
    has_dob = True
    has_address = True
    has_gender = True
    has_photo = random.random() > 0.06
    has_father_name = random.random() > 0.08
    name_matches_profile = random.random() > 0.05
    has_issuer = True                        # Election Commission of India
    has_ac_no = random.random() > 0.1       # Assembly Constituency number

    if not is_valid:
        fault = random.choice([
            "bad_number", "no_name", "bad_format",
            "no_photo", "name_mismatch", "no_address",
        ])
        if fault == "bad_number":
            number = rnd_str(string.digits, 10)
            number_format_ok = False
        elif fault == "no_name":
            has_name = False
        elif fault == "bad_format":
            number = rnd_str(string.ascii_lowercase, 10)
            number_format_ok = False
        elif fault == "no_photo":
            has_photo = False
        elif fault == "name_mismatch":
            name_matches_profile = False
        elif fault == "no_address":
            has_address = False

    return {
        "doc_type_label": DOC_LABEL_MAP["voter_id"],
        "doc_type": "voter_id",
        "has_doc_number": has_number,
        "doc_number_length": len(number),
        "doc_number_format_ok": number_format_ok,
        "has_name": has_name,
        "has_dob": has_dob,
        "has_address": has_address,
        "has_gender": has_gender,
        "has_photo": has_photo,
        "has_expiry": False,
        "expiry_valid": True,
        "has_issuer": has_issuer,
        "has_signature": False,
        "has_qr_or_barcode": random.random() > 0.3,
        "has_enrolment_no": False,
        "name_matches_profile": name_matches_profile,
        "address_complete": has_address,
        "language_secondary_present": random.random() > 0.3,
        "is_poi": True,
        "is_poa": True,
        "is_valid": is_valid,
    }


def gen_driving_licence(is_valid: bool) -> dict:
    """Generate Driving Licence feature record."""
    has_number = True
    number = valid_dl_no()
    number_format_ok = True
    has_name = True
    has_dob = True
    has_address = True
    has_photo = random.random() > 0.05
    has_gender = True
    has_expiry = True
    is_expired = False
    has_blood_group = random.random() > 0.15
    has_vehicle_class = random.random() > 0.1
    has_issuer = True                         # State RTO
    name_matches_profile = random.random() > 0.04

    if not is_valid:
        fault = random.choice([
            "expired", "bad_number", "no_photo",
            "name_mismatch", "no_address", "bad_format",
        ])
        if fault == "expired":
            is_expired = True
        elif fault == "bad_number":
            number = rnd_str(string.digits, 10)
            number_format_ok = False
        elif fault == "no_photo":
            has_photo = False
        elif fault == "name_mismatch":
            name_matches_profile = False
        elif fault == "no_address":
            has_address = False
        elif fault == "bad_format":
            number = rnd_str(string.ascii_lowercase, 14)
            number_format_ok = False

    return {
        "doc_type_label": DOC_LABEL_MAP["driving_licence"],
        "doc_type": "driving_licence",
        "has_doc_number": has_number,
        "doc_number_length": len(number),
        "doc_number_format_ok": number_format_ok,
        "has_name": has_name,
        "has_dob": has_dob,
        "has_address": has_address,
        "has_gender": has_gender,
        "has_photo": has_photo,
        "has_expiry": has_expiry,
        "expiry_valid": not is_expired,
        "has_issuer": has_issuer,
        "has_signature": random.random() > 0.1,
        "has_qr_or_barcode": random.random() > 0.25,
        "has_enrolment_no": False,
        "name_matches_profile": name_matches_profile,
        "address_complete": has_address and random.random() > 0.05,
        "language_secondary_present": random.random() > 0.4,
        "is_poi": True,
        "is_poa": True,
        "is_valid": is_valid,
    }


def gen_bank_passbook(is_valid: bool) -> dict:
    """Generate Bank Passbook feature record."""
    has_number = True
    number = valid_passbook_no()
    number_format_ok = True
    has_name = True
    has_address = True
    has_ifsc = random.random() > 0.1
    has_branch_name = random.random() > 0.1
    has_bank_stamp = random.random() > 0.08
    has_account_open_date = random.random() > 0.15
    name_matches_profile = random.random() > 0.05
    has_issuer = True                         # Scheduled bank in India
    recent_entry = random.random() > 0.2     # Should have recent transaction

    if not is_valid:
        fault = random.choice([
            "bad_account_no", "no_name", "no_address",
            "name_mismatch", "no_ifsc", "no_bank_stamp",
        ])
        if fault == "bad_account_no":
            number = rnd_str(string.ascii_letters, 8)
            number_format_ok = False
        elif fault == "no_name":
            has_name = False
        elif fault == "no_address":
            has_address = False
        elif fault == "name_mismatch":
            name_matches_profile = False
        elif fault == "no_ifsc":
            has_ifsc = False
        elif fault == "no_bank_stamp":
            has_bank_stamp = False

    return {
        "doc_type_label": DOC_LABEL_MAP["bank_passbook"],
        "doc_type": "bank_passbook",
        "has_doc_number": has_number,
        "doc_number_length": len(number),
        "doc_number_format_ok": number_format_ok,
        "has_name": has_name,
        "has_dob": False,            # Passbooks don't have DOB
        "has_address": has_address,
        "has_gender": False,
        "has_photo": False,
        "has_expiry": False,
        "expiry_valid": True,
        "has_issuer": has_issuer,
        "has_signature": has_bank_stamp,
        "has_qr_or_barcode": has_ifsc,   # IFSC barcode / QR
        "has_enrolment_no": False,
        "name_matches_profile": name_matches_profile,
        "address_complete": has_address and random.random() > 0.08,
        "language_secondary_present": False,
        "is_poi": False,
        "is_poa": True,
        "is_valid": is_valid,
    }


GENERATORS = {
    "aadhaar_card":    gen_aadhaar,
    "pan_card":        gen_pan,
    "passport":        gen_passport,
    "voter_id":        gen_voter_id,
    "driving_licence": gen_driving_licence,
    "bank_passbook":   gen_bank_passbook,
}


# ─────────────────────────────────────────────────────────────────────────────
# Dataset generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_dataset(n_per_class: int = 1200) -> pd.DataFrame:
    """Generate balanced dataset: n_per_class valid + invalid per doc type."""
    records = []
    for doc_type in DOC_TYPES:
        gen = GENERATORS[doc_type]
        # Valid samples (~70%) and invalid (~30%)
        n_valid = int(n_per_class * 0.70)
        n_invalid = n_per_class - n_valid
        for _ in range(n_valid):
            records.append(gen(is_valid=True))
        for _ in range(n_invalid):
            records.append(gen(is_valid=False))

    df = pd.DataFrame(records)

    # Derived features
    df["number_length_expected"] = df["doc_type"].map({
        "aadhaar_card":    12,
        "pan_card":        10,
        "passport":         8,
        "voter_id":        10,
        "driving_licence": 15,  # avg with hyphens
        "bank_passbook":   13,  # avg
    })
    df["number_length_diff"] = (df["doc_number_length"] - df["number_length_expected"]).abs()

    # Field completeness score (0-1)
    completeness_cols = [
        "has_doc_number", "has_name", "has_dob", "has_address",
        "has_gender", "has_photo", "has_issuer",
    ]
    df["completeness_score"] = df[completeness_cols].mean(axis=1)

    # Trust signal score
    df["trust_signal_score"] = (
        df["has_photo"].astype(int) * 0.20
        + df["has_signature"].astype(int) * 0.10
        + df["has_qr_or_barcode"].astype(int) * 0.15
        + df["has_issuer"].astype(int) * 0.20
        + df["doc_number_format_ok"].astype(int) * 0.20
        + df["name_matches_profile"].astype(int) * 0.15
    )

    # Validity signal: expiry only matters for docs that have expiry
    df["expiry_concern"] = (df["has_expiry"] & ~df["expiry_valid"]).astype(int)

    log.info(f"Generated dataset: {df.shape}")
    log.info(f"Doc type distribution:\n{df['doc_type'].value_counts().to_string()}")
    log.info(f"Validity distribution:\n{df['is_valid'].value_counts().to_string()}")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Feature schema
# ─────────────────────────────────────────────────────────────────────────────

FEATURES = [
    "has_doc_number",
    "doc_number_length",
    "doc_number_format_ok",
    "has_name",
    "has_dob",
    "has_address",
    "has_gender",
    "has_photo",
    "has_expiry",
    "expiry_valid",
    "has_issuer",
    "has_signature",
    "has_qr_or_barcode",
    "has_enrolment_no",
    "name_matches_profile",
    "address_complete",
    "language_secondary_present",
    "is_poi",
    "is_poa",
    # Derived
    "number_length_diff",
    "completeness_score",
    "trust_signal_score",
    "expiry_concern",
]


# ─────────────────────────────────────────────────────────────────────────────
# Train model 1: Document Type Classifier
# ─────────────────────────────────────────────────────────────────────────────

def train_type_classifier(df: pd.DataFrame):
    """Classify which of the 6 Indian document types the document is."""
    log.info("\n" + "=" * 60)
    log.info("MODEL 1: Document Type Classifier (6 classes)")
    log.info("=" * 60)

    X = df[FEATURES].astype(float)
    y = df["doc_type_label"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = XGBClassifier(
        n_estimators=250,
        max_depth=6,
        learning_rate=0.07,
        subsample=0.85,
        colsample_bytree=0.85,
        min_child_weight=2,
        gamma=0.05,
        reg_alpha=0.1,
        reg_lambda=1.0,
        eval_metric="mlogloss",
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    log.info(f"Type Classifier Accuracy: {acc:.4f}")
    log.info("\n" + classification_report(y_test, y_pred, target_names=DOC_TYPES))

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X, y, cv=cv, scoring="accuracy")
    log.info(f"CV Accuracy: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

    importances = dict(zip(FEATURES, model.feature_importances_))
    top = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:8]
    log.info("Top features:")
    for f, i in top:
        log.info(f"  {f}: {i:.4f}")

    return model, {
        "accuracy": float(acc),
        "cv_mean": float(cv_scores.mean()),
        "cv_std": float(cv_scores.std()),
        "feature_importances": {k: float(v) for k, v in importances.items()},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Train model 2: Document Validity Classifier
# ─────────────────────────────────────────────────────────────────────────────

def train_validity_classifier(df: pd.DataFrame):
    """Binary classification: is the document valid for KYC?"""
    log.info("\n" + "=" * 60)
    log.info("MODEL 2: Document Validity Classifier (binary)")
    log.info("=" * 60)

    # Add doc_type_label as a feature so the model knows what type it's checking
    feat_cols = FEATURES + ["doc_type_label"]
    X = df[feat_cols].astype(float)
    y = df["is_valid"].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Handle class imbalance (70% valid, 30% invalid)
    scale_pos = (y_train == 0).sum() / (y_train == 1).sum()

    model = XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        gamma=0.1,
        scale_pos_weight=scale_pos,
        eval_metric="logloss",
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    acc = accuracy_score(y_test, y_pred)
    log.info(f"Validity Classifier Accuracy: {acc:.4f}")
    log.info("\n" + classification_report(y_test, y_pred, target_names=["Invalid", "Valid"]))
    log.info("Confusion matrix:")
    log.info(str(confusion_matrix(y_test, y_pred)))

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X, y, cv=cv, scoring="accuracy")
    log.info(f"CV Accuracy: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

    importances = dict(zip(feat_cols, model.feature_importances_))
    top = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:8]
    log.info("Top features:")
    for f, i in top:
        log.info(f"  {f}: {i:.4f}")

    return model, {
        "accuracy": float(acc),
        "cv_mean": float(cv_scores.mean()),
        "cv_std": float(cv_scores.std()),
        "feature_importances": {k: float(v) for k, v in importances.items()},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Save artifacts
# ─────────────────────────────────────────────────────────────────────────────

def save_artifacts(type_model, type_metrics, validity_model, validity_metrics, df):
    # Save type classifier
    with open(MODEL_DIR / "doc_type_classifier.pkl", "wb") as f:
        pickle.dump(type_model, f)
    log.info(f"Type classifier saved → {MODEL_DIR}/doc_type_classifier.pkl")

    # Save validity classifier
    with open(MODEL_DIR / "doc_validity_classifier.pkl", "wb") as f:
        pickle.dump(validity_model, f)
    log.info(f"Validity classifier saved → {MODEL_DIR}/doc_validity_classifier.pkl")

    # Save metadata
    metadata = {
        "doc_types": DOC_TYPES,
        "doc_label_map": DOC_LABEL_MAP,
        "doc_label_map_inv": {str(v): k for k, v in DOC_LABEL_MAP.items()},
        "doc_kyc_purpose": DOC_KYC_PURPOSE,
        "features_type": FEATURES,
        "features_validity": FEATURES + ["doc_type_label"],
        "type_model_metrics": type_metrics,
        "validity_model_metrics": validity_metrics,
        "validity_rules": {
            "aadhaar_card": {
                "required": ["has_doc_number", "doc_number_format_ok", "has_name", "has_dob", "has_address"],
                "number_length": 12,
                "number_pattern": "^[2-9]\\d{11}$",
                "description": "12-digit UIDAI number, starts with 2-9",
            },
            "pan_card": {
                "required": ["has_doc_number", "doc_number_format_ok", "has_name", "has_dob"],
                "number_length": 10,
                "number_pattern": "^[A-Z]{5}[0-9]{4}[A-Z]{1}$",
                "description": "5 letters + 4 digits + 1 letter (uppercase)",
            },
            "passport": {
                "required": ["has_doc_number", "doc_number_format_ok", "has_name", "has_dob",
                             "has_photo", "expiry_valid", "has_qr_or_barcode"],
                "number_length": 8,
                "number_pattern": "^[A-Z][0-9]{7}$",
                "description": "1 uppercase letter + 7 digits, must not be expired, MRZ required",
            },
            "voter_id": {
                "required": ["has_doc_number", "doc_number_format_ok", "has_name", "has_photo"],
                "number_length": 10,
                "number_pattern": "^[A-Z]{3}[0-9]{7}$",
                "description": "3 uppercase letters + 7 digits (EPIC number)",
            },
            "driving_licence": {
                "required": ["has_doc_number", "doc_number_format_ok", "has_name",
                             "has_dob", "expiry_valid"],
                "number_length": 15,
                "number_pattern": "^[A-Z]{2}-\\d{2}-\\d{4,7}$",
                "description": "State code + year + serial, must not be expired",
            },
            "bank_passbook": {
                "required": ["has_doc_number", "has_name", "has_address", "has_qr_or_barcode"],
                "number_length_min": 9,
                "number_length_max": 18,
                "description": "Account number 9-18 digits, IFSC required, POA only",
            },
        },
        "sample_count": len(df),
        "valid_count": int(df["is_valid"].sum()),
        "invalid_count": int((~df["is_valid"]).sum()),
    }

    with open(MODEL_DIR / "doc_classifier_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    log.info(f"Metadata saved → {MODEL_DIR}/doc_classifier_metadata.json")

    # Save training data sample for reference
    sample_path = DATA_DIR / "kaggle_raw" / "indian_doc_validation_dataset.csv"
    df.to_csv(sample_path, index=False)
    log.info(f"Training dataset saved → {sample_path} ({len(df)} rows)")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df = generate_dataset(n_per_class=1500)
    type_model, type_metrics = train_type_classifier(df)
    validity_model, validity_metrics = train_validity_classifier(df)
    save_artifacts(type_model, type_metrics, validity_model, validity_metrics, df)
    log.info("\n✓ Indian document classifier models training complete!")
