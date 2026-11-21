"""
Ultimate Post-Processing Engine for Commercial Microstock Assets:
- Isolated PNG (5-Stage Edge-Perfection):
    1. SOTA Segmentation (BiRefNet-General / IS-Net fallback)
    2. Confidence Normalization & Soft-Shadow Killer
    3. RGB-Guided Alpha Matting (Fast O(N) Guided Filter)
    4. Stray Debris & Interior Pinhole Cleanup
    5. Nearest-Foreground RGB Extrapolation (True Anti-Halo) + Tight Crop + 4MP/45MB Guard
- Full-Scene JPEG:
    sRGB IEC61966-2.1 color profile + 95% quality 4:4:4 subsampling
"""

import io
import platform
from pathlib import Path
from typing import Tuple
import numpy as np
import cv2
from PIL import Image, ImageCms
import rembg

from .config import PipelineConfig

_SRGB_PROFILE_BYTES = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def normalize_alpha_confidence(
    alpha: np.ndarray,
    low_cut: int = 35,
    high_snap: int = 215
) -> np.ndarray:
    """
    Eliminate faint residual floor shadows (<= low_cut -> 0) and lock
    subject interior to 100% solid opacity (>= high_snap -> 255).
    """
    if high_snap <= low_cut:
        return alpha

    a_float = alpha.astype(np.float32)
    stretched = (a_float - low_cut) * (255.0 / (high_snap - low_cut))
    return np.clip(stretched, 0, 255).astype(np.uint8)


def guided_filter_alpha(
    rgb: np.ndarray,
    alpha: np.ndarray,
    radius: int = 3,
    eps: float = 1e-4
) -> np.ndarray:
    """
    Fast O(N) Edge-Aware Guided Filter using the crisp upscaled RGB image as guidance.
    Snaps the alpha boundary onto real object edges (fur, velvet, curves).
    """
    if radius <= 0:
        return alpha

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    p = alpha.astype(np.float32) / 255.0
    ksize = (2 * radius + 1, 2 * radius + 1)

    mean_I = cv2.boxFilter(gray, cv2.CV_32F, ksize)
    mean_p = cv2.boxFilter(p, cv2.CV_32F, ksize)
    corr_I = cv2.boxFilter(gray * gray, cv2.CV_32F, ksize)
    corr_Ip = cv2.boxFilter(gray * p, cv2.CV_32F, ksize)

    var_I = corr_I - mean_I * mean_I
    cov_Ip = corr_Ip - mean_I * mean_p

    a = cov_Ip / (var_I + eps)
    b = mean_p - a * mean_I

    mean_a = cv2.boxFilter(a, cv2.CV_32F, ksize)
    mean_b = cv2.boxFilter(b, cv2.CV_32F, ksize)

    q = mean_a * gray + mean_b
    q_u8 = np.clip(q * 255.0, 0, 255).astype(np.uint8)

    # Apply guided filter ONLY along the boundary transition band so solid interior stays 255
    edge_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 3, 2 * radius + 3))
    edge_band = cv2.morphologyEx(alpha, cv2.MORPH_GRADIENT, edge_kernel) > 0

    out = alpha.copy()
    out[edge_band] = q_u8[edge_band]
    out[out < 20] = 0
    out[out > 245] = 255
    return out


def _detect_uniform_bg(raw_rgb: np.ndarray) -> Tuple[bool, np.ndarray]:
    """Detect uniform studio background color from the four image corners."""
    corners = np.vstack([
        raw_rgb[0:10, 0:10], raw_rgb[0:10, -10:],
        raw_rgb[-10:, 0:10], raw_rgb[-10:, -10:]
    ]).reshape(-1, 3).astype(np.float32)
    bg_color = np.median(corners, axis=0)
    is_uniform = float(np.mean(np.linalg.norm(corners - bg_color, axis=1) < 25.0)) > 0.80
    return is_uniform, bg_color


