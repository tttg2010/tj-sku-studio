#!/usr/bin/env python3
"""Offline plan, budget and delivery gates. Never submits a generation request.

Manifest evidence is a review record, not a computer-vision fidelity score.
All final passes require an identified visual reviewer and actual local assets.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

from PIL import Image

VERSION = "v1.8"
ROLES = ("main", "secondary", "aplus")
AXES = ("question", "camera", "composition", "interaction", "evidence_style")
CHECKS = ("identity", "material", "mask_edges", "scene_integration",
          "evidence_visible", "text_layout", "no_invented_claims")
EVIDENCE = {"hero", "macro", "mechanism", "sequence", "scale", "use",
            "bundle", "supported_comparison", "brand_story"}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string with timezone")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp requires a timezone")
    return dt


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def path_at(value, root):
    if not nonempty(value):
        raise ValueError("missing file path")
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def image_record(value, root):
    path = path_at(value, root)
    if not path.is_file():
        raise ValueError(f"missing image: {path}")
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        if getattr(im, "n_frames", 1) != 1:
            raise ValueError(f"expected a still image: {path}")
        im.load()
        size = list(im.size)
    return {"path": str(path), "size": size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def gate(manifest, root, phase="plan", slot_id=None, now=None):
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    errors, pending = [], []
    if not nonempty(manifest.get("run_id")):
        errors.append("run_id is required and must be unique per measured run")
    if manifest.get("run_kind", "set") not in {"set", "local_revision"}:
        errors.append("run_kind must be set or local_revision")
    assets, slots = [], manifest.get("slots", [])
    counts = {role: 0 for role in ROLES}
    requested = manifest.get("requested", {})
    sources = manifest.get("sources", [])
    claims = manifest.get("claims", [])
    if not isinstance(slots, list) or not slots:
        raise ValueError("slots must be a nonempty list")
    if any(not isinstance(s, dict) or not nonempty(s.get("id")) for s in slots):
        raise ValueError("each slot must be an object with a nonempty string ID")
    if not isinstance(requested, dict) or set(requested) - set(ROLES):
        raise ValueError("requested supports main, secondary, aplus counts only")
    if any(type(requested.get(r, 0)) is not int or requested.get(r, 0) < 0 for r in ROLES) or not sum(requested.values()):
        raise ValueError("requested counts must be nonnegative integers, total > 0")
    if not isinstance(sources, list) or not sources or not isinstance(claims, list):
        raise ValueError("sources must be nonempty and claims must be a list")
    source_ids, source_records = set(), []
    for source in sources:
        if not isinstance(source, dict) or not nonempty(source.get("id")) or source["id"] in source_ids:
            errors.append("source IDs must be nonempty and unique")
            continue
        source_ids.add(source["id"])
        try:
            source_records.append(image_record(source.get("path"), root))
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            errors.append(str(error))
    claim_map = {}
    for claim in claims:
        if not isinstance(claim, dict) or not nonempty(claim.get("id")) or claim["id"] in claim_map:
            errors.append("claim IDs must be nonempty and unique")
            continue
        claim_map[claim["id"]] = claim
        if claim.get("basis") not in {"visible", "user_confirmed", "documented"} or not nonempty(claim.get("proof")):
            errors.append(f"claim {claim['id']}: needs visible/user_confirmed/documented basis and proof")
    core = manifest.get("core_claim_ids", [])
    if not isinstance(core, list) or any(not nonempty(c) or c not in claim_map for c in core):
        errors.append("core_claim_ids must reference approved claims")
        core = []
    if not nonempty(manifest.get("identity_lock")):
        errors.append("identity_lock is required, including unknowns and source-view limits")
    ids, covered, ready, hashes, bases = set(), set(), set(), {}, {}
    for slot in slots:
        if not isinstance(slot, dict):
            raise ValueError("each slot must be an object")
        sid, role = slot.get("id"), slot.get("role")
        if not nonempty(sid) or sid in ids:
            errors.append("slot IDs must be nonempty and unique")
            continue
        ids.add(sid)
        if role not in ROLES:
            errors.append(f"{sid}: invalid role")
        elif not slot.get("variant_of"):
            counts[role] += 1
        if any(not nonempty(slot.get(axis)) for axis in AXES):
            errors.append(f"{sid}: all five storyboard axes are required")
        if slot.get("evidence_style") not in EVIDENCE:
            errors.append(f"{sid}: evidence_style must show a hero/detail/process/use, not text_only")
        if not nonempty(slot.get("visual_proof")):
            errors.append(f"{sid}: describe what a viewer sees with all copy hidden")
        if role != "main" and slot.get("evidence_style") == "hero":
            errors.append(f"{sid}: a resized hero plus copy is not secondary/A+ evidence")
        refs = slot.get("source_ids", [])
        if not isinstance(refs, list) or not refs or any(not nonempty(r) or r not in source_ids for r in refs):
            errors.append(f"{sid}: source_ids must point to actual source views")
        claim_ids = slot.get("claim_ids", [])
        if not isinstance(claim_ids, list) or any(not nonempty(c) or c not in claim_map for c in claim_ids):
            errors.append(f"{sid}: unknown/unapproved claim")
            claim_ids = []
        covered.update(claim_ids)
        if slot.get("technique") not in {"original_pixels", "constrained_edit", "concept"}:
            errors.append(f"{sid}: choose a preservation technique")
        if not nonempty(slot.get("scene_fit")):
            errors.append(f"{sid}: record source camera, support/mounting, light, scale and occlusion fit")
        target_size = slot.get("target_size")
        valid_size = (isinstance(target_size, list) and len(target_size) == 2 and
                      all(type(v) is int and v > 0 for v in target_size))
        if not valid_size:
            errors.append(f"{sid}: target_size must contain two positive integers")
        if phase != "delivery":
            continue
        before = len(errors)
        before_pending = len(pending)
        record = None
        try:
            record = image_record(slot.get("output"), root)
            if record["path"] in {s["path"] for s in source_records}:
                errors.append(f"{sid}: original source is not a generated deliverable")
            if record["sha256"] in hashes:
                errors.append(f"{sid}: exact duplicate output of {hashes[record['sha256']]}")
            hashes[record["sha256"]] = sid
            if valid_size and target_size != record["size"]:
                errors.append(f"{sid}: wrong delivery size {record['size']} expected {target_size}")
            assets.append({"slot": sid, "role": role, **record})
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            errors.append(f"{sid}: {error}")
        base = slot.get("base_asset_id")
        if not nonempty(base):
            errors.append(f"{sid}: base_asset_id is required to audit reused finished scenes")
        elif base in bases and slot.get("variant_of") != bases[base]:
            errors.append(f"{sid}: finished scene reused from {bases[base]} without explicit A/B variant")
        else:
            bases[base] = sid
        if slot.get("technique") == "concept":
            pending.append(f"{sid}: concept redraw cannot be final")
        qa = slot.get("qa_report")
        try:
            qa_data = json.loads(path_at(qa, root).read_text(encoding="utf-8"))
            if not isinstance(qa_data, dict):
                raise ValueError("QA must be an object")
            if qa_data.get("status") == "blocked":
                errors.append(f"{sid}: local image QA blocked")
            elif qa_data.get("status") not in {"draft", "passed"}:
                errors.append(f"{sid}: invalid/missing local QA status")
            elif not isinstance(qa_data.get("checks"), dict) or not qa_data["checks"] or not all(v is True for v in qa_data["checks"].values()):
                if not nonempty(slot.get("qa_warning_resolution")):
                    pending.append(f"{sid}: local QA warnings need a specific visual re-review explanation")
            qa_outputs = qa_data.get("outputs", [])
            if not isinstance(qa_outputs, list):
                raise ValueError("QA outputs must be a list")
            matched = [p for p in qa_outputs if isinstance(p, dict) and p.get("path") == str(path_at(slot.get("output"), root))]
            if not matched:
                errors.append(f"{sid}: QA report is not for this output")
            elif matched[0].get("sha256") != image_record(slot.get("output"), root)["sha256"]:
                errors.append(f"{sid}: stale QA report or missing SHA256; screen the current image")
        except (OSError, ValueError, TypeError) as error:
            errors.append(f"{sid}: missing/invalid local QA report: {error}")
        review = slot.get("review", {})
        if not isinstance(review, dict):
            raise ValueError(f"{sid}: review must be an object")
        checks = review.get("checks", {})
        if not isinstance(checks, dict):
            raise ValueError(f"{sid}: review checks must be an object")
        for name in CHECKS:
            if checks.get(name) is False:
                errors.append(f"{sid}: visual review failed {name}")
            elif checks.get(name) is not True:
                pending.append(f"{sid}: unreviewed {name}")
        if not nonempty(review.get("reviewer")) or not nonempty(review.get("notes")):
            pending.append(f"{sid}: needs named reviewer and observed evidence, not a template pass")
        if not nonempty(review.get("output_sha256")):
            pending.append(f"{sid}: visual review must bind output_sha256 after viewing the current image")
        elif record is not None and review["output_sha256"] != record["sha256"]:
            errors.append(f"{sid}: stale visual review; changed output requires a new visual review and hash")
        try:
            reviewed = timestamp(review.get("reviewed_at"))
            if reviewed > (now or datetime.now(timezone.utc)):
                errors.append(f"{sid}: review timestamp is in the future")
        except ValueError:
            pending.append(f"{sid}: missing valid review timestamp")
        if len(errors) == before and len(pending) == before_pending:
            ready.add(sid)
    if counts != {r: requested.get(r, 0) for r in ROLES}:
        errors.append(f"requested role counts {requested} do not match storyboard {counts}; never substitute A+ plans for files")
    if set(core) - covered:
        errors.append(f"uncovered core claims: {sorted(set(core) - covered)}")
    by_id = {s.get("id"): s for s in slots}
    for index, left in enumerate(slots):
        variant = left.get("variant_of")
        if variant:
            base = by_id.get(variant)
            if not base or base.get("variant_of") or base.get("role") != left.get("role"):
                errors.append(f"{left.get('id')}: A/B base must be a regular slot of the same role")
            elif left.get("ab_variable") not in {"copy", "camera", "composition", "interaction"} or not nonempty(left.get("ab_change")):
                errors.append(f"{left['id']}: A/B needs one named variable and exact change")
            elif left.get("claim_ids", []) != base.get("claim_ids", []):
                errors.append(f"{left['id']}: A/B must not change factual claims")
            elif left.get("target_size") != base.get("target_size"):
                errors.append(f"{left['id']}: A/B must use the same target size")
            else:
                allowed = {left["ab_variable"]} if left["ab_variable"] in AXES else set()
                if any(left.get(axis) != base.get(axis) for axis in AXES if axis not in allowed):
                    errors.append(f"{left['id']}: A/B changed more than the declared variable")
            continue
        for right in slots[index+1:]:
            if right.get("variant_of"):
                continue
            differences = sum(str(left.get(a, "")).strip().casefold() != str(right.get(a, "")).strip().casefold() for a in AXES)
            if differences < 3:
                errors.append(f"{left.get('id')}/{right.get('id')}: only {differences}/5 storyboard axes differ; needs visual redesign")
    elapsed = None
    try:
        start = timestamp(manifest.get("started_at"))
        end = timestamp(manifest["finished_at"]) if manifest.get("finished_at") else (now or datetime.now(timezone.utc))
        elapsed = (end-start).total_seconds()
        if elapsed < 0 or start > (now or datetime.now(timezone.utc)) or end > (now or datetime.now(timezone.utc)):
            errors.append("run timestamps are reversed or in the future")
        if phase == "delivery" and not manifest.get("finished_at"):
            pending.append("finished_at is missing; elapsed time is still running")
        if phase == "delivery" and manifest.get("finished_at"):
            for slot in slots:
                review = slot.get("review", {})
                if not isinstance(review, dict):
                    raise ValueError("review must be an object")
                if review.get("reviewed_at") and timestamp(review["reviewed_at"]) > end:
                    errors.append("finished_at must include final visual review, not just download completion")
                if review.get("reviewed_at") and timestamp(review["reviewed_at"]) < start:
                    errors.append("review timestamp cannot predate this run")
    except (ValueError, TypeError):
        errors.append("started_at/finished_at requires valid ISO-8601 with timezone")
    attempts_total, retries_total, unresolved = 0, 0, []
    for slot in slots:
        attempts = slot.get("attempts", [])
        if not isinstance(attempts, list):
            raise ValueError("attempts must be a list of actual submissions")
        attempts_total += len(attempts)
        retries_total += max(0, len(attempts)-1)
        if len(attempts) > 2:
            errors.append(f"{slot['id']}: exceeds initial + one paid retry; change method instead")
        for attempt in attempts:
            if not isinstance(attempt, dict) or attempt.get("status") not in {"submitted", "unknown", "succeeded", "failed"}:
                errors.append(f"{slot['id']}: invalid attempt status")
            elif attempt["status"] in {"unknown", "submitted"}:
                unresolved.append(slot["id"])
    if phase == "delivery" and unresolved:
        pending.append("unresolved paid requests: query/preserve IDs before resubmitting")
    if phase == "next":
        selected = by_id.get(slot_id)
        if not selected:
            errors.append("--slot must identify a storyboard slot")
        elif len(selected.get("attempts", [])) >= 2:
            errors.append("paid retry cap reached for this slot")
        if unresolved:
            errors.append("pending/unknown request exists; reconcile it before a new paid submission")
        budget = 300 if manifest.get("run_kind") == "local_revision" else 1200
        estimate = manifest.get("estimated_next_seconds", 180)
        if not number(estimate) or estimate <= 0:
            errors.append("estimated_next_seconds must be a measured positive estimate")
        elif elapsed is None or elapsed + estimate > budget:
            errors.append("time budget insufficient; deliver honest intermediate state and revision path")
        if manifest.get("finished_at"):
            errors.append("run is finished; do not append paid requests")
    status = "blocked" if errors else "draft" if pending else "passed" if phase == "delivery" else "ready"
    return {"version": VERSION, "phase": phase, "status": status,
            "submitted": False, "errors": errors, "pending_review": pending,
            "counts": {"requested": {r: requested.get(r, 0) for r in ROLES}, "planned": counts,
                       "decoded_files": len(assets), "reviewed_files": len(ready),
                       "paid_requests": attempts_total, "retry_requests": retries_total},
            "elapsed_seconds": elapsed, "assets": assets,
            "claim_coverage": {"core": sorted(core), "planned": sorted(covered)},
            "manual_review_required": phase != "delivery" or status != "passed",
            "limits": ["Does not inspect semantic truth of review notes or claim evidence.",
                       "Storyboard labels are not visual-diversity proof; inspect the full contact sheet.",
                       "passed is an internal reviewed delivery, never marketplace approval or a fidelity percentage."]}


def benchmark(manifests):
    """Aggregate reviewed runs; missing review is not a zero-error success."""
    run_ids = [m.get("run_id") for m, _ in manifests if isinstance(m, dict)]
    if len(run_ids) != len(manifests) or any(not nonempty(i) for i in run_ids) or len(set(run_ids)) != len(run_ids):
        raise ValueError("benchmark requires distinct nonempty run IDs; repeated manifests do not enlarge the sample")
    reports = [(m, gate(m, root, "delivery")) for m, root in manifests]
    # Keep failures, timeouts and unfinished runs in the denominator.
    sets = [(m, r) for m, r in reports if m.get("run_kind", "set") == "set"]
    revisions = [(m, r) for m, r in reports if m.get("run_kind") == "local_revision"]
    def rate(numerator, denominator):
        return {"numerator": numerator, "denominator": denominator,
                "rate": round(numerator/denominator, 4) if denominator else None}
    first_usable = sum(r["status"] == "passed" and m.get("first_round_qa_usable") is True and r["counts"]["retry_requests"] == 0 for m, r in reports)
    missing_first = [m["run_id"] for m, _ in reports if type(m.get("first_round_qa_usable")) is not bool]
    requests = sum(r["counts"]["paid_requests"] for _, r in reports)
    groups = {}
    for m, r in reports:
        key = (m.get("input_fingerprint"), m.get("config_fingerprint"))
        run_id = m.get("run_id")
        if all(nonempty(x) for x in key) and nonempty(run_id):
            groups.setdefault(key, {})[run_id] = (m, r)
    repeats = [{"input_fingerprint": k[0], "config_fingerprint": k[1],
                "distinct_runs": len(v), "reviewed_usable": sum(r["status"] == "passed" for _, r in v.values()),
                "usable_rate": sum(r["status"] == "passed" for _, r in v.values())/len(v),
                "three_repeat_sample_complete": len(v) >= 3,
                "note": "Usable rate is not product/checklist consistency; source/config fingerprints must be verified."}
               for k,v in groups.items()]
    first_rate = rate(first_usable, len(reports))
    if missing_first:
        first_rate.update(rate=None, unrecorded_runs=missing_first)
    missing_rework = [m["run_id"] for m, _ in reports if type(m.get("rework_cycles")) is not int or m["rework_cycles"] < 0]
    failed_retry_rate = rate(sum(r["counts"]["retry_requests"] > 0 or (type(m.get("rework_cycles")) is int and m["rework_cycles"] > 0) for m, r in reports), len(reports))
    if missing_rework:
        failed_retry_rate.update(rate=None, unrecorded_runs=missing_rework)
    return {"version": VERSION, "submitted": False,
            "status": "measurement_only", "run_count": len(reports),
            "unfinished_runs": [m["run_id"] for m, _ in reports if not m.get("finished_at")],
            "usable_delivery_within_20_minutes": rate(sum(r["status"] == "passed" and r["elapsed_seconds"] <= 1200 for _,r in sets), len(sets)),
            "local_revision_usable_within_5_minutes": rate(sum(r["status"] == "passed" and r["elapsed_seconds"] <= 300 for _,r in revisions), len(revisions)),
            "first_attempt_usable_runs": first_rate,
            "failed_retry_or_rework_run_rate": failed_retry_rate,
            "retry_request_rate": rate(sum(r["counts"]["retry_requests"] for _,r in reports), requests),
            "repeat_samples": repeats,
            "unmeasured": ["calibrated product similarity percentage", "same-input three-run checklist consistency (not usable rate)", "logo/color error rates per reviewed image",
                           "naturalness 75/100 and paste score <=2/5 using a fixed human rubric",
                           "platform approval (requires actual platform review)",
                           "conversion A/B outcome (requires real traffic, not image generation)"],
            "note": "Only complete reviewed usable sets count toward the 20-minute target; no assets created by this command."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["plan", "next", "delivery", "benchmark"])
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--slot")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.phase != "benchmark" and len(args.manifest) != 1:
            raise ValueError("use one manifest, or benchmark for several measured runs")
        manifests = [(json.loads(p.read_text(encoding="utf-8")), p.resolve().parent) for p in args.manifest]
        result = benchmark(manifests) if args.phase == "benchmark" else gate(*manifests[0], args.phase, args.slot)
        if args.report:
            if args.report.resolve() in {p.resolve() for p in args.manifest}:
                raise ValueError("report must not overwrite a manifest")
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.open("x", encoding="utf-8") as output:
                output.write(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result["status"] == "blocked" else 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"version": VERSION, "status": "blocked", "error": str(error), "submitted": False}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
