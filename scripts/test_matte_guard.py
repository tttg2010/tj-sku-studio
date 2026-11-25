"""Fixed synthetic Pillow fixtures only. No network or real product images.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_matte_guard
All runtime artifacts live in an automatically cleaned temporary directory.
"""

import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw, ImageFile, PngImagePlugin

import matte_guard as guard


class MatteGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="matte-guard-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.png"
        self.alpha = self.root / "alpha.png"
        self.core = self.root / "core.png"
        self.keep = self.root / "keep.png"
        self.report = self.root / "report.json"
        self.previews = self.root / "previews"
        # White highlight and a black central opening. Core deliberately marks
        # only part of opaque foreground, independently of alpha's plateau.
        with Image.new("RGB", (48, 32), (30, 100, 180)) as source:
            draw = ImageDraw.Draw(source)
            draw.rectangle((6, 6, 12, 12), fill=(255, 255, 255))
            draw.rectangle((20, 12, 27, 19), fill=(10, 10, 10))
            source.save(self.source)
        with Image.new("L", (48, 32), 0) as alpha:
            draw = ImageDraw.Draw(alpha)
            draw.rectangle((3, 3, 44, 28), fill=128)
            draw.rectangle((4, 4, 43, 27), fill=255)
            draw.rectangle((20, 12, 27, 19), fill=0)
            alpha.save(self.alpha)
        with Image.new("L", (48, 32), 0) as core:
            ImageDraw.Draw(core).rectangle((6, 6, 12, 12), fill=255)
            core.save(self.core)
        with Image.new("L", (48, 32), 0) as keep:
            ImageDraw.Draw(keep).rectangle((20, 12, 27, 19), fill=255)
            keep.save(self.keep)
        self.original_bytes = {path: path.read_bytes() for path in self.inputs()}

    def inputs(self):
        return (self.source, self.alpha, self.core, self.keep)

    def check(self, include_keep=True, **kwargs):
        arguments = dict(source=self.source, alpha=self.alpha, opaque_core=self.core,
                         keep_open=self.keep if include_keep else None,
                         report=self.report, preview_dir=self.previews)
        arguments.update(kwargs)
        return guard.run(**arguments)

    def edit_pixel(self, path, xy, value):
        with Image.open(path) as image:
            image.load()
            image.putpixel(xy, value)
            image.save(path)

    def assert_blocked(self, result, code):
        self.assertEqual(result["status"], "blocked", result)
        self.assertIn(code, [error["code"] for error in result["errors"]], result)
        self.assertTrue(result["manual_review_needed"])
        if result["report_written"]:
            self.assertEqual(json.loads(self.report.read_text())["status"], "blocked")

    def test_clean_is_only_draft_and_inputs_unchanged(self):
        result = self.check()
        self.assertEqual(result["status"], "draft")
        self.assertTrue(result["not_segmentation_tool"])
        self.assertTrue(result["manual_review_needed"])
        self.assertFalse(result["core_is_complete_identity_proof"])
        self.assertFalse(result["independent_annotation_verified"])
        self.assertIn("entire contour", " ".join(result["manual_review"]))
        self.assertEqual(result["checks"]["core_pixels"], 49)
        self.assertIsNone(result["checks"]["core_exact_alpha_threshold"])
        self.assertEqual(result["inputs"]["source"]["sha256"], hashlib.sha256(self.original_bytes[self.source]).hexdigest())
        self.assertEqual(json.loads(self.report.read_text()), json.loads(json.dumps(result)))
        for path in self.inputs():
            self.assertEqual(path.read_bytes(), self.original_bytes[path])

    def test_previews_render_highlight_hole_edge_and_checkerboard(self):
        result = self.check()
        self.assertEqual(len(result["previews"]), 5)
        for name, background in (("on-black.png", (0, 0, 0)),
                                 ("on-white.png", (255, 255, 255)),
                                 ("on-magenta.png", (255, 0, 255)),
                                 ("on-green.png", (0, 255, 0))):
            with Image.open(self.previews / name) as image:
                image.load()
                self.assertEqual(image.size, (48, 32))
                self.assertEqual(image.getpixel((8, 8)), (255, 255, 255))
                self.assertEqual(image.getpixel((22, 14)), background)
                self.assertEqual(image.getpixel((0, 0)), background)
                expected = tuple((c * 128 + b * 127 + 127) // 255
                                 for c, b in zip((30, 100, 180), background))
                self.assertEqual(image.getpixel((3, 4)), expected)
        with Image.open(self.previews / "on-checkerboard.png") as image:
            self.assertEqual(image.getpixel((0, 0)), (210, 210, 210))
            self.assertEqual(image.getpixel((17, 0)), (110, 110, 110))

    def test_single_white_highlight_loss_blocks_without_color_heuristics(self):
        self.edit_pixel(self.alpha, (8, 8), 0)
        result = self.check()
        self.assert_blocked(result, "core_alpha_too_low")
        self.assertEqual(result["checks"]["core_alpha_below_250"]["pixels"], 1)
        self.assertEqual(len(result["previews"]), 5)
        self.assertEqual(self.source.read_bytes(), self.original_bytes[self.source])

    def test_core_boundary_249_blocks_250_drafts(self):
        for value, status in ((249, "blocked"), (250, "draft")):
            with self.subTest(value=value):
                self.edit_pixel(self.alpha, (8, 8), value)
                result = self.check(report=self.root / (str(value) + ".json"),
                                    preview_dir=self.root / ("p" + str(value)))
                self.assertEqual(result["status"], status)

    def test_keep_open_boundary_5_drafts_6_blocks(self):
        for value, status in ((5, "draft"), (6, "blocked")):
            with self.subTest(value=value):
                self.edit_pixel(self.alpha, (22, 14), value)
                result = self.check(report=self.root / (str(value) + ".json"),
                                    preview_dir=self.root / ("p" + str(value)))
                self.assertEqual(result["status"], status)
                if value == 6:
                    self.assertEqual(result["checks"]["keep_open_alpha_above_5"]["pixels"], 1)

    def test_keep_open_core_overlap_blocks(self):
        self.edit_pixel(self.keep, (8, 8), 255)
        self.assert_blocked(self.check(), "mask_overlap")

    def test_keep_open_is_optional_and_empty_mask_is_not_hole_proof(self):
        result = self.check(include_keep=False)
        self.assertEqual(result["status"], "draft")
        self.assertIsNone(result["checks"]["keep_open_pixels"])
        self.assertIn("not_supplied", result["checks"]["openings_check"])
        with Image.new("L", (48, 32), 0) as empty:
            empty.save(self.keep)
        result = self.check(report=self.root / "empty.json", preview_dir=self.root / "empty-p")
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["checks"]["keep_open_pixels"], 0)
        self.assertTrue(result["manual_review_needed"])

    def test_binary_mode_one_masks_are_supported(self):
        for path in (self.core, self.keep):
            with Image.open(path) as image:
                image.convert("1").save(path)
        self.assertEqual(self.check()["status"], "draft")

    def test_empty_core_stops_previews(self):
        with Image.new("L", (48, 32), 0) as empty:
            empty.save(self.core)
        self.assert_blocked(self.check(), "empty_core")
        self.assertFalse(self.previews.exists())

    def test_nonbinary_masks_stop_without_thresholding(self):
        for role in ("core", "keep"):
            with self.subTest(role=role):
                path = getattr(self, role)
                self.edit_pixel(path, (8, 8), 254)
                result = self.check(report=self.root / (role + ".json"),
                                    preview_dir=self.root / (role + "-p"))
                self.assertEqual(result["status"], "blocked")
                self.assertIn("nonbinary_mask", [e["code"] for e in result["errors"]])
                self.assertEqual(result["previews"], [])
                path.write_bytes(self.original_bytes[path])

    def test_exact_threshold_cores_block_for_any_cutoff(self):
        for cutoff in (0, 1, 128, 129, 250, 255):
            with self.subTest(cutoff=cutoff):
                with Image.open(self.alpha) as alpha:
                    alpha.point([255 if v >= cutoff else 0 for v in range(256)]).save(self.core)
                result = self.check(report=self.root / (str(cutoff) + ".json"),
                                    preview_dir=self.root / ("p" + str(cutoff)))
                self.assertEqual(result["status"], "blocked")
                self.assertIn("core_is_alpha_threshold", [e["code"] for e in result["errors"]])

    def test_shared_input_paths_symlinks_and_hardlinks_block(self):
        aliases = [self.alpha, self.root / "link.png", self.root / "hardlink.png"]
        aliases[1].symlink_to(self.alpha)
        os.link(self.alpha, aliases[2])
        for index, alias in enumerate(aliases):
            result = self.check(opaque_core=alias, report=self.root / (str(index) + ".json"),
                                preview_dir=self.root / ("p" + str(index)))
            self.assertEqual(result["status"], "blocked")
            self.assertIn("aliased_inputs", [e["code"] for e in result["errors"]])

    def test_dimension_mismatch_for_each_mask(self):
        for role in ("alpha", "core", "keep"):
            path = getattr(self, role)
            with Image.new("L", (32, 48), 255) as image:
                image.save(path)
            result = self.check(report=self.root / (role + ".json"),
                                preview_dir=self.root / (role + "-p"))
            self.assertEqual(result["status"], "blocked")
            self.assertIn("size_mismatch", [e["code"] for e in result["errors"]])
            self.assertEqual(result["previews"], [])
            path.write_bytes(self.original_bytes[path])

    def set_orientation(self, path, orientation):
        with Image.open(path) as image:
            exif = Image.Exif()
            exif[274] = orientation
            image.save(path, exif=exif)

    def test_exif_mismatch_and_invalid_orientation_stop(self):
        self.set_orientation(self.source, 6)
        self.assert_blocked(self.check(), "orientation_mismatch")
        self.assertFalse(self.previews.exists())
        self.set_orientation(self.source, 0)
        result = self.check(report=self.root / "invalid.json", preview_dir=self.root / "invalid-p")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("invalid_orientation", [e["code"] for e in result["errors"]])

    def test_shared_exif_rotation_transforms_only_previews(self):
        for path in self.inputs():
            self.set_orientation(path, 6)
        before = {p: p.read_bytes() for p in self.inputs()}
        result = self.check()
        self.assertEqual(result["status"], "draft")
        with Image.open(self.previews / "on-black.png") as image:
            self.assertEqual(image.size, (32, 48))
            self.assertEqual(image.getpixel((23, 8)), (255, 255, 255))
        for path in self.inputs():
            self.assertEqual(path.read_bytes(), before[path])

    def test_unexpected_modes_for_source_and_masks_stop(self):
        cases = (("source", "P"), ("source", "CMYK"), ("source", "I"),
                 ("alpha", "RGB"), ("core", "RGBA"), ("keep", "P"), ("alpha", "I;16"))
        for index, (role, mode) in enumerate(cases):
            path = getattr(self, role)
            with Image.new(mode, (48, 32)) as image:
                image.save(path, format="TIFF" if mode in ("CMYK", "I") else "PNG")
            result = self.check(report=self.root / (str(index) + ".json"),
                                preview_dir=self.root / ("p" + str(index)))
            self.assertEqual(result["status"], "blocked")
            self.assertIn("invalid_mode", [e["code"] for e in result["errors"]])
            self.assertEqual(result["previews"], [])
            path.write_bytes(self.original_bytes[path])

    def test_implicit_png_transparency_stops(self):
        with Image.open(self.alpha) as alpha:
            alpha.save(self.alpha, transparency=0)
        self.assert_blocked(self.check(), "implicit_transparency")
        self.assertFalse(self.previews.exists())

    def test_corruption_for_every_input_stops_and_hashes_original_bytes(self):
        for role in ("source", "alpha", "core", "keep"):
            path = getattr(self, role)
            path.write_bytes(b"fixed corrupt fixture")
            result = self.check(report=self.root / (role + ".json"),
                                preview_dir=self.root / (role + "-p"))
            self.assertEqual(result["status"], "blocked")
            self.assertIn("unreadable_image", [e["code"] for e in result["errors"]])
            key = {"core": "opaque_core", "keep": "keep_open"}.get(role, role)
            self.assertEqual(result["inputs"][key]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(result["previews"], [])
            path.write_bytes(self.original_bytes[path])

    def test_truncated_png_and_permissive_decoder_setting_block(self):
        self.source.write_bytes(self.original_bytes[self.source][:-24])
        self.assert_blocked(self.check(), "unreadable_image")
        with mock.patch.object(ImageFile, "LOAD_TRUNCATED_IMAGES", True):
            result = self.check(report=self.root / "unsafe.json", preview_dir=self.root / "unsafe-p")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("unsafe_decoder_setting", [e["code"] for e in result["errors"]])

    def test_animation_and_multiframe_files_stop(self):
        for index, (file_format, mode) in enumerate((("PNG", "RGB"), ("GIF", "RGB"), ("TIFF", "L"))):
            with Image.new(mode, (48, 32), 0) as first, Image.new(mode, (48, 32), 255) as second:
                first.save(self.source, format=file_format, save_all=True, append_images=[second], duration=50, loop=0)
            result = self.check(report=self.root / (str(index) + ".json"),
                                preview_dir=self.root / ("p" + str(index)))
            self.assertEqual(result["status"], "blocked")
            self.assertIn("animated_image", [e["code"] for e in result["errors"]])
            self.assertEqual(result["previews"], [])

    def test_decompression_warning_blocks_locally(self):
        with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 1000):
            self.assert_blocked(self.check(), "unreadable_image")
        self.assertFalse(self.previews.exists())

    def test_source_alpha_is_respected_without_resurrecting_pixels(self):
        with Image.open(self.source) as image:
            rgba = image.convert("RGBA")
            rgba.putpixel((15, 15), (255, 255, 255, 0))
            rgba.save(self.source)
            rgba.close()
        result = self.check()
        self.assertEqual(result["status"], "draft")
        with Image.open(self.previews / "on-black.png") as image:
            self.assertEqual(image.getpixel((15, 15)), (0, 0, 0))
        self.edit_pixel(self.source, (8, 8), (255, 255, 255, 249))
        result = self.check(report=self.root / "source-alpha.json", preview_dir=self.root / "source-alpha-p")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("source_alpha_too_low", [e["code"] for e in result["errors"]])

    def test_grayscale_originals_are_supported_without_changing_masks(self):
        for mode in ("L", "LA"):
            with Image.open(io.BytesIO(self.original_bytes[self.source])) as source:
                with source.convert(mode) as converted:
                    converted.save(self.source)
            result = self.check(report=self.root / (mode + ".json"),
                                preview_dir=self.root / (mode + "-p"))
            self.assertEqual(result["status"], "draft")
            self.assertEqual(result["inputs"]["source"]["mode"], mode)
            self.assertEqual(self.alpha.read_bytes(), self.original_bytes[self.alpha])

    def test_single_frame_png_animation_metadata_is_rejected(self):
        # A one-frame APNG is still not a still image. Also reject orphan frame
        # control after IDAT: Pillow exposes its duration only during load(),
        # despite reporting n_frames == 1 and is_animated == False throughout.
        # Generate actual PNG chunks around fixed Pillow pixels, not mock info.
        for role, original in zip(("source", "alpha", "opaque_core", "keep_open"),
                                  self.inputs()):
            for late in (False, True):
                with self.subTest(role=role, late_metadata=late):
                    info = PngImagePlugin.PngInfo()
                    if not late:
                        info.add(b"acTL", struct.pack(">II", 1, 0))
                    info.add(b"fcTL", struct.pack(">IIIIIHHBB", 0, 48, 32, 0, 0,
                                                   1, 10, 0, 0), after_idat=late)
                    name = role + ("-late" if late else "-early")
                    fixture = self.root / (name + ".png")
                    with Image.open(io.BytesIO(self.original_bytes[original])) as image:
                        image.save(fixture, pnginfo=info)
                    with Image.open(fixture) as probe:
                        self.assertEqual(probe.n_frames, 1)
                        self.assertFalse(probe.is_animated)
                        if late:
                            self.assertNotIn("duration", probe.info)
                            self.assertNotIn("loop", probe.info)
                        else:
                            self.assertEqual(probe.info["loop"], 0)
                        probe.load()
                        self.assertEqual(probe.info["duration"], 100.0)
                    fixture_bytes = fixture.read_bytes()
                    self.report = self.root / (name + ".json")
                    self.previews = self.root / (name + "-previews")
                    result = self.check(**{role: fixture})
                    self.assertEqual(result["status"], "blocked")
                    self.assert_blocked(result, "animated_image")
                    self.assertFalse(self.previews.exists())
                    self.assertEqual(fixture.read_bytes(), fixture_bytes)

    def test_unmarked_foreground_loss_remains_draft_requiring_manual_review(self):
        self.edit_pixel(self.alpha, (40, 20), 0)
        result = self.check()
        self.assertEqual(result["status"], "draft")
        self.assertTrue(result["manual_review_needed"])
        self.assertFalse(result["core_is_complete_identity_proof"])

    def test_existing_outputs_and_dangling_symlinks_never_overwritten(self):
        self.report.write_bytes(b"existing report")
        self.assert_blocked(self.check(), "output_exists")
        self.assertEqual(self.report.read_bytes(), b"existing report")
        self.assertFalse(self.previews.exists())
        self.previews.mkdir()
        sentinel = self.previews / "on-black.png"
        sentinel.write_bytes(b"existing preview")
        result = self.check(report=self.root / "new.json")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(sentinel.read_bytes(), b"existing preview")
        self.assertFalse((self.root / "new.json").exists())
        dangling = self.root / "dangling.json"
        dangling.symlink_to(self.root / "absent.json")
        result = self.check(report=dangling, preview_dir=self.root / "fresh-p")
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(dangling.is_symlink())
        self.assertFalse((self.root / "absent.json").exists())

    def test_outputs_cannot_alias_originals(self):
        self.assert_blocked(self.check(report=self.source), "output_exists")
        self.assertEqual(self.source.read_bytes(), self.original_bytes[self.source])
        result = self.check(preview_dir=self.root)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(self.report.exists())

    def test_report_may_be_inside_new_preview_dir_but_not_collide(self):
        result = self.check(report=self.previews / "report.json")
        self.assertEqual(result["status"], "draft")
        self.assertTrue((self.previews / "report.json").is_file())
        fresh = self.root / "fresh"
        result = self.check(report=fresh / "on-black.png", preview_dir=fresh)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("output_collision", [e["code"] for e in result["errors"]])
        self.assertFalse(fresh.exists())

    def test_missing_parents_and_inputs_block(self):
        self.assert_blocked(self.check(preview_dir=self.root / "missing" / "p"), "missing_output_parent")
        self.assertFalse((self.root / "missing").exists())
        result = self.check(source=self.root / "absent.png")
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(self.report.exists())
        self.assertFalse(self.previews.exists())

    def test_fifo_input_does_not_hang(self):
        fifo = self.root / "input.fifo"
        os.mkfifo(fifo)
        self.assert_blocked(self.check(source=fifo), "input_not_regular")

    def test_preview_write_failure_changes_status_to_blocked(self):
        with mock.patch.object(Image.Image, "save", side_effect=OSError("fixture write failure")):
            result = self.check()
        self.assert_blocked(result, "preview_write_failed")
        self.assertTrue(result["report_written"])
        self.assertEqual(result["previews"], [])

    def test_late_preview_collision_does_not_overwrite_existing_file(self):
        original = guard._previews

        def late_collision(source, effective, orientation, directory, result):
            (directory / "on-black.png").write_bytes(b"late existing preview")
            original(source, effective, orientation, directory, result)

        with mock.patch.object(guard, "_previews", side_effect=late_collision):
            result = self.check()
        self.assert_blocked(result, "preview_write_failed")
        self.assertEqual((self.previews / "on-black.png").read_bytes(), b"late existing preview")

    def test_late_report_collision_stops_before_previews(self):
        original = guard._output_paths

        def late_collision(report, preview_dir):
            paths = original(report, preview_dir)
            paths[0].write_bytes(b"late existing report")
            return paths

        with mock.patch.object(guard, "_output_paths", side_effect=late_collision):
            result = self.check()
        self.assert_blocked(result, "output_write_failed")
        self.assertFalse(result["report_written"])
        self.assertEqual(self.report.read_bytes(), b"late existing report")
        self.assertEqual(list(self.previews.iterdir()), [])

    def test_report_io_failure_never_returns_draft(self):
        with mock.patch.object(guard.json, "dump", side_effect=OSError("fixture disk full")):
            result = self.check()
        self.assert_blocked(result, "output_write_failed")
        self.assertFalse(result["report_written"])
        self.assertEqual(len(result["previews"]), 5)

    def test_real_cli_checks_files_and_returns_blocked_on_highlight_loss(self):
        for name, expected in (("clean", "draft"), ("lost-highlight", "blocked")):
            if expected == "blocked":
                self.edit_pixel(self.alpha, (8, 8), 0)
            report = self.root / (name + ".json")
            command = [sys.executable, "-B", str(Path(guard.__file__)),
                       "--source", str(self.source), "--alpha", str(self.alpha),
                       "--opaque-core", str(self.core), "--keep-open", str(self.keep),
                       "--report", str(report), "--preview-dir", str(self.root / name)]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0 if expected == "draft" else 2, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["status"], expected)
            self.assertEqual(json.loads(report.read_text()), result)
            self.assertEqual(self.source.read_bytes(), self.original_bytes[self.source])

    def test_cli_exit_codes_and_no_approval_state(self):
        argv = ["--source", str(self.source), "--alpha", str(self.alpha),
                "--opaque-core", str(self.core), "--keep-open", str(self.keep),
                "--report", str(self.report), "--preview-dir", str(self.previews)]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(guard.main(argv), 0)
        self.assertEqual(json.loads(out.getvalue())["status"], "draft")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(guard.main(argv), 2)
        self.assertEqual(json.loads(out.getvalue())["status"], "blocked")
        completed = subprocess.run([sys.executable, "-B", str(Path(guard.__file__)), "--help"],
                                   capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0)
        self.assertIn("--opaque-core", completed.stdout)
        self.assertIn("--keep-open", completed.stdout)

    def test_python39_syntax_and_pillow_minimum(self):
        for path in (Path(guard.__file__), Path(__file__)):
            ast.parse(path.read_text(), feature_version=(3, 9))
        with mock.patch.object(guard, "PILLOW_VERSION", "9.5.0"):
            self.assert_blocked(self.check(), "unsupported_runtime")


if __name__ == "__main__":
    unittest.main()
