"""
Adobe Stock Metadata Engine, Optional ExifTool IPTC/XMP Embedder, & CSV Exporter.
Conforms to official Adobe Stock specification:
https://helpx.adobe.com/stock/contributor/help/csv-metadata.html
"""

import csv
import shutil
import struct
import subprocess
from html import escape as xml_escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from PIL import Image, PngImagePlugin

try:
    import piexif
except ImportError:
    piexif = None

from .config import PipelineConfig
from .local_metadata import LocalMetadataEngine

_XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"


def build_xmp_packet(title: str, keywords: List[str]) -> bytes:
    """Build an Adobe-Stock-compatible UTF-8 XMP RDF XML packet (dc:title, dc:description, dc:subject)."""
    clean_title = xml_escape((title or "").strip())
    clean_kws = [xml_escape(k.strip()) for k in keywords if k and k.strip()]
    bag_items = "".join(f"<rdf:li>{k}</rdf:li>" for k in clean_kws)
    xml_str = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">{clean_title}</rdf:li></rdf:Alt></dc:title>'
        f'<dc:description><rdf:Alt><rdf:li xml:lang="x-default">{clean_title}</rdf:li></rdf:Alt></dc:description>'
        f'<dc:subject><rdf:Bag>{bag_items}</rdf:Bag></dc:subject>'
        '</rdf:Description>'
        '</rdf:RDF>'
        '</x:xmpmeta>'
        '<?xpacket end="w"?>'
    )
    return xml_str.encode("utf-8")


def _inject_xmp_into_jpeg_bytes(jpeg_bytes: bytes, xmp_bytes: bytes) -> bytes:
    """Losslessly inject or replace an XMP APP1 segment inside JPEG binary stream (preserves ICC & pixels)."""
    if not jpeg_bytes.startswith(b"\xff\xd8"):
        return jpeg_bytes

    payload = _XMP_HEADER + xmp_bytes
    seg_len = len(payload) + 2
    if seg_len > 65535:
        return jpeg_bytes
    xmp_segment = b"\xff\xe1" + struct.pack(">H", seg_len) + payload

    out = bytearray(b"\xff\xd8")
    pos = 2
    inserted = False
    n = len(jpeg_bytes)

    while pos < n:
        if jpeg_bytes[pos] != 0xFF:
            out.extend(jpeg_bytes[pos:])
            break
        # Skip padding 0xFF bytes
        while pos < n and jpeg_bytes[pos] == 0xFF:
            pos += 1
        if pos >= n:
            break
        marker = jpeg_bytes[pos]
        pos += 1

        # SOS (Start of Scan) or EOI: write XMP before compressed scan if not yet inserted, then rest verbatim
        if marker in (0xDA, 0xD9):
            if not inserted:
                out.extend(xmp_segment)
                inserted = True
            out.append(0xFF)
            out.append(marker)
            out.extend(jpeg_bytes[pos:])
            break

        if marker == 0x00 or (0xD0 <= marker <= 0xD7) or marker == 0x01:
            out.append(0xFF)
            out.append(marker)
            continue

        if pos + 2 > n:
            out.append(0xFF)
            out.append(marker)
            out.extend(jpeg_bytes[pos:])
            break

        length = struct.unpack(">H", jpeg_bytes[pos : pos + 2])[0]
        seg_data = jpeg_bytes[pos + 2 : pos + length]
        pos += length

        # Replace any existing XMP APP1 segment cleanly
        if marker == 0xE1 and seg_data.startswith(_XMP_HEADER):
            if not inserted:
                out.extend(xmp_segment)
                inserted = True
            continue

        out.append(0xFF)
        out.append(marker)
        out.extend(struct.pack(">H", length))
        out.extend(seg_data)

    return bytes(out)


