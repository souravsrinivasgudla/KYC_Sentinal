ISO2_TO_NAME: dict[str, str] = {
    "us": "United States", "gb": "United Kingdom", "uk": "United Kingdom",
    "ru": "Russia", "cn": "China", "ir": "Iran", "kp": "North Korea",
    "sy": "Syria", "mm": "Myanmar", "ve": "Venezuela", "by": "Belarus",
    "cu": "Cuba", "sd": "Sudan", "ss": "South Sudan", "af": "Afghanistan",
    "iq": "Iraq", "ly": "Libya", "ye": "Yemen", "zw": "Zimbabwe",
    "sg": "Singapore", "in": "India", "de": "Germany", "fr": "France",
    "br": "Brazil", "mx": "Mexico", "ua": "Ukraine", "tr": "Turkey",
    "ae": "United Arab Emirates", "sa": "Saudi Arabia", "pk": "Pakistan",
    "ng": "Nigeria", "za": "South Africa", "au": "Australia", "ca": "Canada",
    "jp": "Japan", "kr": "South Korea", "nl": "Netherlands", "ch": "Switzerland",
}

SANCTIONED_ISO2 = {"ir", "kp", "sy", "ru", "cu", "by", "ve", "mm", "sd", "ss", "af", "iq", "ly", "ye", "zw"}


def normalize_country(value: str) -> str:
    if not value:
        return ""
    v = value.strip()
    if len(v) == 2 and v.lower() in ISO2_TO_NAME:
        return ISO2_TO_NAME[v.lower()]
    return v.title() if len(v) > 2 else v.upper()


def country_risk_from_iso(iso2: str) -> int:
    code = iso2.lower().strip()
    if code in SANCTIONED_ISO2:
        return 25
    if code in ("us", "gb", "uk", "sg", "de", "fr", "ca", "au", "jp", "ch", "nl"):
        return 5
    return 10
