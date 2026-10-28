"""Pictures in questions: browser-ready copies, and a fingerprint that tells one figure from another."""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps

WEB_TYPES = {"image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp"}
GRID = 64                 # a picture is compared as a 64 x 64 black-and-white grid: 4096 cells
MAX_DIFFERENT_SHARE = 0.01  # up to 1% of cells may differ: scan noise, not a changed figure


def data_uri(blob: bytes, content_type: str) -> str:
    """A picture as a data URI a browser can show. Formats it cannot show (EMF, WMF) become PNG."""
    if content_type not in WEB_TYPES:
        try:
            blob, content_type = to_png(blob), "image/png"
        except Exception:  # Pillow cannot read it: keep the original bytes
            pass
    return f"data:{content_type};base64,{base64.b64encode(blob).decode('ascii')}"


def to_png(blob: bytes) -> bytes:
    out = io.BytesIO()
    _open_on_white(blob).save(out, "PNG")
    return out.getvalue()


def _open_on_white(blob: bytes) -> Image.Image:
    """Transparent areas become white, so a figure reads the same on a page and in the fingerprint."""
    img = Image.open(io.BytesIO(blob)).convert("RGBA")
    background = Image.new("RGBA", img.size, "white")
    background.alpha_composite(img)
    return background.convert("RGB")


def figure_hash(uri: str) -> int | str:
    """The picture as a bit grid: its drawing cropped out, resized, and made black or white.

    A resized copy of a figure gives the same grid. A picture that cannot be read falls back
    to its data, so only an identical copy matches.
    """
    try:
        gray = _open_on_white(base64.b64decode(uri.split(",", 1)[1])).convert("L")
        box = ImageOps.invert(gray).point(lambda v: 255 if v > 40 else 0).getbbox()   # ink, not paper
        if box:
            gray = gray.crop(box)
        grid = gray.resize((GRID, GRID), Image.Resampling.LANCZOS).tobytes()
    except Exception:
        return uri
    bits = 0
    for value in grid:
        bits = bits << 1 | (value < 200)
    return bits


def same_figure(a: int | str, b: int | str) -> bool:
    if isinstance(a, int) and isinstance(b, int):
        return (a ^ b).bit_count() <= MAX_DIFFERENT_SHARE * GRID * GRID
    return a == b
