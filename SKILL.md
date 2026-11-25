---
name: ecommerce-image-editing
description: Plan, edit, and generate Amazon/ecommerce product image sets through SalpX, with image-led proposals, model-tiered production, product-fidelity controls, scene integration, local preflight and QA, main and secondary images, A+ modules, lifestyle scenes, outfit composites, local compression and request preflight for up to 9 references, project-folder setup, and optional product videos. Use when the user invokes 电商改图, supplies a product image, or wants ecommerce image directions; do not use for generic image generation without a product workflow.
agent_created: true
metadata:
  version: "v1.9"
---

# 电商改图

Use the bundled SalpX client to turn product images into controlled ecommerce assets. Codex must be able to plan the images and build complete prompts from the product itself; the user does not need to supply a finished prompt. The client reads SalpX environment configuration, submits OpenAI-compatible image/video requests, polls video tasks when needed, and downloads completed media.

- Read [references/first-use.md](references/first-use.md) at the first Skill invocation in a conversation: show the v1.9 changes, full capability menu, SalpX setup reminder, and project-folder choice.
- Read [references/image-inputs.md](references/image-inputs.md) before processing reference files, handling oversized requests, or preparing a batch.
- Read [references/project-setup.md](references/project-setup.md) when choosing, creating, or organizing a project directory.
- Read [references/creative-planning.md](references/creative-planning.md) when the user supplies only images, asks for ideas, or wants a coordinated main/secondary/A+ set.
- Read [references/amazon-image-rules.md](references/amazon-image-rules.md) before delivering marketplace-ready images or a multi-image set.
- Read [references/quality-gates.md](references/quality-gates.md) before a batch, a claimed final delivery, or a revision request.
- Read [references/production-v18.md](references/production-v18.md) for material-sensitive cutouts, original-pixel compositing, feature evidence, scene compositing, A/B variants, delivery manifests, or measured acceptance.
- Read [references/original-pixel-compositing.md](references/original-pixel-compositing.md) whenever product identity, packaging, printed detail, transparent edges, holes, thin rods, or material fidelity is important.
- Read [references/api.md](references/api.md) only when exact endpoints, model fields, reference-image limits, or error handling are needed.

## What this skill is for

Route the request to the narrowest operation that preserves the source product:

- `plan`: inspect the product and propose distinct image directions without calling a paid generation API. Use this when the user gives an image without a prompt, asks “怎么做图”, or wants Codex to recommend a complete image set.
- `background_replace`: use 1–9 references, product first, followed by explicitly identified scene/detail references; instruct SalpX to change only the background/context. The client sends reference files through `/images/generations`; actual reference support depends on the selected upstream model/channel.
- `single_image`: create a product-focused ecommerce image from a prompt, optionally with up to 9 source/detail references.
- `fission`: specify `--count 2`, `4`, `6`, or `8`. Each output is a separate `/images/generations` request with `n=1`, using the same prompt and references. Use separate prompts for individually directed scenes.
- `outfit`: pass person first and garment second, optionally followed by detail/pose/scene references, up to 9 total, with explicit preservation instructions.
- `video`: optional product-video extension through SalpX `/videos`; use only when the user explicitly asks for video.

The default image model is `gpt-image-2.6-sunburst`, configurable through `SALPX_IMAGE_MODEL`. With this default, use `2k` and `quality=max` unless specified otherwise. Set `--resolution 4k` to select `gpt-image-2.6-sunburst-4k`; use `--quality low|medium|high|max` for images only. A production run has three stages: fast draft, targeted refinement, and final QA. Draft/refinement model IDs are opt-in configuration values; never invent a model ID or claim a speed target without measuring the run. A 20-minute target is an internal service-level goal, not a guarantee. Do not claim that a model can do precise text/layout design, 3D reconstruction, packaging redesign, or factual product-detail correction unless the returned result visibly supports it. Generate clean base photography first and use deterministic composition for final text, arrows, dimensions, icons, and comparison labels. Treat model-rendered typography and A+ layouts as drafts.

## First-session onboarding — v1.9

At the first invocation in each new conversation, read and use the complete Chinese template in [references/first-use.md](references/first-use.md), before paid generation. Include all four parts: what changed in v1.9; all current capabilities; SalpX relay setup; whether to create or reuse a project directory. Show it once per conversation, not on every follow-up. If this conversation already saw an older version, announce the v1.9 additions once without repeating the whole menu.

