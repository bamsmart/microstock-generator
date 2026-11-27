"""
Configuration loader and validator for Microstock Generator Pipeline.
Cross-Platform with intelligent defaults.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field

try:
    import yaml
except ImportError:
    yaml = None

try:
    from dotenv import load_dotenv
    _project_env = Path(__file__).resolve().parent.parent.parent / ".env"
    if _project_env.exists():
        load_dotenv(dotenv_path=_project_env)
    else:
        load_dotenv(find_dotenv=False)
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_default_base_dir() -> Path:
    """Return default desktop microstock directory, with graceful fallback if inaccessible."""
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        target = desktop / "microstock_generator"
        try:
            target.mkdir(parents=True, exist_ok=True)
            return target
        except (PermissionError, OSError):
            pass
    fallback = PROJECT_ROOT / "input"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


@dataclass
class PipelineConfig:
    # Directories
    # Default base_dir is ~/Desktop/microstock_generator
    base_dir: Path = field(default_factory=get_default_base_dir)
    output_dir: Optional[Path] = None

    # Upscayl Binaries
    upscayl_bin: Optional[Path] = None
    models_dir: Optional[Path] = None
    skip_upscale: bool = False

    # Generation
    gen_model: str = "imagen-3.0-generate-002"
    aspect_ratio_isolated: str = "1:1"
    aspect_ratio_scene: str = "3:2"
    number_of_images: int = 4
    max_images_per_run: int = 20

    # Upscaling
    upscale_scale: int = 4
    skip_upscale_if_above_mp: float = 12.0
    target_max_megapixels: float = 20.0
    upscale_timeout_per_image_sec: int = 120
    model_isolated: str = "ultramix-balanced-4x"
    model_scene: str = "high-fidelity-4x"
    model_fallback: str = "ultramix-balanced-4x"

    # Segmentation & Postprocessing (PNG)
    remove_bg: bool = True               # Optional background removal toggle
    bg_output_dir: Optional[Path] = None # Optional separate folder for transparent cutouts
    bg_model: str = "birefnet-general-lite"
    fallback_bg_model: str = "isnet-general-use"
    alpha_low_cut: int = 40
    alpha_high_snap: int = 200
    guided_filter_radius: int = 3
    feather_radius: float = 0.8
    cleanup_stray_pixels: bool = True
    stray_pixel_min_area: int = 50
    color_decontaminate: bool = True
    use_pymatting_foreground: bool = True
    tight_crop: bool = True
    tight_crop_margin_pct: float = 0.03
    auto_reupscale_if_under_4mp: bool = True

    # Validation & QA (Adobe Stock Rules + Scientific IQA)
    min_megapixels: float = 4.0
    max_megapixels: float = 100.0
    max_file_size_mb: float = 45.0
    max_filename_chars: int = 30
    srgb_enforcement: bool = True
    jpeg_quality: int = 95
    dedup_phash_threshold: int = 6
    max_blur_effect: float = 0.45
    max_noise_sigma: float = 12.0
    max_halo_score: float = 0.28
    generate_qa_contact_sheet: bool = True
    portfolio_dedup_enabled: bool = True
    portfolio_dedup_threshold: int = 6
    max_keyword_overlap_ratio: float = 0.65

    # Semantic Audit (Fase 4: OpenCLIP)
    semantic_audit_enabled: bool = True
    semantic_model_name: str = "ViT-B-32"
    semantic_pretrained: str = "laion2b_s34b_b79k"
    semantic_dup_threshold: float = 0.92
    min_keyword_relevance: float = 0.16

    # Metadata & Compliance
    gemini_text_model: str = "gemini-3.8-flash"
    groq_model: str = "openai/gpt-oss-120b"
    mistral_model: str = "mistral-small-latest"
    openrouter_text_model: str = "openrouter/free"
    openrouter_vision_model: str = "openrouter/free"
    free_tier_delay_sec: float = 4.5
    enable_ai_qa: bool = True
    enable_vision_metadata: bool = True
    embed_iptc_metadata: bool = True
    max_title_chars: int = 70
    min_keywords: int = 25
    max_keywords: int = 50
    strip_forbidden_words: bool = True
    export_csv: bool = True

    # Research & Logging (Hybrid Workflow)
    prompts_dir: Optional[Path] = None   # None -> <base_dir>/prompts (default: ~/Desktop/microstock_generator/prompts)
    logs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")
    default_prompt_count: int = 12
    research_horizon_min_days: int = 90
    research_horizon_max_days: int = 120
    research_history_days: int = 120

    # Step 5: Adobe Stock SFTP Upload
    sftp_host: str = "sftp.contributor.adobestock.com"
    sftp_port: int = 22
    sftp_max_retries: int = 3

    # Raw config dictionary
    raw: Dict[str, Any] = field(default_factory=dict)


def _resolve_path(raw_path: Any, base_root: Path = PROJECT_ROOT) -> Optional[Path]:
    """Resolve a path safely, expanding ~ (home) and environment variables."""
    if not raw_path:
        return None
    expanded = os.path.expandvars(os.path.expanduser(str(raw_path).strip()))
    p = Path(expanded)
    if not p.is_absolute():
        p = (base_root / p).resolve()
    else:
        p = p.resolve()
    return p


def load_config(config_path: Path = None) -> PipelineConfig:
    """Load configuration from config.yaml, overriding defaults with sensible cross-platform paths."""
    if config_path is None:
        config_path = PROJECT_ROOT / "config.yaml"

    cfg = PipelineConfig()

    data: Dict[str, Any] = {}
    if config_path.exists() and yaml is not None:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"⚠️ Failed to parse config.yaml: {e}. Using defaults.")

    cfg.raw = data

    # Paths
    paths = data.get("paths", {})
    if "base_dir" in paths and paths["base_dir"]:
        cfg.base_dir = _resolve_path(paths["base_dir"])
    if "output_dir" in paths and paths["output_dir"]:
        cfg.output_dir = _resolve_path(paths["output_dir"])
    if "upscayl_bin" in paths and paths["upscayl_bin"]:
        cfg.upscayl_bin = _resolve_path(paths["upscayl_bin"])
    if "models_dir" in paths and paths["models_dir"]:
        cfg.models_dir = _resolve_path(paths["models_dir"])

    # Generation
    gen = data.get("generation", {})
    cfg.gen_model = gen.get("model", cfg.gen_model)
    cfg.aspect_ratio_isolated = gen.get("aspect_ratio_isolated", cfg.aspect_ratio_isolated)
    cfg.aspect_ratio_scene = gen.get("aspect_ratio_scene", cfg.aspect_ratio_scene)
    cfg.number_of_images = gen.get("number_of_images", cfg.number_of_images)
    cfg.max_images_per_run = gen.get("max_images_per_run", cfg.max_images_per_run)

    # Upscaling
    upsc = data.get("upscaling", {})
    cfg.upscale_scale = upsc.get("scale", cfg.upscale_scale)
    cfg.skip_upscale = bool(upsc.get("skip_upscale", cfg.skip_upscale))
    cfg.skip_upscale_if_above_mp = float(upsc.get("skip_upscale_if_above_mp", cfg.skip_upscale_if_above_mp))
    cfg.target_max_megapixels = float(upsc.get("target_max_megapixels", cfg.target_max_megapixels))
    cfg.upscale_timeout_per_image_sec = int(upsc.get("upscale_timeout_per_image_sec", cfg.upscale_timeout_per_image_sec))
    models = upsc.get("models", {})
    cfg.model_isolated = models.get("isolated", "ultramix-balanced-4x")
    cfg.model_scene = models.get("scene", cfg.model_scene)
    cfg.model_fallback = models.get("fallback", cfg.model_fallback)

    # Segmentation & Background Removal
    seg = data.get("segmentation", {})
    cfg.remove_bg = bool(seg.get("remove_bg", seg.get("enabled", True)))
    if "bg_output_dir" in seg and seg["bg_output_dir"]:
        cfg.bg_output_dir = _resolve_path(seg["bg_output_dir"])
    cfg.bg_model = seg.get("bg_model", "birefnet-general-lite")
    cfg.fallback_bg_model = seg.get("fallback_bg_model", "isnet-general-use")
    cfg.alpha_low_cut = int(seg.get("alpha_low_cut", 40))
    cfg.alpha_high_snap = int(seg.get("alpha_high_snap", 200))
    cfg.guided_filter_radius = int(seg.get("guided_filter_radius", 3))
    cfg.feather_radius = float(seg.get("feather_radius", 0.8))
    cfg.cleanup_stray_pixels = seg.get("cleanup_stray_pixels", cfg.cleanup_stray_pixels)
    cfg.stray_pixel_min_area = int(seg.get("stray_pixel_min_area", cfg.stray_pixel_min_area))
    cfg.color_decontaminate = seg.get("color_decontaminate", cfg.color_decontaminate)
    cfg.use_pymatting_foreground = bool(seg.get("use_pymatting_foreground", cfg.use_pymatting_foreground))
    cfg.tight_crop = seg.get("tight_crop", cfg.tight_crop)
    cfg.tight_crop_margin_pct = float(seg.get("tight_crop_margin_pct", cfg.tight_crop_margin_pct))
    cfg.auto_reupscale_if_under_4mp = seg.get("auto_reupscale_if_under_4mp", cfg.auto_reupscale_if_under_4mp)

    # Validation & QA
    val = data.get("validation", {})
    cfg.min_megapixels = float(val.get("min_megapixels", cfg.min_megapixels))
    cfg.max_megapixels = float(val.get("max_megapixels", cfg.max_megapixels))
    cfg.max_file_size_mb = float(val.get("max_file_size_mb", cfg.max_file_size_mb))
    cfg.max_filename_chars = int(val.get("max_filename_chars", cfg.max_filename_chars))
    cfg.srgb_enforcement = val.get("srgb_enforcement", cfg.srgb_enforcement)
    cfg.jpeg_quality = int(val.get("jpeg_quality", cfg.jpeg_quality))
    cfg.dedup_phash_threshold = int(val.get("dedup_phash_threshold", cfg.dedup_phash_threshold))
    cfg.max_blur_effect = float(val.get("max_blur_effect", cfg.max_blur_effect))
    cfg.max_noise_sigma = float(val.get("max_noise_sigma", cfg.max_noise_sigma))
    cfg.max_halo_score = float(val.get("max_halo_score", cfg.max_halo_score))
    cfg.generate_qa_contact_sheet = bool(val.get("generate_qa_contact_sheet", cfg.generate_qa_contact_sheet))
    cfg.portfolio_dedup_enabled = bool(val.get("portfolio_dedup_enabled", cfg.portfolio_dedup_enabled))
    cfg.portfolio_dedup_threshold = int(val.get("portfolio_dedup_threshold", cfg.portfolio_dedup_threshold))
    cfg.max_keyword_overlap_ratio = float(val.get("max_keyword_overlap_ratio", cfg.max_keyword_overlap_ratio))

    # Semantic Audit (OpenCLIP)
    sem = data.get("semantic_audit", {})
    cfg.semantic_audit_enabled = bool(sem.get("enabled", cfg.semantic_audit_enabled))
    cfg.semantic_model_name = sem.get("model_name", cfg.semantic_model_name)
    cfg.semantic_pretrained = sem.get("pretrained", cfg.semantic_pretrained)
    cfg.semantic_dup_threshold = float(sem.get("semantic_dup_threshold", cfg.semantic_dup_threshold))
    cfg.min_keyword_relevance = float(sem.get("min_keyword_relevance", cfg.min_keyword_relevance))

    # Metadata & Free-Tier Cloud AI
    meta = data.get("metadata", {})
    cfg.gemini_text_model = meta.get("gemini_text_model", cfg.gemini_text_model)
    cfg.max_title_chars = int(meta.get("max_title_chars", cfg.max_title_chars))
    cfg.min_keywords = int(meta.get("min_keywords", cfg.min_keywords))
    cfg.max_keywords = int(meta.get("max_keywords", cfg.max_keywords))
    cfg.strip_forbidden_words = meta.get("strip_forbidden_words", cfg.strip_forbidden_words)
    cfg.export_csv = bool(meta.get("export_csv", cfg.export_csv))
    cfg.embed_iptc_metadata = bool(meta.get("embed_iptc_metadata", cfg.embed_iptc_metadata))

    ft = data.get("free_tier", {})
    cfg.groq_model = ft.get("groq_model", cfg.groq_model)
    cfg.mistral_model = ft.get("mistral_model", cfg.mistral_model)
    cfg.openrouter_text_model = ft.get("openrouter_text_model", cfg.openrouter_text_model)
    cfg.openrouter_vision_model = ft.get("openrouter_vision_model", cfg.openrouter_vision_model)
    cfg.free_tier_delay_sec = float(ft.get("min_delay_sec", cfg.free_tier_delay_sec))
    cfg.enable_ai_qa = bool(ft.get("enable_ai_qa", cfg.enable_ai_qa))
    cfg.enable_vision_metadata = bool(ft.get("enable_vision_metadata", cfg.enable_vision_metadata))

    res_cfg = data.get("research", {})
    if "prompts_dir" in res_cfg and res_cfg["prompts_dir"]:
        cfg.prompts_dir = _resolve_path(res_cfg["prompts_dir"])
    cfg.default_prompt_count = int(res_cfg.get("default_prompt_count", cfg.default_prompt_count))
    cfg.research_horizon_min_days = int(res_cfg.get("horizon_min_days", cfg.research_horizon_min_days))
    cfg.research_horizon_max_days = int(res_cfg.get("horizon_max_days", cfg.research_horizon_max_days))
    cfg.research_history_days = int(res_cfg.get("history_retention_days", cfg.research_history_days))

    log_cfg = data.get("logging", {})
    if "logs_dir" in log_cfg and log_cfg["logs_dir"]:
        cfg.logs_dir = _resolve_path(log_cfg["logs_dir"])

    sftp_cfg = data.get("upload", {})
    cfg.sftp_host = sftp_cfg.get("sftp_host", cfg.sftp_host)
    cfg.sftp_port = int(sftp_cfg.get("sftp_port", cfg.sftp_port))
    cfg.sftp_max_retries = int(sftp_cfg.get("max_retries", cfg.sftp_max_retries))

    return cfg