def embed_metadata_pure_python_jpeg(file_path: Path, title: str, keywords: List[str]) -> bool:
    """Losslessly embed EXIF Title/Keywords (piexif) + Adobe XMP APP1 packet into JPEG without recompression."""
    try:
        xmp_bytes = build_xmp_packet(title, keywords)
        raw = file_path.read_bytes()

        if piexif is not None and title:
            try:
                exif_dict = piexif.load(raw)
            except Exception:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            zeroth = exif_dict.setdefault("0th", {})
            zeroth[piexif.ImageIFD.ImageDescription] = title.encode("utf-8", errors="ignore")
            zeroth[piexif.ImageIFD.XPTitle] = title.encode("utf-16le") + b"\x00\x00"
            kw_str = "; ".join(k.strip() for k in keywords if k and k.strip())
            if kw_str:
                zeroth[piexif.ImageIFD.XPKeywords] = kw_str.encode("utf-16le") + b"\x00\x00"
            import io
            buf = io.BytesIO()
            piexif.insert(piexif.dump(exif_dict), raw, buf)
            raw = buf.getvalue()

        updated = _inject_xmp_into_jpeg_bytes(raw, xmp_bytes)
        tmp = file_path.with_suffix(".xmp.tmp")
        try:
            tmp.write_bytes(updated)
            tmp.replace(file_path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def embed_metadata_pure_python_png(file_path: Path, title: str, keywords: List[str]) -> bool:
    """Embed Adobe XMP (`XML:com.adobe.xmp` iTXt chunk) into PNG while preserving ICC profile & RGBA."""
    try:
        xmp_str = build_xmp_packet(title, keywords).decode("utf-8")
        with Image.open(file_path) as im:
            im.load()
            icc = im.info.get("icc_profile")
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_itxt("XML:com.adobe.xmp", xmp_str, lang="", tkey="")
            if title:
                pnginfo.add_text("Title", title)
            save_kwargs: Dict[str, Any] = {
                "format": "PNG",
                "pnginfo": pnginfo,
                "optimize": True,
                "compress_level": 9,
            }
            if icc:
                save_kwargs["icc_profile"] = icc
            tmp = file_path.with_suffix(".xmp.tmp")
            try:
                im.save(tmp, **save_kwargs)
                tmp.replace(file_path)
            finally:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
        return True
    except Exception:
        return False


class MetadataEngine:
    def __init__(self, config: PipelineConfig):
        self.config = config

    def generate_metadata_for_image(
        self,
        image_path: Path,
        prompt_hint: Optional[str] = None,
        asset_type: str = "isolated"
    ) -> Dict[str, Any]:
        """
        Generate commercial stock title, keywords, and category ID instantly (offline).
        Uses local semantic taxonomy and keyword expansions.
        """
        theme = prompt_hint if prompt_hint else image_path.parent.name.replace("_result", "").replace("_upscaled", "")
        theme = theme.replace("_", " ")

        cat_id, cat_name = LocalMetadataEngine.infer_category(theme)
        title = LocalMetadataEngine.generate_title(
            theme,
            asset_type=asset_type,
            max_chars=self.config.max_title_chars
        )
        keywords = LocalMetadataEngine.generate_keywords(
            theme,
            asset_type=asset_type,
            max_count=self.config.max_keywords
        )

        return {
            "title": title,
            "keywords": keywords,
            "category_id": cat_id,
            "category_name": cat_name
        }

    @staticmethod
    def has_exiftool() -> bool:
        return shutil.which("exiftool") is not None

    @staticmethod
    def embed_iptc_xmp_exiftool(
        file_path: Path,
        title: str,
        keywords: List[str],
        log_callback=None
    ) -> bool:
        """
        Embed Title and Keywords directly into JPEG/PNG IPTC & XMP metadata via ExifTool
        (if installed on system PATH). Gracefully skips if ExifTool is not installed.
        """
        exiftool_bin = shutil.which("exiftool")
        if not exiftool_bin:
            return False

        cmd = [
            exiftool_bin,
            "-overwrite_original",
            "-charset", "utf8",
            f"-IPTC:ObjectName={title}",
            f"-XMP:Title={title}",
            f"-IPTC:Caption-Abstract={title}",
            f"-XMP:Description={title}",
            "-IPTC:Keywords=",
            "-XMP:Subject=",
        ]
        for kw in keywords:
            k = kw.strip()
            if k:
                cmd.append(f"-IPTC:Keywords={k}")
                cmd.append(f"-XMP:Subject={k}")
        cmd.append(str(file_path))

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if proc.returncode == 0:
                return True
            if log_callback:
                log_callback(f"  ⚠️ ExifTool warning on {file_path.name}: {proc.stderr.strip()}")
            return False
        except Exception as e:
            if log_callback:
                log_callback(f"  ⚠️ ExifTool error on {file_path.name}: {e}")
            return False

    @staticmethod
    def embed_metadata(
        file_path: Path,
        title: str,
        keywords: List[str],
        log_callback=None,
    ) -> Tuple[bool, str]:
        """
        Embed Title and Keywords cleanly:
        1. System ExifTool (IPTC + XMP) if installed
        2. Pure-Python Lossless Adobe XMP + EXIF fallback (no ExifTool required)
        """
        if not title:
            return False, "none"
        if MetadataEngine.has_exiftool():
            if MetadataEngine.embed_iptc_xmp_exiftool(file_path, title, keywords, log_callback=log_callback):
                return True, "exiftool"

        ext = file_path.suffix.lower()
        if ext in (".jpg", ".jpeg"):
            ok = embed_metadata_pure_python_jpeg(file_path, title, keywords)
            return ok, ("python_xmp_exif" if ok else "failed")
        if ext == ".png":
            ok = embed_metadata_pure_python_png(file_path, title, keywords)
            return ok, ("python_xmp_png" if ok else "failed")
        return False, "unsupported"

    @staticmethod
    def load_csv_filenames(csv_path: Path) -> Dict[str, Dict[str, Any]]:
        """Read existing rows keyed by Filename from an Adobe Stock metadata CSV."""
        existing_rows: Dict[str, Dict[str, Any]] = {}
        if csv_path.exists():
            try:
                with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        fn = r.get("Filename")
                        if fn:
                            existing_rows[fn] = r
            except Exception:
                pass
        return existing_rows

    @staticmethod
    def export_adobe_csv(
        records: List[Dict[str, Any]],
        csv_path: Path,
        valid_filenames: Optional[Set[str]] = None,
    ):
        """
        Write or update adobe_stock_metadata.csv.
        If valid_filenames is provided, prunes rows whose files no longer exist in result/.
        Adobe Stock official CSV format:
        Filename,Title,Keywords,Category,Releases
        """
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        existing_rows = MetadataEngine.load_csv_filenames(csv_path)

        for rec in records:
            fn = rec["filename"]
            kw_str = ", ".join(rec.get("keywords", [])) if isinstance(rec.get("keywords"), list) else str(rec.get("keywords", ""))
            existing_rows[fn] = {
                "Filename": fn,
                "Title": rec.get("title", ""),
                "Keywords": kw_str,
                "Category": str(rec.get("category_id", 8)),
                "Releases": rec.get("releases", "")
            }

        if valid_filenames is not None:
            existing_rows = {fn: row for fn, row in existing_rows.items() if fn in valid_filenames}

        fieldnames = ["Filename", "Title", "Keywords", "Category", "Releases"]
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in existing_rows.values():
                writer.writerow(row)