Do not present a missing configuration as a successful connection, ask users to paste keys into chat, or create directories just because the Skill was invoked. If they ask to create a directory or authorize automatic setup, use `init-project`; if they already supplied a suitable product folder, reuse it and state the path. Keep useful inspection/planning moving while an optional folder choice is pending. A concrete generation request does not require a second prompt-writing exercise.

## Reference preprocessing — mandatory

All `create --file` calls automatically compress copies and check the complete UTF-8 JSON body before any generation request. Image operations allow at most **9** references; a video still takes exactly one first frame. Never silently drop excess references or append conversation-history images or generated outputs.

Defaults: **2 MiB per prepared reference, 20 MiB combined references, 32 MiB full request**, including Base64, prompt, and JSON overhead. Preserve source files, aspect ratio, orientation, and alpha; inspect prepared copies for readable product details. If the detail floor cannot be met, stop locally rather than submit oversized or unusable images. These are local safety limits, not promises about an upstream channel's capacity.

Use `preflight` or `create --dry-run` for a no-key, no-network check; use `--prepared-dir` to save inspectable copies. See [references/image-inputs.md](references/image-inputs.md) for dependency setup, exact limits, and errors. This protects outbound SalpX requests only: if Codex rejects the incoming conversation before the Skill runs, use a new task with local file paths. The Skill cannot remove or resize already-submitted chat history.

## Production planning and model strategy

When the user gives only a product image or asks for ideas, inspect the product and propose 3–5 meaningfully different directions before any paid generation. Each direction must state the image role, buyer question or supported selling point, shot/composition, product-preservation method, copy-space strategy, ratio, and fidelity risk. Recommend one direction and let the user select; if the user says “直接生成”, choose the safest recommended direction and continue.

For a set, write a short selling-point script before prompts: one buyer question per image, the evidence needed to answer it, the approved factual claim, and the later layout requirement. Use the cheapest configured model that can answer the question. Start with a fast draft when composition is uncertain, refine only the failed region or product interaction, and reserve the configured final model for accepted compositions. Keep a run record with model, elapsed time, retry count, output count, and QA status. If a run approaches 20 minutes, stop creating new paid jobs, return the intermediate result and a concrete revision path, and preserve any task ID or output paths.

For a revision request, classify it before generating: background/lighting, local object or text, product geometry, or new concept. Prefer a local mask or deterministic composite for the first two. A geometry change requires a new source view or a clearly labeled concept draft. Never rerun the whole set when only one region failed.

For a complete main/secondary/A+ set, build the full storyboard before generating individual images. Assign one job to each slot and make the set answer different buyer questions. Two slots are duplicates when they use substantially the same product angle, crop, background, and story while changing only the copy. Main images and A+ modules must not reuse the same finished base image unless the user explicitly asks for reuse.

### Production contract retained from v1.8

For a set, create a run manifest using [references/production-v18.md](references/production-v18.md). Freeze the requested counts **by role** (main/secondary/A+), approved claims and source views. Run `production_guard.py plan` before generation, `next --slot ID` before each paid submission, and `delivery` before claiming completion. These are local gates, not a job scheduler: record actual submissions immediately, retain IDs and ambiguous states, and do not claim the CLI automatically enforces a gate when invoked without a manifest. An A+ storyboard or prompt is not an A+ file. Explicit A/B variants are extra deliverables with one declared changed variable; they cannot replace missing normal slots.

For fidelity-sensitive work, lock the product pixels before calling SalpX: inspect the source, create a local cutout and identity hash, independently review the matte on black/white/magenta/green/checkerboard, and ask SalpX for a continuous text-free scene plate with the product region excluded or neutralized. Composite the unwarped original RGB pixels locally; generated pixels may supply the scene, shadow, reflection, or surrounding occlusion only. If the requested camera/support plane cannot fit the source product, change the scene or request another source view instead of perspective-warping the product.

Every final slot must pass its exact target dimensions, decodability, duplicate check, current output SHA256, and named visual review. Add text, arrows, dimensions, badges, and comparison marks after the base image with deterministic layout. Do not accept model-created text boxes or layout cards as evidence. Keep paid submissions bounded to the initial request plus one retry per slot; preserve an ambiguous task state and query it before any new paid request.

