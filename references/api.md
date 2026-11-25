# SalpX image/video API reference — v1.9

Use the bundled client's request format. The default base URL is `https://www.salpx.com/v1`; the client appends `/v1` if missing. Paths below are relative to that base.

## Configuration and discovery

Use `configure` to enter the key at a hidden terminal prompt. Never commit or print the real key. See [salpx.env.example](salpx.env.example) for the six supported settings. At runtime select one file: global `--env-file PATH` before the subcommand, then `SALPX_ENV_FILE`, then the working directory's `.env`, then `~/.config/salpx/credentials.env`. Nonempty process environment settings override that file. To **write** a different credentials file, use `configure --env-file PATH`.

`--model` overrides the image profile. `--profile standard` (default) uses `SALPX_IMAGE_MODEL`; `draft` and `refine` use `SALPX_DRAFT_IMAGE_MODEL` and `SALPX_REFINE_IMAGE_MODEL`, respectively. Both inherit the standard model if unset. The built-in image default is `gpt-image-2.6-sunburst`; video uses `--model` or `SALPX_VIDEO_MODEL` (default `omni_flash`).

API requests use `Authorization: Bearer {SALPX_API_KEY}` and `Accept: application/json`; requests with a body use `Content-Type: application/json`. `capabilities` calls `GET /models` and reports configured profiles and available IDs. A catalog read does not test generation, account balance, supported sizes, or upstream reference capacity.

## Image generation

The CLI sends both text-only and reference-image requests to `POST /images/generations`. It does not upload files separately, send multipart data, or select `/images/edits` for background replacement. Example default request (prompt abbreviated):

```json
{
  "model": "gpt-image-2.6-sunburst",
  "prompt": "Product-focused ecommerce image; preserve product identity exactly.",
  "size": "2k:1:1",
  "quality": "max",
  "n": 1
}
```

With `--resolution 4k --ratio 4:5` and one reference, the same endpoint receives:

```json
{
  "model": "gpt-image-2.6-sunburst-4k",
  "prompt": "Change only the background; preserve the product exactly.",
  "size": "4k:4:5",
  "quality": "max",
  "n": 1,
  "images": ["data:image/png;base64,..."]
}
```

`images` is an ordered array of preprocessed data URIs, omitted when no references are supplied. The client checks the exact UTF-8 JSON body: defaults are 2 MiB per prepared image, 20 MiB combined, and 32 MiB including prompt, Base64 and JSON overhead. `--max-request-mb` can lower that last bound. See [image-inputs.md](image-inputs.md) for preprocessing and isolated `--prepared-dir` copies. For identity-sensitive work, use the returned scene plate with the [v1.8 compositing workflow](production-v18.md); a generated product is not the locked original.

### Image size and quality

- Tiered base models: `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst`, `gpt-image-2.6-flare`, `gpt-image-2.6-sunburst`. Use `--resolution 2k|4k`. The default is `2k` unless the model ends in `-4k` or `--size` specifies the 4K tier. A 4K request sends the base ID plus `-4k`. Conflicting explicit tiers are rejected locally.
- `--ratio` accepts a positive `N:M` (default `1:1`). Without `--size`, send `tier:N:M`. `--size` overrides framing: `N:M` gets the selected tier prefix; `2k:N:M`, `4k:N:M`, `auto`, or `WxH` are sent as specified (lowercase). For pixel sizes, the longest side must not exceed 2048 for 2K or 3840 for 4K. The tier is not a guarantee of exact delivery dimensions.
- `--quality` accepts `low`, `medium`, `high`, or `max`; default `max` for tiered models. For other image models omit `--resolution`; quality is sent only if specified. An explicit `--size` passes through, otherwise the client uses the pixel presets below (unknown ratio falls back to `1024x1024`).

| Ratio | Non-tiered image size | Ratio | Non-tiered image size |
| --- | --- | --- | --- |
| `1:1` | `1024x1024` | `9:16` | `1024x1792` |
| `4:5` | `1024x1280` | `16:9` | `1792x1024` |
| `3:4` | `1024x1365` | `3:2` | `1536x1024` |
| `2:3` | `1024x1536` | `4:3` | `1365x1024` |

### Operations and request counts

Operation names are CLI routing labels, not API fields. Image operations share the same endpoint and send `n=1` per request.

| Operation | References | Output count |
| --- | --- | --- |
| `single_image` | 0–9 | Positive `--count`, default 1 |
| `background_replace` | 1–9; product first, then scene/details | Positive `--count`, default 1 |
| `outfit` | 2–9; person first, garment second, then details | Positive `--count`, default 1 |
| `fission` | 0–9 | Explicit `--count` of 2, 4, 6, or 8 |

`--count N` submits N sequential requests using the same prompt and prepared references; `--effect` is prompt text, not an API field. Use separate prompts for distinct planned scenes. `preflight` and `create --dry-run` are local, require no key or network, and for images report `model`, `size`, `quality`, `requests` and `submitted: false`. On generation, the client downloads `data[].url` or decodes `data[].b64_json` into `--download-dir` (default `./outputs`).

## Video generation

`POST /videos` takes exactly one preprocessed first frame in the singular `image` field. Specify `--duration 5` or `--duration 10`; `--resolution` and `--quality` are rejected. With `--ratio 9:16`, size defaults to `720x1280`; an explicit `--size` overrides it.

```json
{
  "model": "omni_flash",
  "prompt": "Product-focused 10-second vertical ecommerce video; preserve product identity.",
  "image": "data:image/png;base64,...",
  "aspect_ratio": "9:16",
  "size": "720x1280",
  "duration": 10
}
```

If the submission returns a task ID but no video URL, `create` polls unless `--no-wait` was set. `status` queries the task once; `wait` polls it (default interval 5 s, timeout 900 s). Start with `GET /videos/{task_id}`; on HTTP 404/405 try `/videos/{task_id}/result`, then `/videos/generations/{task_id}`. Recognized URL keys include `url`, `video_url`, `videoUrl`, `download_url`, `output_url`, and `result_url`. A task ID alone is not a completed download.

## Error handling

- `401`: verify or reconfigure the key. `403`: report the permission or account restriction.
- `404`: report an unavailable task or endpoint; do not assume success.
- Local preflight failure: fix the count, image, size/tier, dependency or budget before submitting.
- `413`: do not resend the same body. Reduce the request budget or reference set. A Codex incoming-message limit occurs before this client runs and cannot be fixed by outbound preflight.
- `429`: wait. For a timeout or `5xx` after submission, preserve the uncertain state and check the original task if possible before retrying; do not create duplicate paid jobs.
- Empty image output or missing video URL: report the actual response or task state instead of claiming delivery.
