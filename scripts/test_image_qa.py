"""Offline tests for image_qa.py."""

import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

import image_qa


class ImageQATests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ecommerce-image-qa-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, name, color, line=None):
        image = Image.new("RGB", (400, 300), color)
        if line:
            ImageDraw.Draw(image).line(line, fill="black", width=8)
        path = self.root / name
        image.save(path)
        return path

    def test_valid_distinct_outputs_are_not_blocked(self):
        first = self.save("first.png", "white", (20, 20, 380, 280))
        second = self.save("second.png", "white", (380, 20, 20, 280))
        result = image_qa.run(None, [first, second], None, "4:3", False)
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["automated_status"], "passed")
        self.assertTrue(result["checks"]["dimensions_and_ratio"])

    def test_duplicate_outputs_are_draft_and_reportable(self):
        first = self.save("first.png", "orange")
        second = self.save("second.png", "orange")
        report = self.root / "qa.json"
        result = image_qa.run(None, [first, second], report, None, False)
        self.assertEqual(result["status"], "draft")
        self.assertTrue(result["near_duplicates"])
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "draft")

    def test_invalid_image_blocks(self):
        bad = self.root / "bad.png"
        bad.write_bytes(b"not an image")
        result = image_qa.run(None, [bad], None, None, False)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["checks"]["decode"])

    def test_bad_source_cannot_pass_screen(self):
        output = self.save("valid.png", "blue")
        result = image_qa.run(self.root / "missing.png", [output], None, None, False)
        self.assertEqual(result["status"], "blocked")

    def test_nonfinite_ratio_is_invalid(self):
        for value in ("nan:1", "inf:1", "1:0", "-1:2"):
            with self.assertRaises(ValueError):
                image_qa.parse_ratio(value)

    def test_hamming_distance_handles_full_64_bit_hash(self):
        self.assertEqual(image_qa.hamming_distance(0, (1 << 64)-1), 64)
        self.assertEqual(image_qa.hamming_distance(0b1100, 0b1010), 2)
        self.assertEqual(image_qa.hamming_distance(15, 15), 0)

    def test_report_cannot_overwrite_original_or_existing_report(self):
        output = self.save("valid.png", "blue")
        before = output.read_bytes()
        with self.assertRaises(ValueError):
            image_qa.run(None, [output], output, None, False)
        self.assertEqual(output.read_bytes(), before)
        report = self.root / "existing.json"
        report.write_text("keep")
        with self.assertRaises(FileExistsError):
            image_qa.run(None, [output], report, None, False)
        self.assertEqual(report.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