Use a **text-hidden evidence test**: without the headline, the frame must still show the detail, mechanism, scale, actual interaction or supported process that answers its buyer question. Resizing the same white-background image and adding copy is not a completed feature set. If evidence is missing, choose a visible supported claim or ask for the specific missing view/test; do not invent four-layer fibers, tensile strength, compatibility or material cross-sections.

Approve one high-risk representative crop/interaction before expanding a batch. Freeze reusable approved masks, source crops and typography, not one finished scene pasted into every slot. Build the background around the source camera/support/mounting geometry. For flexible or worn products, unloaded cutouts do not prove a loaded or installed shape; request a real use photo when interaction cannot be shown faithfully. A shadow alone does not establish scene integration.

## Ecommerce preservation rules

Before submitting a job, create a compact product identity sheet from the supplied references: category, silhouette, proportions, exact unit count, repeated-unit consistency, material/finish, color, functional parts, orientation of ends/ports/pads/slots, visible labels/logo, included accessories, and unknowns. For multiple views, map which reference proves each fact. Keep confirmed facts in the prompt as preservation requirements; never promote an inference to a fact.

- Do not invent features, certifications, dimensions, ingredients, warranty claims, ratings, safety claims, or included parts.
- Do not change the product into a different model, add/remove functional components, or make a non-waterproof product look waterproof.
- Do not use a lifestyle scene to imply a use case the product cannot support.
- If the source image does not make a product fact legible, mark it as unknown rather than guessing.
- For a marketplace main image, prefer a clean, uncluttered product presentation and no decorative copy; if the user asks for text overlays, label the result as a draft and preserve exact copy separately.
- If a requested edit would materially alter product identity, explain the conflict and offer a safer scene/background or crop-preserving alternative.

Use this preservation hierarchy:

1. **Original-pixel composite:** default for marketplace main images, background replacement, packaging, dimension-sensitive products, repeated-unit sets, and products whose slots, end pieces, ports, or printed details must be exact. Cut out the original product, generate the background separately, then composite it without warping the product. Add integration effects to the surroundings—contact shadow, surface reflection, or local occlusion—not by redrawing the product.
2. **Constrained reference edit:** use only when the desired interaction cannot be achieved by compositing and the output can be compared against all references.
3. **Concept draft:** use when exact geometry cannot be preserved. Label it clearly; do not deliver an AI-redrawn product as a finished asset.

If the source camera angle cannot physically fit the requested scene, choose a compatible scene or ask for another view. Do not perspective-warp the product merely to force it into the scene.

**Do not equate white pixels with background.** Metallic highlights, white paper/plastic, translucent edges, mesh and actual holes need different masks. Inspect the matte on black, white and a high-contrast colored background, plus original-vs-composite close-ups. Where certain opaque foreground/open holes can be independently marked, run `matte_guard.py`; it detects loss/filled holes in those marked regions, not the whole silhouette. Never derive the protected foreground from the same alpha and call that an independent check. Any lost reflection, pinhole, chipped corner or clipped thin rod blocks expansion. Missing a reliable segmentation/reference is a reason to return a draft or request material, not to blindly flood-remove all bright pixels.

Reject an output rather than deliver it when the count changes; identical units become different lengths; a functional end, pad, hole, wave, slot, port, button, seam, or accessory changes orientation or shape; printed details mutate; the product is placed in a physically impossible way; or the product has been replaced by a look-alike. After one failed paid retry for the same concept, switch to original-pixel compositing, request a better reference, or stop—do not keep buying random rerolls.

These are generation constraints, not a guarantee of current marketplace approval. If the user asks for compliance certification or current marketplace-policy verification, perform that as a separate current-policy check.

## Prompt construction

Translate a vague request into these parts; do not merely translate or repeat the user's words:

1. **Product lock:** what must remain identical, based only on the provided source image and user facts.
2. **Image job:** intended role and the one buyer question this image should answer.
3. **Scene and composition:** background, support surface, camera distance, camera angle, crop, interaction, lighting direction, depth of field, and copy-safe negative space.
4. **Commercial intent:** the customer/use context supported by the product, without adding unsupported claims.
5. **Integration controls:** consistent perspective and scale, believable surface contact, natural contact shadow, matching light direction, edge quality, and physically plausible occlusion.
6. **Negative controls:** no extra or missing units, no altered geometry, no duplicate product, no warped logo/printing, no extra accessories, no watermark, no generated words, no labels, no arrows, no badges, no cards, and no empty white text boxes unless explicitly required.

