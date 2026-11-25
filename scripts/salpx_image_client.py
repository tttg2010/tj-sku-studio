#!/usr/bin/env python3
"""SalpX ecommerce client with local Pillow reference preprocessing."""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from image_preflight import (
    ImageLimits, PreflightError, mib_bytes, prepare_payload, serialize_payload,
    validate_reference_count,
)


DEFAULT_BASE_URL = "https://www.salpx.com/v1"
SKILL_VERSION = "v1.9"
USER_AGENT = f"SalpXEcommerceImageSkill/{SKILL_VERSION.removeprefix('v')}"
DEFAULT_IMAGE_MODEL = "gpt-image-2.6-sunburst"
TIERED_MODELS = {"gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2.6-flare", DEFAULT_IMAGE_MODEL}
DEFAULT_VIDEO_MODEL = "omni_flash"
DEFAULT_ENV_FILE = Path.home() / ".config" / "salpx" / "credentials.env"
COPY_BUFFER_SIZE = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_POLL_TIMEOUT_SECONDS = 900.0
RATIO_TO_SIZE = {
    "1:1": "1024x1024",
    "4:5": "1024x1280",
    "3:4": "1024x1365",
    "2:3": "1024x1536",
    "9:16": "1024x1792",
    "16:9": "1792x1024",
    "3:2": "1536x1024",
    "4:3": "1365x1024",
}
VIDEO_URL_KEYS = ("url", "video_url", "videoUrl", "download_url", "output_url", "result_url")
IMAGE_URL_KEYS = ("url", "image_url", "imageUrl", "download_url", "output_url", "result_url")


class ClientError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


