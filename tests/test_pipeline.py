"""
Unit and Integration Test Suite for Microstock Generator Pipeline.
"""

import tempfile
from pathlib import Path
import numpy as np
from PIL import Image

from src.pipeline.config import load_config
from src.pipeline.categories import normalize_category_id
from src.pipeline.compliance import sanitize_filename, lint_title, lint_keywords
from src.pipeline.dedup import filter_near_duplicates
from src.pipeline.postprocess import (
    clean_stray_pixels,
    tight_crop_rgba,
    normalize_alpha_confidence,
    guided_filter_alpha,
    decontaminate_rgb_fringes,
    color_projection_matting,
    PostProcessor,
)
from src.pipeline.validator import TechnicalValidator
from src.pipeline.local_metadata import LocalMetadataEngine
from src.pipeline.metadata import MetadataEngine
from src.pipeline.coordinator import classify_asset_type


def test_local_metadata_engine():
    # Test category inference
    cat_id, cat_name = LocalMetadataEngine.infer_category("cute watercolor christmas cat")
    assert cat_id == 1  # Animals
    assert cat_name == "Animals"

    cat_id, cat_name = LocalMetadataEngine.infer_category("modern luxury kitchen interior")
    assert cat_id == 2  # Buildings and Architecture

    # Test title generation
    title = LocalMetadataEngine.generate_title("cute watercolor christmas cat", asset_type="isolated")
    assert "Cute" in title
    assert "Cat" in title
    assert len(title) <= 70
    assert "," not in title

    # Test keyword expansion
    keywords = LocalMetadataEngine.generate_keywords("cute watercolor christmas cat", asset_type="isolated", max_count=40)
    assert len(keywords) >= 20
    assert "cat" in keywords
    assert "christmas" in keywords
    assert "isolated" in keywords
    assert "white background" in keywords


def test_config_loading():
    cfg = load_config()
    assert cfg.min_megapixels == 4.0
    assert cfg.max_file_size_mb == 45.0
    assert cfg.max_filename_chars == 30
    assert cfg.model_isolated == "ultramix-balanced-4x"
    assert cfg.model_scene == "high-fidelity-4x"
    assert cfg.bg_model == "birefnet-general-lite"


def test_auto_asset_classification():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # White studio background with colored center -> isolated
        iso = Image.new("RGB", (100, 100), (255, 255, 255))
        for x in range(30, 70):
            for y in range(30, 70):
                iso.putpixel((x, y), (200, 20, 20))
        p_iso = tmp_path / "iso.jpg"
        iso.save(p_iso)
        assert classify_asset_type(p_iso) == "isolated"

        # Dark / environmental background -> scene
        scene = Image.new("RGB", (100, 100), (45, 20, 15))
        p_scene = tmp_path / "scene.jpg"
        scene.save(p_scene)
        assert classify_asset_type(p_scene) == "scene"


def test_ultimate_alpha_and_antihalo():
    # 1. Confidence normalization: shadow <=35 -> 0, interior >=215 -> 255
    alpha = np.array([[0, 30, 125, 220, 255]], dtype=np.uint8)
    norm = normalize_alpha_confidence(alpha, low_cut=35, high_snap=215)
    assert norm[0, 0] == 0
    assert norm[0, 1] == 0      # shadow killed
    assert norm[0, 3] == 255    # interior locked solid
    assert norm[0, 4] == 255

    # 2. Nearest-foreground RGB extrapolation (anti-halo)
    rgb = np.full((10, 10, 3), 255, dtype=np.uint8)
    rgb[3:7, 3:7] = [0, 120, 40]  # Dark green foreground
    a_mask = np.zeros((10, 10), dtype=np.uint8)
    a_mask[3:7, 3:7] = 255
    a_mask[2, 3:7] = 128          # Semi-transparent fringe with white RGB

    decontam = decontaminate_rgb_fringes(rgb, a_mask)
    assert list(decontam[2, 4]) == [0, 120, 40]  # White halo replaced with foreground green
    assert list(decontam[0, 0]) == [0, 0, 0]     # Transparent background zeroed

    # 3. Guided filter preserves shape without error
    gf = guided_filter_alpha(rgb, a_mask, radius=2)
    assert gf.shape == a_mask.shape
    assert gf[4, 4] == 255