By default, ask SalpX for a continuous text-free base photograph with clean negative space. When copy is needed, preserve the exact copy separately and add it after image generation with deterministic typography/layout. Never use “space for text” alone; models may turn it into an empty box. Specify “natural continuous background with uncluttered negative space; no panels, frames, cards, rectangles, callouts, or placeholder boxes.”

If the user has not specified the image role, infer one only when the request is unambiguous; otherwise choose a neutral product-focused scene and state the assumption in the result summary.

## SalpX configuration

The client uses the SalpX OpenAI-compatible base URL. The default is `https://www.salpx.com/v1`; a URL without `/v1` is normalized automatically. Configure the following values through the shell, a project `.env`, or the client’s user-only configuration file:

```bash
SALPX_API_KEY=your-key
SALPX_BASE_URL=https://www.salpx.com/v1
SALPX_IMAGE_MODEL=gpt-image-2.6-sunburst
SALPX_VIDEO_MODEL=omni_flash
```

Never put a real key in Skill source, prompt text, generated artifacts, JSON result files, version control, or normal responses. If the key is missing, guide the user to `configure` and its hidden terminal prompt; do not ask them to paste the key into chat or put it in command arguments. The client stores a user-only `~/.config/salpx/credentials.env` file when `configure` is used. Only pass protected stdin when the user has supplied it through a suitable secure mechanism.

```bash
python3 scripts/salpx_image_client.py configure
python3 scripts/salpx_image_client.py capabilities
```

`capabilities` queries SalpX `/models` and reports configured model names plus the available model IDs. A successful catalog read is not a nine-reference generation test, an account-balance check, or proof that all requested sizes are supported.

## Workflow

1. On first use, give the v1.9 introduction, SalpX reminder, and project-directory choice. Check the local input list/count and prepare bounded inspection copies; inspect relevant originals locally for exact detail and create the product identity sheet. Do not embed full-size image bytes in tool logs or use screen capture/browser cookies.
2. If the user supplied only images, asks for ideas, or requests a full set, follow [references/creative-planning.md](references/creative-planning.md) and prepare the storyboard before generation.
3. Decide the image role, selling-point evidence, model profile, narrowest operation, preservation method, text strategy, and distinct job of every output.
4. For generation, verify configuration/model availability with `capabilities`, without treating the catalog as proof of upstream reference capacity. Run local `preflight` with the intended files, prompt, operation, and limits; inspect prepared references when resized/compressed. Planning, preflight, project initialization, and local QA do not need a key or network.
5. Use `create --file` to automatically preprocess references and check the exact serialized body before sending data URIs. For strict background replacement, packaging, dimension-sensitive products, or a known product-fidelity failure, generate only a scene plate through SalpX and composite the locked **original** product pixels locally; never use the generated product region as the final asset and never replace the original product with a compressed reference copy. For folder batches, use the same source/output product folder and a distinct `generated-...` prefix. For arbitrary output counts such as 3, 5, or 6, `single_image` and `background_replace --count N` send one image request at a time, reusing only the current checked reference group; they never accumulate six groups or history. Give separate prompts/storyboards when different poses/scenes are required; `--count` alone does not guarantee distinct concepts.
6. Add final text, arrows, dimensions, icons, and panels separately from the model-generated base image. Use only exact user-supplied or verified facts.
7. Wait for video completion by default. On timeout, retain the SalpX task ID and use `status` or `wait` instead of resubmitting a paid job.
8. Run local file QA (`draft` until visual review), material matte checks where applicable, then compare each image to every relevant reference and review the whole set together as a contact sheet. Bind the observed file hash in `review.output_sha256` only after looking at that version; changed files require fresh QA and fresh visual review, not an automatic hash refresh. Run `production_guard.py delivery` to reconcile role counts, actual files, output hashes, sizes and named visual reviews. Apply [references/amazon-image-rules.md](references/amazon-image-rules.md); block identity errors, random text/boxes, impossible placement, and duplicate A+ or main-image concepts. A failed or partial set must be reported with exact missing/blocked slots, not “全部完成”.
9. Report the absolute output path, provider, model/profile, operation, elapsed time, retries, preservation method, prompt assumptions, QA status, and unresolved risks. Never label an unverified AI redraw as ready to publish.

