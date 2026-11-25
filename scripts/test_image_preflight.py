"""Offline regression tests: no credentials, upstream requests, or paid generation."""

import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

from PIL import Image

import image_preflight as prep
import salpx_image_client as client


SETTINGS = {"SALPX_IMAGE_MODEL": "gpt-image-2.5-flare", "SALPX_VIDEO_MODEL": "omni_flash"}


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="salpx-preflight-test-")
        self.root = Path(self.temp.name)
        self.source = self.root / "product.png"
        Image.new("RGB", (180, 120), (240, 100, 20)).save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def args(self, *extra):
        return client.build_parser().parse_args(["create", "--operation", "single_image", *extra])

    def test_nine_large_images_compress_before_network_and_preserve_originals(self):
        # Nine uncompressed photographic-size PNGs exceed the reported 128 MB incident.
        size = (2800, 2200)
        pixels = random.Random(14).randbytes(size[0] * size[1] * 3)
        master = self.root / "large-1.png"
        Image.frombytes("RGB", size, pixels).save(master, compress_level=0)
        del pixels
        files = [master]
        for i in range(2, 10):
            path = self.root / f"large-{i}.png"
            shutil.copyfile(master, path)
            files.append(path)
        digest = hashlib.sha256(master.read_bytes()).hexdigest()
        args = self.args("--count", "6", "--prompt", "保留产品细节与材质")
        args.file = files
        with mock.patch.object(client, "urlopen", side_effect=AssertionError("Unexpected network")):
            body, report = client.prepare_image_request(args, SETTINGS)
        self.assertGreater(report["source_bytes"], 128 * prep.MIB)
        self.assertEqual(len(body["images"]), 9)
        self.assertEqual(body["n"], 1)
        self.assertLessEqual(report["prepared_image_bytes"], 20 * prep.MIB)
        self.assertLessEqual(report["request_bytes"], 32 * prep.MIB)
        self.assertEqual(report["request_bytes"], len(prep.serialize_payload(body)))
        self.assertNotIn("data:image", json.dumps(report))
        self.assertEqual([r["source"] for r in report["references"]], [str(f.resolve()) for f in files])
        for path, uri, record in zip(files, body["images"], report["references"]):
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            raw = base64.b64decode(uri.split(",", 1)[1])
            self.assertEqual(len(raw), record["prepared_bytes"])
            self.assertLessEqual(len(raw), 2 * prep.MIB)
            with Image.open(io.BytesIO(raw)) as image:
                self.assertGreaterEqual(max(image.size), prep.MIN_LONG_EDGE)
                self.assertAlmostEqual(image.width / image.height, size[0] / size[1], places=2)
        print(json.dumps({"offline_large_fixture": {k: report[k] for k in ("reference_count", "source_bytes", "prepared_image_bytes", "request_bytes")}}))

    def test_tenth_reference_rejected_before_read_or_send(self):
        args = self.args()
        args.file = [self.root / "does-not-exist.png"] * 10
        with mock.patch.object(prep, "_compress_reference", side_effect=AssertionError("Should not decode")), mock.patch.object(client, "urlopen", side_effect=AssertionError("Should not send")):
            with self.assertRaisesRegex(prep.PreflightError, "At most 9"):
                client.prepare_image_request(args, SETTINGS)

    def test_all_image_operations_accept_nine_in_order(self):
        for operation in ("single_image", "background_replace", "outfit", "fission"):
            with self.subTest(operation=operation):
                args = self.args()
                args.operation, args.count, args.file = operation, 6, [self.source] * 9
                body, _ = client.prepare_image_request(args, SETTINGS)
                self.assertEqual(len(body["images"]), 9)
                self.assertEqual(body["n"], 1)

    def test_model_profiles_select_configured_models_and_explicit_model_wins(self):
        settings = {**SETTINGS, "SALPX_DRAFT_IMAGE_MODEL": "draft-model", "SALPX_REFINE_IMAGE_MODEL": "refine-model"}
        for profile, expected in (("draft", "draft-model"), ("standard", "gpt-image-2.5-flare"), ("refine", "refine-model")):
            with self.subTest(profile=profile):
                args = self.args("--profile", profile)
                args.file = [self.source]
                body, _ = client.prepare_image_request(args, settings)
                self.assertEqual(body["model"], expected)
        args = self.args("--profile", "draft", "--model", "explicit-model")
        args.file = [self.source]
        body, _ = client.prepare_image_request(args, settings)
        self.assertEqual(body["model"], "explicit-model")

    def test_six_outputs_prepare_once_and_do_not_accumulate_references(self):
        args = self.args("--count", "6")
        args.file = [self.source] * 9
        api = mock.Mock()
        api.generate_image.return_value = {"data": [{"b64_json": "test"}]}
        with mock.patch.object(client, "prepare_image_request", wraps=client.prepare_image_request) as prepare, mock.patch.object(client, "save_image_outputs", return_value=["offline-output.png"]), contextlib.redirect_stderr(io.StringIO()):
            result = client.create_image(api, args, SETTINGS)
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(api.generate_image.call_count, 6)
        self.assertEqual(len(result["downloaded"]), 6)
        for call in api.generate_image.call_args_list:
            self.assertEqual(len(call.args[0]["images"]), 9)
            self.assertEqual(call.args[0]["n"], 1)
            self.assertEqual(len(prep.serialize_payload(call.args[0])), result["preflight"]["request_bytes"])

    def test_actual_transport_bytes_equal_preflight_and_have_only_current_refs(self):
        args = self.args("--prompt", "中文材质检查 🧻")
        args.file = [self.source] * 9
        body, report = client.prepare_image_request(args, SETTINGS)
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"data": []}'
        response.status = 200
        with mock.patch.object(client, "urlopen", return_value=response) as send:
            client.SalpXClient("offline-test", "https://invalid.example/v1").generate_image(body)
        request = send.call_args.args[0]
        self.assertEqual(len(request.data), report["request_bytes"])
        self.assertEqual(request.data, prep.serialize_payload(body))
        self.assertEqual(set(json.loads(request.data)), {"model", "prompt", "size", "quality", "n", "images"})

    def test_transport_hard_limit_blocks_before_urlopen(self):
        api = client.SalpXClient("offline-test", "https://invalid.example/v1")
        with mock.patch.object(client, "urlopen", side_effect=AssertionError("Should not send")):
            with self.assertRaisesRegex(prep.PreflightError, "above the local"):
                api.generate_image({"prompt": "x" * prep.MAX_REQUEST_BYTES})

    def test_direct_client_tenth_reference_is_also_blocked(self):
        api = client.SalpXClient("offline-test", "https://invalid.example/v1")
        with mock.patch.object(client, "urlopen", side_effect=AssertionError("Should not send")):
            with self.assertRaisesRegex(prep.PreflightError, "At most 9"):
                api.generate_image({"images": ["not-read"] * 10})
            with self.assertRaisesRegex(prep.PreflightError, "must be a list"):
                api.generate_image({"images": "not-a-list"})

    def test_alpha_pixels_retained_and_mime_detected_not_guessed(self):
        path = self.root / "mislabelled.jpg"
        source = Image.new("RGBA", (51, 33), (255, 120, 0, 77))
        source.putpixel((0, 0), (10, 20, 30, 0))
        source.save(path, format="PNG")
        body, report = prep.prepare_payload({}, [path], prep.ImageLimits(), operation="single_image")
        uri = body["images"][0]
        self.assertTrue(uri.startswith("data:image/png;"))
        with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as result:
            self.assertEqual(result.tobytes(), source.tobytes())
        self.assertTrue(report["references"][0]["alpha_preserved"])

    def test_exif_orientation_and_metadata_removed(self):
        path = self.root / "oriented.jpg"
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = "private-camera-owner"
        Image.new("RGB", (80, 40), "red").save(path, exif=exif)
        body, report = prep.prepare_payload({}, [path], prep.ImageLimits(), operation="single_image")
        with Image.open(io.BytesIO(base64.b64decode(body["images"][0].split(",", 1)[1]))) as result:
            self.assertEqual(result.size, (40, 80))
            self.assertFalse(result.getexif())
        self.assertEqual(report["references"][0]["oriented_size"], [40, 80])

    def test_adaptive_total_and_request_budgets(self):
        args = self.args("--max-reference-total-mb", "0.2", "--max-request-mb", "0.3")
        args.file = [self.source] * 9
        body, report = client.prepare_image_request(args, SETTINGS)
        self.assertLessEqual(report["prepared_image_bytes"], int(0.2 * prep.MIB))
        self.assertLessEqual(len(prep.serialize_payload(body)), int(0.3 * prep.MIB))

    def test_tiny_budget_fails_instead_of_destroying_detail(self):
        args = self.args("--max-reference-mb", "0.00001")
        args.file = [self.source]
        with self.assertRaisesRegex(prep.PreflightError, "detail floor"):
            client.prepare_image_request(args, SETTINGS)

    def test_huge_prompt_is_rejected_before_image_decode(self):
        args = self.args("--max-request-mb", "0.01", "--prompt", "图" * 5000)
        args.file = [self.source]
        with mock.patch.object(prep, "_compress_reference", side_effect=AssertionError("Should not decode")):
            with self.assertRaisesRegex(prep.PreflightError, "Request body"):
                client.prepare_image_request(args, SETTINGS)

    def test_invalid_missing_animated_inputs_stop_locally(self):
        bad = self.root / "bad.png"
        bad.write_bytes(b"this is not an image")
        gif = self.root / "animated.gif"
        Image.new("RGB", (20, 20), "red").save(gif, save_all=True, append_images=[Image.new("RGB", (20, 20), "blue")])
        for path in (bad, self.root / "missing.png", gif):
            with self.subTest(path=path), self.assertRaises(prep.PreflightError):
                prep.prepare_payload({}, [path], prep.ImageLimits(), operation="single_image")

    def test_decode_pixel_guard(self):
        with mock.patch.object(prep, "MAX_INPUT_PIXELS", 100):
            with self.assertRaisesRegex(prep.PreflightError, "megapixel"):
                prep.prepare_payload({}, [self.source], prep.ImageLimits(), operation="single_image")

    def test_decode_file_size_guard(self):
        with mock.patch.object(prep, "MAX_INPUT_BYTES", 1):
            with self.assertRaisesRegex(prep.PreflightError, "decode limit"):
                prep.prepare_payload({}, [self.source], prep.ImageLimits(), operation="single_image")

    def test_icc_conversion_and_unknown_cmyk_rejection(self):
        from PIL import ImageCms
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        rgb = self.root / "tagged.png"
        Image.new("RGB", (80, 60), (200, 100, 40)).save(rgb, icc_profile=profile)
        body, report = prep.prepare_payload({}, [rgb], prep.ImageLimits(), operation="single_image")
        self.assertEqual(report["references"][0]["color_profile"], "converted_to_srgb")
        with Image.open(io.BytesIO(base64.b64decode(body["images"][0].split(",", 1)[1]))) as output:
            self.assertTrue(output.info.get("icc_profile"))
            self.assertLessEqual(max(abs(a-b) for a, b in zip(output.getpixel((40, 30)), (200, 100, 40))), 3)
        cmyk = self.root / "unknown-colors.jpg"
        Image.new("CMYK", (80, 60), (20, 30, 50, 0)).save(cmyk)
        with self.assertRaisesRegex(prep.PreflightError, "no color profile"):
            prep.prepare_payload({}, [cmyk], prep.ImageLimits(), operation="single_image")

    def test_palette_transparency_survives(self):
        path = self.root / "palette.png"
        source = Image.new("P", (24, 18), 1)
        source.putpalette([0, 0, 0, 255, 100, 20] + [0] * 762)
        source.putpixel((0, 0), 0)
        source.save(path, transparency=0)
        body, _ = prep.prepare_payload({}, [path], prep.ImageLimits(), operation="single_image")
        with Image.open(io.BytesIO(base64.b64decode(body["images"][0].split(",", 1)[1]))) as output:
            self.assertEqual(output.getpixel((0, 0))[3], 0)
            self.assertEqual(output.getpixel((1, 1)), (255, 100, 20, 255))

    def test_no_pillow_has_actionable_error(self):
        with mock.patch.dict(sys.modules, {"PIL": None}):
            with self.assertRaisesRegex(prep.PreflightError, "pip install Pillow"):
                prep.prepare_payload({}, [self.source], prep.ImageLimits(), operation="single_image")

    def test_prepared_copies_are_isolated_and_original_is_unchanged(self):
        before = self.source.read_bytes()
        records = []
        for _ in range(2):
            _, report = prep.prepare_payload({}, [self.source], prep.ImageLimits(), operation="single_image", prepared_dir=self.root)
            record = report["references"][0]
            self.assertTrue(Path(record["prepared_path"]).is_file())
            records.append(record["prepared_path"])
        self.assertNotEqual(*records)
        self.assertEqual(before, self.source.read_bytes())

    def test_video_uses_same_preflight_but_only_one_frame(self):
        args = self.args()
        args.operation, args.duration, args.file = "video", 5, [self.source]
        body, report = client.prepare_video_request(args, SETTINGS)
        self.assertTrue(body["image"].startswith("data:image/jpeg;"))
        self.assertEqual(report["request_bytes"], len(prep.serialize_payload(body)))
        args.file *= 2
        with self.assertRaisesRegex(prep.PreflightError, "exactly one"):
            client.prepare_video_request(args, SETTINGS)

    def test_invalid_limits_and_required_counts(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(prep.PreflightError):
                prep.mib_bytes(value)
        for limits in (prep.ImageLimits(request_bytes=33 * prep.MIB), prep.ImageLimits(max_edge=100), prep.ImageLimits(total_image_bytes=21 * prep.MIB)):
            with self.subTest(limits=limits), self.assertRaises(prep.PreflightError):
                limits.validate()
        for operation, files in (("outfit", [self.source]), ("background_replace", [])):
            args = self.args()
            args.operation, args.file = operation, files
            with self.assertRaises(prep.PreflightError):
                client.prepare_image_request(args, SETTINGS)
        with self.assertRaises(client.ClientError):
            client.prepare_image_request(self.args("--count", "0"), SETTINGS)

    def test_cli_preflight_and_dry_run_need_no_key_and_emit_no_base64(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SALPX_")}
        script = str(Path(client.__file__).resolve())
        for command in ("preflight", "create"):
            args = [sys.executable, script, "--env-file", str(self.root / "no-credentials.env"), command, "--operation", "single_image", "--file", str(self.source)]
            if command == "create":
                args.append("--dry-run")
            run = subprocess.run(args, env=env, capture_output=True, text=True, check=True)
            output = json.loads(run.stdout)
            self.assertFalse(output["submitted"])
            self.assertNotIn("data:image", run.stdout + run.stderr)
            self.assertNotIn("Authorization", run.stdout + run.stderr)

    def test_sunburst_defaults_and_overrides(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = client.settings_from_env(self.root / "absent.env")
        for flags, model, size, quality in (
            ([], "gpt-image-2.6-sunburst", "2k:1:1", "max"),
            (["--ratio", "5:7"], "gpt-image-2.6-sunburst", "2k:5:7", "max"),
            (["--ratio", "16:9", "--resolution", "4K", "--quality", "low"], "gpt-image-2.6-sunburst-4k", "4k:16:9", "low"),
            (["--size", "4k:9:16"], "gpt-image-2.6-sunburst-4k", "4k:9:16", "max"),
        ):
            with self.subTest(flags=flags):
                body, _ = client.prepare_image_request(self.args(*flags), settings)
                self.assertEqual(body, dict(model=model, size=size, quality=quality, n=1, prompt=body["prompt"]))
        for flags in (["--ratio", "0:3"], ["--resolution", "2k", "--size", "4k:3:4"], ["--size", "3840x2160"]):
            with self.subTest(flags=flags), self.assertRaises(client.ClientError):
                client.prepare_image_request(self.args(*flags), settings)

    def test_fission_uses_separate_requests_and_saves_jpeg(self):
        args = self.args("--count", "2", "--download-dir", str(self.root))
        args.operation = "fission"
        api = mock.Mock()
        jpeg = io.BytesIO()
        Image.new("RGB", (8, 8)).save(jpeg, format="JPEG")
        api.generate_image.return_value = {"data": [{"b64_json": base64.b64encode(jpeg.getvalue()).decode()}]}
        with contextlib.redirect_stderr(io.StringIO()):
            result = client.create_image(api, args, SETTINGS)
        self.assertEqual([c.args[0]["n"] for c in api.generate_image.call_args_list], [1, 1])
        self.assertEqual(len(set(result["downloaded"])), 2)
        for path in map(Path, result["downloaded"]):
            self.assertEqual(path.suffix, ".jpg")
            self.assertEqual(path.read_bytes(), jpeg.getvalue())

    def test_http_413_is_not_retried(self):
        api = client.SalpXClient("offline-test", "https://invalid.example/v1")
        error = HTTPError("https://invalid.example/v1", 413, "Too Large", {}, io.BytesIO(b"{}"))
        with mock.patch.object(client, "urlopen", side_effect=error) as send:
            with self.assertRaisesRegex(client.ClientError, "Do not resend"):
                api.generate_image({"prompt": "small"})
        self.assertEqual(send.call_count, 1)

    def test_project_creation_and_reuse_preserve_existing_images(self):
        root = self.root / "new-project"
        args = client.build_parser().parse_args(["init-project", "--project-dir", str(root), "--product-name", "纸巾"])
        with mock.patch.object(client, "urlopen", side_effect=AssertionError("Should not send")):
            first = client.init_project(args)
            image = Path(first["product_dir"]) / "原图.png"
            shutil.copyfile(self.source, image)
            second = client.init_project(args)
        self.assertTrue(first["project_created"])
        self.assertTrue(first["product_created"])
        self.assertFalse(second["project_created"])
        self.assertFalse(second["product_created"])
        self.assertFalse(second["originals_moved"])
        self.assertEqual(image.read_bytes(), self.source.read_bytes())
        self.assertTrue(self.source.exists())

    def test_project_rejects_bad_names_and_file_conflicts(self):
        root = self.root / "must-not-create"
        for name in ("../escape", "/tmp", "..", "a/b", "a\\b", "\n", ""):
            args = client.build_parser().parse_args(["init-project", "--project-dir", str(root), "--product-name", name])
            with self.subTest(name=name), self.assertRaises(client.ClientError):
                client.init_project(args)
            self.assertFalse(root.exists())
        args = client.build_parser().parse_args(["init-project", "--project-dir", str(self.source)])
        before = self.source.read_bytes()
        with self.assertRaisesRegex(client.ClientError, "occupied by a file"):
            client.init_project(args)
        self.assertEqual(before, self.source.read_bytes())

    def test_project_rejects_symlink_child(self):
        external = self.root / "external"
        external.mkdir()
        root = self.root / "project"
        root.mkdir()
        (root / "商品01").symlink_to(external, target_is_directory=True)
        args = client.build_parser().parse_args(["init-project", "--project-dir", str(root)])
        with self.assertRaisesRegex(client.ClientError, "symlink"):
            client.init_project(args)
        self.assertEqual(list(external.iterdir()), [])

    def test_project_cli_without_key_or_pillow_and_version(self):
        script = str(Path(client.__file__).resolve())
        env = {k: v for k, v in os.environ.items() if not k.startswith("SALPX_")}
        run = subprocess.run([sys.executable, "-S", script, "init-project", "--project-dir", str(self.root / "cli-project")], capture_output=True, text=True, env=env, check=True)
        result = json.loads(run.stdout)
        self.assertEqual(result["version"], "v1.9")
        self.assertTrue(Path(result["product_dir"]).is_dir())
        self.assertFalse(result["submitted"])
        version = subprocess.run([sys.executable, "-S", script, "--version"], capture_output=True, text=True, check=True)
        self.assertEqual(version.stdout.strip(), "v1.9")

    def test_release_metadata_and_onboarding_contract(self):
        root = Path(client.__file__).resolve().parent.parent
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('version: "v1.9"', skill)
        self.assertIn("references/first-use.md", skill)
        welcome = (root / "references" / "first-use.md").read_text(encoding="utf-8")
        for required in ("v1.9", "本次改版新增", "我能做什么", "SalpX 中转站", "项目目录", "直接创建", "9 张", "32 MiB", "不要把密钥贴在聊天里", "生产质检", "原始像素", "场景底图"):
            self.assertIn(required, welcome)
        for number in range(1, 15):
            self.assertIn(f"\n{number}. ", welcome)
        self.assertEqual(client.USER_AGENT, "SalpXEcommerceImageSkill/1.9")


if __name__ == "__main__":
    unittest.main(verbosity=2)