def punch_enclosed_background_holes(
    raw_rgb: np.ndarray,
    alpha: np.ndarray,
    scale_ratio: float = 1.0
) -> np.ndarray:
    """
    Punch trapped flat studio-background pockets (e.g. gaps between pine needles,
    tag string holes, tassel gaps) BEFORE color-projection matting so their edges
    also receive sub-pixel alpha and RGB decontamination.
    Uses a specular/paper ring guard so glossy highlights and white tags are preserved.
    """
    is_uniform, bg_color = _detect_uniform_bg(raw_rgb)
    if not is_uniform:
        return alpha

    dist_bg = np.linalg.norm(raw_rgb.astype(np.float32) - bg_color, axis=2)
    chroma = np.max(raw_rgb, axis=2).astype(np.int16) - np.min(raw_rgb, axis=2).astype(np.int16)

    gray = cv2.cvtColor(raw_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    m = cv2.boxFilter(gray, cv2.CV_32F, (5, 5))
    m2 = cv2.boxFilter(gray * gray, cv2.CV_32F, (5, 5))
    local_std = np.sqrt(np.maximum(0.0, m2 - m * m))

    bg_cand = (alpha > 0) & (dist_bg <= 10.5) & (chroma <= 12) & (local_std <= 3.0)
    if not np.any(bg_cand):
        return alpha

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(bg_cand.astype(np.uint8), connectivity=8)
    max_hole_area = int(150_000 * (scale_ratio / 4.0) ** 2)
    min_hole_area = 12
    punch_mask = np.zeros_like(bg_cand)
    ker_ring = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))

    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if min_hole_area <= area <= max_hole_area:
            x, y, bw, bh, _ = stats[i]
            pad = 6
            y0, y1 = max(0, y - pad), min(gray.shape[0], y + bh + pad)
            x0, x1 = max(0, x - pad), min(gray.shape[1], x + bw + pad)
            comp = (labels[y0:y1, x0:x1] == i).astype(np.uint8)
            ring = (cv2.dilate(comp, ker_ring) > 0) & (comp == 0)
            if np.any(ring):
                ring_vals = gray[y0:y1, x0:x1][ring]
                if float(np.median(ring_vals)) < 185.0 and float(np.percentile(ring_vals, 15)) < 145.0:
                    punch_mask[y0:y1, x0:x1][comp > 0] = True

    if not np.any(punch_mask):
        return alpha

    out_alpha = alpha.copy()
    out_alpha[punch_mask] = 0
    return out_alpha


def color_projection_matting(
    raw_rgb: np.ndarray,
    ai_alpha: np.ndarray,
    scale_ratio: float = 1.0
) -> np.ndarray:
    """
    Sub-Pixel Color-Projection Matting for uniform studio backgrounds:
    1. Detects uniform background color B from image corners.
    2. Builds a narrow Trimap (definite FG, definite BG, unknown boundary band) around the AI mask.
    3. For every pixel I in the unknown band where local foreground F_local is distinct from B,
       computes exact physical coverage: alpha = clip(dot(B - I, B - F_local) / ||B - F_local||^2, 0, 1).
    Eliminates upscaled AI mask overshoot, stair-stepping, and white halos at true sub-pixel precision.
    """
    is_uniform_bg, bg_color = _detect_uniform_bg(raw_rgb)
    if not is_uniform_bg:
        return ai_alpha

    k_erode = max(9, int(round(scale_ratio * 3.5)) | 1)
    k_dilate = max(3, int(round(scale_ratio * 1.0)) | 1)
    ker_e = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_erode, k_erode))
    ker_d = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_dilate, k_dilate))

    solid_mask = cv2.erode((ai_alpha >= 242).astype(np.uint8), ker_e) > 0
    outer_mask = cv2.dilate((ai_alpha > 25).astype(np.uint8), ker_d) > 0
    unknown_band = outer_mask & (~solid_mask)

    if not (np.any(solid_mask) and np.any(unknown_band)):
        return ai_alpha

    inv = (~solid_mask).astype(np.uint8)
    _, labels = cv2.distanceTransformWithLabels(
        inv, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
    )
    zero_coords = np.argwhere(inv == 0)
    nearest_yx = zero_coords[labels[unknown_band] - 1]
    f_local = raw_rgb[nearest_yx[:, 0], nearest_yx[:, 1]].astype(np.float32)
    i_band = raw_rgb[unknown_band].astype(np.float32)

    vec_fb = bg_color - f_local
    norm_sq = np.sum(vec_fb * vec_fb, axis=1)
    distinct = norm_sq > (18.0 ** 2)

    alpha_proj = np.zeros(len(i_band), dtype=np.float32)
    dot_val = np.sum((bg_color - i_band[distinct]) * vec_fb[distinct], axis=1)
    alpha_proj[distinct] = np.clip(dot_val / norm_sq[distinct], 0.0, 1.0)

    # Tighter S-curve fallback for true white-on-white edges
    alpha_ai = ai_alpha[unknown_band].astype(np.float32) / 255.0
    alpha_proj[~distinct] = np.clip((alpha_ai[~distinct] - 0.45) / (0.85 - 0.45), 0.0, 1.0)

    # Clean residual noise floor (< 10% -> 0, > 94% -> 100%)
    alpha_proj = np.clip((alpha_proj - 0.10) / (0.94 - 0.10), 0.0, 1.0)

    out_alpha = np.zeros_like(ai_alpha)
    out_alpha[solid_mask] = 255
    out_alpha[unknown_band] = np.round(alpha_proj * 255.0).astype(np.uint8)
    return out_alpha


