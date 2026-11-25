# Image-led ecommerce creative planning

Read this reference when the user supplies product images without a finished prompt, asks Codex to propose image directions, or wants a coordinated main/secondary/A+ set.

## Start from the product

Inspect all supplied views and build a product identity sheet before inventing creative directions. Separate:

- confirmed visible facts;
- facts supplied explicitly by the user;
- reasonable but unverified hypotheses;
- details that cannot be read or measured.

Do not convert a visual guess into a material, dimension, performance, safety, age-range, compatibility, certification, or bundle claim. Use hypotheses only to propose questions or neutral visual directions.

## Proposal mode

The user may provide only an image. Do not ask them to write a prompt. Offer 3–5 distinct directions in a compact table:

| Field | Required content |
| --- | --- |
| Direction | Short human-readable concept name |
| Image role | Main, secondary feature, detail, lifestyle, comparison, instruction, or A+ module |
| Buyer question | The one question this image answers |
| Visual treatment | Shot distance, product angle, composition, scene, interaction, and lighting |
| Fidelity method | Original-pixel composite, constrained reference edit, or concept draft |
| Copy plan | Text-free, or exact copy to add separately plus natural negative-space location |
| Format | Ratio or target dimensions |
| Risk | Product detail, unsupported claim, source-angle, or layout risk |

Recommend the safest high-value direction. Wait for selection before a paid generation unless the user explicitly says to generate directly; in that case use the recommended direction and state the assumption.

## Complete-set storyboard

Plan the set as one system before generating individual images. Select only roles supported by the product and user facts. A typical pool is:

- clean hero/main image;
- material or construction close-up;
- mechanism or how-it-works view;
- dimensions, compatibility, or what-is-included view, only with verified facts;
- one or more real use cases;
- benefit demonstration that does not exaggerate performance;
- comparison, only when the comparison is factual and defensible;
- A+ brand/lifestyle banner;
- A+ feature-detail module;
- A+ application story or multi-scenario module;
- A+ bundle/packaging/trust module.

Every slot must have a unique buyer question and visual job. Main and secondary images usually show the product clearly; A+ modules should expand the story through environment, detail, sequence, comparison, or use—not repeat the same hero view with different copy.

Before writing prompts, reconcile the requested main/secondary/A+ counts separately. Do not silently reduce a large request or replace A+ outputs with a plan. Every slot needs a source-view mapping and a concrete **text-hidden visual proof**. A material detail needs an actual readable crop; a mechanism needs a visible functional part or real sequence; a scale claim needs verified dimensions and an appropriate scale reference. A stock use scene plus a pasted pack shot does not prove the product benefit. If the view/evidence is unavailable, offer a supported alternative or ask for that specific input.

For risky masks, reflective materials, mounting or flexible products, validate one representative sample first. Do not mass-produce an unapproved template. Build each scene around the source geometry; choose another scene rather than force the product into an incompatible perspective or fake a deformed/in-use product. See [production-v18.md](production-v18.md) and [original-pixel-compositing.md](original-pixel-compositing.md).

## Diversity gate

Before generation, compare every pair of planned images across these axes:

1. buyer question or selling point;
2. camera distance and product angle;
3. composition and crop;
4. environment or interaction;
5. evidence style, such as macro detail, process, lifestyle, scale, or bundle view.

Each pair should differ meaningfully on at least three axes. If two slots differ only in headline or body copy, merge or redesign one. Do not reuse the same finished base image for the main image and A+ unless the user explicitly requests a repeated brand motif.

An explicitly requested A/B pair is a separate exception, not two normal set slots: identify the base, declare one variable (copy, camera, composition or interaction), keep claims and all other variables fixed, and list the pair separately. Do not count it toward an unrelated missing A+ module or claim conversion improvement without traffic data.

## Prompt package

For each approved direction, build two separate artifacts:

1. **Base-image prompt:** product identity lock, image job, scene/composition, integration controls, and negative controls. Default to no text, no labels, no arrows, no badges, no UI cards, no frames, and no placeholder boxes.
2. **Layout brief:** exact verified copy, hierarchy, alignment, copy-safe region, arrow/icon/dimension positions, safe margins, and export size. Apply this after the base image is accepted.

Use “natural continuous background with uncluttered negative space” instead of merely “space for text”. The latter often produces empty cards or white rectangles.

## Final set review

Review a contact sheet of the entire set, not only individual images. Check visual rhythm, role coverage, repeated backgrounds, repeated camera angles, repeated copy structure, unsupported claims, and whether A+ adds information beyond the main/secondary set. Replace or block weak duplicates before delivery.