For `outfit`, file order is person then garment, followed by labeled details. For `background_replace`, file order is subject then clearly labeled scene/detail references. The local client supports up to nine image references, subject to the selected upstream model/channel's actual limits.

## Commands

```bash
python3 scripts/salpx_image_client.py --version
python3 scripts/salpx_image_client.py init-project --project-dir ./my-product-project --product-name product-01
python3 scripts/salpx_image_client.py preflight --operation single_image --file product.png --file detail.jpg --prepared-dir ./my-product-project/.salpx-prepared
python3 scripts/salpx_image_client.py create --dry-run --operation fission --file product.png --count 6 --resolution 4k --ratio 4:5 --quality high
python3 scripts/salpx_image_client.py capabilities
python3 scripts/salpx_image_client.py create --operation background_replace --file product.png --file scene.jpg --ratio 1:1 --prompt "Clean ecommerce lifestyle scene" --download-dir ./outputs
python3 scripts/salpx_image_client.py create --operation single_image --file product.png --ratio 4:5 --prompt "Product-focused secondary image" --download-dir ./outputs
python3 scripts/salpx_image_client.py create --operation single_image --file product.png --ratio 4:5 --prompt "Product-focused secondary image" --download-dir ./product-folder --output-prefix generated-01
python3 scripts/salpx_image_client.py create --operation single_image --file product.png --count 5 --ratio 1:1 --prompt "Amazon main image and US home lifestyle scenes" --download-dir ./product-folder --output-prefix generated
python3 scripts/salpx_image_client.py create --operation fission --file product.png --count 4 --effect "four distinct ecommerce scene concepts" --ratio 1:1 --download-dir ./outputs
python3 scripts/salpx_image_client.py status TASK-ABC123DEF456
python3 scripts/salpx_image_client.py wait TASK-ABC123DEF456
```

The current client treats `--effect` as part of the fission prompt concept; if an explicit effect field is required by a future SalpX model, read the live model documentation before adding it. Use `--no-wait` only when the user wants asynchronous submission.

## Batch output layout

Keep each product's source image and generated images in one folder. Never overwrite the source; use descriptive prefixes such as `generated-01-standing`, `generated-02-walking`, and `generated-03-seated`.

Ask whether to create a project folder when none is specified; honor “直接创建/帮我安排” with a safe, announced new path. `init-project` creates/reuses a chosen project and product folder without moving images. Follow [references/project-setup.md](references/project-setup.md). Keep optional preprocessing copies in the project-level `.salpx-prepared/` directory; freeze the original input list before a batch and exclude `generated-*`, `.salpx-prepared/`, `salpx-prepared-*`, and other output folders so subsequent runs do not ingest their own results.

```text
product-folder/
├── source.png
├── generated-01-standing-1.png
├── generated-02-walking-1.png
└── generated-03-seated-1.png
```

## Output and failure handling

Return only media relevant to the request and local `downloaded` paths. Never relay saved credentials or raw request headers.

- `401`: ask the user to verify or reconfigure `SALPX_API_KEY`.
- `403`: report the denied permission or account restriction; do not claim a successful generation.
- `404` on a task: report that the task is unavailable or not owned by the configured key.
- Local preflight failure: stop before generation; explain the offending file/count/budget and corrective action. Do not bypass preprocessing or silently reduce the reference set.
- `413`: do not resend the same body. Identify whether the error came from SalpX or from Codex before the Skill ran; reduce the local request budget/select fewer references for SalpX, or use a fresh task and file paths for an incoming Codex limit.
- `429` or transient 5xx: allow bounded retry/polling behavior; do not repeatedly create new paid jobs.
- Timeout: retain the task ID and ask the user to query it before resubmitting.
- Failed task or empty output: report the actual SalpX error and do not substitute another product or invent a successful result.

After generation, perform both item-level and set-level visual QA. Compare the product against every relevant source view for shape, dimensions/proportions, exact count, repeated-unit consistency, functional orientation, material/color, printing/logo, accessories, and physical placement. Then review all outputs together for repeated compositions, repeated stories, random typography, empty text boxes, warped layout, and A+ images that only change copy. Mark an unverified result as `draft`; mark a visible identity or layout failure as `blocked` and do not present it as final.