def test_color_projection_matting():
    # White background (255,255,255), gold foreground (220,170,80) in center 20..40
    raw_rgb = np.full((60, 60, 3), 255, dtype=np.uint8)
    raw_rgb[20:40, 20:40] = [220, 170, 80]

    # Simulate overshot AI mask extending 3px into white background (17..43)
    ai_alpha = np.zeros((60, 60), dtype=np.uint8)
    ai_alpha[17:43, 17:43] = 255

    refined = color_projection_matting(raw_rgb, ai_alpha, scale_ratio=1.0)
    assert refined[30, 30] == 255  # Solid gold interior preserved
    assert refined[18, 30] == 0    # Overshot white background killed to 0!


def test_filename_sanitization():
    # Long filename with special characters
    long_name = "My Beautiful_Vintage Mushroom & Flowers! 2026 Edition"
    clean = sanitize_filename(long_name, ext=".png", max_len=30)
    assert len(clean) <= 30
    assert clean.endswith(".png")
    assert "!" not in clean
    assert "&" not in clean


def test_compliance_title_and_keywords():
    raw_title = "Generative AI Cute Dog by Picasso, trending on Artstation, 4k"
    cleaned_title, warnings = lint_title(raw_title, max_chars=70)
    assert "generative ai" not in cleaned_title.lower()
    assert "picasso" not in cleaned_title.lower()
    assert "," not in cleaned_title

    raw_keywords = ["dog", "generative AI", "cute", "puppy", "dog", "nike", "digital art", "trending"]
    cleaned_kw, kw_warnings = lint_keywords(raw_keywords, max_count=50)
    assert "generative ai" not in cleaned_kw
    assert "nike" not in cleaned_kw
    assert "trending" not in cleaned_kw
    assert cleaned_kw.count("dog") == 1  # Deduplicated


def test_category_normalization():
    assert normalize_category_id(1) == 1
    assert normalize_category_id("animals") == 1
    assert normalize_category_id("Graphic Resources") == 8
    assert normalize_category_id(999) == 8  # Fallback to 8


def test_deduplication_phash():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # img1: top-left quadrant black
        img1 = Image.new("RGB", (100, 100), color=(255, 255, 255))
        for x in range(50):
            for y in range(50):
                img1.putpixel((x, y), (0, 0, 0))

        # img2: exact copy of img1
        img2 = img1.copy()

        # img3: bottom-right quadrant black + diagonal
        img3 = Image.new("RGB", (100, 100), color=(255, 255, 255))
        for x in range(50, 100):
            for y in range(50, 100):
                img3.putpixel((x, y), (0, 0, 0))
        for i in range(100):
            img3.putpixel((i, i), (0, 0, 0))

        p1 = tmp_path / "img1.png"
        p2 = tmp_path / "img2.png"
        p3 = tmp_path / "img3.png"

        img1.save(p1)
        img2.save(p2)
        img3.save(p3)

        kept, rejected = filter_near_duplicates([p1, p2, p3], threshold=4)
        assert len(kept) == 2
        assert len(rejected) == 1
        assert p2 in [r[0] for r in rejected]


def test_stray_pixel_cleaning():
    # 50x50 alpha channel with main 20x20 block and isolated single pixel dots
    alpha = np.zeros((50, 50), dtype=np.uint8)
    alpha[10:30, 10:30] = 255  # Main block (area 400)
    alpha[5, 5] = 255           # Stray 1-pixel dot
    alpha[45, 45] = 255         # Stray 1-pixel dot

    cleaned = clean_stray_pixels(alpha, min_area=30)
    assert cleaned[10, 10] == 255
    assert cleaned[5, 5] == 0
    assert cleaned[45, 45] == 0


def test_tight_crop():
    # 200x200 canvas with a 50x50 subject in the center
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    subject = Image.new("RGBA", (50, 50), (255, 100, 50, 255))
    img.paste(subject, (75, 75))

    cropped = tight_crop_rgba(img, margin_pct=0.02)
    assert cropped.size[0] < 200
    assert cropped.size[1] < 200
    assert cropped.size[0] >= 50
    assert cropped.size[1] >= 50


