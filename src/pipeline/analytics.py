"""
Portfolio Analytics & Consultant Health Dashboard (`--report`).
Scans all batch folders under base_dir offline and summarizes approval rate,
megapixel sweet spot compliance, category distribution, rejection breakdown,
keyword counts, and upload readiness.
"""

from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _iter_batch_folders(base_dir: Path) -> List[Path]:
    if not base_dir.exists():
        return []
    candidates: List[Path] = []
    if (base_dir / "result").exists() or (base_dir / "raw").exists():
        candidates.append(base_dir)
    for child in sorted(base_dir.iterdir()):
        if child.is_dir() and not child.name.startswith(".") and child.name not in (
            "prompts", "logs", "raw", "result", "upscaled",
            "rejected_qa", "rejected_ai_qa", "rejected_similar",
        ):
            candidates.append(child)
    return candidates


def generate_portfolio_report(
    base_dir: Path,
    custom_output: Optional[Path] = None,
    log_callback=print,
) -> Dict[str, Any]:
    """Aggregate manifest, CSV, portfolio index, and rejection stats across all batches."""
    batches = _iter_batch_folders(base_dir)
    total_ready = 0
    total_uploaded = 0
    total_isolated = 0
    total_scene = 0
    total_removed = 0
    rejected_ai = 0
    rejected_similar = 0
    rejected_tech = 0
    mp_values: List[float] = []
    mb_values: List[float] = []
    kw_counts: List[int] = []
    categories: Counter = Counter()
    batch_rows: List[Dict[str, Any]] = []

    for batch in batches:
        if batch == base_dir:
            res_dir = custom_output or (batch / "result")
        else:
            res_dir = (custom_output / batch.name) if custom_output else (batch / "result")

        manifest_path = res_dir / "manifest.json"
        csv_path = res_dir / "adobe_stock_metadata.csv"

        ready_here = 0
        uploaded_here = 0
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                records = data.get("records", data.get("assets", {}))
                for _, rec in records.items():
                    if rec.get("manually_removed") is True:
                        total_removed += 1
                        continue
                    out_name = rec.get("output_name", "")
                    if out_name and res_dir.exists() and not (res_dir / out_name).exists():
                        continue
                    ready_here += 1
                    total_ready += 1
                    if rec.get("uploaded_sftp"):
                        uploaded_here += 1
                        total_uploaded += 1
                    atype = rec.get("asset_type", "scene")
                    if atype == "isolated":
                        total_isolated += 1
                    else:
                        total_scene += 1
                    mp = float(rec.get("megapixels", 0.0) or 0.0)
                    mb = float(rec.get("file_size_mb", 0.0) or 0.0)
                    if mp > 0:
                        mp_values.append(mp)
                    if mb > 0:
                        mb_values.append(mb)
                    cat = rec.get("category_id")
                    if cat is not None:
                        categories[str(cat)] += 1
                    kws = rec.get("keywords", [])
                    if isinstance(kws, list) and kws:
                        kw_counts.append(len(kws))
            except Exception:
                pass
        elif csv_path.exists():
            try:
                with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        fn = row.get("Filename", "")
                        if fn and (res_dir / fn).exists():
                            ready_here += 1
                            total_ready += 1
                            categories[str(row.get("Category", "8"))] += 1
                            kws = [k.strip() for k in str(row.get("Keywords", "")).split(",") if k.strip()]
                            if kws:
                                kw_counts.append(len(kws))
            except Exception:
                pass

        ai_rej_dir = batch / "rejected_ai_qa"
        sim_rej_dir = batch / "rejected_similar"
        tech_rej_dir = batch / "rejected_qa"
        r_ai = len([p for p in ai_rej_dir.iterdir() if p.is_file()]) if ai_rej_dir.exists() else 0
        r_sim = len([p for p in sim_rej_dir.iterdir() if p.is_file()]) if sim_rej_dir.exists() else 0
        r_tech = len([p for p in tech_rej_dir.iterdir() if p.is_file()]) if tech_rej_dir.exists() else 0
        rejected_ai += r_ai
        rejected_similar += r_sim
        rejected_tech += r_tech

        if ready_here or r_ai or r_sim or r_tech:
            batch_rows.append({
                "batch": batch.name,
                "ready": ready_here,
                "uploaded": uploaded_here,
                "rejected": r_ai + r_sim + r_tech,
            })

    total_rejected = rejected_ai + rejected_similar + rejected_tech
    total_evaluated = total_ready + total_rejected
    pass_rate = round((total_ready / total_evaluated) * 100.0, 1) if total_evaluated > 0 else 0.0
    avg_mp = round(sum(mp_values) / len(mp_values), 2) if mp_values else 0.0
    avg_mb = round(sum(mb_values) / len(mb_values), 2) if mb_values else 0.0
    avg_kw = round(sum(kw_counts) / len(kw_counts), 1) if kw_counts else 0.0

    idx_path = base_dir / ".portfolio_index.json"
    indexed_count = 0
    if idx_path.exists():
        try:
            indexed_count = len(json.loads(idx_path.read_text(encoding="utf-8")).get("entries", []))
        except Exception:
            pass

    summary = {
        "base_dir": str(base_dir),
        "batches_scanned": len(batches),
        "total_ready": total_ready,
        "total_uploaded": total_uploaded,
        "pending_upload": max(0, total_ready - total_uploaded),
        "isolated_png": total_isolated,
        "scene_jpeg": total_scene,
        "total_rejected": total_rejected,
        "rejected_breakdown": {
            "ai_qa": rejected_ai,
            "similar_dup": rejected_similar,
            "technical_qa": rejected_tech,
        },
        "manually_removed": total_removed,
        "pass_rate_pct": pass_rate,
        "avg_megapixels": avg_mp,
        "avg_file_size_mb": avg_mb,
        "avg_keywords": avg_kw,
        "top_categories": categories.most_common(5),
        "portfolio_index_entries": indexed_count,
        "batches": batch_rows,
    }

    log_callback("\n===================================================")
    log_callback("📊 MICROSTOCK PORTFOLIO CONSULTANT REPORT (OFFLINE)")
    log_callback("===================================================")
    log_callback(f" • Workspace          : {base_dir}")
    log_callback(f" • Batches Active     : {len(batch_rows)} (scanned {len(batches)})")
    log_callback(f" • Production Ready   : {total_ready} assets ({total_isolated} Isolated PNG | {total_scene} Scene JPEG)")
    log_callback(f" • Upload Status      : {total_uploaded} uploaded | {summary['pending_upload']} pending")
    log_callback(f" • Rejected Total     : {total_rejected} (AI QC={rejected_ai}, Similar={rejected_similar}, Tech={rejected_tech})")
    log_callback(f" • Pipeline Pass Rate : {pass_rate}%")
    log_callback(f" • Avg Resolution/Size: {avg_mp} MP | {avg_mb} MB | {avg_kw} keywords/asset")
    log_callback(f" • Portfolio Guard    : {indexed_count} indexed assets (.portfolio_index.json)")
    if categories:
        top_cat_str = ", ".join(f"Cat#{c} ({n})" for c, n in categories.most_common(5))
        log_callback(f" • Top Categories     : {top_cat_str}")
    if batch_rows:
        log_callback("\n📦 Per-Batch Breakdown:")
        for b in batch_rows:
            log_callback(f"   - {b['batch']}: ready={b['ready']}, uploaded={b['uploaded']}, rejected={b['rejected']}")
    log_callback("===================================================\n")

    return summary
