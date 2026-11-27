---
name: microstock-analyst-qa
description: Senior Microstock Consultant Analyst QA, Anti-Rejection, Visual Inspection & Portfolio Hygiene skill for Adobe Stock Generative AI assets. Use whenever auditing image quality metrics (blur_effect, noise_sigma, halo_score), configuring upscaling/supersampling (12-20 MP sweet spot), reviewing Dark-BG QA contact sheets, running cross-batch portfolio deduplication, checking keyword cannibalization, or evaluating commercial-safe free Python libraries.
---

# Microstock Consultant Analyst QA & Anti-Rejection Playbook (2026)

This skill encodes senior microstock QA engineering standards for **Adobe Stock**, **Shutterstock**, **Freepik**, and **Getty/iStock** under a strict **$0 / Commercial-License-Safe** stack.

---

## 1. Adobe Stock Rejection Taxonomy & Automated Defenses

| Adobe Stock Rejection Reason | Root Technical Cause | Automated Defense in Pipeline |
|---|---|---|
| **Quality Issues (Soft / Blurry at 100% Zoom)** | Over-upscaling 4 MP/16 MP inputs to 45–67 MP exposes synthetic upscaler softness & causes macOS swap thrashing | **Smart Adaptive Upscale + 16–20 MP Lanczos Supersampling**: Skip Upscayl if raw $\ge 12\text{ MP}$; cap output $\le 20\text{ MP}$ before heavy matting (`postprocess.py`) |
| **Cutout Fringe / White Halo / Pixel Gaps (*Celah Pixel*)** | Imperfect alpha segmentation on `#FFFFFF` floor leaving white matte or micro-gaps inside dark objects | **BiRefNet-Lite + Guided Filter + Color-Projection Matting + `fill_interior_pinholes` + PyMatting `estimate_foreground_ml`** (MIT) + Halo Rim Detector (`validator.py`) |
| **Compression Artifacts / Color Noise** | High ISO / synthetic grain amplified by 4x GAN upscaler | **`skimage.restoration.estimate_sigma`** wavelet noise check (`<= 12.0`) + **4:4:4 `quality=95` sRGB JPEG** |
| **Similar Content (Account Spam Risk)** | Uploading near-identical angles/framing OR reusing $>65\%$ identical keywords across assets | **Within-batch pHash** (`<= 6`) + **Cross-batch `.portfolio_index.json`** + **OpenCLIP Semantic Cosine Audit** (`>= 0.92`) + **Keyword Jaccard Overlap Guard** (`<= 65%`) |
| **Non-Compliant File / Metadata Error** | Missing sRGB ICC profile, wrong CSV columns, missing "Generative AI" disclosure, missing IPTC/XMP | Mandatory **`sRGB IEC61966-2.1`** ICC on PNG & JPEG, pure-Python lossless **Adobe XMP + EXIF** fallback when `exiftool` absent, `<= 30` char filenames |

---

## 2. Commercial-Safe Free Library Matrix (Strictly Zero Non-Commercial Traps)

* **APPROVED (MIT / BSD / Apache 2.0):**
  * `rembg` (`birefnet-general-lite`, `birefnet-general`, `isnet-general-use`) — MIT
  * `PyMatting` (`estimate_foreground_ml`) — MIT
  * `scikit-image` (`measure.blur_effect`, `restoration.estimate_sigma`) — Modified BSD
  * `opencv-python-headless` — Apache 2.0
  * `ImageHash` — BSD
  * `piexif` + Pure-Python Adobe XMP APP1/`iTXt` — MIT
  * `open-clip-torch` (`ViT-B-32` / `laion2b_s34b_b79k`) — MIT
* **BANNED FOR COMMERCIAL MICROSTOCK WORK:**
  * `pyiqa` — **PolyForm Noncommercial 1.0.0** (FORBIDDEN)
  * `BRIA RMBG 1.4 / 2.0 / 3.0` — **CC BY-NC 4.0** (FORBIDDEN for commercial asset preparation)

---

## 3. Scientific IQA Thresholds (Target Sweet Spots)

* **Resolution:** Minimum `4.0 MP`, Maximum `100.0 MP`. Optimal target after supersampling: **`12.0 – 20.0 MP`**.
* **File Size:** Strictly `<= 45.0 MB` (PNG lossless `compress_level=9`, JPEG `quality=95`, `subsampling=0`).
* **Resolution-Invariant Blur (`skimage.measure.blur_effect`):**
  * `0.00 – 0.30`: Crisp commercial focus
  * `0.30 – 0.45`: Acceptable soft studio depth
  * `> 0.45`: **WARN** (inspect 100% zoom or reject)
* **Wavelet Noise (`skimage.restoration.estimate_sigma`):**
  * `<= 6.0`: Ultra-clean studio render
  * `> 12.0`: **WARN** (excess grain/color noise)
* **Isolated Cutout Halo Score (`detect_isolated_halo_score`):**
  * Compares semi-transparent boundary band (`10 < alpha < 245`) against adjacent solid core (`alpha >= 245`) on colored/dark subjects (`core_luma < 200`).
  * `<= 0.15`: Invisible cutout seam on dark `#181818` canvas
  * `> 0.28`: **WARN** (possible bright matte halo; inspect on `qa_contact_sheet.jpg`)

---

## 4. Dark-Canvas Inspection & Pre-Upload Protocol

1. **Always check `<batch>/qa_contact_sheet.jpg` first** (located outside `result/` so it is never uploaded).
2. Transparent PNGs are rendered over a dark `#181818` studio canvas so any faint floor haze, white rim halo, or untrapped background pocket jumps out within 10 seconds.
3. Run portfolio audit anytime offline:
   ```bash
   .venv/bin/python main.py --report
   ```
4. Before submitting on Adobe Stock Contributor:
   * Upload `result/*.jpg` and `result/*.png`
   * Click **Upload CSV** → select `result/adobe_stock_metadata.csv`
   * Mandatory checkboxes: **"Created using generative AI tools"** (+ **"People and Property are fictional"** if applicable).