def test_validator_and_csv_export():
    cfg = load_config()
    validator = TechnicalValidator(cfg)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Valid 2000x2000 image (= 4.0 MP)
        img = Image.new("RGBA", (2000, 2000), (255, 255, 255, 255))
        test_file = tmp_path / "valid_test.png"
        img.save(test_file)

        res = validator.validate_asset(test_file, asset_type="isolated")
        assert res["is_valid"] is True
        assert res["stats"]["megapixels"] == 4.0

        # Test CSV generation
        csv_file = tmp_path / "test_metadata.csv"
        records = [{
            "filename": "valid_test.png",
            "title": "Cute Happy Golden Retriever Puppy",
            "keywords": ["dog", "puppy", "golden retriever", "happy", "pet"],
            "category_id": 1,
            "releases": ""
        }]
        MetadataEngine.export_adobe_csv(records, csv_file)
        assert csv_file.exists()
        content = csv_file.read_text(encoding="utf-8-sig")
        assert "Filename,Title,Keywords,Category,Releases" in content
        assert "valid_test.png" in content


def test_scene_jpeg_srgb():
    cfg = load_config()
    pp = PostProcessor(cfg)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        src = tmp_path / "scene_in.png"
        dst = tmp_path / "scene_out.jpg"
        Image.new("RGB", (2000, 2000), (120, 80, 40)).save(src)
        ok, err = pp.process_scene_jpeg(src, dst)
        assert ok is True, f"process_scene_jpeg failed: {err}"
        assert dst.exists()
        with Image.open(dst) as out_img:
            assert out_img.format == "JPEG"
            assert "icc_profile" in out_img.info


def test_punch_enclosed_background_holes():
    from src.pipeline.postprocess import punch_enclosed_background_holes

    # 200x200 white studio background
    rgb = np.full((200, 200, 3), 255, dtype=np.uint8)
    alpha = np.zeros((200, 200), dtype=np.uint8)

    # 1. Dark green foreground block with a 20x20 trapped white hole inside
    rgb[30:90, 30:90] = [20, 70, 25]
    rgb[50:70, 50:70] = [255, 255, 255]
    alpha[30:90, 30:90] = 255

    # 2. Bright gold/cream glossy ball with a 12x12 specular white highlight inside
    rgb[110:170, 110:170] = [240, 225, 180]
    rgb[134:146, 134:146] = [255, 255, 255]
    alpha[110:170, 110:170] = 255

    out = punch_enclosed_background_holes(rgb, alpha, scale_ratio=1.0)
    # Trapped dark-rimmed hole must be punched to 0
    assert out[60, 60] == 0
    # Glossy bright-ringed specular highlight must be preserved at 255
    assert out[140, 140] == 255


def test_remove_white_matte_smart():
    from src.pipeline.postprocess import remove_white_matte_smart

    # 40x40 image with dark green foreground (20, 100, 30)
    rgb = np.full((40, 40, 3), 255, dtype=np.uint8)
    rgb[10:30, 10:30] = [20, 100, 30]

    # Semi-transparent border at y=9, x=10..30 with alpha=100 and white blended RGB
    # True blended RGB: 0.39 * [20,100,30] + 0.61 * [255,255,255] = [163, 194, 167]
    alpha = np.zeros((40, 40), dtype=np.uint8)
    alpha[10:30, 10:30] = 255
    alpha[9, 10:30] = 100
    rgb[9, 10:30] = [163, 194, 167]

    clean_rgb, clean_a = remove_white_matte_smart(rgb, alpha, alpha_floor=20)
    # The semi-transparent border must have white matte removed, restoring dark green color!
    assert clean_rgb[9, 20][1] < 120  # Green channel is dark, not pale pastel white
    assert clean_rgb[0, 0][0] == 0    # Transparent pixels zeroed
    assert clean_a[9, 20] > 0         # Fringe retained without stepping


