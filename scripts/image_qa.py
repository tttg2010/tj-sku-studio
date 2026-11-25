#!/usr/bin/env python3
"""Offline screening for ecommerce image outputs.

This is a triage tool, not proof that a generated product is faithful. It
checks files that can be checked deterministically and leaves product identity
and scene-naturalness decisions to the manual review gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from PIL import Image, ImageFilter, ImageOps
except ImportError:  # pragma: no cover - exercised by the CLI environment
    print("Pillow is required: python3 -m pip install Pillow", file=sys.stderr)
    raise SystemExit(2)


HASH_SIZE = 8
DEFAULT_DUPLICATE_DISTANCE = 4


def pixel_values(image: Image.Image):
    """Use the current Pillow API while keeping compatibility with older Pillow."""
    getter = getattr(image, "get_flattened_data", None)
    return list(getter()) if getter else list(image.getdata())


def load_image(path: Path) -> Tuple[Optional[Image.Image], Optional[str]]:
    try:
        with Image.open(path) as opened:
            opened.verify()
        image = Image.open(path)
        image.load()
        return image, None
    except Exception as error:  # Pillow uses several exception types here.
        return None, str(error)


def average_hash(image: Image.Image) -> int:
    gray = ImageOps.grayscale(image).resize((HASH_SIZE, HASH_SIZE))
    values = pixel_values(gray)
    average = sum(values) / len(values)
    value = 0
    for pixel in values:
        value = (value << 1) | int(pixel >= average)
    return value


def hamming_distance(left: int, right: int) -> int:
    # int.bit_count() requires Python 3.10; the Skill also supports 3.9.
    return bin(left ^ right).count("1")


def color_summary(image: Image.Image) -> List[Dict[str, Any]]:
    small = image.convert("RGB").resize((64, 64))
    buckets: Dict[Tuple[int, int, int], int] = {}
    for red, green, blue in pixel_values(small):
        key = (red // 32, green // 32, blue // 32)
        buckets[key] = buckets.get(key, 0) + 1
    ranked = sorted(buckets.items(), key=lambda item: item[1], reverse=True)[:3]
    return [{"bucket": list(bucket), "pixels": count} for bucket, count in ranked]


def edge_density(image: Image.Image) -> float:
    gray = ImageOps.grayscale(image).resize((128, 128))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    values = pixel_values(edges)
    return round(sum(pixel >= 32 for pixel in values) / len(values), 4)


def optional_ocr(image: Image.Image, enabled: bool) -> Dict[str, Any]:
    if not enabled:
        return {"available": False, "skipped": True, "text": ""}
    try:
        import pytesseract
    except ImportError:
        return {"available": False, "skipped": False, "text": ""}
    try:
        text = pytesseract.image_to_string(image, config="--psm 11").strip()
        return {"available": True, "skipped": False, "text": text[:2000]}
    except Exception as error:
        return {"available": True, "skipped": False, "text": "", "error": str(error)}


def parse_ratio(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        width, height = value.split(":", 1)
        ratio = float(width) / float(height)
    except (ValueError, ZeroDivisionError):
        raise ValueError("expected ratio in W:H form, for example 16:9") from None
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError("expected ratio in W:H form, for example 16:9")
    return ratio


def inspect(path: Path, expected_ratio: Optional[float], ocr: bool) -> Dict[str, Any]:
    resolved = str(path.expanduser().resolve())
    record: Dict[str, Any] = {"path": resolved, "exists": path.is_file()}
    if not path.is_file():
        record.update({"decode_ok": False, "error": "file does not exist"})
        return record
    image, error = load_image(path)
    if image is None:
        record.update({"decode_ok": False, "error": error or "unable to decode image"})
        return record
    width, height = image.size
    ratio = width / height if height else 0
    record.update({
        "decode_ok": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "format": image.format,
        "mode": image.mode,
        "size": [width, height],
        "ratio": round(ratio, 6),
        "ratio_ok": expected_ratio is None or abs(ratio - expected_ratio) / expected_ratio <= 0.03,
        "average_hash": f"{average_hash(image):016x}",
        "edge_density": edge_density(image),
        "dominant_color_buckets": color_summary(image),
        "ocr": optional_ocr(image, ocr),
    })
    image.close()
    return record


def run(source: Optional[Path], outputs: Iterable[Path], report_path: Optional[Path], expected_ratio: Optional[str], ocr: bool) -> Dict[str, Any]:
    ratio = parse_ratio(expected_ratio)
    output_paths = list(outputs)
    if not output_paths:
        raise ValueError("at least one --output is required")
    source_record = inspect(source, ratio, ocr) if source else None
    output_records = [inspect(path, ratio, ocr) for path in output_paths]
    duplicates: List[Dict[str, Any]] = []
    for index, left in enumerate(output_records):
        for right in output_records[index + 1:]:
            if left.get("decode_ok") and right.get("decode_ok"):
                distance = hamming_distance(int(left["average_hash"], 16), int(right["average_hash"], 16))
                if distance <= DEFAULT_DUPLICATE_DISTANCE:
                    duplicates.append({"left": left["path"], "right": right["path"], "hamming_distance": distance})
    decode_ok = all(record.get("decode_ok") for record in output_records) and (source_record is None or source_record.get("decode_ok", False))
    ratio_ok = all(record.get("ratio_ok", False) for record in output_records)
    ocr_text = [record["ocr"]["text"] for record in output_records if record.get("ocr", {}).get("text")]
    automated_status = "blocked" if not decode_ok or not ratio_ok else "warnings" if duplicates or ocr_text else "passed"
    # A file-level screen must never masquerade as completed visual acceptance.
    status = "blocked" if automated_status == "blocked" else "draft"
    result: Dict[str, Any] = {
        "ok": status != "blocked",
        "status": status,
        "automated_status": automated_status,
        "source": source_record,
        "outputs": output_records,
        "near_duplicates": duplicates,
        "checks": {
            "decode": decode_ok,
            "dimensions_and_ratio": ratio_ok,
            "near_duplicates": not duplicates,
            "ocr_review": not ocr_text,
        },
        "manual_review_required": True,
        "manual_review_reasons": [
            "Confirm product identity, materials, logo/print, proportions, and scene integration by eye.",
        ],
    }
    if duplicates:
        result["manual_review_reasons"].append("Near-duplicate outputs detected; keep only genuinely distinct variants.")
    if ocr_text:
        result["manual_review_reasons"].append("OCR detected text; confirm it is intentional product printing or approved copy.")
    if report_path:
        target = report_path.expanduser().resolve()
        if target in {p.expanduser().resolve() for p in output_paths + ([source] if source else [])}:
            raise ValueError("report must not overwrite a source or output image")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as output:
            output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        result["report"] = str(target)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline ecommerce image QA screening")
    parser.add_argument("--source", type=Path, help="Optional original product image")
    parser.add_argument("--output", type=Path, action="append", required=True, help="Generated image; repeat for a set")
    parser.add_argument("--report", type=Path, help="Write a JSON QA report")
    parser.add_argument("--expected-ratio", help="Expected output ratio such as 1:1 or 16:9")
    parser.add_argument("--no-ocr", action="store_true", help="Skip optional OCR screening")
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        result = run(args.source, args.output, args.report, args.expected_ratio, not args.no_ocr)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] != "blocked" else 2
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
