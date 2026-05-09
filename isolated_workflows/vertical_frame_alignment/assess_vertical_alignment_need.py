from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from statistics import mean, pstdev

from PIL import Image, ImageDraw

from vertical_align_sheet import (
    GUIDE_CENTER,
    GUIDE_GROUND,
    GUIDE_WAIST,
    alpha_bbox,
    checker,
    draw_guides,
    estimate_waist_y,
    make_contact_sheet,
    make_overlay,
    shift_frame_vertical,
    split_sheet,
)


def stats(values: list[int]) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "range": None,
            "mean": None,
            "stddev": None,
        }
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "range": max(values) - min(values),
        "mean": round(mean(values), 3),
        "stddev": round(pstdev(values), 3) if len(values) > 1 else 0.0,
    }


def make_metric_graph(
    output: Path,
    waist_y: list[int],
    bottom_y: list[int],
    ground_y: int,
    target_waist_y: int,
) -> None:
    width = 960
    height = 360
    left = 54
    right = 24
    top = 24
    bottom = 42
    chart_w = width - left - right
    chart_h = height - top - bottom
    img = Image.new("RGBA", (width, height), (24, 28, 33, 255))
    draw = ImageDraw.Draw(img)

    def x_for(index: int) -> float:
        if len(waist_y) <= 1:
            return left
        return left + (index / (len(waist_y) - 1)) * chart_w

    def y_for(value: int) -> float:
        return top + (value / 255) * chart_h

    draw.rectangle((left, top, left + chart_w, top + chart_h), fill=(32, 37, 43, 255), outline=(67, 78, 91, 255))
    for y in range(0, 256, 32):
        yy = y_for(y)
        draw.line((left, yy, left + chart_w, yy), fill=(54, 62, 72, 255))
        draw.text((8, yy - 7), str(y), fill=(160, 172, 188, 255))
    for index in range(len(waist_y)):
        if index % 2 == 0:
            xx = x_for(index)
            draw.line((xx, top, xx, top + chart_h), fill=(43, 50, 59, 255))
            draw.text((xx - 4, top + chart_h + 10), str(index + 1), fill=(160, 172, 188, 255))

    draw.line((left, y_for(ground_y), left + chart_w, y_for(ground_y)), fill=GUIDE_GROUND, width=2)
    draw.line((left, y_for(target_waist_y), left + chart_w, y_for(target_waist_y)), fill=GUIDE_WAIST, width=2)

    def draw_polyline(values: list[int], color: tuple[int, int, int, int], width_px: int) -> None:
        points = [(x_for(index), y_for(value)) for index, value in enumerate(values)]
        if len(points) > 1:
            draw.line(points, fill=color, width=width_px)
        for x, y in points:
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=color)

    draw_polyline(bottom_y, (255, 118, 118, 230), 2)
    draw_polyline(waist_y, (255, 218, 72, 235), 2)
    draw.text((left, 4), "waist/core Y", fill=GUIDE_WAIST)
    draw.text((left + 130, 4), "bottom/feet Y", fill=(255, 118, 118, 230))
    draw.text((left + 260, 4), "guides: red floor, yellow target waist", fill=(188, 199, 214, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output)


def make_diagnostic_contact(
    frames: list[Image.Image],
    output: Path,
    contact_indices: set[int],
    center_x: int,
    ground_y: int,
    target_waist_y: int,
    cols: int = 6,
) -> None:
    cell_width, cell_height = frames[0].size
    tile = 160
    label_h = 24
    rows = (len(frames) + cols - 1) // cols
    out = Image.new("RGBA", (cols * tile, rows * (tile + label_h)), (28, 31, 36, 255))
    draw = ImageDraw.Draw(out)
    for index, frame in enumerate(frames):
        col = index % cols
        row = index // cols
        x = col * tile
        y = row * (tile + label_h)
        bg = checker((tile, tile), cell=20)
        scaled = frame.copy()
        scaled.thumbnail((tile, tile), Image.Resampling.LANCZOS)
        bg.alpha_composite(scaled, ((tile - scaled.width) // 2, (tile - scaled.height) // 2))
        scale = tile / cell_width
        frame_draw = ImageDraw.Draw(bg)
        frame_draw.line((center_x * scale, 0, center_x * scale, tile), fill=GUIDE_CENTER, width=1)
        frame_draw.line((0, ground_y * scale, tile, ground_y * scale), fill=GUIDE_GROUND, width=1)
        frame_draw.line((0, target_waist_y * scale, tile, target_waist_y * scale), fill=GUIDE_WAIST, width=1)
        out.alpha_composite(bg, (x, y + label_h))
        fill = (25, 93, 74, 230) if index in contact_indices else (0, 0, 0, 190)
        label = f"{index + 1} {'C' if index in contact_indices else 'A'}"
        draw.rectangle((x, y, x + 52, y + label_h), fill=fill)
        draw.text((x + 6, y + 4), label, fill=(255, 255, 255, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    out.save(output)


def classify_assessment(
    contact_waist_range: int | None,
    contact_bottom_range: int | None,
    airborne_span: int,
    strict_floor_penetration: int,
    waist_range_threshold: int,
    bottom_range_threshold: int,
    airborne_threshold: int,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if contact_waist_range is None:
        return "review_manually", ["No reliable contact frames were detected."]

    if contact_bottom_range is not None and contact_bottom_range > bottom_range_threshold:
        reasons.append(f"Contact-frame feet/ground bottom varies by {contact_bottom_range}px.")

    if contact_waist_range > waist_range_threshold:
        reasons.append(f"Contact-frame waist/core estimate varies by {contact_waist_range}px.")

    if airborne_span >= airborne_threshold:
        reasons.append(f"Sheet contains intentional airborne vertical motion: bottom rises {airborne_span}px above ground.")

    if strict_floor_penetration > 0:
        reasons.append(f"Strict waist locking would push frames up to {strict_floor_penetration}px below the floor.")

    if contact_waist_range <= waist_range_threshold and contact_bottom_range is not None and contact_bottom_range <= bottom_range_threshold:
        if airborne_span >= airborne_threshold:
            return "probably_no_or_minor", reasons or ["Contact frames are already stable; most vertical movement looks intentional."]
        return "probably_no", reasons or ["Contact frames and waist/core estimates are already stable."]

    if strict_floor_penetration > 0:
        return "yes_but_constrained", reasons

    return "yes_likely", reasons


def make_assessment_html(run_dir: Path, report: dict[str, object]) -> None:
    recommendations = report["recommendations"]
    assert isinstance(recommendations, list)
    rec_items = "".join(f"<li>{item}</li>" for item in recommendations)
    reasons = report["reasons"]
    assert isinstance(reasons, list)
    reason_items = "".join(f"<li>{item}</li>" for item in reasons)
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Vertical Alignment Need Assessment</title>
  <style>
    :root {{ color-scheme: dark; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #15191e; color: #edf3f8; }}
    main {{ max-width: 1160px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px; }}
    h2 {{ margin: 22px 0 12px; }}
    p, li {{ color: #b9c4d1; line-height: 1.5; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin: 18px 0; }}
    .metrics div {{ background: #20262d; border: 1px solid #3a4552; border-radius: 6px; padding: 12px; }}
    b {{ display: block; font-size: 12px; color: #93a4b8; text-transform: uppercase; }}
    span {{ display: block; margin-top: 5px; font-size: 18px; }}
    figure {{ margin: 0 0 16px; background: #20262d; border: 1px solid #3a4552; border-radius: 6px; padding: 12px; }}
    figcaption {{ color: #cbd5e1; font-size: 13px; margin-bottom: 8px; }}
    img {{ max-width: 100%; height: auto; background: #101419; border-radius: 4px; }}
    .verdict {{ border-left: 5px solid #67d4ad; padding: 12px 16px; background: #1b2528; border-radius: 6px; }}
    code {{ color: #f8d86b; }}
  </style>
</head>
<body>
<main>
  <h1>Vertical Alignment Need Assessment</h1>
  <p>This script does not fix the sheet. It asks whether vertical alignment is warranted and whether strict waist locking would be safe.</p>
  <section class=\"verdict\">
    <b>Verdict</b>
    <span>{report["verdict"]}</span>
  </section>
  <div class=\"metrics\">
    <div><b>Frames</b><span>{report["frame_count"]}</span></div>
    <div><b>Contact frames</b><span>{report["contact_frame_count"]}</span></div>
    <div><b>Contact waist range</b><span>{report["contact_waist_stats"]["range"]} px</span></div>
    <div><b>Contact bottom range</b><span>{report["contact_bottom_stats"]["range"]} px</span></div>
    <div><b>Airborne span</b><span>{report["airborne_span_px"]} px</span></div>
    <div><b>Strict floor risk</b><span>{report["strict_waist_floor_penetration_max_px"]} px</span></div>
  </div>
  <h2>Why</h2>
  <ul>{reason_items}</ul>
  <h2>Recommendations</h2>
  <ul>{rec_items}</ul>
  <h2>Metrics Graph</h2>
  <figure><figcaption>Yellow: waist/core estimate. Red: bottom/feet. Horizontal guides are target waist and frame-1 floor.</figcaption><img src=\"metric_graph.png\"></figure>
  <h2>Overlay</h2>
  <figure><figcaption>Onion-skin source overlay with center, floor, and target waist guides</figcaption><img src=\"source_overlay.png\"></figure>
  <h2>Frame Contact Diagnostic</h2>
  <figure><figcaption>Labels: C = contact/near-floor frame, A = airborne/high frame</figcaption><img src=\"diagnostic_contact.png\"></figure>
  <h2>Strict Waist Risk</h2>
  <figure><figcaption>Preview of strict waist lock risk, for diagnosis only</figcaption><img src=\"strict_waist_risk_overlay.png\"></figure>
  <p>Report: <code>vertical_alignment_assessment.json</code></p>
</main>
</body>
</html>
"""
    (run_dir / "vertical_alignment_assessment.html").write_text(html)


def compact_summary(report: dict[str, object]) -> dict[str, object]:
    verdict = str(report["verdict"])
    recommendations = report["recommendations"]
    reasons = report["reasons"]
    assert isinstance(recommendations, list)
    assert isinstance(reasons, list)
    return {
        "verdict": verdict,
        "needs_vertical_alignment": verdict in {"yes_likely", "yes_but_constrained"},
        "alignment_mode": "constrained" if verdict == "yes_but_constrained" else "none_or_standard",
        "strict_waist_safe": int(report["strict_waist_floor_penetration_max_px"]) == 0,
        "metrics": {
            "frame_count": report["frame_count"],
            "contact_frame_count": report["contact_frame_count"],
            "contact_waist_range_px": report["contact_waist_stats"]["range"],  # type: ignore[index]
            "contact_bottom_range_px": report["contact_bottom_stats"]["range"],  # type: ignore[index]
            "airborne_span_px": report["airborne_span_px"],
            "strict_waist_floor_risk_px": report["strict_waist_floor_penetration_max_px"],
            "ground_y": report["ground_y"],
            "target_waist_y": report["target_waist_y"],
        },
        "reasons": reasons,
        "recommendations": recommendations,
        "report_generated": bool(report.get("report_html")),
        "report_html": report.get("report_html"),
        "report_json": report.get("report_json"),
    }


def run(args: argparse.Namespace) -> dict[str, object]:
    input_path = Path(args.input)
    run_dir = Path(args.output_dir) if args.output_dir else None
    if args.write_report and run_dir is None:
        raise ValueError("--output-dir is required when --write-report is used")
    source_copy: Path | None = None
    if args.write_report:
        assert run_dir is not None
        run_dir.mkdir(parents=True, exist_ok=True)
        source_copy = run_dir / f"{input_path.stem}.source_copy{input_path.suffix}"
        shutil.copy2(input_path, source_copy)

    sheet = Image.open(source_copy or input_path).convert("RGBA")
    frames = split_sheet(sheet, args.cell_width, args.cell_height)
    center_x = args.cell_width // 2
    bboxes = [alpha_bbox(frame) for frame in frames]
    bottom_y = [bbox[3] for bbox in bboxes]
    top_y = [bbox[1] for bbox in bboxes]
    ground_y = bottom_y[0]

    estimates = [
        estimate_waist_y(
            frame,
            core_center_x=center_x,
            core_half_width=args.core_half_width,
            waist_start_ratio=args.waist_start,
            waist_end_ratio=args.waist_end,
        )
        for frame in frames
    ]
    waist_y = [int(item["waist_y"]) for item in estimates]
    target_waist_y = waist_y[0]
    contact_indices = [
        index
        for index, bottom in enumerate(bottom_y)
        if bottom >= ground_y - args.contact_tolerance
    ]
    airborne_indices = [
        index
        for index in range(len(frames))
        if index not in contact_indices
    ]
    contact_index_set = set(contact_indices)
    contact_waist = [waist_y[index] for index in contact_indices]
    contact_bottom = [bottom_y[index] for index in contact_indices]
    airborne_span = max(0, ground_y - min(bottom_y))

    strict_shifts = [target_waist_y - value for value in waist_y]
    strict_bottom_y = [bottom + shift for bottom, shift in zip(bottom_y, strict_shifts)]
    strict_penetrations = [
        max(0, bottom - (ground_y + args.floor_tolerance))
        for bottom in strict_bottom_y
    ]
    contact_waist_stats = stats(contact_waist)
    contact_bottom_stats = stats(contact_bottom)
    verdict, reasons = classify_assessment(
        contact_waist_stats["range"],  # type: ignore[arg-type]
        contact_bottom_stats["range"],  # type: ignore[arg-type]
        airborne_span,
        max(strict_penetrations),
        args.waist_range_threshold,
        args.bottom_range_threshold,
        args.airborne_threshold,
    )

    recommendations = []
    if verdict == "yes_but_constrained":
        recommendations.append("Use vertical alignment, but reject strict waist-only output unless it passes floor and clipping validation.")
        recommendations.append("Generate constrained candidates such as floor-clamped, capped-shift, or blended-shift variants.")
    elif verdict == "yes_likely":
        recommendations.append("Vertical alignment is likely useful; still validate with floor, clipping, and overlay checks.")
    elif verdict.startswith("probably_no"):
        recommendations.append("Do not align by default; vertical motion appears intentional or already stable.")
    else:
        recommendations.append("Review manually before changing the sheet.")
    if max(strict_penetrations) > 0:
        recommendations.append("Strict waist locking is unsafe for this sheet because it would create floor penetration.")
    if airborne_span >= args.airborne_threshold:
        recommendations.append("Because this is airborne motion, preserve jump height instead of forcing every frame to the ground.")

    frame_records = []
    for index, (bbox, waist, bottom, shift, strict_bottom, penetration) in enumerate(
        zip(bboxes, waist_y, bottom_y, strict_shifts, strict_bottom_y, strict_penetrations),
        start=1,
    ):
        frame_records.append(
            {
                "index": index,
                "classification": "contact" if (index - 1) in contact_index_set else "airborne",
                "bbox": list(bbox),
                "top_y": top_y[index - 1],
                "bottom_y": bottom,
                "waist_y": waist,
                "strict_waist_shift_y": shift,
                "strict_waist_bottom_y": strict_bottom,
                "strict_floor_penetration_px": penetration,
            }
        )

    report: dict[str, object] = {
        "input": str(input_path),
        "source_copy": str(source_copy) if source_copy else None,
        "frame_count": len(frames),
        "cell_size": [args.cell_width, args.cell_height],
        "verdict": verdict,
        "reasons": reasons,
        "recommendations": recommendations,
        "ground_y": ground_y,
        "target_waist_y": target_waist_y,
        "contact_tolerance": args.contact_tolerance,
        "floor_tolerance": args.floor_tolerance,
        "contact_frame_indices": [index + 1 for index in contact_indices],
        "airborne_frame_indices": [index + 1 for index in airborne_indices],
        "contact_frame_count": len(contact_indices),
        "contact_waist_stats": contact_waist_stats,
        "contact_bottom_stats": contact_bottom_stats,
        "all_waist_stats": stats(waist_y),
        "all_bottom_stats": stats(bottom_y),
        "airborne_span_px": airborne_span,
        "strict_waist_floor_penetration_by_frame": strict_penetrations,
        "strict_waist_floor_penetration_max_px": max(strict_penetrations),
        "frames": frame_records,
    }
    if args.write_report:
        assert run_dir is not None
        strict_frames = [shift_frame_vertical(frame, shift) for frame, shift in zip(frames, strict_shifts)]
        strict_estimates = [
            estimate_waist_y(
                frame,
                core_center_x=center_x,
                core_half_width=args.core_half_width,
                waist_start_ratio=args.waist_start,
                waist_end_ratio=args.waist_end,
            )
            for frame in strict_frames
        ]
        strict_waist_y = [int(item["waist_y"]) for item in strict_estimates]
        source_overlay = run_dir / "source_overlay.png"
        strict_overlay = run_dir / "strict_waist_risk_overlay.png"
        metric_graph = run_dir / "metric_graph.png"
        contact_sheet = run_dir / "diagnostic_contact.png"
        report_json = run_dir / "vertical_alignment_assessment.json"
        report_html = run_dir / "vertical_alignment_assessment.html"
        make_overlay(frames, waist_y, source_overlay, center_x, ground_y, target_waist_y)
        make_overlay(strict_frames, strict_waist_y, strict_overlay, center_x, ground_y, target_waist_y)
        make_metric_graph(metric_graph, waist_y, bottom_y, ground_y, target_waist_y)
        make_diagnostic_contact(frames, contact_sheet, contact_index_set, center_x, ground_y, target_waist_y)
        report.update(
            {
                "source_overlay": str(source_overlay),
                "strict_waist_risk_overlay": str(strict_overlay),
                "metric_graph": str(metric_graph),
                "diagnostic_contact": str(contact_sheet),
                "report_json": str(report_json),
                "report_html": str(report_html),
            }
        )
        report_json.write_text(json.dumps(report, indent=2))
        make_assessment_html(run_dir, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Assess whether a sprite sheet needs vertical alignment.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--write-report", action="store_true", help="Write HTML/images/full JSON report artifacts. Requires --output-dir.")
    parser.add_argument("--full-json", action="store_true", help="Print the full assessment JSON instead of the compact AI summary.")
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=256)
    parser.add_argument("--core-half-width", type=int, default=76)
    parser.add_argument("--waist-start", type=float, default=0.34)
    parser.add_argument("--waist-end", type=float, default=0.70)
    parser.add_argument("--contact-tolerance", type=int, default=3)
    parser.add_argument("--floor-tolerance", type=int, default=2)
    parser.add_argument("--waist-range-threshold", type=int, default=8)
    parser.add_argument("--bottom-range-threshold", type=int, default=3)
    parser.add_argument("--airborne-threshold", type=int, default=12)
    args = parser.parse_args()
    report = run(args)
    output = report if args.full_json else compact_summary(report)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
