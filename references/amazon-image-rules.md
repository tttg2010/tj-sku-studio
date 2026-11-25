# Ecommerce image QA checklist

Use this reference after a generation when the user asks for marketplace-ready output. It is a conservative production checklist, not a current marketplace-policy citation.

## Product fidelity

- Same product model and silhouette as the source
- Same number of units and accessories
- Repeated units have consistent length, width, thickness, color, and construction
- Functional ends, pads, ports, buttons, holes, waves, slots, seams, fasteners, and moving parts retain their exact shape and orientation
- No invented buttons, seams, ports, labels, ingredients, or certifications
- Same material, color, finish, and functional parts
- Logo and printed text are not warped or replaced

Treat any count, silhouette, proportion, functional-orientation, repeated-unit, logo/print, or material mismatch as a hard failure. A visually attractive look-alike does not pass. When a model redraw fails, switch to the original-pixel composite or request a more useful reference angle rather than continuing random rerolls.

## Scene integration

- Product scale is plausible relative to nearby objects
- Product camera angle and support plane agree with the scene perspective
- The product makes believable contact with the surface or mounting point
- Contact shadows follow the scene's light direction and softness
- Occlusion is physically plausible; hands, props, and the product do not merge unnaturally
- Edge mattes are clean, without white halos or chopped details
- Background light and color may affect surrounding shadow/reflection, but must not recolor or redraw the product material
- If the source view cannot fit the scene naturally, change the scene or request another source view instead of warping the product

## Composition

- Image role is explicit: main image, feature/detail image, lifestyle image, or concept draft
- Product is the visual subject and is not hidden by props
- Crop, aspect ratio, and negative space are suitable for the intended placement
- Shadows and reflections are physically plausible
- No watermark, random typography, duplicated product, or accidental extra packaging

## Text and layout

- Base photography contains no generated copy, letters, labels, arrows, icons, badges, UI cards, frames, callouts, or placeholder rectangles unless the brief explicitly requires them
- Copy space is part of a continuous natural background, not an unexplained blank box
- Final copy exactly matches the approved text and uses a deliberate hierarchy and alignment
- Dimensions, quantities, compatibility statements, and performance claims are added only from verified facts
- Text, arrows, icons, and comparison marks are composed separately when exactness matters
- No element is stretched, clipped, overlapping, floating without purpose, or placed over a critical product detail

Model-rendered text or layout that is misspelled, distorted, duplicated, unsupported, or visually arbitrary is `blocked`, not `passed`.

## Set diversity

Review all outputs together in a contact sheet.

- Every image has one explicit role and buyer question
- Main, secondary, and A+ images do not reuse the same finished base image unless reuse was requested
- A+ modules add a new detail, use case, sequence, comparison, or brand story rather than only changing copy
- Any pair of images differs meaningfully on at least three of: buyer question, camera angle/distance, composition/crop, environment/interaction, and evidence style
- The set has deliberate visual rhythm rather than repeated centered product shots

If two images remain highly similar after removing their text, treat them as duplicates and redesign one.

## Delivery record

Record:

- source file(s) and operation used
- requested ratio and prompt assumptions
- task ID and output path(s)
- visual QA status: `passed`, `draft`, or `blocked`
- unresolved risks, especially unreadable source details or distorted text/logo
- preservation method: original-pixel composite, constrained reference edit, or concept draft
- set-level duplicate review when more than one image is delivered

If a current Amazon or marketplace rule is material to acceptance, verify the current rule separately instead of treating this checklist as a guarantee.
