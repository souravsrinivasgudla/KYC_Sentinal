import base64
import io
from pathlib import Path

MAX_TEXT_LEN = 8000
# Groq vision API accepts images up to ~4MB as base64
MAX_IMAGE_B64_BYTES = 4 * 1024 * 1024


def _resize_image_if_needed(content: bytes, ext: str) -> bytes:
    """
    Resize an image to keep base64 under Groq's limit.
    Falls back to original if Pillow not installed.
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(content))
        # Convert RGBA/P to RGB for JPEG compatibility
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Downscale until under limit
        max_dim = 1600
        while True:
            buf = io.BytesIO()
            fmt = "JPEG" if ext in (".jpg", ".jpeg") else "PNG"
            img.save(buf, format=fmt, quality=85)
            if len(buf.getvalue()) * 4 / 3 <= MAX_IMAGE_B64_BYTES or max_dim < 400:
                return buf.getvalue()
            max_dim = int(max_dim * 0.75)
            img = img.resize(
                (min(img.width, max_dim), min(img.height, max_dim)),
                Image.LANCZOS,
            )
    except Exception:
        return content


def _extract_images_from_pdf(content: bytes) -> list[bytes]:
    """
    Extract embedded images from a PDF page using pypdf.
    Returns list of raw image bytes (JPEG/PNG).
    Falls back to empty list if extraction fails.
    """
    images: list[bytes] = []
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        for page in reader.pages[:3]:  # first 3 pages
            for img_obj in page.images:
                try:
                    images.append(img_obj.data)
                    if len(images) >= 2:  # cap at 2 images
                        return images
                except Exception:
                    pass
    except Exception:
        pass
    return images


def extract_text(filename: str, content: bytes) -> dict:
    ext = Path(filename).suffix.lower()
    is_image = ext in {".jpg", ".jpeg", ".png", ".webp"}
    result = {
        "filename": filename,
        "extension": ext,
        "size_bytes": len(content),
        "text_content": "",
        "extraction_method": "none",
        "is_image": is_image,
        "needs_vision": False,
        "image_base64": None,       # base64 string ready for Groq vision
        "image_media_type": None,   # e.g. "image/jpeg"
    }

    if ext == ".txt":
        result["text_content"] = content.decode("utf-8", errors="replace")[:MAX_TEXT_LEN]
        result["extraction_method"] = "text"

    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            pages = [p.extract_text() or "" for p in reader.pages[:5]]
            extracted = "\n".join(pages).strip()

            if len(extracted) >= 30:
                # Has meaningful selectable text — also try embedded images for vision
                result["text_content"] = extracted[:MAX_TEXT_LEN]
                result["extraction_method"] = "pypdf"
                page_images = _extract_images_from_pdf(content)
                if page_images:
                    img_bytes = _resize_image_if_needed(page_images[0], ".jpg")
                    result["image_base64"] = base64.b64encode(img_bytes).decode("ascii")
                    result["image_media_type"] = "image/jpeg"
                    result["needs_vision"] = True
            else:
                # Image-based / scanned PDF — no selectable text
                # Try to extract embedded page images
                page_images = _extract_images_from_pdf(content)
                if page_images:
                    img_bytes = _resize_image_if_needed(page_images[0], ".jpg")
                    result["image_base64"] = base64.b64encode(img_bytes).decode("ascii")
                    result["image_media_type"] = "image/jpeg"
                    result["text_content"] = "[Scanned PDF — image extracted for vision analysis]"
                    result["extraction_method"] = "pdf_image"
                    result["needs_vision"] = True
                    result["is_image"] = True
                else:
                    # Fallback: send the whole PDF page as a rendered image if possible
                    result["text_content"] = "[Scanned PDF — no selectable text, no embedded images found]"
                    result["extraction_method"] = "pdf_empty"
                    result["needs_vision"] = True
        except Exception as e:
            result["text_content"] = f"[PDF parse error: {e}]"
            result["extraction_method"] = "failed"

    elif is_image:
        # Resize if needed, store as base64 for Groq vision
        resized = _resize_image_if_needed(content, ext)
        media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        result["image_base64"] = base64.b64encode(resized).decode("ascii")
        result["image_media_type"] = media_type
        result["text_content"] = f"[Image document: {filename}]"
        result["extraction_method"] = "image"
        result["needs_vision"] = True
        # Keep legacy base64_preview for backward compatibility
        result["base64_preview"] = base64.b64encode(content[:500_000]).decode("ascii")

    else:
        result["text_content"] = f"[Binary file: {filename}]"
        result["extraction_method"] = "binary"

    return result
