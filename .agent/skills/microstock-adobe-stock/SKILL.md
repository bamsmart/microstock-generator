---
name: microstock-adobe-stock
description: Commercial-grade Adobe Stock rules, anti-rejection isolated studio prompt engineering, 3-4 month daily anti-repeat research strategy, 3-tier SEO metadata, and technical/legal compliance guardrails for Generative AI microstock assets. Use whenever researching niches, crafting image generation prompts, auditing Vision QC, post-processing transparent PNGs, or optimizing titles/keywords for Adobe Stock.
---

# Adobe Stock Commercial-Grade Microstock Skill (v2 — Zero-Rejection Isolated & Scene)

Follow these strict commercial, technical, and legal standards for every Generative AI asset targeting **Adobe Stock** (plus Shutterstock, Freepik, and iStock). Every asset is reviewed at **100%–300% zoom** under Adobe's [Quality & Technical Standards](https://helpx.adobe.com/stock/contributor/content-moderation/quality-technical-standards-reasons-content-refusal.html).

---

## 1. Mandatory Adobe Stock Legal & IP Rules (Zero Tolerance)
Never allow any of the following in prompts, images, titles, or keywords:
- **Trademarks & Brands**: No logos, product packaging, brand names (`Apple`, `iPhone`, `Nike`, `Lego`, `Coca-Cola`, `Starbucks`, `Tesla`, etc.), or recognizable designer electronics/furniture/toys.
- **Artists & Styles**: Never use living or deceased artist names or `"in the style of [artist]"` (strictly prohibited by Adobe Stock Generative AI policy).
- **Protected Landmarks & Architecture**: Avoid recognizable landmarks or modern copyrighted buildings (`Eiffel Tower`, `Burj Khalifa`, `Louvre`, `Sydney Opera House`, `Hollywood Sign`, `Empire State Building`, etc.).
- **People & Releases**: Avoid recognizable faces, celebrities, or complex hand/crowd scenes. Prefer **faceless/hands-free editorial compositions**, tangible objects, botanicals, food, workspaces, interiors, podiums, and 3D clay icons.
- **No Illustrative Editorial**: Generative AI cannot be submitted as editorial; keep concepts 100% commercial evergreen or seasonal.

---

## 2. Why Isolated AI Assets Get Rejected for "Quality Issues" (And How to Prevent It)
Adobe Stock rejects isolated AI assets at 3–5× higher rates than scenes because flat white/transparent backdrops expose every micro-defect at 100% zoom:
1. **Halos, Fringing & Pixel Gaps (*celah pixel*)**: Caused by low contrast against white, translucent materials (glass/ice/water), fuzzy edges (fur/hair/feathers/smoke/steam/watercolor bleed), or shallow depth-of-field blur along the silhouette.
2. **Dirty / Gradient White Space**: AI generates off-white vignettes, studio curves, or noisy gray patches instead of flat `#FFFFFF`, causing messy masks and jagged edges.
3. **Messy Cast Shadows**: Harsh or smudged gray shadows confuse background removal and leave gray fringes.
4. **Soft Focus & Plastic Over-Smoothing**: Shallow aperture (`f/1.8`) blurs back edges of the object; buzzwords like `8k`/`photorealistic`/`octane render` produce waxy plastic surfaces that moderators reject as over-processed artifacts.
5. **Missing sRGB ICC Profile or Sub-4MP Resolution**: Transparent PNGs missing an embedded **sRGB IEC61966-2.1** profile or cropped under 4 MP trigger technical refusals.

---

## 3. Commercial-Grade Prompt Formulas

### A. Edge-Safe Isolated Assets (`isolated`, Aspect Ratio `1:1`)
**Subject Selection Rule (CRITICAL)**:
- **CHOOSE**: Solid, **opaque**, medium-to-dark or rich-colored objects with crisp geometric/organic silhouettes (matte ceramics, leather, cast iron, wood, opaque fruit/bakery, hardcover books, kraft boxes, brass ornaments, matte 3D clay icons, compact succulents).
- **AVOID**: Transparent/frosted **glass**, **ice cubes**, **condensation droplets**, **steam/smoke/mist**, **fur/hair/feathers**, **tassels/lace/mesh/strings**, **watercolor bleed**, **glitter/confetti/crumbs**, or **white-on-white** objects.

**Mandatory Isolated Studio Recipe**:
1. **Backdrop**: `isolated on a seamless pure white background (#FFFFFF), evenly lit background with zero gradient and zero vignette`
2. **Subject Contrast**: `solid opaque subject with a well-defined silhouette and strong tonal contrast against the white`
3. **Edge Separation Lighting**: `large softbox key light with a subtle rim light separating every edge from the background`
4. **Sharp Optics**: `shot with a 100mm macro lens at f/11 for edge-to-edge sharp focus, no depth-of-field blur`
5. **Framing & Margin**: `centered and fully in frame, full uncropped silhouette with about 12% clean margin on all sides` (NEVER touching borders)
6. **Zero Shadows / Zero Noise**: `no drop shadows, no cast shadows, no floor reflection, clean noise-free surfaces with natural micro-texture, no grain, no blur, no floating particles, no loose fragments, no props, no text, no logos, no watermarks`

