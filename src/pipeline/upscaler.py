"""
Upscayl CLI Wrapper and AI Super-Resolution Engine.
Cross-Platform support for macOS, Linux, and Windows.
"""

import os
import sys
import time
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional, Tuple

from .config import PipelineConfig


def find_upscayl_binary_and_models(
    custom_bin: Optional[Path] = None,
    custom_models: Optional[Path] = None
) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Cross-platform auto-detector for Upscayl CLI binary and models directory.
    Supports macOS, Linux, and Windows.
    Checks environment variables (UPSCAYL_BIN, UPSCAYL_MODELS_DIR),
    custom configuration, system PATH, and standard OS installation paths.
    """
    found_bin: Optional[Path] = None
    found_models: Optional[Path] = None

    # 1. Check custom paths if provided and valid
    if custom_bin and Path(custom_bin).is_file():
        found_bin = Path(custom_bin).resolve()
    if custom_models and Path(custom_models).is_dir():
        found_models = Path(custom_models).resolve()

    # 2. Check environment variables
    env_bin = os.environ.get("UPSCAYL_BIN")
    if not found_bin and env_bin and Path(env_bin).is_file():
        found_bin = Path(env_bin).resolve()

    env_models = os.environ.get("UPSCAYL_MODELS_DIR") or os.environ.get("UPSCAYL_MODELS")
    if not found_models and env_models and Path(env_models).is_dir():
        found_models = Path(env_models).resolve()

    # 3. Check system PATH
    bin_names = ["upscayl-bin.exe", "upscayl.exe"] if sys.platform == "win32" else ["upscayl-bin", "upscayl"]
    if not found_bin:
        for b_name in bin_names:
            which_path = shutil.which(b_name)
            if which_path and Path(which_path).is_file():
                found_bin = Path(which_path).resolve()
                break

    # 4. Platform-specific well-known paths
    if not found_bin:
        candidates = []
        if sys.platform == "darwin":  # macOS
            candidates = [
                Path("/Applications/Upscayl.app/Contents/Resources/bin/upscayl-bin"),
                Path.home() / "Applications/Upscayl.app/Contents/Resources/bin/upscayl-bin",
            ]
        elif sys.platform == "win32":  # Windows
            prog_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            prog_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            local_appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
            appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
            candidates = [
                prog_files / "Upscayl" / "resources" / "bin" / "upscayl-bin.exe",
                prog_files_x86 / "Upscayl" / "resources" / "bin" / "upscayl-bin.exe",
                local_appdata / "Programs" / "Upscayl" / "resources" / "bin" / "upscayl-bin.exe",
                appdata / "Upscayl" / "resources" / "bin" / "upscayl-bin.exe",
            ]
        else:  # Linux / Unix
            candidates = [
                Path("/usr/bin/upscayl-bin"),
                Path("/usr/local/bin/upscayl-bin"),
                Path("/opt/Upscayl/resources/bin/upscayl-bin"),
                Path.home() / ".local/share/upscayl/resources/bin/upscayl-bin",
                Path("/var/lib/flatpak/app/org.upscayl.Upscayl/current/active/files/bin/upscayl-bin"),
                Path.home() / ".local/share/flatpak/app/org.upscayl.Upscayl/current/active/files/bin/upscayl-bin",
            ]

        for cand in candidates:
            if cand.is_file():
                found_bin = cand.resolve()
                break

    # 5. Discover models directory relative to binary if not found yet
    if found_bin and not found_models:
        model_candidates = [
            found_bin.parent.parent / "models",
            found_bin.parent / "models",
            found_bin.parent.parent / "resources" / "models",
        ]
        if sys.platform == "darwin":
            model_candidates.extend([
                Path("/Applications/Upscayl.app/Contents/Resources/models"),
                Path.home() / "Applications/Upscayl.app/Contents/Resources/models",
            ])
        elif sys.platform == "win32":
            prog_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            local_appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
            model_candidates.extend([
                prog_files / "Upscayl" / "resources" / "models",
                local_appdata / "Programs" / "Upscayl" / "resources" / "models",
            ])
        else:
            model_candidates.extend([
                Path("/opt/Upscayl/resources/models"),
                Path("/usr/share/upscayl/models"),
                Path("/usr/local/share/upscayl/models"),
                Path.home() / ".local/share/upscayl/resources/models",
                Path("/var/lib/flatpak/app/org.upscayl.Upscayl/current/active/files/share/upscayl/models"),
            ])

        for cand_m in model_candidates:
            if cand_m.is_dir():
                found_models = cand_m.resolve()
                break

    return found_bin, found_models


class UpscaylEngine:
    def __init__(self, config: PipelineConfig):
        self.config = config

        # Perform cross-platform detection
        discovered_bin, discovered_models = find_upscayl_binary_and_models(
            custom_bin=config.upscayl_bin,
            custom_models=config.models_dir
        )
        self.bin_path = discovered_bin or config.upscayl_bin
        self.models_dir = discovered_models or config.models_dir

    def verify_binary(self) -> bool:
        """Returns True if both Upscayl binary and models directory exist."""
        return (
            self.bin_path is not None
            and self.models_dir is not None
            and self.bin_path.is_file()
            and self.models_dir.is_dir()
        )

    @staticmethod
    def get_installation_instructions() -> str:
        """Returns platform-tailored installation instructions for Upscayl."""
        if sys.platform == "darwin":
            return (
                "Install Upscayl on macOS:\n"
                "  • Via Homebrew: brew install --cask upscayl\n"
                "  • Or download .dmg from: https://www.upscayl.org/"
            )
        elif sys.platform == "win32":
            return (
                "Install Upscayl on Windows:\n"
                "  • Via WinGet: winget install Upscayl.Upscayl\n"
                "  • Or download installer from: https://www.upscayl.org/"
            )
        else:
            return (
                "Install Upscayl on Linux:\n"
                "  • Via Flatpak: flatpak install flathub org.upscayl.Upscayl\n"
                "  • Via AppImage / deb / rpm from: https://www.upscayl.org/"
            )

    def get_model_for_type(self, asset_type: str) -> str:
        if asset_type == "isolated":
            return self.config.model_isolated
        elif asset_type == "scene":
            return self.config.model_scene
        return self.config.model_fallback

    def upscale_folder(
        self,
        input_folder: Path,
        output_folder: Path,
        model_name: Optional[str] = None,
        scale: Optional[int] = None,
        timeout_sec: Optional[int] = None,
        log_callback=print
    ) -> bool:
        """
        Upscale all supported images in input_folder to output_folder.
        Uses a smart inactivity/stall watchdog (resets on stdout progress or new output bytes)
        so large multi-image batches are never killed while Upscayl is actively working.
        """
        if not self.verify_binary():
            log_callback(
                f"❌ Upscayl binary or models dir missing:\n"
                f"   Binary : {self.bin_path}\n"
                f"   Models : {self.models_dir}\n"
                f"{self.get_installation_instructions()}"
            )
            return False

        output_folder.mkdir(parents=True, exist_ok=True)
        scale = scale or self.config.upscale_scale
        model_name = model_name or self.config.model_fallback

        if timeout_sec is None:
            stall_timeout = int(getattr(self.config, "upscale_timeout_per_image_sec", 600))
        else:
            stall_timeout = int(timeout_sec)

        cmd = [
            str(self.bin_path),
            "-i", str(input_folder),
            "-o", str(output_folder),
            "-m", str(self.models_dir),
            "-n", model_name,
            "-s", str(scale),
            "-f", "png"
        ]

        start_time = time.time()
        last_activity = [time.monotonic()]
        timed_out = threading.Event()
        stop_watchdog = threading.Event()
        process = None
        watchdog = None
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            def _snapshot_output() -> Tuple[int, int]:
                try:
                    files = [p for p in output_folder.iterdir() if p.is_file()]
                    return len(files), sum(p.stat().st_size for p in files)
                except Exception:
                    return 0, 0

            def _watchdog_loop():
                poll_interval = min(1.0, max(0.2, stall_timeout / 4.0))
                last_snap = _snapshot_output()
                while not stop_watchdog.wait(poll_interval):
                    if process is None or process.poll() is not None:
                        break
                    snap = _snapshot_output()
                    if snap != last_snap:
                        last_snap = snap
                        last_activity[0] = time.monotonic()
                    if time.monotonic() - last_activity[0] >= stall_timeout:
                        timed_out.set()
                        try:
                            process.kill()
                        except Exception:
                            pass
                        break

            if stall_timeout > 0:
                watchdog = threading.Thread(target=_watchdog_loop, daemon=True)
                watchdog.start()

            completed = 0
            if process.stdout is not None:
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        last_activity[0] = time.monotonic()
                    if "Upscayled Successfully" in line:
                        completed += 1
                        log_callback(f"  [Upscayl {scale}x] Image #{completed} upscaled successfully ✅")
                    elif "Error" in line:
                        log_callback(f"  ⚠️ Upscayl Warning: {line}")

            process.wait()
            elapsed = time.time() - start_time
            if timed_out.is_set():
                log_callback(f"⏱️ Upscayl stalled with no progress for {stall_timeout}s — terminated hung subprocess.")
                return False
            if process.returncode == 0:
                log_callback(f"✨ Upscaling finished in {elapsed:.1f}s (Exit 0).")
                return True
            else:
                log_callback(f"❌ Upscayl failed with code {process.returncode}")
                return False

        except Exception as e:
            log_callback(f"❌ Subprocess error while running Upscayl: {e}")
            return False
        finally:
            stop_watchdog.set()
            if watchdog is not None:
                watchdog.join(timeout=1.0)
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except Exception:
                    pass

    def upscale_single_image(
        self,
        input_image: Path,
        output_image: Path,
        model_name: Optional[str] = None,
        scale: int = 2,
        log_callback=print
    ) -> bool:
        """Upscale a single image (used e.g. for re-upscaling tight-cropped images under 4 MP)."""
        temp_dir = input_image.parent / f"_temp_single_{input_image.stem}"
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_input_dir = temp_dir / "in"
            temp_input_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(input_image, temp_input_dir / input_image.name)

            temp_out_dir = temp_dir / "out"
            temp_out_dir.mkdir(parents=True, exist_ok=True)

            ok = self.upscale_folder(
                temp_input_dir,
                temp_out_dir,
                model_name=model_name or self.config.model_isolated,
                scale=scale,
                log_callback=log_callback
            )

            if ok:
                generated = list(temp_out_dir.glob("*.png")) + list(temp_out_dir.glob("*.jpg"))
                if generated:
                    shutil.move(generated[0], output_image)
                    return True
            return False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
