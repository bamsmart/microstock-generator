"""
Dark-Background QA Contact Sheet Generator (Fase 2).
Renders all finished assets in a batch onto a charcoal (#181818) studio grid
with dark checkerboard behind transparent PNGs so white halos, missed pockets,
or soft cutouts stand out within 10 seconds of human review.

Saved OUTSIDE result/ (at <batch>/qa_contact_sheet.jpg) so it is never
uploaded to Adobe Stock or included in adobe_stock_metadata.csv.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from PIL import Image, ImageDraw, ImageFont, ImageOps

Image.MAX_IMAGE_PIXELS = 250_000_000

_SHEET_EXTS = {".png", ".jpg", ".jpeg"}


def _make_dark_checkerboard(width: int, height: int, cell: int = 16) -> Image.Image:
    """Create a subtle dark studio checkerboard (#181818 / #222222) for transparent PNG QC."""
    tile = Image.new("RGB", (cell * 2, cell * 2), (24, 24, 24))
    draw = ImageDraw.Draw(tile)
    draw.rectangle([0, 0, cell - 1, cell - 1], fill=(34, 34, 34))
    draw.rectangle([cell, cell, cell * 2 - 1, cell * 2 - 1], fill=(34, 34, 34))

    bg = Image.new("RGB", (width, height), (24, 24, 24))
    for y in range(0, height, cell * 2):
        for x in range(0, width, cell * 2):
            bg.paste(tile, (x, y))
    return bg


def generate_qa_contact_sheet(
    result_folder: Path,
    validation_map: Optional[Dict[str, Dict[str, Any]]] = None,
    output_path: Optional[Path] = None,
    tile_size: int = 480,
    cols: int = 4,
) -> Optional[Path]:
    """
    Build a high-contrast dark-background QA contact sheet summarizing all assets in result_folder.
    Returns output Path if written, else None.
    """
    if not result_folder.exists():
        return None

    assets: List[Path] = sorted([
        p for p in result_folder.iterdir()
        if p.is_file()
        and p.suffix.lower() in _SHEET_EXTS
        and not p.name.startswith(".")
        and p.name != "qa_contact_sheet.jpg"
    ])
    if not assets:
        return None

    target_path = output_path or (result_folder.parent / "qa_contact_sheet.jpg")
    validation_map = validation_map or {}

    actual_cols = max(1, min(cols, len(assets)))
    rows = (len(assets) + actual_cols - 1) // actual_cols
    pad = 18
    caption_h = 54
    cell_w = tile_size
    cell_h = tile_size + caption_h

    canvas_w = pad + actual_cols * (cell_w + pad)
    canvas_h = pad + rows * (cell_h + pad) + 46

    sheet = Image.new("RGB", (canvas_w, canvas_h), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    draw.text(
        (pad, 14),
        f"ADOBE STOCK DARK-CANVAS QA SHEET ({len(assets)} assets) | Check halos, edges, gaps & sharpness",
        fill=(225, 225, 225),
        font=font,
    )

    top_offset = 44
    for idx, asset_path in enumerate(assets):
        r = idx // actual_cols
        c = idx % actual_cols
        x0 = pad + c * (cell_w + pad)
        y0 = top_offset + pad + r * (cell_h + pad)

        tile_bg = _make_dark_checkerboard(tile_size, tile_size)
        try:
            with Image.open(asset_path) as raw:
                im = ImageOps.exif_transpose(raw)
                im.thumbnail((tile_size - 16, tile_size - 16), Image.Resampling.LANCZOS)
                px = x0 + (tile_size - im.width) // 2
                py = y0 + (tile_size - im.height) // 2
                sheet.paste(tile_bg, (x0, y0))
                if im.mode == "RGBA":
                    sheet.paste(im, (px, py), mask=im.split()[3])
                else:
                    sheet.paste(im.convert("RGB"), (px, py))
        except Exception:
            sheet.paste(tile_bg, (x0, y0))
            draw.text((x0 + 16, y0 + 16), "ERROR READING IMAGE", fill=(255, 100, 100), font=font)

        val = validation_map.get(asset_path.name, {})
        stats = val.get("stats", {})
        warnings = val.get("warnings", [])
        border_color = (240, 175, 50) if warnings else (60, 185, 110)
        draw.rectangle([x0 - 1, y0 - 1, x0 + cell_w, y0 + cell_h], outline=border_color, width=2)
        draw.rectangle([x0, y0 + tile_size, x0 + cell_w - 1, y0 + cell_h - 1], fill=(28, 28, 30))

        mp = stats.get("megapixels", "?")
        mb = stats.get("file_size_mb", "?")
        blur = stats.get("blur_effect")
        halo = stats.get("halo_score")
        status_label = "WARN" if warnings else "OK"

        line1 = f"{asset_path.name[:28]} [{status_label}]"
        parts2 = [f"{mp}MP", f"{mb}MB"]
        if blur is not None:
            parts2.append(f"blur={blur}")
        if halo is not None:
            parts2.append(f"halo={halo}")
        line2 = " | ".join(parts2)

        draw.text((x0 + 8, y0 + tile_size + 8), line1, fill=(240, 240, 240), font=font)
        draw.text((x0 + 8, y0 + tile_size + 28), line2, fill=(180, 190, 200), font=font)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target_path, format="JPEG", quality=92, optimize=True)
    return target_path