**Recommended Negative Prompt (Isolated)**:
`shadow, cast shadow, drop shadow, gradient background, gray background, vignette, halo, fringe, soft edges, blur, depth of field, noise, grain, jpeg artifacts, cropped, cut off, out of frame, props, text, letters, logo, watermark, glass, transparency, smoke, steam, fur, hair strands, floating particles, reflection`

### B. Full-Scene Commercial Assets (`scene`, Aspect Ratio `3:2`)
Must provide immediate **buyer utility** (hero banners, SaaS headers, presentations, ads, packaging):
1. **Authentic Materials & Natural Light**: Tangible textures (`warm oak wood`, `matte travertine`, `raw linen`, `fresh ingredients`) lit by natural window daylight or golden hour.
2. **Editorial Optics**: `shot on a 50mm prime lens, realistic editorial color grading, authentic surface micro-textures`.
3. **Deliberate Copy Space**: Explicitly reserve clean negative space (`generous clean negative copy space on the left/right/upper third for designer typography`).
4. **Hard Exclusions**: `no people, no text, no logos, no watermarks`.

**Recommended Negative Prompt (Scene)**:
`text, letters, logo, watermark, signature, people faces, hands, distorted anatomy, blur, noise, grain, jpeg artifacts, oversaturated, overprocessed, plastic look, cluttered composition, cropped subject`

### C. Banned Prompt Spam (Causes "AI Plastic" Rejections)
Never include: `8k`, `4k`, `hd`, `photorealistic`, `hyperrealistic`, `unreal engine`, `octane render`, `masterpiece`, `award winning`, `ultra detailed`, `trending on artstation`, `midjourney`, `generative ai`, `hdr`.

---

## 4. Daily High-Demand Research Strategy (3–4 Months Ahead + Zero Repeats)
Buyers, agencies, and brands license seasonal assets **90–120 days (3–4 months) in advance**:
- Always target the **H-90 to H-120 rolling calendar window** (e.g., late Nov → late Feb to late Mar: Ramadan/Eid, Spring Botanicals, Tax Season, Earth Day, Easter, Q2 Business/ESG) combined with **daily rotating evergreen niches** (24 commercial verticals).
- **Mandatory 120-Day Anti-Repeat History (`prompt_history.json`)**: Log every generated subject & prompt signature; reject exact or fuzzy-similar duplicates (Jaccard ≥ 0.50) across at least 120 days so daily generation always produces fresh, non-spammy portfolio coverage (preventing Adobe Stock "Similar Content" refusals).

---

## 5. Page-1 Adobe Stock SEO Metadata Standards
- **Filename**: ASCII snake_case, specific to main subject, **≤ 30 characters** including extension (`.jpg` / `.png`).
- **Title**: **≤ 70 characters**, plain English phrase, **zero commas**, zero brands/buzzwords. Formula:
  `[Specific Style/Material] + [Exact Main Subject] + [Key Visual Detail/Color] + [Setting/Copy Space or Isolated]`
- **Keywords (35–45, strictly ranked by Adobe search weight)**:
  - **#1–#10 (Highest Weight)**: Exact literal subject, medium/style, and primary commercial concept.
  - **#11–#25 (Visual Specifics)**: Exact colors, materials/textures, lighting, camera angle/framing.
  - **#26–#45 (Buyer Intent)**: Target industries and commercial uses (`skincare`, `packaging`, `hero banner`, `branding`, `e-commerce`).
  - **Ban Generic Filler Spam**: Strip weak fillers (`beautiful`, `nice`, `creative`, `artistic`, `visual`, `element`, `object`, `image`, `high quality`).

---

## 6. Technical & Portal Submission Checklist
- **Resolution**: `4 MP` to `100 MP`, **≤ 45 MB**, embedded **sRGB IEC61966-2.1** ICC profile on BOTH JPEGs and transparent PNGs.
- **Isolated PNG Cleanup**: Fill tiny interior alpha pinholes (≤ 64 px), strip white matte fringes, zero RGB on transparent pixels, tight crop with 3% margin, auto-reupscale if under 4.0 MP.
- **100% Zoom QC**: Reject soft edges, gray halos, pixel cracks, noise in white space, extra fingers, garbled text, and over-sharpened artifacts *before* upscaling.
- **Portal Submission**: Classify GenAI assets as **Illustrations**, check **"Created using generative AI tools"**, and check **"People and Property are fictional"** when applicable.
