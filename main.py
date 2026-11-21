#!/usr/bin/env python3
"""
===================================================================
 Microstock Generator (Cross-Platform Auto-Run 2.0)
===================================================================
 100% Offline, Non-Interactive, Fast Local Pipeline:
   - Compatible with Linux, macOS, and Windows.
   - Universal commercial compliance (Adobe Stock, Shutterstock, Freepik, etc.).
   - Default source & result in downloaded repository folder or custom paths.
   - Optional AI Background Removal & dedicated cutout directory.
   - Auto-detect per image: Isolated PNG vs Full-Scene sRGB JPEG.
   - Output production-ready commercial stock assets.
===================================================================
"""

import sys
import argparse
from pathlib import Path

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

from src.pipeline.config import load_config, PROJECT_ROOT
from src.pipeline.coordinator import PipelineCoordinator


def print_banner():
    print("""
===================================================================
 🎨 MICROSTOCK GENERATOR (MULTI-PLATFORM 2.0)
 ⚡ Cross-Platform (Linux, macOS, Windows) | Zero-Prompt | Local
 🌟 Universal Stock Compliance: Adobe Stock, Shutterstock, Freepik
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
            and d.name != "result"
            and d.name != "raw"
            and d.name != "upscaled"
        ],
        key=lambda p: p.name
    )


def ensure_desktop_launchers(base_dir: Path, project_root: Path):
    """Generates 1-click execution shortcuts inside the default desktop working directory."""
    desktop = Path.home() / "Desktop"
    try:
        resolved_base = base_dir.resolve()
        # Avoid deploying launchers into arbitrary custom input folders
        if desktop.exists() and (resolved_base == (desktop / "microstock_generator") or desktop in resolved_base.parents):
            pass
        else:
            return

        base_dir.mkdir(parents=True, exist_ok=True)
        # macOS 1-click launcher
        mac_launcher = base_dir / "Run_Microstock_Generator.command"
        if not mac_launcher.exists():
            with open(mac_launcher, "w", encoding="utf-8") as f:
                f.write(f'#!/usr/bin/env bash\ncd "{project_root}" && ./run.sh "$@"\n')
            mac_launcher.chmod(0o755)

        # Windows 1-click launcher
        win_launcher = base_dir / "Run_Microstock_Generator.bat"
        if not win_launcher.exists():
            with open(win_launcher, "w", encoding="utf-8") as f:
                f.write(f'@echo off\ncd /d "{project_root}"\ncall run.bat %*\n')

        # Linux 1-click launcher
        linux_launcher = base_dir / "run_microstock_generator.sh"
        if not linux_launcher.exists():
            with open(linux_launcher, "w", encoding="utf-8") as f:
                f.write(f'#!/usr/bin/env bash\ncd "{project_root}" && ./run.sh "$@"\n')
            linux_launcher.chmod(0o755)
    except Exception:
        pass


def run_auto_pipeline(coordinator: PipelineCoordinator, asset_type: str = "auto", custom_output: Path = None):
    print_banner()
    cfg = coordinator.config
    base_dir = cfg.base_dir

    # Ensure desktop directory and 1-click launchers exist
    ensure_desktop_launchers(base_dir, PROJECT_ROOT)

    print(f"📁 Source Folder      : {base_dir}")
    if custom_output:
        print(f"📂 Output Folder      : {custom_output}")
    elif cfg.output_dir:
        print(f"📂 Output Folder      : {cfg.output_dir}")
    else:
        print(f"📂 Output Folder      : <batch>/result/ (default)")

    print(f"✂️  Remove Background  : {'ENABLED ✅' if cfg.remove_bg else 'DISABLED (Original Background Preserved) ⚪'}")
    if cfg.bg_output_dir:
        print(f"🖼️  Cutouts Output     : {cfg.bg_output_dir}")
    print(f"🤖 Upscayl Binary     : {'OK ✅' if coordinator.upscaler.verify_binary() else 'MISSING ❌ (Skipped/Passthrough)'}")
    print(f"🎨 Mode               : {asset_type.upper()}")

    try:
        if not base_dir.exists():
            base_dir.mkdir(parents=True, exist_ok=True)
            print(f"\n📁 Created new input directory at: {base_dir}")
            print(f"   Please place raw images inside and re-run.")
            return
    except (PermissionError, OSError):
        base_dir = PROJECT_ROOT / "input"
        base_dir.mkdir(parents=True, exist_ok=True)
        cfg.base_dir = base_dir
        print(f"\n📁 Desktop directory was inaccessible. Falling back to: {base_dir}")

    # Check if base_dir contains images directly (single-folder mode)
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

    # Single-folder processing mode if loose images exist directly in base_dir
    if direct_images and not folders:
        print(f"\n📦 Found {len(direct_images)} images directly in: {base_dir}")
        res_dir = custom_output or cfg.output_dir or (base_dir / "result")
        if res_dir.exists() and list(res_dir.glob("*.png")) + list(res_dir.glob("*.jpg")):
            print(f"⏭️  Skipping: results already exist in '{res_dir}'.")
            return
        coordinator.process_batch_folder(base_dir, asset_type=asset_type, custom_output_folder=res_dir)
        coordinator.print_submission_checklist()
        return

    if not folders and not direct_images:
        print(f"\n⚠️ No input folders or raw images found in: {base_dir}")
        print(f"   Place raw images directly in '{base_dir}' or create batch subfolders (e.g. '{base_dir}/batch1'), then re-run.")
        return

    processed_any = False

    for f in folders:
        result_folder = (custom_output / f.name) if custom_output else ((cfg.output_dir / f.name) if cfg.output_dir else (f / "result"))
        raw_folder = f / "raw"

        # Skip if result folder already exists and has files
        if result_folder.exists() and (list(result_folder.glob("*.png")) + list(result_folder.glob("*.jpg"))):
            print(f"⏭️  Skipping '{f.name}': results already exist in '{result_folder}'.")
            continue

        imgs = [x for x in f.iterdir() if x.is_file() and x.suffix.lower() in VALID_EXTENSIONS and not x.name.startswith(".")]
        if not imgs and raw_folder.exists():
            imgs = [x for x in raw_folder.iterdir() if x.is_file() and x.suffix.lower() in VALID_EXTENSIONS and not x.name.startswith(".")]

        if not imgs:
            print(f"⏭️  Skipping '{f.name}': no images found in '{f.name}/' or '{f.name}/raw/'.")
            continue

        processed_any = True
        coordinator.process_batch_folder(f, asset_type=asset_type, custom_output_folder=result_folder)

    if processed_any:
        coordinator.print_submission_checklist()
    else:
        print("\n✅ All folders have already been processed. No new images to process.")


def main():
    parser = argparse.ArgumentParser(
        description="Microstock Generator - Cross-Platform Asset Pipeline (Linux / macOS / Windows)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Input & Output Directory Options
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
        help="Destination directory for processed assets (default: '<batch>/result/' or './output')"
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

    # Upscaling Options
    parser.add_argument(
        "--skip-upscale", "--no-upscale",
        action="store_true",
        help="Skip AI upscaling (use images at their current resolution)"
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
        help="Inspect environment, binary detection, and configuration without executing"
    )

    args = parser.parse_args()
    config = load_config()

    # Override config with CLI arguments if provided
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

    coordinator = PipelineCoordinator(config)

    if args.dry_run:
        print_banner()
        print("🔍 DRY RUN ENVIRONMENT CHECK:")
        print(f" • Platform         : {sys.platform} ({'macOS' if sys.platform == 'darwin' else 'Windows' if sys.platform == 'win32' else 'Linux'})")
        print(f" • Project Root     : {PROJECT_ROOT}")
        print(f" • Source Folder    : {config.base_dir}")
        print(f" • Output Folder    : {config.output_dir or '<batch>/result/'}")
        print(f" • Remove Background: {'ENABLED ✅' if config.remove_bg else 'DISABLED ⚪'}")
        if config.bg_output_dir:
            print(f" • Cutouts Folder   : {config.bg_output_dir}")
        print(f" • Upscayl Binary   : {'OK ✅' if coordinator.upscaler.verify_binary() else 'MISSING ❌'}")
        if coordinator.upscaler.bin_path:
            print(f"   - Executable     : {coordinator.upscaler.bin_path}")
            print(f"   - Models Dir     : {coordinator.upscaler.models_dir}")
        else:
            print(f"   {coordinator.upscaler.get_installation_instructions()}")
        print(f" • Skip Upscale     : {'YES ⏭️' if config.skip_upscale else 'NO'}")
        print(f" • Mode             : {args.type.upper()}")
        print(f" • Isolated Model   : {config.model_isolated}")
        print(f" • Scene Model      : {config.model_scene}")
        print(f" • Segmentation     : {config.bg_model}")
        return

    run_auto_pipeline(coordinator, asset_type=args.type, custom_output=config.output_dir)


if __name__ == "__main__":
    main()
