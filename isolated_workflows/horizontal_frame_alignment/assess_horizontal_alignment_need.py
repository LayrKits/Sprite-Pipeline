from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from statistics import mean, pstdev

from PIL import Image, ImageDraw

from horizontal_align_sheet import (
    GUIDE_CENTER_X,
    GUIDE_CENTER_Y,
    GUIDE_CORE,
    alpha_bbox,
    checker,
    estimate_core_x,
    make_overlay,
    shift_frame_horizontal,
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
    core_x: list[int],
    bbox_center_x: list[int],
    target_core_x: int,
    center_x: int,
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
        if len(core_x) <= 1:
            return left
        return left + (index / (len(core_x) - 1)) * chart_w

    def y_for(value: int) -> float:
        return top + (value / 255) * chart_h

    draw.rectangle((left, top, left + chart_w, top + chart_h), fill=(32, 37, 43, 255), outline=(67, 78, 91, 255))
    for x_value in range(0, 256, 32):
        yy = y_for(x_value)
        draw.line((left, yy, left + chart_w, yy), fill=(54, 62, 72, 255))
        draw.text((8, yy - 7), str(x_value), fill=(160, 172, 188, 255))
    for index in range(len(core_x)):
        if index % 2 == 0:
            xx = x_for(index)
            draw.line((xx, top, xx, top + chart_h), fill=(43, 50, 59, 255))
            draw.text((xx - 4, top + chart_h + 10), str(index + 1), fill=(160, 172, 188, 255))

    draw.line((left, y_for(center_x), left + chart_w, y_for(center_x)), fill=GUIDE_CENTER_X, width=2)
    draw.line((left, y_for(target_core_x), left + chart_w, y_for(target_core_x)), fill=GUIDE_CORE, width=2)

    def draw_polyline(values: list[int], color: tuple[int, int, int, int], width_px: int) -> None:
        points = [(x_for(index), y_for(value)) for index, value in enumerate(values)]
        if len(points) > 1:
            draw.line(points, fill=color, width=width_px)
        for x, y in points:
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=color)

    draw_polyline(bbox_center_x, (255, 118, 118, 230), 2)
    draw_polyline(core_x, (255, 218, 72, 235), 2)
    draw.text((left, 4), "core/energy X", fill=GUIDE_CORE)
    draw.text((left + 130, 4), "bbox center X", fill=(255, 118, 118, 230))
    draw.text((left + 260, 4), "guides: blue frame center, yellow target core", fill=(188, 199, 214, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output)


def make_diagnostic_sheet(
    frames: list[Image.Image],
    output: Path,
    core_x: list[int],
    target_core_x: int,
    center_x: int,
    center_y: int,
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
        scale_x = tile / cell_width
        scale_y = tile / cell_height
        frame_draw = ImageDraw.Draw(bg)
        frame_draw.line((center_x * scale_x, 0, center_x * scale_x, tile), fill=GUIDE_CENTER_X, width=1)
        frame_draw.line((0, center_y * scale_y, tile, center_y * scale_y), fill=GUIDE_CENTER_Y, width=1)
        frame_draw.line((target_core_x * scale_x, 0, target_core_x * scale_x, tile), fill=GUIDE_CORE, width=1)
        frame_draw.ellipse(
            (core_x[index] * scale_x - 3, center_y * scale_y - 3, core_x[index] * scale_x + 3, center_y * scale_y + 3),
            fill=(255, 255, 255, 230),
        )
        out.alpha_composite(bg, (x, y + label_h))
        label = f"{index + 1}"
        draw.rectangle((x, y, x + 42, y + label_h), fill=(0, 0, 0, 190))
        draw.text((x + 6, y + 4), label, fill=(255, 255, 255, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    out.save(output)


def classify_assessment(
    core_range: int | None,
    bbox_center_range: int | None,
    edge_range: int | None,
    strict_canvas_clip: int,
    core_range_threshold: int,
    bbox_center_range_threshold: int,
    edge_range_threshold: int,
    travel_threshold: int,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if core_range is None or bbox_center_range is None or edge_range is None:
        return "review_manually", ["No reliable foreground frames were detected."]

    if core_range > core_range_threshold:
        reasons.append(f"Estimated core/energy column varies by {core_range}px.")

    if bbox_center_range > bbox_center_range_threshold:
        reasons.append(f"Frame bbox center varies by {bbox_center_range}px.")

    if edge_range > edge_range_threshold:
        reasons.append(f"Horizontal foreground edges vary by up to {edge_range}px.")

    if bbox_center_range >= travel_threshold:
        reasons.append(f"Sheet contains {bbox_center_range}px of lateral travel or drift; review whether that motion is intentional.")

    if strict_canvas_clip > 0:
        reasons.append(f"Strict core locking would clip or push frames outside the cell by up to {strict_canvas_clip}px.")

    if core_range <= core_range_threshold and bbox_center_range <= bbox_center_range_threshold:
        return "probably_no", reasons or ["Horizontal registration already looks stable."]

    if strict_canvas_clip > 0:
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
  <title>Horizontal Alignment Need Assessment</title>
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
  <h1>Horizontal Alignment Need Assessment</h1>
  <p>This script does not fix the sheet. It asks whether horizontal alignment is warranted and whether strict core-column locking would be safe.</p>
  <section class=\"verdict\">
    <b>Verdict</b>
    <span>{report["verdict"]}</span>
  </section>
  <div class=\"metrics\">
    <div><b>Frames</b><span>{report["frame_count"]}</span></div>
    <div><b>Core X range</b><span>{report["core_x_stats"]["range"]} px</span></div>
    <div><b>Bbox center range</b><span>{report["bbox_center_x_stats"]["range"]} px</span></div>
    <div><b>Edge range</b><span>{report["horizontal_edge_range_px"]} px</span></div>
    <div><b>Strict clip risk</b><span>{report["strict_core_canvas_clip_max_px"]} px</span></div>
    <div><b>Target core X</b><span>{report["target_core_x"]}</span></div>
  </div>
  <h2>Why</h2>
  <ul>{reason_items}</ul>
  <h2>Recommendations</h2>
  <ul>{rec_items}</ul>
  <h2>Metrics Graph</h2>
  <figure><figcaption>Yellow: core/energy X. Red: bbox center X. Horizontal guide values are frame center and target core.</figcaption><img src=\"metric_graph.png\"></figure>
  <h2>Overlay</h2>
  <figure><figcaption>Onion-skin source overlay with frame center, center row, and target core column guides</figcaption><img src=\"source_overlay.png\"></figure>
  <h2>Frame Diagnostic</h2>
  <figure><figcaption>White dots show the detected core/energy column in each frame</figcaption><img src=\"diagnostic_frames.png\"></figure>
  <h2>Strict Core Risk</h2>
  <figure><figcaption>Preview of strict core-column lock risk, for diagnosis only</figcaption><img src=\"strict_core_risk_overlay.png\"></figure>
  <p>Report: <code>horizontal_alignment_assessment.json</code></p>
</main>
</body>
</html>
"""
    (run_dir / "horizontal_alignment_assessment.html").write_text(html)


def compact_summary(report: dict[str, object]) -> dict[str, object]:
    verdict = str(report["verdict"])
    recommendations = report["recommendations"]
    reasons = report["reasons"]
    assert isinstance(recommendations, list)
    assert isinstance(reasons, list)
    return {
        "verdict": verdict,
        "needs_horizontal_alignment": verdict in {"yes_likely", "yes_but_constrained"},
        "alignment_mode": "constrained" if verdict == "yes_but_constrained" else "none_or_standard",
        "strict_core_safe": int(report["strict_core_canvas_clip_max_px"]) == 0,
        "metrics": {
            "frame_count": report["frame_count"],
            "core_x_range_px": report["core_x_stats"]["range"],  # type: ignore[index]
            "bbox_center_x_range_px": report["bbox_center_x_stats"]["range"],  # type: ignore[index]
            "horizontal_edge_range_px": report["horizontal_edge_range_px"],
            "strict_core_canvas_clip_risk_px": report["strict_core_canvas_clip_max_px"],
            "target_core_x": report["target_core_x"],
            "center_x": report["center_x"],
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
    center_y = args.cell_height // 2
    bboxes = [alpha_bbox(frame) for frame in frames]
    left_x = [bbox[0] for bbox in bboxes]
    right_x = [bbox[2] for bbox in bboxes]
    bbox_center_x = [round((bbox[0] + bbox[2]) / 2) for bbox in bboxes]

    estimates = [
        estimate_core_x(
            frame,
            core_center_y=center_y,
            core_half_height=args.core_half_height,
            core_y_start_ratio=args.core_y_start,
            core_y_end_ratio=args.core_y_end,
        )
        for frame in frames
    ]
    core_x = [int(item["core_x"]) for item in estimates]
    target_core_x = core_x[0]
    strict_shifts = [target_core_x - value for value in core_x]
    strict_left_x = [left + shift for left, shift in zip(left_x, strict_shifts)]
    strict_right_x = [right + shift for right, shift in zip(right_x, strict_shifts)]
    strict_clips = [
        max(0, args.left_padding - left) + max(0, right - (args.cell_width - args.right_padding))
        for left, right in zip(strict_left_x, strict_right_x)
    ]
    edge_range = max(max(left_x) - min(left_x), max(right_x) - min(right_x))
    core_x_stats = stats(core_x)
    bbox_center_x_stats = stats(bbox_center_x)
    verdict, reasons = classify_assessment(
        core_x_stats["range"],  # type: ignore[arg-type]
        bbox_center_x_stats["range"],  # type: ignore[arg-type]
        edge_range,
        max(strict_clips),
        args.core_range_threshold,
        args.bbox_center_range_threshold,
        args.edge_range_threshold,
        args.travel_threshold,
    )

    recommendations = []
    if verdict == "yes_but_constrained":
        recommendations.append("Use horizontal alignment, but reject strict core-only output unless it passes left/right clipping validation.")
        recommendations.append("Generate constrained candidates such as edge-clamped, capped-shift, or blended-shift variants.")
    elif verdict == "yes_likely":
        recommendations.append("Horizontal alignment is likely useful; still validate with clipping and overlay checks.")
    elif verdict == "probably_no":
        recommendations.append("Do not align by default; horizontal registration appears stable.")
    else:
        recommendations.append("Review manually before changing the sheet.")
    if max(strict_clips) > 0:
        recommendations.append("Strict core locking is unsafe for this sheet because it would clip or push content outside the cell.")
    if bbox_center_x_stats["range"] is not None and int(bbox_center_x_stats["range"]) >= args.travel_threshold:
        recommendations.append("Because the sheet has lateral travel, preserve intentional travel unless review confirms it is drift.")

    frame_records = []
    for index, (bbox, core, bbox_center, shift, strict_left, strict_right, clip) in enumerate(
        zip(bboxes, core_x, bbox_center_x, strict_shifts, strict_left_x, strict_right_x, strict_clips),
        start=1,
    ):
        frame_records.append(
            {
                "index": index,
                "bbox": list(bbox),
                "left_x": bbox[0],
                "right_x": bbox[2],
                "bbox_center_x": bbox_center,
                "core_x": core,
                "strict_core_shift_x": shift,
                "strict_core_left_x": strict_left,
                "strict_core_right_x": strict_right,
                "strict_canvas_clip_px": clip,
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
        "target_core_x": target_core_x,
        "center_x": center_x,
        "center_y": center_y,
        "left_padding": args.left_padding,
        "right_padding": args.right_padding,
        "core_x_stats": core_x_stats,
        "bbox_center_x_stats": bbox_center_x_stats,
        "left_x_stats": stats(left_x),
        "right_x_stats": stats(right_x),
        "horizontal_edge_range_px": edge_range,
        "strict_core_canvas_clip_by_frame": strict_clips,
        "strict_core_canvas_clip_max_px": max(strict_clips),
        "frames": frame_records,
    }
    if args.write_report:
        assert run_dir is not None
        strict_frames = [shift_frame_horizontal(frame, shift) for frame, shift in zip(frames, strict_shifts)]
        strict_estimates = [
            estimate_core_x(
                frame,
                core_center_y=center_y,
                core_half_height=args.core_half_height,
                core_y_start_ratio=args.core_y_start,
                core_y_end_ratio=args.core_y_end,
            )
            for frame in strict_frames
        ]
        strict_core_x = [int(item["core_x"]) for item in strict_estimates]
        source_overlay = run_dir / "source_overlay.png"
        strict_overlay = run_dir / "strict_core_risk_overlay.png"
        metric_graph = run_dir / "metric_graph.png"
        diagnostic = run_dir / "diagnostic_frames.png"
        report_json = run_dir / "horizontal_alignment_assessment.json"
        report_html = run_dir / "horizontal_alignment_assessment.html"
        make_overlay(frames, core_x, source_overlay, center_x, center_y, target_core_x)
        make_overlay(strict_frames, strict_core_x, strict_overlay, center_x, center_y, target_core_x)
        make_metric_graph(metric_graph, core_x, bbox_center_x, target_core_x, center_x)
        make_diagnostic_sheet(frames, diagnostic, core_x, target_core_x, center_x, center_y)
        report.update(
            {
                "source_overlay": str(source_overlay),
                "strict_core_risk_overlay": str(strict_overlay),
                "metric_graph": str(metric_graph),
                "diagnostic_frames": str(diagnostic),
                "report_json": str(report_json),
                "report_html": str(report_html),
            }
        )
        report_json.write_text(json.dumps(report, indent=2))
        make_assessment_html(run_dir, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Assess whether a sprite sheet needs horizontal alignment.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--write-report", action="store_true", help="Write HTML/images/full JSON report artifacts. Requires --output-dir.")
    parser.add_argument("--full-json", action="store_true", help="Print the full assessment JSON instead of the compact AI summary.")
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=256)
    parser.add_argument("--core-half-height", type=int, default=76)
    parser.add_argument("--core-y-start", type=float, default=0.30)
    parser.add_argument("--core-y-end", type=float, default=0.74)
    parser.add_argument("--left-padding", type=int, default=0)
    parser.add_argument("--right-padding", type=int, default=0)
    parser.add_argument("--core-range-threshold", type=int, default=8)
    parser.add_argument("--bbox-center-range-threshold", type=int, default=8)
    parser.add_argument("--edge-range-threshold", type=int, default=8)
    parser.add_argument("--travel-threshold", type=int, default=18)
    args = parser.parse_args()
    report = run(args)
    output = report if args.full_json else compact_summary(report)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