def test_cross_platform_upscayl_discovery():
    from src.pipeline.upscaler import find_upscayl_binary_and_models, UpscaylEngine

    # Test with non-existent custom paths -> gracefully handles without crash
    b, m = find_upscayl_binary_and_models(
        custom_bin=Path("/path/to/fake_upscayl_bin"),
        custom_models=Path("/path/to/fake_models")
    )
    # Returns tuple
    assert isinstance(b, (Path, type(None)))
    assert isinstance(m, (Path, type(None)))

    # Engine initialization should succeed without crashing
    cfg = load_config()
    engine = UpscaylEngine(cfg)
    assert hasattr(engine, "verify_binary")
    assert isinstance(engine.get_installation_instructions(), str)


def test_input_output_folder_options():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        in_dir = tmp_path / "custom_input"
        out_dir = tmp_path / "custom_output"
        bg_dir = tmp_path / "custom_cutouts"
        in_dir.mkdir()

        cfg = load_config()
        cfg.base_dir = in_dir
        cfg.output_dir = out_dir
        cfg.bg_output_dir = bg_dir
        cfg.remove_bg = False

        assert cfg.base_dir == in_dir
        assert cfg.output_dir == out_dir
        assert cfg.bg_output_dir == bg_dir
        assert cfg.remove_bg is False


def test_filename_sanitization_and_length_compliance():
    # Long filename with special characters, emojis, and spaces
    ugly_name = "Super Long Image Name With Spaces & Emojis 🎉 2026! Over Limit File"
    clean_name = sanitize_filename(ugly_name, ext=".png", max_len=30)
    
    assert len(clean_name) <= 30
    assert clean_name.endswith(".png")
    assert " " not in clean_name
    assert "!" not in clean_name
    assert "&" not in clean_name
    assert "🎉" not in clean_name
    assert clean_name.isascii()


def test_run_logger_txt_output():
    from src.pipeline.logger import RunLogger

    with tempfile.TemporaryDirectory() as tmp_dir:
        logger = RunLogger(Path(tmp_dir), run_name="test")
        logger.log("Hello microstock")
        logger.write_summary(["Passed: 5", "Failed: 0"])
        log_path = logger.get_path()
        assert log_path.exists()
        assert log_path.suffix == ".txt"
        content = log_path.read_text(encoding="utf-8")
        assert "Hello microstock" in content
        assert "Passed: 5" in content


def test_high_demand_researcher_offline_prompt_pack():
    from src.pipeline.llm_router import FreeTierLLMRouter
    from src.pipeline.researcher import HighDemandResearcher, get_upcoming_seasonal_themes

    window_label, themes = get_upcoming_seasonal_themes()
    assert len(window_label) > 0
    assert len(themes) >= 1

    # Force offline router (no keys) to test deterministic commercial blueprint output
    router = FreeTierLLMRouter(min_delay_sec=0)
    router.groq_key = ""
    router.gemini_key = ""
    router.mistral_key = ""
    router.openrouter_key = ""

    researcher = HighDemandResearcher(llm_router=router)
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = researcher.run_research(Path(tmp_dir), count=6, log_callback=lambda *_: None)
        assert res["count"] == 6
        assert res["txt_path"].exists()
        assert res["json_path"].exists()
        txt = res["txt_path"].read_text(encoding="utf-8")
        assert "PROMPT (COPY BELOW):" in txt
        assert "Suggested File:" in txt
        assert "no text" in txt.lower()
        for p in res["prompts"]:
            assert len(p["suggested_filename"]) <= 30
            assert p["suggested_filename"].endswith((".jpg", ".png"))


def test_vision_qa_auditor_offline_fallback():
    from src.pipeline.llm_router import FreeTierLLMRouter
    from src.pipeline.qa_auditor import VisionQAAuditor

    cfg = load_config()
    router = FreeTierLLMRouter(min_delay_sec=0)
    router.gemini_key = ""
    router.openrouter_key = ""
    auditor = VisionQAAuditor(cfg, llm_router=router)

    with tempfile.TemporaryDirectory() as tmp_dir:
        img_path = Path(tmp_dir) / "modern_office_desk.jpg"
        Image.new("RGB", (600, 400), (200, 180, 160)).save(img_path)
        res = auditor.audit_and_generate_metadata(img_path, asset_type="scene", prompt_hint="modern office desk")
        assert res["passed"] is True
        assert len(res["title"]) <= 70
        assert len(res["keywords"]) >= 20
        assert res["suggested_filename"].endswith(".jpg")
        assert len(res["suggested_filename"]) <= 30


