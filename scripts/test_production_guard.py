import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

import image_qa
import production_guard as guard

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


class ProductionGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ecommerce-production-guard-")
        self.root = Path(self.temp.name)
        Image.new("RGB", (200, 200), "red").save(self.root / "source.png")
        self.manifest = {
            "run_id": "fixture-01", "started_at": "2026-10-27T11:50:00Z",
            "finished_at": "2026-10-27T11:59:00Z", "run_kind": "set",
            "input_fingerprint": "same-sources", "config_fingerprint": "same-plan-model",
            "first_round_qa_usable": True, "rework_cycles": 0,
            "requested": {"main": 1, "secondary": 1, "aplus": 1},
            "sources": [{"id": "front", "path": "source.png"}],
            "identity_lock": "Red object, one unit; rear view unknown.",
            "claims": [{"id": "texture", "basis": "visible", "proof": "front view texture"}],
            "core_claim_ids": ["texture"], "slots": []}
        for i, role in enumerate(guard.ROLES):
            output = f"output{i}.png"
            im = Image.new("RGB", (200, 200), (30+i*60, 140, 160))
            ImageDraw.Draw(im).line((0, i*40, 200, 200-i*30), fill="white", width=10)
            im.save(self.root / output)
            report = f"qa{i}.json"
            image_qa.run(None, [self.root/output], self.root/report, None, False)
            self.manifest["slots"].append({
                "id": f"slot{i}", "role": role, "source_ids": ["front"],
                "claim_ids": ["texture"] if i else [], "question": f"question{i}",
                "camera": f"angle{i}", "composition": f"composition{i}",
                "interaction": f"interaction{i}", "evidence_style": ("hero", "macro", "use")[i],
                "visual_proof": f"Observable detail {i} without text.",
                "technique": "original_pixels", "scene_fit": "Source plane and light match; object sits on desk.",
                "output": output, "qa_report": report, "target_size": [200, 200],
                "base_asset_id": f"base{i}", "attempts": [],
                "review": {"reviewer": "Synthetic test, not a real product review",
                           "output_sha256": hashlib.sha256((self.root/output).read_bytes()).hexdigest(),
                           "reviewed_at": "2026-10-27T11:58:00Z", "notes": "Fixture assertions only.",
                           "checks": {k: True for k in guard.CHECKS}}})

    def tearDown(self):
        self.temp.cleanup()

    def run_gate(self, phase="delivery", slot=None):
        return guard.gate(self.manifest, self.root, phase, slot, NOW)

    def test_complete_reviewed_fixture(self):
        self.assertEqual(self.run_gate()["status"], "passed")
        self.assertEqual(self.run_gate("plan")["status"], "ready")

    def test_missing_aplus_not_hidden_by_plan(self):
        self.manifest["slots"].pop()
        self.assertEqual(self.run_gate()["status"], "blocked")

    def test_missing_output_blocks(self):
        self.manifest["slots"][2]["output"] = "missing.png"
        self.assertEqual(self.run_gate()["status"], "blocked")

    def test_only_copy_different_blocks(self):
        a,b = self.manifest["slots"][:2]
        for axis in guard.AXES:
            b[axis] = a[axis]
        b["evidence_style"] = "macro"
        self.assertEqual(self.run_gate("plan")["status"], "blocked")

    def test_text_only_evidence_blocks(self):
        self.manifest["slots"][1]["evidence_style"] = "text_only"
        self.assertEqual(self.run_gate("plan")["status"], "blocked")

    def test_claim_needs_actual_support(self):
        self.manifest["claims"][0]["basis"] = "guess"
        self.assertEqual(self.run_gate("plan")["status"], "blocked")

    def test_coverage_required(self):
        for slot in self.manifest["slots"]:
            slot["claim_ids"] = []
        self.assertEqual(self.run_gate("plan")["status"], "blocked")

    def test_false_material_review_blocks(self):
        self.manifest["slots"][1]["review"]["checks"]["material"] = False
        self.assertEqual(self.run_gate()["status"], "blocked")

    def test_local_qa_never_replaces_visual_review(self):
        self.manifest["slots"][1]["review"] = {}
        self.assertEqual(self.run_gate()["status"], "draft")

    def test_wrong_size_blocks(self):
        self.manifest["slots"][1]["target_size"] = [970,600]
        self.assertEqual(self.run_gate()["status"], "blocked")

    def test_invalid_size_stops_before_paid_submission(self):
        for value in (None, [], [970], [True, 600], [970, 0]):
            self.manifest["slots"][1]["target_size"] = value
            self.assertEqual(self.run_gate("plan")["status"], "blocked")

    def test_reused_scene_blocks(self):
        self.manifest["slots"][2]["base_asset_id"] = "base0"
        self.assertEqual(self.run_gate()["status"], "blocked")

    def test_stale_report_blocks(self):
        Image.new("RGB", (200,200), "pink").save(self.root / "output1.png")
        self.assertEqual(self.run_gate()["status"], "blocked")

    def test_missing_review_hash_is_unreviewed(self):
        del self.manifest["slots"][1]["review"]["output_sha256"]
        result = self.run_gate()
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["counts"]["reviewed_files"], 2)

    def test_fresh_file_qa_cannot_reuse_old_visual_review(self):
        output = self.root / "output1.png"
        Image.new("RGB", (200, 200), "black").save(output)
        fresh_report = self.root / "fresh-qa1.json"
        image_qa.run(None, [output], fresh_report, None, False)
        self.manifest["slots"][1]["qa_report"] = fresh_report.name
        result = self.run_gate()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("stale visual review" in error for error in result["errors"]))
        self.assertTrue(result["manual_review_required"])

    def test_exact_duplicate_blocks(self):
        self.manifest["slots"][1]["output"] = "output0.png"
        self.manifest["slots"][1]["qa_report"] = "qa0.json"
        self.assertEqual(self.run_gate()["status"], "blocked")

    def test_three_paid_attempts_block(self):
        self.manifest["slots"][1]["attempts"] = [{"status": "failed"}]*3
        self.assertEqual(self.run_gate()["status"], "blocked")

    def test_unknown_billing_state_prevents_next(self):
        self.manifest.pop("finished_at")
        self.manifest["slots"][0]["attempts"] = [{"status": "unknown", "task_id": "preserve-me"}]
        self.assertEqual(self.run_gate("next", "slot1")["status"], "blocked")

    def test_near_deadline_prevents_new_paid_job(self):
        self.manifest.pop("finished_at")
        self.manifest["started_at"] = "2026-10-27T11:41:00Z"
        self.manifest["estimated_next_seconds"] = 180
        self.assertEqual(self.run_gate("next", "slot1")["status"], "blocked")

    def test_budget_allows_prechecked_next_slot(self):
        self.manifest.pop("finished_at")
        self.assertEqual(self.run_gate("next", "slot1")["status"], "ready")

    def test_finished_time_must_include_review(self):
        self.manifest["finished_at"] = "2026-10-27T11:51:00Z"
        self.assertEqual(self.run_gate()["status"], "blocked")

    def test_ab_does_not_replace_required_aplus(self):
        variant = copy.deepcopy(self.manifest["slots"][1])
        variant.update(id="variant1", variant_of="slot1", ab_variable="copy", ab_change="Approved headline A vs B")
        self.manifest["slots"].append(variant)
        self.assertEqual(self.run_gate("plan")["status"], "ready")
        self.manifest["slots"].pop(2)
        self.assertEqual(self.run_gate("plan")["status"], "blocked")

    def test_ab_multiple_changes_block(self):
        variant = copy.deepcopy(self.manifest["slots"][1])
        variant.update(id="variant1", variant_of="slot1", ab_variable="copy", ab_change="headline", camera="different")
        self.manifest["slots"].append(variant)
        self.assertEqual(self.run_gate("plan")["status"], "blocked")

    def test_ab_size_must_match_base_before_submission(self):
        variant = copy.deepcopy(self.manifest["slots"][1])
        variant.update(id="variant1", variant_of="slot1", ab_variable="copy",
                       ab_change="headline", target_size=[970, 600])
        self.manifest["slots"].append(variant)
        self.assertEqual(self.run_gate("plan")["status"], "blocked")

    def test_benchmark_cannot_call_fast_unreviewed_output_usable(self):
        self.manifest["slots"][1]["review"] = {}
        result = guard.benchmark([(self.manifest, self.root)])
        self.assertEqual(result["usable_delivery_within_20_minutes"]["rate"], 0)
        self.assertFalse(result["repeat_samples"][0]["three_repeat_sample_complete"])
        self.assertEqual(result["status"], "measurement_only")

    def test_empty_sample_has_null_rate(self):
        result = guard.benchmark([])
        self.assertIsNone(result["usable_delivery_within_20_minutes"]["rate"])

    def test_unfinished_run_stays_in_benchmark_denominator(self):
        self.manifest.pop("finished_at")
        result = guard.benchmark([(self.manifest, self.root)])
        self.assertEqual(result["usable_delivery_within_20_minutes"]["denominator"], 1)
        self.assertEqual(result["usable_delivery_within_20_minutes"]["numerator"], 0)
        self.assertEqual(result["unfinished_runs"], ["fixture-01"])

    def test_duplicate_run_cannot_inflate_benchmark_sample(self):
        with self.assertRaises(ValueError):
            guard.benchmark([(self.manifest, self.root)] * 2)

    def test_missing_first_round_observation_is_not_invented(self):
        del self.manifest["first_round_qa_usable"]
        result = guard.benchmark([(self.manifest, self.root)])
        self.assertIsNone(result["first_attempt_usable_runs"]["rate"])

    def test_missing_rework_observation_is_not_zero(self):
        del self.manifest["rework_cycles"]
        result = guard.benchmark([(self.manifest, self.root)])
        self.assertIsNone(result["failed_retry_or_rework_run_rate"]["rate"])

    def test_future_finish_blocks(self):
        self.manifest["finished_at"] = "2099-01-01T00:00:00Z"
        self.assertEqual(self.run_gate()["status"], "blocked")

    def test_review_cannot_predate_run(self):
        self.manifest["slots"][0]["review"]["reviewed_at"] = "2026-10-27T11:49:00Z"
        self.assertEqual(self.run_gate()["status"], "blocked")

    def test_invalid_slot_and_nested_reference_fail_closed(self):
        self.manifest["slots"][0]["source_ids"] = [{}]
        self.assertEqual(self.run_gate("plan")["status"], "blocked")
        self.manifest["slots"].append(None)
        with self.assertRaises(ValueError):
            self.run_gate("plan")


if __name__ == "__main__":
    unittest.main()
