#!/usr/bin/env python3
"""Offline, partial matte checks; Python 3.9+ and Pillow 10+ only.

This is not a segmentation tool. Supply independently marked masks in the same
pixel grid and EXIF orientation as the original. Nothing is inferred from color,
brightness or material, and nothing repairs a matte. A clean check is only a
draft requiring manual review of the entire contour and product identity.

Outputs are exclusive creations. Their parents must exist, except that the
report may be directly inside the new preview directory. Exit 0 means draft
(manual review still needed); exit 2 means blocked. JSON is also sent to stdout
if the requested report cannot safely be written.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Dict, Optional, Sequence, Tuple
import warnings

from PIL import Image, ImageChops, ImageDraw, ImageFile, __version__ as PILLOW_VERSION


CORE_MIN_ALPHA = 250
OPEN_MAX_ALPHA = 5
SOURCE_MODES = frozenset(("RGB", "RGBA", "L", "LA"))
MASK_MODES = frozenset(("1", "L"))
PREVIEW_NAMES = (
    "on-black.png", "on-white.png", "on-magenta.png", "on-green.png",
    "on-checkerboard.png",
)
REVIEW_ITEMS = [
    "Manual review needed: compare the entire contour and all internal openings "
    "against the original, including pixels outside the marked masks.",
    "Check bright white highlights, thin parts, transparency, missing foreground, "
    "halos and leftover background on every preview at native resolution.",
    "Confirm mask alignment and independent annotation history. Matching size "
    "and EXIF cannot establish semantic alignment or prove mask provenance.",
    "The opaque core is partial evidence, not a complete product identity proof. "
    "Verify shape, count, geometry, color, labels and functional details manually.",
]


class GuardError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _error(result: Dict[str, Any], code: str, message: str, **details: Any) -> None:
    result["errors"].append(dict(code=code, message=message, **details))
    result["status"] = "blocked"


def _new_report() -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "tool": "matte_guard",
        "status": "blocked",
        "not_segmentation_tool": True,
        "manual_review_needed": True,
        "manual_review": REVIEW_ITEMS[:],
        "independent_annotation_verified": False,
        "core_is_complete_identity_proof": False,
        "threshold_detection_limit": "Exact alpha-threshold matches are blocked, "
        "but pixel checks cannot prove independent annotation. A modified, "
        "eroded or otherwise alpha-derived core can evade this check.",
        "preview_policy": "Diagnostic drafts only. Original RGB is used without "
        "recoloring, decontamination, segmentation, resizing or material inference. "
        "Effective alpha = supplied alpha * original alpha / 255 (if present). "
        "Only a shared EXIF display transform is applied to previews. RGB blends "
        "are not color-managed or a physical transparency certification.",
        "thresholds": {"core_min_alpha": CORE_MIN_ALPHA,
                       "keep_open_max_alpha": OPEN_MAX_ALPHA},
        "runtime": {"python": sys.version.split()[0], "pillow": PILLOW_VERSION},
        "inputs": {},
        "checks": {},
        "errors": [],
        "previews": [],
        "report_written": False,
    }


def _read_image(path: Path, role: str, result: Dict[str, Any]) -> Image.Image:
    metadata = {"path": str(path), "sha256": None}
    result["inputs"][role] = metadata
    try:
        # Nonblocking open lets a FIFO/device fail without waiting for a writer.
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise GuardError("input_not_regular", role + " must be a regular file")
            raw = handle.read()
            after = os.fstat(handle.fileno())
        metadata.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if signature(before) != signature(after) or len(raw) != after.st_size:
            raise GuardError("input_changed", role + " changed while being read")
        with warnings.catch_warnings():
            # Includes decompression bombs and damaged metadata, even if a decoder
            # could otherwise continue. Do not relax Pillow's decoder globally.
            warnings.simplefilter("error")
            with Image.open(io.BytesIO(raw)) as probe:
                frames = getattr(probe, "n_frames", 1)
                metadata.update(format=probe.format, mode=probe.mode,
                                size=list(probe.size), frames=frames)
                if (frames != 1 or getattr(probe, "is_animated", False)
                        or "loop" in probe.info or "duration" in probe.info):
                    raise GuardError("animated_image", role + " is animated or multi-frame")
                allowed = SOURCE_MODES if role == "source" else MASK_MODES
                if probe.mode not in allowed:
                    raise GuardError("invalid_mode", role + " has unsupported mode " + probe.mode)
                if "transparency" in probe.info:
                    raise GuardError("implicit_transparency", role + " has ambiguous tRNS transparency")
                orientation = probe.getexif().get(274, 1)
                if type(orientation) is not int or orientation not in range(1, 9):
                    raise GuardError("invalid_orientation", role + " has invalid EXIF orientation")
                metadata["exif_orientation"] = orientation
            # PNG getexif() may load the image while reading trailing metadata.
            # verify() therefore needs its own freshly opened decoder.
            with Image.open(io.BytesIO(raw)) as verifier:
                verifier.verify()
            with Image.open(io.BytesIO(raw)) as decoded:
                decoded.load()
                # Some PNG control chunks become info only after IDAT decoding.
                # A header-only probe cannot establish the still-image contract.
                if (getattr(decoded, "n_frames", 1) != 1
                        or getattr(decoded, "is_animated", False)
                        or "loop" in decoded.info or "duration" in decoded.info):
                    raise GuardError("animated_image", role + " is animated or multi-frame")
                image = decoded.copy()
        # No mask color conversion is permitted. Mode 1 is already binary.
        if role != "source" and image.mode == "1":
            converted = image.convert("L")
            image.close()
            image = converted
        return image
    except GuardError:
        raise
    except Exception as exc:
        raise GuardError("unreadable_image", role + ": " + str(exc)) from exc


def _binary_mask(mask: Image.Image, role: str, nonempty: bool = False) -> int:
    histogram = mask.histogram()
    if any(histogram[1:255]):
        raise GuardError("nonbinary_mask", role + " must contain only 0 and 255")
    if nonempty and not histogram[255]:
        raise GuardError("empty_core", "opaque_core must contain marked foreground")
    return histogram[255]


def _threshold_match(alpha: Image.Image, core: Image.Image) -> Optional[int]:
    """Return t if core exactly equals alpha >= t, for any t in 0..255.

    This conservative rejection is not a provenance test. A legitimate separately
    drawn core can coincide with a threshold; require manual re-annotation then.
    """
    inside = alpha.histogram(mask=core)
    with ImageChops.invert(core) as inverse:
        outside = alpha.histogram(mask=inverse)
    minimum_inside = next(i for i, count in enumerate(inside) if count)
    maximum_outside = max((i for i, count in enumerate(outside) if count), default=-1)
    return minimum_inside if minimum_inside > maximum_outside else None


def _violations(mask: Image.Image, alpha: Image.Image, table: Sequence[int]) -> Dict[str, Any]:
    with alpha.point(table) as selected:
        with ImageChops.multiply(mask, selected) as bad:
            return {"pixels": bad.histogram()[255], "bbox": bad.getbbox()}


def _check_pixels(images: Dict[str, Image.Image], result: Dict[str, Any]) -> Image.Image:
    source, alpha, core = (images[role] for role in ("source", "alpha", "opaque_core"))
    checks = result["checks"]
    checks["core_pixels"] = _binary_mask(core, "opaque_core", nonempty=True)
    keep = images.get("keep_open")
    if keep is not None:
        checks["keep_open_pixels"] = _binary_mask(keep, "keep_open")
    else:
        checks["keep_open_pixels"] = None
        checks["openings_check"] = "not_supplied; openings require manual review"

    threshold = _threshold_match(alpha, core)
    checks["core_exact_alpha_threshold"] = threshold
    if threshold is not None:
        _error(result, "core_is_alpha_threshold",
               "Core exactly matches alpha >= threshold; supply independent annotations. "
               "Coincidental independent matches are conservatively blocked.", threshold=threshold)
    for role in ("opaque_core", "keep_open"):
        if role in images and result["inputs"][role]["sha256"] == result["inputs"]["alpha"]["sha256"]:
            _error(result, "mask_copies_alpha", role + " is a byte-for-byte copy of alpha", role=role)

    below = [255 if value < CORE_MIN_ALPHA else 0 for value in range(256)]
    above = [255 if value > OPEN_MAX_ALPHA else 0 for value in range(256)]
    bad = _violations(core, alpha, below)
    checks["core_alpha_below_250"] = bad
    if bad["pixels"]:
        _error(result, "core_alpha_too_low", "Marked opaque foreground has alpha < 250", **bad)
    if keep is not None:
        bad = _violations(keep, alpha, above)
        checks["keep_open_alpha_above_5"] = bad
        if bad["pixels"]:
            _error(result, "keep_open_not_clear", "Marked true background has alpha > 5", **bad)
        with ImageChops.multiply(keep, core) as overlap:
            bad = {"pixels": overlap.histogram()[255], "bbox": overlap.getbbox()}
        checks["core_keep_open_overlap"] = bad
        if bad["pixels"]:
            _error(result, "mask_overlap", "keep_open must not overlap opaque_core", **bad)

    if source.mode in ("RGBA", "LA"):
        with source.getchannel("A") as original_alpha:
            effective = ImageChops.multiply(alpha, original_alpha)
        bad = _violations(core, effective, below)
        checks["core_effective_alpha_below_250"] = bad
        if bad["pixels"]:
            _error(result, "source_alpha_too_low",
                   "Original transparency makes effective core alpha < 250", **bad)
    else:
        effective = alpha.copy()
    checks["alpha_histogram"] = alpha.histogram()
    return effective


def _absolute(path: Any) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _output_paths(report: Any, preview_dir: Any) -> Tuple[Path, Path]:
    report_path, directory = _absolute(report), _absolute(preview_dir)
    # lexists also rejects dangling symlinks. Resolve ancestors for alias checks.
    for path in (report_path, directory):
        if os.path.lexists(str(path)):
            raise GuardError("output_exists", "Refusing existing output path: " + str(path))
    report_path, directory = report_path.resolve(), directory.resolve()
    if report_path == directory or report_path in (directory / name for name in PREVIEW_NAMES):
        raise GuardError("output_collision", "Report and preview paths collide")
    if not directory.parent.is_dir():
        raise GuardError("missing_output_parent", "Preview parent must already exist")
    if report_path.parent != directory and not report_path.parent.is_dir():
        raise GuardError("missing_output_parent", "Report parent must exist or be preview-dir")
    return report_path, directory


def _display(image: Image.Image, orientation: int) -> Image.Image:
    operations = {
        2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }
    return image.transpose(operations[orientation]) if orientation != 1 else image.copy()


def _previews(source: Image.Image, effective: Image.Image, orientation: int,
              directory: Path, result: Dict[str, Any]) -> None:
    backgrounds = ((0, 0, 0), (255, 255, 255), (255, 0, 255), (0, 255, 0), None)
    with source.convert("RGB") as rgb:
        for name, color in zip(PREVIEW_NAMES, backgrounds):
            with Image.new("RGB", source.size, color or (210, 210, 210)) as background:
                if color is None:
                    draw = ImageDraw.Draw(background)
                    for y in range(0, source.height, 16):
                        for x in range(0, source.width, 16):
                            if (x // 16 + y // 16) % 2:
                                draw.rectangle((x, y, x + 15, y + 15), fill=(110, 110, 110))
                with Image.composite(rgb, background, effective) as composite:
                    with _display(composite, orientation) as rendered:
                        path = directory / name
                        # An exclusive open also protects against late collisions.
                        with path.open("xb") as handle:
                            rendered.save(handle, format="PNG")
                        result["previews"].append({
                            "path": str(path), "background": color or "checkerboard",
                            "size": list(rendered.size), "diagnostic_only": True,
                        })


def run(source: Any, alpha: Any, opaque_core: Any, keep_open: Any = None,
        *, report: Any, preview_dir: Any) -> Dict[str, Any]:
    """Check original files and create only the explicitly requested new outputs."""
    result = _new_report()
    images = {}  # type: Dict[str, Image.Image]
    effective = None
    try:
        report_path, directory = _output_paths(report, preview_dir)
    except (GuardError, OSError, ValueError, RuntimeError) as exc:
        _error(result, getattr(exc, "code", "invalid_output_path"), str(exc))
        return result
    result["requested_outputs"] = {"report": str(report_path), "preview_dir": str(directory)}
    try:
        if sys.version_info < (3, 9) or int(PILLOW_VERSION.split(".")[0]) < 10:
            raise GuardError("unsupported_runtime", "Requires Python 3.9+ and Pillow 10+")
        if ImageFile.LOAD_TRUNCATED_IMAGES:
            raise GuardError("unsafe_decoder_setting", "Pillow truncated-image recovery must be disabled")
        paths = {"source": _absolute(source), "alpha": _absolute(alpha),
                 "opaque_core": _absolute(opaque_core)}
        if keep_open is not None:
            paths["keep_open"] = _absolute(keep_open)
        seen = []
        for role, path in paths.items():
            if any(os.path.samefile(path, previous) for previous in seen):
                raise GuardError("aliased_inputs", "Input roles must use separate original files")
            images[role] = _read_image(path, role, result)
            seen.append(path)
        metadata = result["inputs"]
        expected = (metadata["source"]["size"], metadata["source"]["exif_orientation"])
        for role, entry in metadata.items():
            if entry["size"] != expected[0]:
                raise GuardError("size_mismatch", role + " dimensions differ from source")
            if entry["exif_orientation"] != expected[1]:
                raise GuardError("orientation_mismatch", role + " EXIF orientation differs from source")
        result["checks"]["dimensions_and_exif_orientation_match"] = True
        effective = _check_pixels(images, result)
        result["checks"]["local_checks_complete"] = True
        if not result["errors"]:
            result["status"] = "draft"
    except Exception as exc:
        _error(result, getattr(exc, "code", "input_check_failed"), str(exc))

    try:
        # Structural failures stop previews. Semantic failures keep diagnostic
        # previews when possible, but can never produce a non-blocked report.
        if effective is not None or report_path.parent == directory:
            directory.mkdir()  # no parents=True or exist_ok: must be a new path
        with report_path.open("x", encoding="utf-8") as handle:
            if effective is not None:
                try:
                    _previews(images["source"], effective, expected[1], directory, result)
                except Exception as exc:
                    _error(result, "preview_write_failed", str(exc))
            result["report_written"] = True
            json.dump(result, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except Exception as exc:
        result["report_written"] = False
        _error(result, "output_write_failed", str(exc))
    finally:
        if effective is not None:
            effective.close()
        for image in images.values():
            image.close()
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Original RGB/RGBA/L/LA image; read only")
    parser.add_argument("--alpha", required=True, help="L or 1 matte in the original pixel grid")
    parser.add_argument("--opaque-core", required=True, help="Independent nonempty 0/255 opaque foreground mask")
    parser.add_argument("--keep-open", help="Independent 0/255 true-background opening mask")
    parser.add_argument("--report", required=True, help="New JSON file; never overwrites")
    parser.add_argument("--preview-dir", required=True, help="New directory for diagnostic composites")
    args = parser.parse_args(argv)
    result = run(args.source, args.alpha, args.opaque_core, args.keep_open,
                 report=args.report, preview_dir=args.preview_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "draft" else 2


if __name__ == "__main__":
    sys.exit(main())