def test_secret_redaction_in_logger():
    import os
    from src.pipeline.logger import RunLogger, redact_secrets

    fake_key = "dummy_test_secret_token_999999"
    prev = os.environ.get("GROQ_API_KEY")
    os.environ["GROQ_API_KEY"] = fake_key
    try:
        assert fake_key not in redact_secrets(f"Error with {fake_key} and Bearer abc123xyz and ?key=dummy_query_999")
        assert "dummy_query_999" not in redact_secrets("https://example.com/api?key=dummy_query_999&x=1")

        with tempfile.TemporaryDirectory() as tmp_dir:
            logger = RunLogger(Path(tmp_dir), run_name="sec")
            logger.log(f"Leaked test: {fake_key} Bearer tok_999", to_stdout=False)
            content = logger.get_path().read_text(encoding="utf-8")
            assert fake_key not in content
            assert "tok_999" not in content
            assert "[REDACTED]" in content
    finally:
        if prev is None:
            os.environ.pop("GROQ_API_KEY", None)
        else:
            os.environ["GROQ_API_KEY"] = prev


def test_sftp_uploader_discovery_and_antidup():
    from src.pipeline.manifest import ManifestManager, calculate_file_hash
    from src.pipeline.uploader import AdobeSFTPUploader

    cfg = load_config()
    uploader = AdobeSFTPUploader(cfg)

    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        res_dir = base / "batch1" / "result"
        res_dir.mkdir(parents=True)
        # Prompts folder should be ignored
        (base / "prompts").mkdir()

        img1 = res_dir / "asset_01.jpg"
        img2 = res_dir / "asset_02.png"
        Image.new("RGB", (100, 100), (120, 120, 120)).save(img1)
        Image.new("RGBA", (100, 100), (120, 120, 120, 255)).save(img2)

        # Before marking uploaded: both discovered
        pending = uploader.discover_pending_files(base)
        assert len(pending) == 2

        # Dry run reports 2 pending, 0 uploaded
        dry = uploader.upload_pending(base, dry_run=True, log_callback=lambda *_: None)
        assert dry["pending"] == 2
        assert dry["uploaded"] == 0

        # Mark img1 as uploaded -> only img2 should remain pending
        manifest = ManifestManager(res_dir / "manifest.json")
        manifest.mark_uploaded(calculate_file_hash(img1), img1.name)
        pending_after = uploader.discover_pending_files(base)
        assert len(pending_after) == 1
        assert pending_after[0][0].name == "asset_02.png"


def test_commercial_prompt_linter_adobe_rules():
    from src.pipeline.compliance import lint_commercial_prompt

    dirty_scene = (
        "Luxury cafe in front of Eiffel Tower in the style of Van Gogh, "
        "iPhone on table, masterpiece, award winning, 8k resolution, photorealistic"
    )
    clean_scene, warnings = lint_commercial_prompt(dirty_scene, asset_type="scene")
    low = clean_scene.lower()
    assert "eiffel tower" not in low
    assert "van gogh" not in low
    assert "in the style of" not in low
    assert "iphone" not in low
    assert "masterpiece" not in low
    assert "photorealistic" not in low
    assert "copy space" in low
    assert "no text" in low
    assert "no logos" in low
    assert "no watermarks" in low
    assert len(warnings) >= 4

    dirty_iso = "Ceramic coffee cup with Nike logo, octane render"
    clean_iso, _ = lint_commercial_prompt(dirty_iso, asset_type="isolated")
    low_iso = clean_iso.lower()
    assert "nike" not in low_iso
    assert "octane render" not in low_iso
    assert "white background" in low_iso
    assert "no drop shadow" in low_iso
    assert "no text" in low_iso


