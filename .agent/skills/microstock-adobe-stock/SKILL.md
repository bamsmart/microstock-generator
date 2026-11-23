---
name: microstock-adobe-stock
description: Commercial-grade Adobe Stock rules, prompt engineering standards, 3-tier SEO metadata strategy, and technical/legal compliance guardrails for Generative AI microstock assets. Use whenever researching niches, crafting image generation prompts, auditing Vision QC, or optimizing titles/keywords for Adobe Stock.
---

# Adobe Stock Commercial-Grade Microstock Skill

Follow these strict commercial, technical, and legal standards for every Generative AI asset created for Adobe Stock (and Shutterstock / Freepik / iStock).

## 1. Mandatory Adobe Stock Legal & IP Rules (Zero Tolerance)
Never allow any of the following in prompts, images, titles, or keywords:
- **Trademarks & Brands**: No logos, product packaging, brand names (`Apple`, `iPhone`, `Nike`, `Lego`, `Coca-Cola`, `Starbucks`, `Tesla`, etc.), or recognizable designer furniture/electronics/toys.
- **Artists & Styles**: Never use living or deceased artist names or `"in the style of [artist]"` (explicitly prohibited by Adobe Stock Generative AI policy).
- **Protected Landmarks & Architecture**: Avoid recognizable landmarks or modern copyrighted buildings (`Eiffel Tower`, `Burj Khalifa`, `Louvre`, `Sydney Opera House`, `Hollywood Sign`, `Empire State Building`, etc.).
- **People & Releases**: Avoid recognizable faces, celebrities, or public figures. Prefer **faceless/hands-free editorial compositions**, objects, botanicals, textures, interiors, or 3D icons to eliminate Model/Property Release rejections and AI hand/face anatomy defects.
- **No Editorial / Newsworthy Events**: Generative AI assets cannot be submitted as Illustrative Editorial; keep concepts evergreen or seasonal commercial.

## 2. Commercial-Grade Prompt Formula

### A. Full-Scene Commercial Assets (`scene`, Aspect Ratio `3:2`)
Must have clear **buyer utility** (hero banners, SaaS websites, presentations, packaging, ads):
1. **Exact Subject & Material**: Describe tangible, authentic materials (`warm oak wood`, `matte travertine stone`, `raw cream linen`, `ceramic mug`).
2. **Editorial Lighting & Camera**: Natural daylight, soft north-facing window light, golden hour, 50mm prime lens, shallow depth of field, authentic micro-textures (never plastic/over-smoothed).
3. **Deliberate Copy Space**: Explicitly reserve clean negative space (`generous clean negative copy space on the left third for headline typography`).
4. **Hard Exclusions**: Always end with `no text, no logos, no watermarks`.

### B. Isolated Cutout Assets (`isolated`, Aspect Ratio `1:1`)
Must be cleanly extractable to transparent PNG:
1. **Pure White Studio Backdrop**: `isolated on a pure solid white background (#FFFFFF)`.
2. **Full Uncropped Silhouette**: `centered subject filling 75% to 80% of frame, full uncropped silhouette with clean breathing margin on all sides` (subject must NEVER touch image edges).
3. **Zero Shadows & Clean Edges**: `soft even studio lighting, crisp distinct outer edges, no drop shadows, no cast shadows, no floating debris, no text, no logos, no watermarks`.

### C. Banned Prompt Spam (Avoids "AI Plastic" Quality Rejections)
Never include: `8k`, `4k`, `hd`, `photorealistic`, `hyperrealistic`, `unreal engine`, `octane render`, `masterpiece`, `award winning`, `ultra detailed`, `trending on artstation`, `midjourney`, `generative ai`.

## 3. Page-1 Adobe Stock SEO Metadata Standards
- **Filename**: ASCII snake_case, descriptive of main subject, **≤ 30 characters** including extension (`.jpg` / `.png`).
- **Title**: **≤ 70 characters**, plain English phrase, **zero commas**, zero brands/buzzwords. Formula:
  `[Specific Style/Material] + [Exact Main Subject] + [Key Visual Detail/Color] + [Setting/Copy Space or Isolated]`
- **Keywords (35–45, strictly ranked by Adobe search weight)**:
  - **#1–#10 (Highest Weight)**: Exact literal subject, medium/style, and primary commercial concept.
  - **#11–#25 (Visual Specifics)**: Exact colors, textures/materials, lighting, camera angle/framing.
  - **#26–#45 (Buyer Intent)**: Target industries and commercial uses (`skincare`, `packaging`, `hero banner`, `branding`, `e-commerce`, `wedding invitation`).
  - **Ban Generic Filler Spam**: Strip weak fillers (`beautiful`, `nice`, `creative`, `artistic`, `visual`, `element`, `object`, `image`, `high quality`).

## 4. Technical & Portal Submission Checklist
- **Resolution**: `4 MP` to `100 MP` (4x Upscayl target ~16 MP).
- **File Size**: `≤ 45 MB`, **sRGB IEC61966-2.1** ICC profile, JPEG quality 95% (4:4:4) for scenes; anti-halo RGBA PNG for isolated.
- **100% Zoom QC**: Reject extra fingers, garbled text, warped straight lines, floating/melting objects, and over-sharpened noise *before* upscaling.
- **Portal Submission**: Classify GenAI assets as **Illustrations**, check **"Created using generative AI tools"**, and check **"People and Property are fictional"** when applicable.