def trim_white_background_overshoot(
    rgb: np.ndarray,
    alpha: np.ndarray,
    scale_ratio: float = 1.0
) -> np.ndarray:
    """
    When the image has a white studio background, AI masks upscaled from 1024px
    can overshoot by 5-15px into the white background.
    Uses connected-component flood from the exterior (alpha == 0) restricted to a
    narrow outer safety collar so interior white highlights are NEVER touched.
    """
    is_uniform, bg_color = _detect_uniform_bg(rgb)
    if not is_uniform or float(np.min(bg_color)) < 220.0:
        return alpha

    # Safety collar: only allow trimming within ~4.0 * scale_ratio pixels of the mask edge
    k_collar = max(7, int(round(scale_ratio * 8.0)) | 1)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_collar, k_collar))
    fg_bin = (alpha > 10).astype(np.uint8)
    deep_fg = cv2.erode(fg_bin, ker)
    collar = (fg_bin == 1) & (deep_fg == 0)

    min_rgb = np.min(rgb, axis=2)
    chroma = np.max(rgb, axis=2).astype(np.int16) - min_rgb.astype(np.int16)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    m = cv2.boxFilter(gray, cv2.CV_32F, (5, 5))
    m2 = cv2.boxFilter(gray * gray, cv2.CV_32F, (5, 5))
    local_std = np.sqrt(np.maximum(0.0, m2 - m * m))
    neutral_white = (min_rgb >= 205) & (chroma <= 18) & (local_std <= 8.0)

    # Flood-connect neutral_white pixels in the collar to the exterior (alpha <= 20)
    candidate = ((alpha <= 20) | (collar & neutral_white)).astype(np.uint8)
    num_labels, labels = cv2.connectedComponents(candidate, connectivity=8)

    # Label at (0,0) (or any border pixel with alpha <= 10) is the exterior background
    border_labels = set(np.unique(np.concatenate([
        labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]
    ]))) - {0}

    if not border_labels:
        return alpha

    ext_mask = np.isin(labels, list(border_labels))
    out_alpha = alpha.copy()
    out_alpha[ext_mask & collar] = 0
    return out_alpha


def clean_stray_pixels(alpha: np.ndarray, min_area: int = 50) -> np.ndarray:
    """
    Remove tiny floating debris/islands outside the subject.
    """
    binary = (alpha > 15).astype(np.uint8) * 255
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

    cleaned = alpha.copy()
    for i in range(1, num_labels):
        if stats[i, cv2.CC_STAT_AREA] < min_area:
            cleaned[labels == i] = 0

    return cleaned


