import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.document_parser import extract_text

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"
MANIFEST_FILE = UPLOAD_DIR / "manifest.json"

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".jpg", ".jpeg", ".png", ".webp"}

# Fields that are too large to keep in manifest JSON
# (image_base64 can be MBs; we regenerate it from stored_path on demand)
_MANIFEST_EXCLUDE = {"image_base64", "base64_preview"}


def _load_manifest() -> dict:
    if not MANIFEST_FILE.exists():
        return {}
    with open(MANIFEST_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_manifest(data: dict) -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _hydrate_image(entry: dict) -> dict:
    """
    Re-read the stored image file and inject image_base64 / image_media_type
    back into the entry dict if the document is an image or needs vision processing.
    This keeps the manifest lean while ensuring agents always have
    the image data available when needed.
    """
    # Trigger hydration if: explicitly flagged, OR is an image file extension
    stored_path = entry.get("stored_path", "")
    ext = Path(stored_path).suffix.lower() if stored_path else ""
    is_img_ext = ext in {".jpg", ".jpeg", ".png", ".webp"}

    needs_vision = entry.get("needs_vision") or entry.get("is_image") or is_img_ext

    if not needs_vision:
        return entry

    if not stored_path:
        return entry

    path = Path(stored_path)
    if not path.exists():
        return entry

    # Already hydrated in memory
    if entry.get("image_base64"):
        return entry

    try:
        import base64
        content = path.read_bytes()
        ext_actual = path.suffix.lower()
        media_type = "image/jpeg" if ext_actual in (".jpg", ".jpeg") else "image/png"

        from app.services.document_parser import _resize_image_if_needed
        resized = _resize_image_if_needed(content, ext_actual)

        entry = dict(entry)  # copy — don't mutate manifest cache
        entry["image_base64"]     = base64.b64encode(resized).decode("ascii")
        entry["image_media_type"] = media_type
        entry["needs_vision"]     = True
        entry["is_image"]         = True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("_hydrate_image failed for %s: %s", stored_path, e)

    return entry


def save_evidence_files(files: list[tuple[str, bytes]], case_id: str | None = None) -> list[dict]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    saved: list[dict] = []

    for filename, content in files:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue
        evidence_id = f"EVD-{uuid.uuid4().hex[:8].upper()}"
        safe_name = f"{evidence_id}{ext}"
        file_path = UPLOAD_DIR / safe_name
        file_path.write_bytes(content)

        parsed = extract_text(filename, content)

        # Strip large binary fields from what goes into manifest
        manifest_entry = {
            "evidence_id": evidence_id,
            "original_filename": filename,
            "stored_path": str(file_path),
            "case_id": case_id,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            **{k: v for k, v in parsed.items() if k not in _MANIFEST_EXCLUDE},
        }
        manifest[evidence_id] = manifest_entry

        # The in-memory entry returned to callers DOES include image_base64
        # (it was already computed by extract_text)
        full_entry = {**manifest_entry}
        if "image_base64" in parsed:
            full_entry["image_base64"]    = parsed["image_base64"]
            full_entry["image_media_type"] = parsed.get("image_media_type", "image/jpeg")

        saved.append(full_entry)

    _save_manifest(manifest)
    return saved


def get_evidence(evidence_ids: list[str]) -> list[dict]:
    """
    Load evidence entries. For image/scanned docs, re-read the file
    from disk and inject image_base64 so vision processing works.
    """
    manifest = _load_manifest()
    results = []
    for eid in evidence_ids:
        if eid in manifest:
            entry = _hydrate_image(manifest[eid])
            results.append(entry)
    return results


def link_evidence_to_case(evidence_ids: list[str], case_id: str) -> None:
    manifest = _load_manifest()
    for eid in evidence_ids:
        if eid in manifest:
            manifest[eid]["case_id"] = case_id
    _save_manifest(manifest)
