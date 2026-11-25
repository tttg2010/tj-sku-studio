"""Local reference compression and exact JSON-body checks; never calls an API."""

from __future__ import annotations

import base64
import io
import json
import math
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MIB = 1024 * 1024
MAX_REFERENCE_IMAGES = 9
MAX_REQUEST_BYTES = 32 * MIB
MAX_INPUT_BYTES = 256 * MIB
MAX_INPUT_PIXELS = 64_000_000
MIN_LONG_EDGE = 1280


class PreflightError(RuntimeError):
    """A local validation failure; no generation should be submitted."""


@dataclass(frozen=True)
class ImageLimits:
    per_image_bytes: int = 2 * MIB
    total_image_bytes: int = 20 * MIB
    request_bytes: int = MAX_REQUEST_BYTES
    max_edge: int = 2560

    def validate(self) -> None:
        for label, value, ceiling in (
            ("per-image bytes", self.per_image_bytes, 5 * MIB),
            ("total image bytes", self.total_image_bytes, 20 * MIB),
            ("request bytes", self.request_bytes, MAX_REQUEST_BYTES),
        ):
            if not isinstance(value, int) or not 0 < value <= ceiling:
                raise PreflightError(f"{label} must be between 1 and {ceiling}")
        if not MIN_LONG_EDGE <= self.max_edge <= 4096:
            raise PreflightError(f"Reference max edge must be {MIN_LONG_EDGE}..4096 pixels")


def mib_bytes(value: float) -> int:
    if not math.isfinite(value) or value <= 0:
        raise PreflightError("Size limits must be finite positive MiB values")
    return int(value * MIB)


def validate_reference_count(files: List[Path], operation: str) -> None:
    count = len(files)
    if count > MAX_REFERENCE_IMAGES:
        raise PreflightError(f"At most {MAX_REFERENCE_IMAGES} reference images per request; received {count}. Select references explicitly; no files were dropped or submitted.")
    if operation == "video" and count != 1:
        raise PreflightError("video requires exactly one first-frame image")
    if operation == "background_replace" and count < 1:
        raise PreflightError("background_replace requires at least one product reference")
    if operation == "outfit" and count < 2:
        raise PreflightError("outfit requires person first, garment second; extra detail references may follow (up to 9 total)")


def serialize_payload(payload: Dict[str, Any], limit: int = MAX_REQUEST_BYTES) -> bytes:
    # Used for BOTH preflight and transport, including Unicode, prompt and data-URI overhead.
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(body) > min(limit, MAX_REQUEST_BYTES):
        raise PreflightError(f"Request body is {len(body)} bytes, above the local {min(limit, MAX_REQUEST_BYTES)}-byte limit. Nothing was sent; reduce references or prompt size.")
    return body


def _compress_reference(path: Path, byte_budget: int, limits: ImageLimits) -> Tuple[bytes, Dict[str, Any]]:
    try:
        from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError
    except ImportError:
        raise PreflightError("Reference preprocessing requires Pillow. Install it in this Python environment: python3 -m pip install Pillow") from None

    path = path.expanduser().resolve()
    if not path.is_file():
        raise PreflightError(f"Input image does not exist: {path}")
    source_bytes = path.stat().st_size
    if source_bytes > MAX_INPUT_BYTES:
        raise PreflightError(f"Input exceeds the local 256 MiB decode limit: {path.name}; export a smaller source first")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                original_size = source.size
                if source.width * source.height > MAX_INPUT_PIXELS:
                    raise PreflightError(f"Image exceeds the local 64-megapixel decode limit: {path.name}")
                if getattr(source, "n_frames", 1) != 1:
                    raise PreflightError(f"Animated/multipage reference is not supported: {path.name}; choose a single frame explicitly")
                if source.mode not in {"1", "L", "LA", "P", "RGB", "RGBA", "CMYK"}:
                    raise PreflightError(f"Unsupported color mode {source.mode}: {path.name}; export an 8-bit sRGB image")
                source.load()
                oriented = ImageOps.exif_transpose(source)
                oriented_size = oriented.size
                alpha = "A" in oriented.getbands() or "transparency" in oriented.info
                converted = oriented.convert("RGBA" if alpha else "RGB")
                icc = source.info.get("icc_profile")
                output_icc = None
                if icc:
                    try:
                        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
                        color_input = oriented if oriented.mode in {"RGB", "CMYK", "L"} else converted.convert("RGB")
                        rgb = ImageCms.profileToProfile(color_input, ImageCms.ImageCmsProfile(io.BytesIO(icc)), srgb, outputMode="RGB")
                        if alpha:
                            rgb.putalpha(converted.getchannel("A"))
                        converted = rgb
                        output_icc = srgb.tobytes()
                    except (ImageCms.PyCMSError, OSError, ValueError):
                        raise PreflightError(f"Cannot preserve the color profile of {path.name}; export an sRGB reference first") from None
                elif oriented.mode == "CMYK":
                    raise PreflightError(f"CMYK reference has no color profile: {path.name}; export an sRGB reference first")
                converted.thumbnail((limits.max_edge, limits.max_edge), Image.Resampling.LANCZOS)

        # Metadata is stripped; alpha stays lossless. Small images are never upscaled.
        converted.info.clear()
        floor_edge = min(MIN_LONG_EDGE, max(converted.size))
        original_working = converted
        working = converted
        chosen_quality = None
        while True:
            for quality in ((None,) if alpha else (95, 90, 85, 80)):
                buffer = io.BytesIO()
                options: Dict[str, Any] = {"icc_profile": output_icc} if output_icc else {}
                if alpha:
                    working.save(buffer, format="PNG", optimize=True, **options)
                else:
                    # Non-optimized encoding avoids libjpeg's fixed-buffer failure
                    # on large, high-entropy 4:4:4 images. Size is still checked below.
                    working.save(buffer, format="JPEG", quality=quality, subsampling=0, optimize=False, **options)
                data = buffer.getvalue()
                if len(data) <= byte_budget:
                    chosen_quality = quality
                    report = {
                        "source": str(path), "source_bytes": source_bytes,
                        "source_size": list(original_size), "oriented_size": list(oriented_size),
                        "prepared_size": list(working.size), "prepared_bytes": len(data),
                        "mime": "image/png" if alpha else "image/jpeg",
                        "alpha_preserved": alpha, "jpeg_quality": chosen_quality,
                        "color_profile": "converted_to_srgb" if output_icc else "untagged",
                        "resized": working.size != oriented_size,
                        "source_unchanged": True,
                    }
                    return data, report
            edge = max(working.size)
            if edge <= floor_edge:
                raise PreflightError(f"Cannot fit {path.name} within {byte_budget} bytes without going below the detail floor ({floor_edge}px; JPEG quality 80; alpha retained). Use fewer references or a tighter detail source.")
            next_edge = max(floor_edge, int(edge * 0.8))
            working = original_working.copy()
            working.thumbnail((next_edge, next_edge), Image.Resampling.LANCZOS)
    except PreflightError:
        raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise PreflightError(f"Cannot decode/prepare {path.name}: {error}") from None