def test_incremental_per_file_skip_already_in_result():
    from src.pipeline.coordinator import PipelineCoordinator

    cfg = load_config()
    cfg.skip_upscale = True
    cfg.remove_bg = False
    cfg.enable_ai_qa = False
    cfg.enable_vision_metadata = False
    cfg.embed_iptc_metadata = False
    cfg.export_csv = True

    with tempfile.TemporaryDirectory() as tmp_dir:
        batch = Path(tmp_dir) / "workspace_batch"
        raw_dir = batch / "raw"
        raw_dir.mkdir(parents=True)

        # Run 1: 1st raw image (2100x2000 = 4.2 MP)
        img1 = Image.new("RGB", (2100, 2000), (120, 90, 60))
        img1.save(raw_dir / "oak_desk_01.jpg", format="JPEG")

        coord = PipelineCoordinator(cfg)
        res1 = coord.process_batch_folder(batch, asset_type="scene")
        assert res1["passed"] == 1
        assert res1["skipped"] == 0

        # Run 2: add 2nd raw image -> 1st must be skipped, only 2nd processed
        img2 = Image.new("RGB", (2100, 2000), (40, 110, 140))
        img2.save(raw_dir / "solar_panel_02.jpg", format="JPEG")

        res2 = coord.process_batch_folder(batch, asset_type="scene")
        assert res2["skipped"] == 1
        assert res2["passed"] == 1

        csv_text = (batch / "result" / "adobe_stock_metadata.csv").read_text(encoding="utf-8-sig")
        assert "oak_desk_01.jpg" in csv_text
        assert "solar_panel_02.jpg" in csv_text

        # Run 3: no new images -> both skipped, 0 processed
        res3 = coord.process_batch_folder(batch, asset_type="scene")
        assert res3["skipped"] == 2
        assert res3["passed"] == 0


def test_llm_router_circuit_breaker_skips_dead_provider():
    from src.pipeline.llm_router import FreeTierLLMRouter

    router = FreeTierLLMRouter(min_delay_sec=0, timeout_sec=5)
    router.gemini_key = "dummy_key_1"
    router.mistral_key = ""
    router.openrouter_key = "dummy_key_2"

    assert router.available_vision_providers() == ["gemini", "openrouter"]

    # Simulate permanent/quota error on gemini -> circuit breaker must disable it immediately
    router._record_failure("gemini", "429 RESOURCE_EXHAUSTED: daily quota exceeded")
    assert router.available_vision_providers() == ["openrouter"]

    # Simulate 2 consecutive timeouts on openrouter -> circuit breaker disables it too
    router._record_failure("openrouter", "timed out")
    assert router.available_vision_providers() == ["openrouter"]  # 1st timeout still allowed
    router._record_failure("openrouter", "timed out")
    assert router.available_vision_providers() == []  # 2nd consecutive timeout trips breaker


def test_upcoming_seasonal_window_3_to_4_months():
    from datetime import date
    from src.pipeline.researcher import get_upcoming_seasonal_themes, get_upcoming_target_months

    ref = date(2026, 11, 26)
    window_label, themes = get_upcoming_seasonal_themes(today=ref)
    months = get_upcoming_target_months(today=ref)
    assert window_label == "Feb 2027 - Mar 2027"
    assert months == [2, 3]
    assert any("Ramadan" in t["theme"] or "Spring" in t["theme"] for t in themes)


def test_daily_research_no_repeats_across_consecutive_days():
    from datetime import date, timedelta
    from src.pipeline.llm_router import FreeTierLLMRouter
    from src.pipeline.prompt_library import assess_isolation_risk
    from src.pipeline.researcher import HighDemandResearcher

    router = FreeTierLLMRouter(min_delay_sec=0)
    router.groq_key = ""
    router.gemini_key = ""
    router.mistral_key = ""
    router.openrouter_key = ""

    researcher = HighDemandResearcher(llm_router=router)
    base_day = date(2026, 11, 26)
    seen_subjects = set()
    all_prompts = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        for day_offset in range(3):
            res = researcher.run_research(
                out_dir,
                count=12,
                today=base_day + timedelta(days=day_offset),
                log_callback=lambda *_: None,
            )
            assert res["count"] == 12
            assert res["history_path"].exists()
            txt = res["txt_path"].read_text(encoding="utf-8")
            assert "NEGATIVE PROMPT" in txt
            for p in res["prompts"]:
                key = (p["asset_type"], p["subject"].lower())
                assert key not in seen_subjects, f"Duplicate subject generated across daily runs: {key}"
                seen_subjects.add(key)
                all_prompts.append(p)
                if p["asset_type"] == "isolated":
                    low = p["prompt"].lower()
                    assert "#ffffff" in low
                    assert "f/11" in low
                    assert "no drop shadow" in low
                    assert assess_isolation_risk(p["prompt"]) == []

    assert len(all_prompts) == 36