def decontaminate_rgb_fringes(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """
    True Anti-Halo: Extrapolates the nearest solid foreground pixel RGB into
    every semi-transparent border pixel using C++ distanceTransformWithLabels.
    Also zeroes RGB on fully transparent pixels for cleaner compression.
    """
    solid_mask = alpha >= 253
    if not np.any(solid_mask):
        return rgb

    fringe = (alpha > 0) & (~solid_mask)
    out_rgb = rgb.copy()

    if np.any(fringe):
        inv = (~solid_mask).astype(np.uint8)
        _, labels = cv2.distanceTransformWithLabels(
            inv, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
        )
        zero_coords = np.argwhere(inv == 0)
        nearest_idx = labels[fringe] - 1
        nearest_yx = zero_coords[nearest_idx]
        out_rgb[fringe] = rgb[nearest_yx[:, 0], nearest_yx[:, 1]]

    # Zero out completely transparent pixels (prevents halo during buyer downsampling)
    out_rgb[alpha == 0] = 0
    return out_rgb


def remove_white_matte_smart(
    rgb: np.ndarray,
    alpha: np.ndarray,
    bg_color: np.ndarray = np.array([255.0, 255.0, 255.0], dtype=np.float32),
    alpha_floor: int = 25
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Studio-grade white matte un-premultiplication and deep-core color decontamination:
    1. Zeroes low alpha noise floor (< alpha_floor -> 0) and smoothly stretches the transition.
    2. Mathematically un-premultiplies white studio matte from semi-transparent edge pixels:
       F = clip((I - (1 - a) * B) / a, 0, 255)
    3. Identifies deep core foreground (alpha >= 245, eroded by 2px) to detect true local colors.
    4. For any edge pixel bordering white background where the subject is colored/dark,
       extrapolates local core color to guarantee ZERO white halo.
    5. Preserves genuine white objects (e.g. white paper, snow, white clothing) without color distortion.
    6. Zeroes out completely transparent pixels.
    """
    a_f = alpha.astype(np.float32) / 255.0
    floor_f = float(alpha_floor) / 255.0

    # 1. Floor threshold & stretch
    clean_a = np.where(a_f < floor_f, 0.0, a_f)
    clean_a = np.clip((clean_a - floor_f) / max(1e-5, 1.0 - floor_f), 0.0, 1.0)
    out_alpha = (clean_a * 255.0).round().astype(np.uint8)

    # 2. Mathematical un-premultiplication of white matte
    out_rgb = rgb.astype(np.float32).copy()
    valid_fringe = (clean_a > 0.01) & (clean_a < 0.99)
    if np.any(valid_fringe):
        a_v = clean_a[valid_fringe, None]
        unmatted = (out_rgb[valid_fringe] - (1.0 - a_v) * bg_color) / np.maximum(a_v, 0.05)
        out_rgb[valid_fringe] = np.clip(unmatted, 0.0, 255.0)

    # 3. Identify Core Solid Foreground (alpha >= 245, eroded by 2px)
    ker_core = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    deep_core = cv2.erode((out_alpha >= 245).astype(np.uint8), ker_core) > 0

    if np.any(deep_core):
        inv_core = (~deep_core).astype(np.uint8)
        _, labels = cv2.distanceTransformWithLabels(
            inv_core, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
        )
        zero_coords = np.argwhere(inv_core == 0)

        # Look at the transition border (0 < alpha < 255)
        fringe_mask = (out_alpha > 0) & (~deep_core)
        if np.any(fringe_mask):
            nearest_idx = labels[fringe_mask] - 1
            nearest_yx = zero_coords[nearest_idx]
            local_core_rgb = out_rgb[nearest_yx[:, 0], nearest_yx[:, 1]]

            # Check if local core foreground is DISTINCT from white background
            dist_to_bg = np.linalg.norm(local_core_rgb - bg_color, axis=1)
            is_colored_subject = dist_to_bg > 30.0

            # For colored subjects, if the fringe pixel is contaminated with white,
            # extrapolate local core color!
            fringe_indices = np.argwhere(fringe_mask)
            replace_mask = is_colored_subject
            replace_coords = fringe_indices[replace_mask]
            replace_core_rgb = local_core_rgb[replace_mask]

            out_rgb[replace_coords[:, 0], replace_coords[:, 1]] = replace_core_rgb

    out_rgb_u8 = np.clip(out_rgb, 0.0, 255.0).round().astype(np.uint8)
    out_rgb_u8[out_alpha == 0] = 0

    return out_rgb_u8, out_alpha


def refine_alpha_boundary(alpha: np.ndarray, feather_radius: float = 0.8) -> np.ndarray:
    """Apply subtle anti-aliasing ONLY on the 1-2px transition border."""
    if feather_radius <= 0:
        return alpha

    ksize = max(3, int(round(feather_radius * 2)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    edge_zone = cv2.morphologyEx(alpha, cv2.MORPH_GRADIENT, kernel)
    edge_mask = edge_zone > 10

    blurred = cv2.GaussianBlur(alpha, (ksize, ksize), sigmaX=feather_radius)
    refined = alpha.copy()
    refined[edge_mask] = blurred[edge_mask]
    return refined


def tight_crop_rgba(img_rgba: Image.Image, margin_pct: float = 0.03) -> Image.Image:
    """Crop excess empty transparent canvas with a clean breathing margin."""
    alpha = img_rgba.split()[3]
    bbox = alpha.getbbox()
    if not bbox:
        return img_rgba

    left, top, right, bottom = bbox
    w, h = img_rgba.size
    margin = int(max(w, h) * margin_pct)

    new_left = max(0, left - margin)
    new_top = max(0, top - margin)
    new_right = min(w, right + margin)
    new_bottom = min(h, bottom + margin)

    return img_rgba.crop((new_left, new_top, new_right, new_bottom))


class PostProcessor:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self._bg_session = None

    def get_bg_session(self, log_callback=print):
        if self._bg_session is None:
            providers = ["CPUExecutionProvider"]
            # CoreMLExecutionProvider leaks contexts & hangs on Intel Macs (x86_64)
            if platform.machine() == "arm64":
                try:
                    import onnxruntime as ort
                    if "CoreMLExecutionProvider" in ort.get_available_providers():
                        providers.insert(0, "CoreMLExecutionProvider")
                except Exception:
                    pass

            try:
                self._bg_session = rembg.new_session(self.config.bg_model, providers=providers)
            except Exception as e:
                fallback = getattr(self.config, "fallback_bg_model", "isnet-general-use")
                log_callback(f"  ⚠️ Model '{self.config.bg_model}' unavailable ({e}). Falling back to '{fallback}'.")
                self._bg_session = rembg.new_session(fallback, providers=providers)
        return self._bg_session

    def process_isolated_png(
        self,
        input_image_path: Path,
        output_image_path: Path,
        log_callback=print
    ) -> Tuple[bool, str]:
        """
        5-Stage Ultimate Isolated PNG Pipeline:
        1. SOTA Background Removal (BiRefNet / IS-Net)
        2. Confidence Stretch & Shadow Killer
        3. Guided Filter Edge Alignment to 4K RGB
        4. Stray Debris & Pinhole Cleanup
        5. Nearest-Foreground RGB Decontamination + Tight Crop + 4MP/45MB Guard
        """
        try:
            with Image.open(input_image_path) as raw_img:
                raw_rgb = np.array(raw_img.convert("RGB"))
                session = self.get_bg_session(log_callback=log_callback)
                res = rembg.remove(raw_img, session=session, alpha_matting=False)
                if isinstance(res, Image.Image):
                    rgba_img = res.convert("RGBA")
                else:
                    rgba_img = Image.open(io.BytesIO(bytes(res))).convert("RGBA")

                alpha = np.array(rgba_img)[:, :, 3]
                rgb = raw_rgb.copy()
                h, w = alpha.shape
                scale_ratio = max(1.0, max(h, w) / 1024.0)

                # Stage 1: Guided Filter Edge-Snap onto 4K RGB (adaptive radius, sharp)
                alpha = guided_filter_alpha(raw_rgb, alpha, radius=max(2, int(round(scale_ratio * 0.75))), eps=1e-4)

                # Stage 2: Punch Enclosed Studio-Background Pockets (before matting)
                alpha = punch_enclosed_background_holes(raw_rgb, alpha, scale_ratio=scale_ratio)

                # Stage 3: Sub-Pixel Color-Projection Matting (uses true raw_rgb vs AI trimap)
                alpha = color_projection_matting(raw_rgb, alpha, scale_ratio=scale_ratio)

                # Stage 4: Exterior White/Shadow Collar Flood Trimmer
                alpha = trim_white_background_overshoot(raw_rgb, alpha, scale_ratio=scale_ratio)

                # Stage 5: Stray Debris Cleanup
                if self.config.cleanup_stray_pixels:
                    alpha = clean_stray_pixels(alpha, min_area=self.config.stray_pixel_min_area)

                # Stage 6: Studio-Grade White Matte Removal & Deep-Core Anti-Halo Decontamination
                if self.config.color_decontaminate:
                    is_uniform, bg_color = _detect_uniform_bg(raw_rgb)
                    if is_uniform and float(np.min(bg_color)) >= 210.0:
                        rgb, alpha = remove_white_matte_smart(
                            rgb, alpha,
                            bg_color=bg_color,
                            alpha_floor=max(20, self.config.alpha_low_cut // 2)
                        )
                    else:
                        rgb = decontaminate_rgb_fringes(rgb, alpha)

                clean_np = np.dstack((rgb, alpha))
                clean_pil = Image.fromarray(clean_np, mode="RGBA")

                # Tight crop
                if self.config.tight_crop:
                    clean_pil = tight_crop_rgba(clean_pil, margin_pct=self.config.tight_crop_margin_pct)

                # 4.0 MP Guard: if tight-crop shrank below 4.0 MP, scale cleanly to >= 4.2 MP
                w, h = clean_pil.size
                mp = (w * h) / 1_000_000.0
                if mp < self.config.min_megapixels and self.config.auto_reupscale_if_under_4mp:
                    scale_up = (4.2 / max(mp, 0.1)) ** 0.5
                    new_w = int(round(w * scale_up))
                    new_h = int(round(h * scale_up))
                    log_callback(f"  ℹ️ Tight-crop was {mp:.2f} MP (<4.0 MP). Scaling smoothly to {new_w}x{new_h} px...")
                    clean_pil = clean_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    w, h = clean_pil.size

                # Save with maximum lossless compression
                output_image_path.parent.mkdir(parents=True, exist_ok=True)
                clean_pil.save(output_image_path, format="PNG", optimize=True, compress_level=9)

                # 45 MB File Size Guard
                file_size_mb = output_image_path.stat().st_size / (1024 * 1024)
                if file_size_mb > self.config.max_file_size_mb:
                    log_callback(f"  ⚠️ File size ({file_size_mb:.1f} MB) > 45 MB. Optimizing dimensions...")
                    new_w = int(w * 0.85)
                    new_h = int(h * 0.85)
                    clean_pil = clean_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    clean_pil.save(output_image_path, format="PNG", optimize=True, compress_level=9)

                return True, "Success"

        except Exception as e:
            return False, str(e)

    def process_scene_jpeg(
        self,
        input_image_path: Path,
        output_image_path: Path,
        log_callback=print
    ) -> Tuple[bool, str]:
        """
        Processes a full-scene asset into a compliant high-quality sRGB JPEG:
        1. Convert to RGB (no transparency removal)
        2. Attach sRGB ICC Profile
        3. Save with quality=95, optimize=True, subsampling=0 (4:4:4)
        """
        try:
            with Image.open(input_image_path) as raw_img:
                rgb_img = raw_img.convert("RGB")
                output_image_path.parent.mkdir(parents=True, exist_ok=True)

                rgb_img.save(
                    output_image_path,
                    format="JPEG",
                    quality=self.config.jpeg_quality,
                    optimize=True,
                    subsampling=0,
                    icc_profile=_SRGB_PROFILE_BYTES
                )

                file_size_mb = output_image_path.stat().st_size / (1024 * 1024)
                if file_size_mb > self.config.max_file_size_mb:
                    rgb_img.save(
                        output_image_path,
                        format="JPEG",
                        quality=90,
                        optimize=True,
                        subsampling=0,
                        icc_profile=_SRGB_PROFILE_BYTES
                    )

                return True, "Success"

        except Exception as e:
            return False, str(e)