def prepare_payload(
    base: Dict[str, Any], files: List[Path], limits: ImageLimits,
    *, operation: str, prepared_dir: Optional[Path] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Prepare once for a batch; only return sizes/paths in the public report."""
    limits.validate()
    validate_reference_count(files, operation)
    field = "image" if operation == "video" else "images"
    if field in base:
        raise PreflightError("Reference data must come from --file and pass preprocessing")
    body = dict(base)
    empty = dict(base)
    if files:
        empty[field] = "" if operation == "video" else [""] * len(files)
    overhead = len(serialize_payload(empty, limits.request_bytes))
    # Reserve all MIME/data URI overhead, then account for 4*ceil(N/3) expansion.
    raw_budget = min(limits.total_image_bytes, ((limits.request_bytes - overhead - 128 * len(files)) // 4) * 3)
    per_budget = min(limits.per_image_bytes, raw_budget // len(files)) if files else 0
    if files and per_budget <= 0:
        raise PreflightError("Prompt/JSON overhead leaves no image budget; nothing was sent")
    prepared: List[Tuple[bytes, Dict[str, Any]]] = []
    for index, path in enumerate(files, 1):
        data, record = _compress_reference(Path(path), per_budget, limits)
        record["reference_index"] = index
        record["base64_bytes"] = 4 * ((len(data) + 2) // 3)
        prepared.append((data, record))
    image_bytes = sum(len(data) for data, _ in prepared)
    if image_bytes > limits.total_image_bytes:
        raise PreflightError("Prepared references exceed the total image limit; nothing was sent")
    uris = [f"data:{record['mime']};base64," + base64.b64encode(data).decode("ascii") for data, record in prepared]
    if uris:
        body[field] = uris[0] if operation == "video" else uris
    serialized_bytes = len(serialize_payload(body, limits.request_bytes))
    # Persist only when requested, after ALL validation passes; isolated run dirs prevent overwrite.
    if prepared_dir and prepared:
        target_root = prepared_dir.expanduser().resolve()
        target_root.mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix="salpx-prepared-", dir=str(target_root)))
        for data, record in prepared:
            suffix = ".png" if record["mime"] == "image/png" else ".jpg"
            target = run_dir / f"ref-{record['reference_index']:02d}{suffix}"
            target.write_bytes(data)
            record["prepared_path"] = str(target)
    report: Dict[str, Any] = {
        "ok": True, "scope": "salpx_request_only", "reference_count": len(files),
        "source_bytes": sum(record["source_bytes"] for _, record in prepared),
        "prepared_image_bytes": image_bytes,
        "base64_bytes": sum(record["base64_bytes"] for _, record in prepared),
        "request_bytes": serialized_bytes, "request_mib": round(serialized_bytes / MIB, 3),
        "limits": {"reference_count": MAX_REFERENCE_IMAGES, "per_image_bytes": limits.per_image_bytes,
                   "total_image_bytes": limits.total_image_bytes, "request_bytes": limits.request_bytes,
                   "max_edge": limits.max_edge, "effective_per_image_bytes": per_budget},
        "references": [record for _, record in prepared],
        "upstream_reference_capacity": "not_verified_by_local_preflight",
    }
    return body, report
