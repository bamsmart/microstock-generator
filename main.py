#!/usr/bin/env python3
"""
===================================================================
 Microstock Generator (Hybrid Free-Tier Pipeline 2.1)
===================================================================
 Hybrid End-to-End Microstock Automation (Rp 0 / Free-Tier):
   - Step 1 (--research): High-Demand Seasonal & Trend Research ->
     Commercial-Grade Copy-Paste Prompt Pack (.txt & .json)
   - Step 2 & 3 (Manual): Copy-paste prompts & place raw assets in batch/raw/
   - Step 4 (Default): Free-Tier Vision QC + Adobe Stock SEO Metadata +
     4x Upscayl + Anti-Halo Cutout/sRGB JPEG + CSV/IPTC + .txt Run Log
===================================================================
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

# Ensure UTF-8 output on Windows / multi-platform terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

from src.pipeline.config import PROJECT_ROOT, load_config
from src.pipeline.coordinator import PipelineCoordinator
from src.pipeline.llm_router import FreeTierLLMRouter
from src.pipeline.logger import RunLogger
from src.pipeline.metadata import MetadataEngine
from src.pipeline.researcher import HighDemandResearcher
from src.pipeline.uploader import AdobeSFTPUploader


def print_banner(log_fn=print):
    log_fn("""
===================================================================
 🎨 MICROSTOCK GENERATOR (HYBRID FREE-TIER PIPELINE 2.1)
 ⚡ Step 1: High-Demand Research -> Commercial Prompts (.txt)
 ⚡ Step 4: Free-Tier Vision QC + SEO + Upscale + Compliance + .txt Log