def normalize_base_url(url: str) -> str:
    normalized = (url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not normalized.endswith("/v1"):
        normalized += "/v1"
    return normalized


def load_env_file(path: Optional[Path]) -> Dict[str, str]:
    if not path or not path.is_file():
        return {}
    values: Dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ClientError(f"Cannot read SalpX env file: {error}") from None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in {"SALPX_API_KEY", "SALPX_BASE_URL", "SALPX_IMAGE_MODEL", "SALPX_DRAFT_IMAGE_MODEL", "SALPX_REFINE_IMAGE_MODEL", "SALPX_VIDEO_MODEL"}:
            values[key] = value
    return values


def resolve_env_file(explicit: Optional[Path]) -> Optional[Path]:
    if explicit:
        return explicit.expanduser().resolve()
    env_path = os.environ.get("SALPX_ENV_FILE")
    if env_path:
        return Path(env_path).expanduser().resolve()
    project_env = Path.cwd() / ".env"
    if project_env.is_file():
        return project_env.resolve()
    if DEFAULT_ENV_FILE.is_file():
        return DEFAULT_ENV_FILE.resolve()
    return None


def settings_from_env(explicit_env_file: Optional[Path]) -> Dict[str, str]:
    values = load_env_file(resolve_env_file(explicit_env_file))
    for key in ("SALPX_API_KEY", "SALPX_BASE_URL", "SALPX_IMAGE_MODEL", "SALPX_DRAFT_IMAGE_MODEL", "SALPX_REFINE_IMAGE_MODEL", "SALPX_VIDEO_MODEL"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    values.setdefault("SALPX_BASE_URL", DEFAULT_BASE_URL)
    values.setdefault("SALPX_IMAGE_MODEL", DEFAULT_IMAGE_MODEL)
    values.setdefault("SALPX_DRAFT_IMAGE_MODEL", values["SALPX_IMAGE_MODEL"])
    values.setdefault("SALPX_REFINE_IMAGE_MODEL", values["SALPX_IMAGE_MODEL"])
    values.setdefault("SALPX_VIDEO_MODEL", DEFAULT_VIDEO_MODEL)
    return values


def atomic_write_env(path: Path, values: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("# SalpX local configuration. Do not commit this file.\n")
            for key in ("SALPX_API_KEY", "SALPX_BASE_URL", "SALPX_IMAGE_MODEL", "SALPX_DRAFT_IMAGE_MODEL", "SALPX_REFINE_IMAGE_MODEL", "SALPX_VIDEO_MODEL"):
                if values.get(key):
                    output.write(f"{key}={values[key]}\n")
        os.chmod(temporary, 0o600)
        os.replace(str(temporary), str(path))
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for number in range(2, 10000):
        candidate = path.with_name(f"{path.stem}-{number}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ClientError(f"Could not choose an output path for {path.name}")


def extension_from_url(url: str, fallback: str = ".png") -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm"}
    return suffix if suffix in allowed else fallback


def download_url(url: str, target: Path, timeout: int) -> str:
    target = unique_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=timeout) as response, target.open("wb") as output:
            shutil.copyfileobj(response, output, COPY_BUFFER_SIZE)
    except (HTTPError, URLError, OSError) as error:
        if target.exists():
            target.unlink()
        raise ClientError(f"Failed to download SalpX output: {error}") from None
    return str(target.resolve())


def first_value(value: Any, keys: Iterable[str]) -> Optional[str]:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.startswith("http"):
                return candidate
        for child in value.values():
            found = first_value(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = first_value(child, keys)
            if found:
                return found
    return None


def find_task_id(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        for key in ("task_id", "taskId", "video_id", "videoId", "generation_id", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        for child in value.values():
            found = find_task_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_task_id(child)
            if found:
                return found
    return None


class SalpXClient:
    def __init__(self, api_key: str, base_url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        if not api_key:
            raise ClientError("SALPX_API_KEY is not configured")
        self.api_key = api_key
        self.base_url = normalize_base_url(base_url)
        self.timeout = timeout

    def request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, timeout: Optional[int] = None) -> Any:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": USER_AGENT,
        }
        body = None
        if payload is not None:
            # Final guard on the exact bytes sent, including calls outside the CLI.
            body = serialize_payload(payload)
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}/{path.lstrip('/')}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = response.status
        except HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            if error.code == 413:
                raise ClientError("SalpX returned HTTP 413 for a locally checked request. The upstream limit may be lower; reduce --max-request-mb or select fewer references. Do not resend the same payload.", 413) from None
            raise ClientError(self.error_message(raw, error.reason), error.code) from None
        except URLError as error:
            raise ClientError(f"SalpX API is unreachable: {error.reason}") from None
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            raise ClientError(f"SalpX returned invalid JSON (HTTP {status})", status) from None
        if status >= 400:
            raise ClientError(self.error_message(raw, f"HTTP {status}"), status)
        if isinstance(data, dict) and data.get("error"):
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise ClientError(str(message or "SalpX request failed"), status)
        return data

    @staticmethod
    def error_message(raw: str, fallback: Any) -> str:
        try:
            data = json.loads(raw)
            error = data.get("error") if isinstance(data, dict) else None
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if isinstance(error, str):
                return error
            if isinstance(data, dict) and data.get("message"):
                return str(data["message"])
        except json.JSONDecodeError:
            pass
        return str(fallback)

    def models(self) -> Dict[str, Any]:
        return self.request("GET", "/models", timeout=60)

    def generate_image(self, body: Dict[str, Any], *, edits: bool = False) -> Dict[str, Any]:
        references = body.get("images", [])
        if not isinstance(references, list):
            raise PreflightError("images must be a list of references")
        validate_reference_count(references, "single_image")
        endpoint = "/images/edits" if edits else "/images/generations"
        return self.request("POST", endpoint, payload=body, timeout=self.timeout)

    def generate_video(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.request("POST", "/videos", payload=body, timeout=self.timeout)

    def video_status(self, task_id: str) -> Dict[str, Any]:
        last: Dict[str, Any] = {}
        for path in (f"/videos/{task_id}", f"/videos/{task_id}/result", f"/videos/generations/{task_id}"):
            try:
                result = self.request("GET", path, timeout=60)
                return result if isinstance(result, dict) else {"data": result}
            except ClientError as error:
                last = {"error": str(error), "status": error.status, "endpoint": path}
                if error.status not in {404, 405}:
                    break
        return last


def wait_for_video(client: SalpXClient, task_id: str, interval: float, timeout: float) -> Dict[str, Any]:
    if interval <= 0 or timeout <= 0:
        raise ClientError("Polling interval and timeout must be greater than zero")
    deadline = time.monotonic() + timeout
    last: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = client.video_status(task_id)
        url = first_value(last, VIDEO_URL_KEYS)
        status = str(last.get("status", "")).lower()
        if url or status in {"success", "succeeded", "completed", "failed", "error", "cancelled", "canceled"}:
            return last
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
    raise ClientError(f"Timed out waiting for SalpX video task {task_id}; query it again with status")


def ratio_size(ratio: str, explicit_size: Optional[str]) -> str:
    if explicit_size:
        return explicit_size
    return RATIO_TO_SIZE.get(ratio, RATIO_TO_SIZE["1:1"])


def selected_image_model(args: argparse.Namespace, settings: Dict[str, str]) -> str:
    if getattr(args, "model", None):
        return args.model
    profile = getattr(args, "profile", "standard")
    model_key = {
        "draft": "SALPX_DRAFT_IMAGE_MODEL",
        "standard": "SALPX_IMAGE_MODEL",
        "refine": "SALPX_REFINE_IMAGE_MODEL",
    }[profile]
    return settings.get(model_key) or settings["SALPX_IMAGE_MODEL"]


def operation_prompt(args: argparse.Namespace) -> str:
    prompt = (args.prompt or "").strip()
    if getattr(args, "effect", None):
        prompt = f"{prompt} {args.effect.strip()}".strip()
    additions = {
        "background_replace": "Treat the source product as locked; change only the background and supported scene context. Do not redraw, reshape, or perspective-warp the product.",
        "single_image": "Create a product-focused ecommerce image while preserving the exact source product identity.",
        "fission": "Create one distinct ecommerce scene concept while preserving the exact source product identity.",
        "outfit": "Use the first image as the person and the second image as the garment; preserve the garment construction, material, color, trim, and printed details accurately.",
    }
    if args.operation in additions:
        prompt = f"{prompt} {additions[args.operation]}".strip()
    quality = (
        "Keep the exact source silhouette, proportions, unit count, repeated-unit consistency, material, color, finish, "
        "functional-part shape and orientation, included accessories, logo, and printed product details. "
        "Use coherent scale and perspective, believable surface contact, clean edges, physically plausible occlusion, "
        "and contact shadows matching the scene light. No duplicate or missing product, no changed slots, holes, pads, "
        "ports, buttons, seams, ends, or accessories, no warped logo or printing, and no watermark. "
        "Outside existing printing on the product, add no generated words, captions, labels, arrows, badges, panels, "
        "cards, frames, callouts, placeholder rectangles, or empty text boxes; keep any copy space as a continuous natural background."
    )
    return f"{prompt} {quality}".strip()


def save_image_outputs(response: Dict[str, Any], output_dir: Path, task_label: str, timeout: int) -> List[str]:
    outputs: List[str] = []
    data = response.get("data", []) if isinstance(response, dict) else []
    if not isinstance(data, list):
        data = [data]
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        encoded = item.get("b64_json") or item.get("b64Json")
        if isinstance(encoded, str) and encoded:
            raw = base64.b64decode(encoded)
            suffix = ".jpg" if raw.startswith(b"\xff\xd8\xff") else ".png"
            target = unique_path(output_dir / f"{task_label}-{index}{suffix}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            outputs.append(str(target.resolve()))
            continue
        url = first_value(item, IMAGE_URL_KEYS)
        if url:
            outputs.append(download_url(url, output_dir / f"{task_label}-{index}{extension_from_url(url)}", timeout))
    return outputs


def prepare_image_request(args: argparse.Namespace, settings: Dict[str, str]):
    files = list(args.file)
    validate_reference_count(files, args.operation)
    requested_count = args.count if args.count is not None else 1
    if args.operation == "fission" and args.count not in {2, 4, 6, 8}:
        raise ClientError("fission count must be one of 2, 4, 6, or 8")
    if args.operation != "fission" and requested_count < 1:
        raise ClientError("count must be greater than zero")
    model = selected_image_model(args, settings)
    base_model = model.removesuffix("-4k")
    body_base: Dict[str, Any] = {"model": model, "prompt": operation_prompt(args), "n": 1}
    if base_model in TIERED_MODELS:
        ratio_pattern = r"[1-9][0-9]*:[1-9][0-9]*"
        if not re.fullmatch(ratio_pattern, args.ratio):
            raise ClientError("--ratio must be a positive N:M ratio")
        size = (args.size or "").lower()
        sized_ratio = re.fullmatch(rf"(2k|4k):({ratio_pattern})", size)
        tier = args.resolution or (sized_ratio[1] if sized_ratio else None) or ("4k" if model.endswith("-4k") else "2k")
        if (model.endswith("-4k") and tier != "4k") or (sized_ratio and sized_ratio[1] != tier):
            raise ClientError("Conflicting model, --size and --resolution tiers")
        pixels = re.fullmatch(r"([1-9][0-9]{0,4})x([1-9][0-9]{0,4})", size)
        if pixels and max(map(int, pixels.groups())) > (3840 if tier == "4k" else 2048):
            raise ClientError("--size exceeds the selected model tier; for 4K use --resolution 4k")
        if not size or re.fullmatch(ratio_pattern, size):
            size = f"{tier}:{size or args.ratio}"
        elif not (sized_ratio or pixels or size == "auto"):
            raise ClientError("--size must be auto, WxH, N:M, or 2k:/4k: followed by N:M")
        body_base.update(model=base_model + ("-4k" if tier == "4k" else ""), size=size, quality=args.quality or "max")
    else:
        if args.resolution:
            raise ClientError("--resolution requires a tiered GPT Image 2.5/2.6 model")
        body_base["size"] = ratio_size(args.ratio, args.size)
        if args.quality:
            body_base["quality"] = args.quality
    return prepare_payload(body_base, files, limits_from_args(args), operation=args.operation, prepared_dir=getattr(args, "prepared_dir", None))


def limits_from_args(args: argparse.Namespace) -> ImageLimits:
    return ImageLimits(
        per_image_bytes=mib_bytes(getattr(args, "max_reference_mb", 2)),
        total_image_bytes=mib_bytes(getattr(args, "max_reference_total_mb", 20)),
        request_bytes=mib_bytes(getattr(args, "max_request_mb", 32)),
        max_edge=getattr(args, "reference_max_edge", 2560),
    )


def create_image(client: SalpXClient, args: argparse.Namespace, settings: Dict[str, str]) -> Dict[str, Any]:
    started = time.monotonic()
    body, preflight = prepare_image_request(args, settings)
    # A report goes to stderr before the paid request; never log the encoded body.
    print(json.dumps({"event": "preflight_passed", **preflight}, ensure_ascii=False), file=os.sys.stderr)
    requested_count = args.count if args.count is not None else 1
    output_dir = args.download_dir or Path("./outputs")
    downloaded: List[str] = []
    endpoint = "/images/generations"
    for index in range(1, requested_count + 1):
        response = client.generate_image(body, edits=False)
        label = args.output_prefix or f"generated-{args.operation}"
        if requested_count > 1:
            label = f"{label}-{index:02d}"
        downloaded.extend(save_image_outputs(response, output_dir, label, args.request_timeout))
    if not downloaded:
        raise ClientError("SalpX returned no image URL or b64_json output")
    return {"ok": True, "provider": "salpx", "operation": args.operation, "profile": getattr(args, "profile", "standard"), "model": body["model"], "endpoint": endpoint, "downloaded": downloaded, "elapsed_seconds": round(time.monotonic() - started, 2), "retry_count": 0, "preflight": preflight}


def prepare_video_request(args: argparse.Namespace, settings: Dict[str, str]):
    if args.resolution or args.quality:
        raise ClientError("--resolution and --quality are image-only options")
    validate_reference_count(list(args.file), "video")
    if args.duration not in {5, 10}:
        raise ClientError("video duration must be 5 or 10 seconds")
    body: Dict[str, Any] = {
        "model": args.model or settings["SALPX_VIDEO_MODEL"],
        "prompt": (args.prompt or "").strip() or "Product-focused ecommerce video; preserve product identity exactly.",
        "aspect_ratio": args.ratio,
        "size": args.size or ("720x1280" if args.ratio == "9:16" else ratio_size(args.ratio, None)),
        "duration": args.duration,
    }
    return prepare_payload(body, list(args.file), limits_from_args(args), operation="video", prepared_dir=getattr(args, "prepared_dir", None))


def create_video(client: SalpXClient, args: argparse.Namespace, settings: Dict[str, str]) -> Dict[str, Any]:
    body, preflight = prepare_video_request(args, settings)
    print(json.dumps({"event": "preflight_passed", **preflight}, ensure_ascii=False), file=os.sys.stderr)
    response = client.generate_video(body)
    task_id = find_task_id(response)
    result = {"provider": "salpx", "operation": "video", "model": body["model"], "task_id": task_id, "preflight": preflight}
    url = first_value(response, VIDEO_URL_KEYS)
    if not url and task_id and not args.no_wait:
        response = wait_for_video(client, task_id, args.interval, args.timeout)
        url = first_value(response, VIDEO_URL_KEYS)
        result["status_response"] = {"status": response.get("status"), "task_id": task_id}
    if not url:
        result["ok"] = bool(task_id)
        return result
    output_dir = args.download_dir or Path("./outputs")
    result.update({"ok": True, "downloaded": [download_url(url, output_dir / f"salpx-video{extension_from_url(url, '.mp4')}", args.request_timeout)]})
    return result


def configure(args: argparse.Namespace) -> Dict[str, Any]:
    key = args.api_key.strip() if args.api_key else ""
    if not key and args.api_key_stdin:
        key = os.sys.stdin.readline().strip()
    if not key:
        key = getpass.getpass("SalpX API key: ").strip()
    if not key:
        raise ClientError("SalpX API key is empty")
    path = (args.env_file or DEFAULT_ENV_FILE).expanduser().resolve()
    base_url = normalize_base_url(args.base_url or DEFAULT_BASE_URL)
    image_model = args.image_model or DEFAULT_IMAGE_MODEL
    atomic_write_env(path, {"SALPX_API_KEY": key, "SALPX_BASE_URL": base_url, "SALPX_IMAGE_MODEL": image_model,
                            "SALPX_DRAFT_IMAGE_MODEL": args.draft_model or image_model,
                            "SALPX_REFINE_IMAGE_MODEL": args.refine_model or image_model,
                            "SALPX_VIDEO_MODEL": args.video_model or DEFAULT_VIDEO_MODEL})
    return {"configured": True, "provider": "salpx", "envFile": str(path), "baseUrl": base_url}


def init_project(args: argparse.Namespace) -> Dict[str, Any]:
    """Create or reuse explicitly chosen folders only; never move user images."""
    name = args.product_name.strip()
    if not name or name in {".", ".."} or any(c in name for c in "/\\") or any(ord(c) < 32 for c in name):
        raise ClientError("product-name must be a single folder name, not a path")
    root = args.project_dir.expanduser().resolve()
    product = root / name
    for path in (root, product):
        if path.exists() and not path.is_dir():
            raise ClientError(f"Project path is occupied by a file: {path}")
        if path.is_symlink():
            raise ClientError(f"Project child folder must not be a symlink: {path}")
    root_created, product_created = not root.exists(), not product.exists()
    product.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "version": SKILL_VERSION, "project_dir": str(root),
            "product_dir": str(product), "project_created": root_created,
            "product_created": product_created, "originals_moved": False,
            "source_and_output_same_folder": True, "submitted": False}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SalpX ecommerce image editing client")
    parser.add_argument("--version", action="version", version=SKILL_VERSION)
    parser.add_argument("--env-file", type=Path, help="SalpX env file; defaults to cwd/.env or ~/.config/salpx/credentials.env")
    parser.add_argument("--request-timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    project = subparsers.add_parser("init-project", help="Create/reuse an explicit project and product folder locally; never move originals")
    project.add_argument("--project-dir", required=True, type=Path)
    project.add_argument("--product-name", default="商品01")
    configure_parser = subparsers.add_parser("configure", help="Save SalpX API settings in a user-only env file")
    configure_parser.add_argument("--env-file", type=Path)
    configure_parser.add_argument("--api-key", help=argparse.SUPPRESS)
    configure_parser.add_argument("--api-key-stdin", action="store_true", help="Read the SalpX key from stdin")
    configure_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    configure_parser.add_argument("--image-model", default=DEFAULT_IMAGE_MODEL)
    configure_parser.add_argument("--draft-model", help="Optional faster SalpX image model for draft composition")
    configure_parser.add_argument("--refine-model", help="Optional higher-quality SalpX image model for local refinement")
    configure_parser.add_argument("--video-model", default=DEFAULT_VIDEO_MODEL)
    subparsers.add_parser("capabilities", help="List models available through SalpX")
    status = subparsers.add_parser("status", help="Query a SalpX video task")
    status.add_argument("task_id")
    wait = subparsers.add_parser("wait", help="Wait for a SalpX video task")
    wait.add_argument("task_id")
    wait.add_argument("--interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    wait.add_argument("--timeout", type=float, default=DEFAULT_POLL_TIMEOUT_SECONDS)
    create_options = argparse.ArgumentParser(add_help=False)
    add_create_options(create_options)
    subparsers.add_parser("create", parents=[create_options], help="Preprocess references, check body size, then create through SalpX")
    subparsers.add_parser("preflight", parents=[create_options], help="Compress and check locally; no API key or network required")
    return parser


def add_create_options(create: argparse.ArgumentParser) -> None:
    create.add_argument("--operation", required=True, choices=["single_image", "outfit", "background_replace", "fission", "video"])
    create.add_argument("--file", action="append", default=[], type=Path)
    create.add_argument("--prompt")
    create.add_argument("--model")
    create.add_argument("--profile", choices=["draft", "standard", "refine"], default="standard", help="Configured model profile; --model overrides it")
    create.add_argument("--ratio", default="1:1")
    create.add_argument("--size", help="覆盖比例预设，例如 4k:16:9 或 1536x1024")
    create.add_argument("--resolution", type=str.lower, choices=["2k", "4k"], help="图片档位，默认 2k；4k 自动选择 -4k 型号")
    create.add_argument("--quality", type=str.lower, choices=["low", "medium", "high", "max"], help="图片画质，GPT Image 2.5/2.6 默认 max")
    create.add_argument("--count", type=int)
    create.add_argument("--effect")
    create.add_argument("--duration", type=int)
    create.add_argument("--download-dir", type=Path)
    create.add_argument("--output-prefix", help="Output filename prefix; use a distinct prefix when saving beside the source image")
    create.add_argument("--no-wait", action="store_true")
    create.add_argument("--dry-run", action="store_true", help="Local preflight only; never submit generation")
    create.add_argument("--prepared-dir", type=Path, help="Optionally save reference copies in a new isolated subfolder for local inspection")
    create.add_argument("--max-reference-mb", type=float, default=2, help="Per-reference limit in MiB (default 2, ceiling 5)")
    create.add_argument("--max-reference-total-mb", type=float, default=20, help="Combined prepared references in MiB (default/ceiling 20)")
    create.add_argument("--max-request-mb", type=float, default=32, help="Full serialized request in MiB (default/ceiling 32; lower for a smaller upstream limit)")
    create.add_argument("--reference-max-edge", type=int, default=2560, help="Reference long edge in pixels (1280..4096, default 2560); never crop or upscale")
    create.add_argument("--interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    create.add_argument("--timeout", type=float, default=DEFAULT_POLL_TIMEOUT_SECONDS)


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init-project":
            print(json.dumps(init_project(args), ensure_ascii=False, indent=2))
            return 0
        if args.command == "configure":
            print(json.dumps(configure(args), ensure_ascii=False, indent=2))
            return 0
        settings = settings_from_env(args.env_file)
        if args.command == "preflight" or (args.command == "create" and args.dry_run):
            prepare = prepare_video_request if args.operation == "video" else prepare_image_request
            body, report = prepare(args, settings)
            result = {"ok": True, "provider": "salpx", "operation": args.operation,
                      "profile": getattr(args, "profile", "standard"), "model": body["model"], "submitted": False, "preflight": report}
            if args.operation != "video":
                result.update(size=body["size"], quality=body.get("quality"), requests=args.count or 1)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        client = SalpXClient(settings.get("SALPX_API_KEY", ""), settings["SALPX_BASE_URL"], args.request_timeout)
        if args.command == "capabilities":
            models = client.models()
            ids = [item.get("id") for item in models.get("data", []) if isinstance(item, dict) and item.get("id")]
            result = {"provider": "salpx", "baseUrl": client.base_url,
                      "imageModel": settings["SALPX_IMAGE_MODEL"],
                      "imageProfiles": {"draft": settings["SALPX_DRAFT_IMAGE_MODEL"], "standard": settings["SALPX_IMAGE_MODEL"], "refine": settings["SALPX_REFINE_IMAGE_MODEL"]},
                      "videoModel": settings["SALPX_VIDEO_MODEL"], "models": ids}
        elif args.command == "status":
            result = client.video_status(args.task_id)
        elif args.command == "wait":
            result = wait_for_video(client, args.task_id, args.interval, args.timeout)
        elif args.command == "create":
            result = create_video(client, args, settings) if args.operation == "video" else create_image(client, args, settings)
        else:
            raise ClientError(f"Unknown command: {args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ClientError, PreflightError, OSError) as error:
        print(json.dumps({"error": str(error), "status": getattr(error, "status", None), "provider": "salpx"}, ensure_ascii=False), file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