def test_isolated_edge_risk_and_pinhole_and_png_srgb():
    from unittest.mock import patch
    from src.pipeline.postprocess import fill_interior_pinholes
    from src.pipeline.prompt_library import assess_isolation_risk

    # 1. Edge-risk detector catches problematic materials for isolated cutouts
    risks = assess_isolation_risk("iced coffee in clear glass with condensation droplets and steam")
    assert any("glass" in r for r in risks)
    assert any("droplets" in r for r in risks)
    assert any("steam" in r for r in risks)
    assert assess_isolation_risk("matte ceramic coffee mug on pure white background, no glass, no steam") == []

    # 2. Pinhole sealing closes tiny interior pixel cracks while keeping real cutouts and exterior open
    alpha = np.zeros((100, 100), dtype=np.uint8)
    alpha[10:90, 10:90] = 255
    alpha[25:30, 25:30] = 0    # 5x5 = 25 px micro pixel gap (celah pixel) -> MUST be sealed to 255
    alpha[50:70, 50:70] = 0    # 20x20 = 400 px genuine hole (e.g. mug handle) -> MUST stay 0
    sealed = fill_interior_pinholes(alpha, max_pinhole_area=64)
    assert sealed[27, 27] == 255
    assert sealed[60, 60] == 0
    assert sealed[0, 0] == 0

    # 3. process_isolated_png embeds sRGB ICC profile and seals micro pixel cracks
    cfg = load_config()
    pp = PostProcessor(cfg)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        src = tmp_path / "iso_in.png"
        dst = tmp_path / "iso_out.png"

        rgb = np.full((2200, 2200, 3), 255, dtype=np.uint8)
        rgb[300:1900, 300:1900] = [180, 70, 50]
        Image.fromarray(rgb, mode="RGB").save(src)

        mock_alpha = np.zeros((2200, 2200), dtype=np.uint8)
        mock_alpha[300:1900, 300:1900] = 255
        mock_alpha[1000:1004, 1000:1004] = 0  # 4x4 interior pixel crack
        mock_rgba = Image.fromarray(np.dstack((rgb, mock_alpha)), mode="RGBA")

        with patch.object(pp, "get_bg_session", return_value=object()), \
             patch("src.pipeline.postprocess.rembg.remove", return_value=mock_rgba):
            ok, err = pp.process_isolated_png(src, dst)
            assert ok is True, f"process_isolated_png failed: {err}"
            with Image.open(dst) as out_img:
                assert out_img.format == "PNG"
                assert out_img.mode == "RGBA"
                assert "icc_profile" in out_img.info
                out_alpha = np.array(out_img)[:, :, 3]
                # Center pixel crack inside subject must be solid 255
                cy, cx = out_alpha.shape[0] // 2, out_alpha.shape[1] // 2
                assert out_alpha[cy, cx] == 255