===================================================================
""")


VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


def get_available_input_folders(base_dir: Path):
    """Finds valid batch subfolders inside base_dir."""
    if not base_dir.exists():
        base_dir.mkdir(parents=True, exist_ok=True)
        return []

    return sorted(
        [
            d for d in base_dir.iterdir()
            if d.is_dir()
            and not d.name.startswith(".")
            and not d.name.endswith("_upscaled")
            and not d.name.endswith("_result")
            and not d.name.endswith("_rejected_qa")
            and not d.name.endswith("_rejected_similar")
            and not d.name.endswith("_temp_in")
            and not d.name.endswith("_temp_isolated")
            and not d.name.endswith("_temp_scene")
            and d.name not in ("result", "raw", "upscaled", "rejected_qa", "rejected_similar", "rejected_ai_qa", "prompts", "logs")
        ],
        key=lambda p: p.name
    )


def ensure_desktop_launchers(base_dir: Path, project_root: Path):
    """Generates 1-click execution shortcuts inside the default desktop working directory."""
    desktop = Path.home() / "Desktop"
    try:
        resolved_base = base_dir.resolve()
        if desktop.exists() and (resolved_base == (desktop / "microstock_generator") or desktop in resolved_base.parents):
            pass
        else:
            return

        base_dir.mkdir(parents=True, exist_ok=True)
        mac_launcher = base_dir / "Run_Microstock_Generator.command"
        if not mac_launcher.exists():
            with open(mac_launcher, "w", encoding="utf-8") as f:
                f.write(f'#!/usr/bin/env bash\ncd "{project_root}" && ./Run_Microstock_Generator.command "$@"\n')
            mac_launcher.chmod(0o755)

        mac_research_launcher = base_dir / "Run_Step1_Research.command"
        if not mac_research_launcher.exists():
            with open(mac_research_launcher, "w", encoding="utf-8") as f:
                f.write(f'#!/usr/bin/env bash\ncd "{project_root}" && ./Run_Step1_Research.command "$@"\n')
            mac_research_launcher.chmod(0o755)

        mac_upload_launcher = base_dir / "Run_Step5_Upload.command"
        if not mac_upload_launcher.exists():
            with open(mac_upload_launcher, "w", encoding="utf-8") as f:
                f.write(f'#!/usr/bin/env bash\ncd "{project_root}" && ./Run_Step5_Upload.command "$@"\n')
            mac_upload_launcher.chmod(0o755)

        win_launcher = base_dir / "Run_Microstock_Generator.bat"
        if not win_launcher.exists():
            with open(win_launcher, "w", encoding="utf-8") as f:
                f.write(f'@echo off\ncd /d "{project_root}"\ncall run.bat %*\n')

        linux_launcher = base_dir / "run_microstock_generator.sh"
        if not linux_launcher.exists():
            with open(linux_launcher, "w", encoding="utf-8") as f:
                f.write(f'#!/usr/bin/env bash\ncd "{project_root}" && ./run.sh "$@"\n')
            linux_launcher.chmod(0o755)
    except Exception:
        pass


def resolve_prompts_dir(config) -> Path:
    """Resolve prompt output directory: explicit prompts_dir > <base_dir>/prompts, with safe fallback."""
    target = config.prompts_dir or (config.base_dir / "prompts")
    try:
        target.mkdir(parents=True, exist_ok=True)
        return target
    except (PermissionError, OSError):
        fallback = PROJECT_ROOT / "output" / "prompts"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def run_research_step(config, count: int, niche: Optional[str] = None):
    run_logger = RunLogger(config.logs_dir, run_name="research")
    print_banner(run_logger.log)

    ensure_desktop_launchers(config.base_dir, PROJECT_ROOT)
    prompts_dir = resolve_prompts_dir(config)

    router = FreeTierLLMRouter(
        gemini_model=config.gemini_text_model,
        groq_model=config.groq_model,
        mistral_model=config.mistral_model,
        openrouter_text_model=config.openrouter_text_model,
        openrouter_vision_model=config.openrouter_vision_model,
        min_delay_sec=config.free_tier_delay_sec,
    )
    researcher = HighDemandResearcher(llm_router=router)
    result = researcher.run_research(
        output_dir=prompts_dir,
        count=count,
        niche_focus=niche,
        log_callback=run_logger.log,
    )

    run_logger.write_summary([
        f"Mode            : STEP 1 HIGH-DEMAND RESEARCH",
        f"Buyer Window    : {result['target_window']}",
        f"Provider Used   : {result['provider']}",
        f"Prompts Created : {result['count']}",
        f"Prompt Pack TXT : {result['txt_path']}",
        f"Prompt Pack JSON: {result['json_path']}",
    ])
    return result


def run_upload_step(config, dry_run: bool = False):
    run_logger = RunLogger(config.logs_dir, run_name="upload")
    print_banner(run_logger.log)

    ensure_desktop_launchers(config.base_dir, PROJECT_ROOT)
    uploader = AdobeSFTPUploader(config)
    result = uploader.upload_pending(
        base_dir=config.base_dir,
        custom_output=config.output_dir,
        dry_run=dry_run,
        log_callback=run_logger.log,
    )

    run_logger.write_summary([
        f"Mode            : STEP 5 ADOBE STOCK SFTP UPLOAD ({'DRY-RUN' if dry_run else 'LIVE'})",
        f"SFTP Host       : {uploader.host}:{uploader.port}",
        f"Transport       : {uploader.available_transport()}",
        f"Pending Found   : {result['pending']}",
        f"Uploaded        : {result['uploaded']}",
        f"Failed          : {result['failed']}",
    ])
    return result


def run_auto_pipeline(
    coordinator: PipelineCoordinator,
    asset_type: str = "auto",
    custom_output: Optional[Path] = None,
):
    log = coordinator.log
    print_banner(log)
    cfg = coordinator.config
    base_dir = cfg.base_dir

    ensure_desktop_launchers(base_dir, PROJECT_ROOT)

    log(f"📁 Source Folder      : {base_dir}")
    if custom_output:
        log(f"📂 Output Folder      : {custom_output}")
    elif cfg.output_dir:
        log(f"📂 Output Folder      : {cfg.output_dir}")
    else:
        log(f"📂 Output Folder      : <batch>/result/ (default)")

    log(f"✂️  Remove Background  : {'ENABLED ✅' if cfg.remove_bg else 'DISABLED (Original Background Preserved) ⚪'}")
    if cfg.bg_output_dir:
        log(f"🖼️  Cutouts Output     : {cfg.bg_output_dir}")
    log(f"🤖 Upscayl Binary     : {'OK ✅' if coordinator.upscaler.verify_binary() else 'MISSING ❌ (Skipped/Passthrough)'}")
    log(f"🧠 Free-Tier Vision   : {', '.join(coordinator.qa_auditor.llm.available_vision_providers()) or 'OFFLINE (LocalMetadataEngine)'}")
    log(f"🏷️  ExifTool IPTC      : {'OK ✅' if MetadataEngine.has_exiftool() else 'NOT INSTALLED (CSV still exported)'}")
    log(f"🎨 Mode               : {asset_type.upper()}")

    try:
        if not base_dir.exists():
            base_dir.mkdir(parents=True, exist_ok=True)
            log(f"\n📁 Created new input directory at: {base_dir}")
            log("   Please place raw images inside and re-run.")
            return
    except (PermissionError, OSError):
        base_dir = PROJECT_ROOT / "input"
        base_dir.mkdir(parents=True, exist_ok=True)
        cfg.base_dir = base_dir
        log(f"\n📁 Desktop directory was inaccessible. Falling back to: {base_dir}")

    direct_images = [
        f for f in base_dir.iterdir()
        if f.is_file() and f.suffix.lower() in VALID_EXTENSIONS and not f.name.startswith(".")
    ]
    raw_subfolder = base_dir / "raw"
    if not direct_images and raw_subfolder.exists():
        direct_images = [
            f for f in raw_subfolder.iterdir()
            if f.is_file() and f.suffix.lower() in VALID_EXTENSIONS and not f.name.startswith(".")
        ]

    folders = get_available_input_folders(base_dir)
    batch_summaries: List[str] = []

    if direct_images and not folders:
        log(f"\n📦 Found {len(direct_images)} images directly in: {base_dir}")
        res_dir = custom_output or cfg.output_dir or (base_dir / "result")
        if res_dir.exists() and list(res_dir.glob("*.png")) + list(res_dir.glob("*.jpg")):
            log(f"⏭️  Skipping: results already exist in '{res_dir}'.")
            return
        res = coordinator.process_batch_folder(base_dir, asset_type=asset_type, custom_output_folder=res_dir)
        batch_summaries.append(f"{res['folder']}: passed={res['passed']}, failed={res['failed']}, ai_rejected={res.get('ai_rejected', 0)}")
        coordinator.print_submission_checklist()
        if coordinator.run_logger:
            coordinator.run_logger.write_summary(batch_summaries)
        return

    if not folders and not direct_images:
        log(f"\n⚠️ No input folders or raw images found in: {base_dir}")
        log(f"   Place raw images directly in '{base_dir}' or create batch subfolders (e.g. '{base_dir}/batch1/raw'), then re-run.")
        return

    processed_any = False
    for f in folders:
        result_folder = (custom_output / f.name) if custom_output else ((cfg.output_dir / f.name) if cfg.output_dir else (f / "result"))
        raw_folder = f / "raw"

        if result_folder.exists() and (list(result_folder.glob("*.png")) + list(result_folder.glob("*.jpg"))):
            log(f"⏭️  Skipping '{f.name}': results already exist in '{result_folder}'.")
            continue

        imgs = [x for x in f.iterdir() if x.is_file() and x.suffix.lower() in VALID_EXTENSIONS and not x.name.startswith(".")]
        if not imgs and raw_folder.exists():
            imgs = [x for x in raw_folder.iterdir() if x.is_file() and x.suffix.lower() in VALID_EXTENSIONS and not x.name.startswith(".")]

        if not imgs:
            log(f"⏭️  Skipping '{f.name}': no images found in '{f.name}/' or '{f.name}/raw/'.")
            continue

        processed_any = True
        res = coordinator.process_batch_folder(f, asset_type=asset_type, custom_output_folder=result_folder)
        batch_summaries.append(
            f"{res['folder']}: passed={res['passed']}, failed={res['failed']}, ai_rejected={res.get('ai_rejected', 0)}"
        )

    if processed_any:
        coordinator.print_submission_checklist()
        if coordinator.run_logger:
            coordinator.run_logger.write_summary(batch_summaries)
    else:
        log("\n✅ All folders have already been processed. No new images to process.")


def main():
    parser = argparse.ArgumentParser(
        description="Microstock Generator - Hybrid Free-Tier Asset Pipeline (Step 1 Research + Step 4 Processing)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Step 1: High-Demand Research
    parser.add_argument(
        "--research",
        action="store_true",
        help="Run Step 1: High-Demand Research & generate copy-paste commercial-grade prompts (.txt & .json)"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Number of prompts to generate when running --research (default: 12)"
    )
    parser.add_argument(
        "--niche",
        type=str,
        default=None,
        help="Optional niche focus for --research (e.g. 'Ramadan luxury', 'minimalist skincare', 'fintech 3d')"
    )

    # Step 5: Adobe Stock SFTP Upload
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Run Step 5: Upload pending production-ready assets from result/ folders to Adobe Stock SFTP"
    )

    # Input & Output Directory Options (Step 4)
    parser.add_argument(
        "--input", "-i", "--source", "-s",
        type=str,
        default=None,
        help="Source directory containing raw images or batch subfolders (default: '~/Desktop/microstock_generator')"
    )
    parser.add_argument(
        "--output", "-o", "--result", "-r",
        type=str,
        default=None,
        help="Destination directory for processed assets (default: '<batch>/result/')"
    )

    # Background Removal Options
    bg_group = parser.add_mutually_exclusive_group()
    bg_group.add_argument(
        "--remove-bg",
        dest="remove_bg",
        action="store_true",
        default=None,
        help="Enable AI background removal for isolated studio assets (default)"
    )
    bg_group.add_argument(
        "--no-remove-bg", "--skip-bg-remove",
        dest="remove_bg",
        action="store_false",
        help="Disable background removal; preserve original backgrounds"
    )

    parser.add_argument(
        "--bg-output", "--bg-output-dir",
        type=str,
        default=None,
        help="Optional separate directory to save an extra copy of transparent PNG cutouts"
    )

    # Upscaling & AI QA Options
    parser.add_argument(
        "--skip-upscale", "--no-upscale",
        action="store_true",
        help="Skip AI upscaling (use images at their current resolution)"
    )
    parser.add_argument(
        "--skip-ai-qa",
        action="store_true",
        help="Skip Free-Tier Vision QC & Vision SEO metadata (use offline LocalMetadataEngine)"
    )

    # Mode and Dry-run
    parser.add_argument(
        "--type", "-t",
        choices=["auto", "isolated", "scene"],
        default="auto",
        help="Asset type mode: auto (automatic detection), isolated (transparent PNG), or scene (sRGB JPEG)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect environment, free-tier API status, binary detection, and configuration without executing"
    )

    args = parser.parse_args()
    config = load_config()

    if args.input:
        config.base_dir = Path(args.input).resolve()
    if args.output:
        config.output_dir = Path(args.output).resolve()
    if args.remove_bg is not None:
        config.remove_bg = args.remove_bg
    if args.bg_output:
        config.bg_output_dir = Path(args.bg_output).resolve()
    if args.skip_upscale:
        config.skip_upscale = True
    if args.skip_ai_qa:
        config.enable_ai_qa = False
        config.enable_vision_metadata = False

    if args.research:
        prompt_count = args.count or config.default_prompt_count
        run_research_step(config, count=prompt_count, niche=args.niche)
        return

    if args.upload:
        run_upload_step(config, dry_run=args.dry_run)
        return

    if args.dry_run:
        coordinator = PipelineCoordinator(config)
        uploader = AdobeSFTPUploader(config)
        print_banner()
        print("🔍 DRY RUN ENVIRONMENT CHECK:")
        print(f" • Platform          : {sys.platform} ({'macOS' if sys.platform == 'darwin' else 'Windows' if sys.platform == 'win32' else 'Linux'})")
        print(f" • Project Root      : {PROJECT_ROOT}")
        print(f" • Source Folder     : {config.base_dir}")
        print(f" • Output Folder     : {config.output_dir or '<batch>/result/'}")
        print(f" • Prompts Folder    : {config.prompts_dir or (config.base_dir / 'prompts')}")
        print(f" • Logs Folder (.txt): {config.logs_dir}")
        print(f" • Free-Tier Text    : {', '.join(coordinator.qa_auditor.llm.available_text_providers()) or 'NONE (will use offline blueprints)'}")
        print(f" • Free-Tier Vision  : {', '.join(coordinator.qa_auditor.llm.available_vision_providers()) or 'NONE (will use offline LocalMetadataEngine)'}")
        print(f" • Adobe SFTP Upload : {'CONFIGURED ✅' if uploader.is_configured() else 'NOT CONFIGURED (set ADOBE_SFTP_USER & PASS in .env)'} | Transport: {uploader.available_transport()}")
        print(f" • ExifTool IPTC     : {'OK ✅' if MetadataEngine.has_exiftool() else 'NOT INSTALLED (CSV export still active)'}")
        print(f" • Export Adobe CSV  : {'ENABLED ✅' if config.export_csv else 'DISABLED ⚪'}")
        print(f" • Remove Background : {'ENABLED ✅' if config.remove_bg else 'DISABLED ⚪'}")
        print(f" • Upscayl Binary    : {'OK ✅' if coordinator.upscaler.verify_binary() else 'MISSING ❌'}")
        if coordinator.upscaler.bin_path:
            print(f"   - Executable      : {coordinator.upscaler.bin_path}")
            print(f"   - Models Dir      : {coordinator.upscaler.models_dir}")
        else:
            print(f"   {coordinator.upscaler.get_installation_instructions()}")
        print(f" • Skip Upscale      : {'YES ⏭️' if config.skip_upscale else 'NO'}")
        print(f" • Mode              : {args.type.upper()}")
        return

    run_logger = RunLogger(config.logs_dir, run_name="process")
    coordinator = PipelineCoordinator(config, run_logger=run_logger)
    run_auto_pipeline(coordinator, asset_type=args.type, custom_output=config.output_dir)


if __name__ == "__main__":
    main()
