"""
Plain-text (.txt) Run Logger for Microstock Generator Pipeline.
Replaces external chat notifications (e.g. Telegram) with clean, timestamped
.txt log files stored in the project's logs/ directory.
"""

import os
import re
from datetime import datetime
from pathlib import Path

_SECRET_ENV_VARS = (
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY",
    "ADOBE_SFTP_USER",
    "ADOBE_SFTP_PASS",
)


def redact_secrets(text: str) -> str:
    """Redact any configured API keys or bearer/query tokens before logging."""
    if not text:
        return text
    sanitized = str(text)
    for var in _SECRET_ENV_VARS:
        val = os.getenv(var, "").strip()
        if val and len(val) >= 6:
            sanitized = sanitized.replace(val, "[REDACTED]")
    sanitized = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._\-]+", r"\1[REDACTED]", sanitized)
    sanitized = re.sub(r"(?i)([?&]key=)[^&\s\"']+", r"\1[REDACTED]", sanitized)
    return sanitized


class RunLogger:
    """Mirrors pipeline output to stdout and a timestamped .txt log file."""

    def __init__(self, logs_dir: Path, run_name: str = "pipeline"):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.log_file = self.logs_dir / f"run_{run_name}_{ts}.txt"
        self._header_written = False
        self._write_header(run_name)

    def _write_header(self, run_name: str):
        if self._header_written:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = (
            "======================================================================\n"
            f" MICROSTOCK GENERATOR LOG ({run_name.upper()})\n"
            f" Timestamp : {now}\n"
            f" Log File  : {self.log_file}\n"
            "======================================================================\n"
        )
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(header)
        self._header_written = True

    def log(self, message: str = "", to_stdout: bool = True):
        """Log a sanitized line to both stdout (optional) and the .txt log file."""
        safe_message = redact_secrets(message)
        if to_stdout:
            print(safe_message, flush=True)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{safe_message}\n")
        except Exception:
            pass

    def section(self, title: str):
        self.log(f"\n--- {title} ---")

    def write_summary(self, summary_lines: list):
        self.log("\n======================================================================")
        self.log(" RUN SUMMARY")
        self.log("======================================================================")
        for line in summary_lines:
            self.log(f" {line}")
        self.log(f" Log saved to: {self.log_file}")
        self.log("======================================================================")

    def get_path(self) -> Path:
        return self.log_file