def test_missing_result_asset_mid_run_skips_without_crash():
    from src.pipeline.coordinator import PipelineCoordinator

    cfg = load_config()
    cfg.skip_upscale = True
    cfg.remove_bg = False
    cfg.enable_ai_qa = False
    cfg.enable_vision_metadata = False
    cfg.embed_iptc_metadata = False
    cfg.export_csv = True

    with tempfile.TemporaryDirectory() as tmp_dir:
        batch = Path(tmp_dir) / "mid_delete_batch"
        raw_dir = batch / "raw"
        raw_dir.mkdir(parents=True)

        # Make img_a and img_b perceptually distinct so pHash dedup keeps both
        arr_a = np.full((2000, 2100, 3), 240, dtype=np.uint8)
        arr_a[100:900, 100:900] = [140, 40, 40]
        Image.fromarray(arr_a, mode="RGB").save(raw_dir / "img_a.jpg", format="JPEG")

        arr_b = np.full((2000, 2100, 3), 240, dtype=np.uint8)
        arr_b[1000:1900, 1000:1900] = [30, 120, 160]
        Image.fromarray(arr_b, mode="RGB").save(raw_dir / "img_b.jpg", format="JPEG")

        coord = PipelineCoordinator(cfg)
        real_process_scene = coord.postprocessor.process_scene_jpeg

        def delete_first_after_second(src, dst, log_callback=print):
            ok, err = real_process_scene(src, dst, log_callback=log_callback)
            if dst.name == "img_b.jpg":
                first_out = dst.parent / "img_a.jpg"
                if first_out.exists():
                    first_out.unlink()  # Simulate user manually deleting asset mid-run
            return ok, err

        coord.postprocessor.process_scene_jpeg = delete_first_after_second

        res = coord.process_batch_folder(batch, asset_type="scene")
        assert res["passed"] == 1
        csv_text = (batch / "result" / "adobe_stock_metadata.csv").read_text(encoding="utf-8-sig")
        assert "img_b.jpg" in csv_text
        assert "img_a.jpg" not in csv_text

        # Re-running must skip manually deleted img_a.jpg and already-ready img_b.jpg cleanly
        res2 = coord.process_batch_folder(batch, asset_type="scene")
        assert res2["passed"] == 0
        assert res2["skipped"] == 2


def test_retry_recovers_missing_metadata_and_csv_only():
    from src.pipeline.coordinator import PipelineCoordinator

    cfg = load_config()
    cfg.skip_upscale = True
    cfg.remove_bg = False
    cfg.enable_ai_qa = False
    cfg.enable_vision_metadata = False
    cfg.embed_iptc_metadata = False
    cfg.export_csv = True

    with tempfile.TemporaryDirectory() as tmp_dir:
        batch = Path(tmp_dir) / "recover_batch"
        raw_dir = batch / "raw"
        result_dir = batch / "result"
        raw_dir.mkdir(parents=True)
        result_dir.mkdir(parents=True)

        # Both raw and result exist, but CSV and manifest.json are missing (mid-run crash simulation)
        Image.new("RGB", (2100, 2000), (130, 95, 70)).save(raw_dir / "desk_01.jpg", format="JPEG")
        Image.new("RGB", (2100, 2000), (130, 95, 70)).save(result_dir / "desk_01.jpg", format="JPEG")

        coord = PipelineCoordinator(cfg)

        def fail_if_reprocessed(*args, **kwargs):
            raise AssertionError("Should NOT re-run post-processing when result/ already has the asset!")

        coord.postprocessor.process_scene_jpeg = fail_if_reprocessed

        res = coord.process_batch_folder(batch, asset_type="scene")
        assert res["reconciled"] == 1
        assert (result_dir / "manifest.json").exists()
        csv_path = result_dir / "adobe_stock_metadata.csv"
        assert csv_path.exists()
        csv_text = csv_path.read_text(encoding="utf-8-sig")
        assert "desk_01.jpg" in csv_text

        # Stale CSV pruning: remove desk_01.jpg and add desk_02.jpg in raw+result, then re-run
        (result_dir / "desk_01.jpg").unlink()
        (raw_dir / "desk_01.jpg").unlink()
        Image.new("RGB", (2100, 2000), (60, 120, 90)).save(raw_dir / "desk_02.jpg", format="JPEG")
        Image.new("RGB", (2100, 2000), (60, 120, 90)).save(result_dir / "desk_02.jpg", format="JPEG")

        res2 = coord.process_batch_folder(batch, asset_type="scene")
        assert res2["reconciled"] == 1
        csv_text2 = csv_path.read_text(encoding="utf-8-sig")
        assert "desk_02.jpg" in csv_text2
        assert "desk_01.jpg" not in csv_text2







