"""
Step 5: Automated Adobe Stock Contributor SFTP Uploader.

Features:
- Connects to official Adobe Stock SFTP (sftp.contributor.adobestock.com:22)
- Anti-duplicate tracking via SHA-256 + result/manifest.json (never uploads the same asset twice)
- Primary transport: Paramiko (cross-platform Python SFTP)
- Zero-install fallback on macOS/Linux: curl SFTP using a temporary 0600 netrc file (credentials never in CLI args)
- Supports dry-run preview (--upload --dry-run)
- All errors sanitized via redact_secrets() so credentials never leak to stdout or logs/*.txt
"""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import PipelineConfig
from .logger import redact_secrets
from .manifest import ManifestManager, calculate_file_hash

UPLOADABLE_EXTS = {".jpg", ".jpeg", ".png"}


class AdobeSFTPUploader:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.host = os.getenv("ADOBE_SFTP_HOST", config.sftp_host).strip() or "sftp.contributor.adobestock.com"
        self.port = int(os.getenv("ADOBE_SFTP_PORT", str(config.sftp_port)))
        self.username = os.getenv("ADOBE_SFTP_USER", "").strip()
        self.password = os.getenv("ADOBE_SFTP_PASS", "").strip()
        self.max_retries = max(1, int(config.sftp_max_retries))

    def is_configured(self) -> bool:
        return bool(self.host and self.username and self.password)

    @staticmethod
    def available_transport() -> str:
        try:
            import paramiko  # noqa: F401
            return "paramiko"
        except ImportError:
            if shutil.which("curl"):
                return "curl_sftp"
            return "none"

    def discover_pending_files(self, base_dir: Path, custom_output: Optional[Path] = None) -> List[Tuple[Path, Path]]:
        """
        Scan result folders and return list of (file_path, manifest_path) for assets
        not yet marked uploaded_sftp in manifest.json.
        """
        result_dirs: List[Path] = []
        try:
            if custom_output and custom_output.exists():
                direct = [p for p in custom_output.iterdir() if p.is_file() and p.suffix.lower() in UPLOADABLE_EXTS]
                if direct:
                    result_dirs.append(custom_output)
                for sub in sorted(custom_output.iterdir()):
                    if sub.is_dir() and not sub.name.startswith("."):
                        result_dirs.append(sub)
            elif base_dir.exists():
                top_result = base_dir / "result"
                if top_result.is_dir():
                    result_dirs.append(top_result)
                for sub in sorted(base_dir.iterdir()):
                    if sub.is_dir() and not sub.name.startswith(".") and sub.name not in ("prompts", "logs", "result"):
                        cand = sub / "result"
                        if cand.is_dir():
                            result_dirs.append(cand)
        except (PermissionError, OSError):
            return []

        pending: List[Tuple[Path, Path]] = []
        seen_paths = set()

        for res_dir in result_dirs:
            manifest_path = res_dir / "manifest.json"
            manifest = ManifestManager(manifest_path)
            for img in sorted(res_dir.iterdir()):
                if not img.is_file() or img.suffix.lower() not in UPLOADABLE_EXTS or img.name.startswith("."):
                    continue
                resolved = img.resolve()
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                try:
                    f_hash = calculate_file_hash(img)
                    if not manifest.is_uploaded(f_hash):
                        pending.append((img, manifest_path))
                except Exception:
                    continue

        return pending

    def _upload_batch_paramiko(
        self,
        pending: List[Tuple[Path, Path]],
        log_callback=print,
    ) -> Tuple[int, int]:
        import paramiko

        uploaded = 0
        failed = 0
        manifests_cache: Dict[Path, ManifestManager] = {}

        transport = None
        sftp = None
        try:
            transport = paramiko.Transport((self.host, self.port))
            transport.connect(username=self.username, password=self.password)
            sftp = paramiko.SFTPClient.from_transport(transport)
            log_callback(f"🔌 Connected to {self.host}:{self.port} via Paramiko SFTP ✅")

            for idx, (file_path, manifest_path) in enumerate(pending, start=1):
                ok = False
                last_err = ""
                for attempt in range(1, self.max_retries + 1):
                    try:
                        sftp.put(str(file_path), file_path.name)
                        ok = True
                        break
                    except Exception as e:
                        last_err = redact_secrets(str(e))
                        if attempt < self.max_retries:
                            time.sleep(2 * attempt)

                if ok:
                    uploaded += 1
                    manifest = manifests_cache.setdefault(manifest_path, ManifestManager(manifest_path))
                    manifest.mark_uploaded(calculate_file_hash(file_path), file_path.name, remote_host=self.host)
                    log_callback(f"  ✅ [{idx}/{len(pending)}] Uploaded: {file_path.name}")
                else:
                    failed += 1
                    log_callback(f"  ❌ [{idx}/{len(pending)}] Failed: {file_path.name} ({last_err})")
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass

        return uploaded, failed

    def _upload_batch_curl(
        self,
        pending: List[Tuple[Path, Path]],
        log_callback=print,
    ) -> Tuple[int, int]:
        """Fallback SFTP upload using system curl + temporary 0600 netrc file (no credentials in argv)."""
        curl_bin = shutil.which("curl")
        if not curl_bin:
            raise RuntimeError("Neither 'paramiko' nor system 'curl' is available for SFTP upload.")

        uploaded = 0
        failed = 0
        manifests_cache: Dict[Path, ManifestManager] = {}

        netrc_fd, netrc_path_str = tempfile.mkstemp(prefix="ms_sftp_", suffix=".netrc")
        netrc_path = Path(netrc_path_str)
        try:
            os.chmod(netrc_path, 0o600)
            with os.fdopen(netrc_fd, "w", encoding="utf-8") as f:
                f.write(f"machine {self.host} login {self.username} password {self.password}\n")

            log_callback(f"🔌 Uploading to {self.host}:{self.port} via system curl SFTP fallback...")

            for idx, (file_path, manifest_path) in enumerate(pending, start=1):
                remote_url = f"sftp://{self.host}:{self.port}/{file_path.name}"
                ok = False
                last_err = ""
                for attempt in range(1, self.max_retries + 1):
                    proc = subprocess.run(
                        [
                            curl_bin,
                            "-sS",
                            "--fail",
                            "--netrc-file",
                            str(netrc_path),
                            "-T",
                            str(file_path),
                            remote_url,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if proc.returncode == 0:
                        ok = True
                        break
                    last_err = redact_secrets(proc.stderr.strip() or f"exit {proc.returncode}")
                    if attempt < self.max_retries:
                        time.sleep(2 * attempt)

                if ok:
                    uploaded += 1
                    manifest = manifests_cache.setdefault(manifest_path, ManifestManager(manifest_path))
                    manifest.mark_uploaded(calculate_file_hash(file_path), file_path.name, remote_host=self.host)
                    log_callback(f"  ✅ [{idx}/{len(pending)}] Uploaded: {file_path.name}")
                else:
                    failed += 1
                    log_callback(f"  ❌ [{idx}/{len(pending)}] Failed: {file_path.name} ({last_err})")
        finally:
            try:
                netrc_path.unlink(missing_ok=True)
            except Exception:
                pass

        return uploaded, failed

    def upload_pending(
        self,
        base_dir: Path,
        custom_output: Optional[Path] = None,
        dry_run: bool = False,
        log_callback=print,
    ) -> Dict[str, Any]:
        """Discover and upload all pending production-ready assets to Adobe Stock SFTP."""
        pending = self.discover_pending_files(base_dir, custom_output=custom_output)
        log_callback(f"📦 Pending assets ready for Adobe Stock SFTP: {len(pending)}")

        if not pending:
            log_callback("✅ Nothing new to upload (all assets already uploaded or no result/ files found).")
            return {"pending": 0, "uploaded": 0, "failed": 0, "dry_run": dry_run}

        if dry_run:
            log_callback("🔍 UPLOAD DRY-RUN (no files transferred):")
            for idx, (fp, _) in enumerate(pending, start=1):
                size_mb = fp.stat().st_size / (1024 * 1024)
                log_callback(f"  • [{idx}/{len(pending)}] {fp.parent.parent.name}/{fp.parent.name}/{fp.name} ({size_mb:.2f} MB)")
            return {"pending": len(pending), "uploaded": 0, "failed": 0, "dry_run": True}

        if not self.is_configured():
            log_callback(
                "❌ Adobe Stock SFTP credentials not configured.\n"
                "   Add ADOBE_SFTP_USER and ADOBE_SFTP_PASS to your local .env file (see .env.example),\n"
                "   retrieved from https://contributor.stock.adobe.com/ -> Upload -> Learn more about SFTP."
            )
            return {"pending": len(pending), "uploaded": 0, "failed": len(pending), "dry_run": False}

        transport = self.available_transport()
        if transport == "paramiko":
            uploaded, failed = self._upload_batch_paramiko(pending, log_callback=log_callback)
        elif transport == "curl_sftp":
            uploaded, failed = self._upload_batch_curl(pending, log_callback=log_callback)
        else:
            log_callback("❌ No SFTP transport available. Install paramiko: pip install paramiko")
            return {"pending": len(pending), "uploaded": 0, "failed": len(pending), "dry_run": False}

        log_callback(f"\n🎉 SFTP Upload Complete: {uploaded} uploaded, {failed} failed.")
        if uploaded > 0:
            log_callback(
                "\n📋 NEXT (1-MINUTE HYBRID FINALIZATION ON ADOBE STOCK PORTAL):\n"
                "  1. Open https://contributor.stock.adobe.com/ -> Uploaded Files (New)\n"
                "  2. Upload 'adobe_stock_metadata.csv' from each batch's result/ folder (if ExifTool wasn't used)\n"
                "  3. Select All -> Check 'Created using generative AI tools' -> Click 'Submit for Review'"
            )

        return {"pending": len(pending), "uploaded": uploaded, "failed": failed, "dry_run": False}
