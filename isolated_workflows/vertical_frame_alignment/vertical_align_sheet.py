from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path
from statistics import mean, pstdev

from PIL import Image, ImageDraw, ImageFont


ALPHA_THRESHOLD = 12
GUIDE_CENTER = (80, 218, 255, 210)
GUIDE_GROUND = (255, 92, 92, 230)
GUIDE_WAIST = (255, 218, 72, 230)
CHECKER_A = (34, 38, 43, 255)
CHECKER_B = (43, 48, 55, 255)


def alpha_bbox(frame: Image.Image, threshold: int = ALPHA_THRESHOLD) -> tuple[int, int, int, int]:
    alpha = frame.getchannel("A").point(lambda value: 255 if value > threshold else 0)
    bbox = alpha.getbbox()
    if not bbox:
        raise ValueError("Frame has no alpha foreground")
    return bbox


def split_sheet(sheet: Image.Image, cell_width: int, cell_height: int) -> list[Image.Image]:
    if sheet.width % cell_width != 0:
        raise ValueError(f"Sheet width {sheet.width} is not divisible by cell width {cell_width}")
    if sheet.height != cell_height:
        raise ValueError(f"Sheet height {sheet.height} does not match cell height {cell_height}")
    frame_count = sheet.width // cell_width
    return [
        sheet.crop((index * cell_width, 0, (index + 1) * cell_width, cell_height)).convert("RGBA")
        for index in range(frame_count)
    ]


def smooth_counts(counts: list[int], radius: int = 3) -> list[float]:
    smoothed: list[float] = []
    for index in range(len(counts)):
        start = max(0, index - radius)
        end = min(len(counts), index + radius + 1)
        smoothed.append(sum(counts[start:end]) / max(1, end - start))
    return smoothed


def estimate_waist_y(
    frame: Image.Image,
    core_center_x: int,
    core_half_width: int,
    waist_start_ratio: float,
    waist_end_ratio: float,
    threshold: int = ALPHA_THRESHOLD,
) -> dict[str, object]:
    bbox = alpha_bbox(frame, threshold)
    x0, y0, x1, y1 = bbox
    height = y1 - y0
    zone_y0 = max(y0, round(y0 + height * waist_start_ratio))
    zone_y1 = min(y1, round(y0 + height * waist_end_ratio))
    if zone_y1 <= zone_y0:
        zone_y0, zone_y1 = y0, y1

    scan_x0 = max(0, core_center_x - core_half_width)
    scan_x1 = min(frame.width, core_center_x + core_half_width + 1)
    alpha = frame.getchannel("A")
    px = alpha.load()
    counts: list[int] = []
    rows = list(range(zone_y0, zone_y1))
    for y in rows:
        count = 0
        for x in range(scan_x0, scan_x1):
            if px[x, y] > threshold:
                count += 1
        counts.append(count)

    if not counts or max(counts) == 0:
        waist_y = round(y0 + height * 0.55)
        confidence = 0.0
        peak_count = 0
    else:
        smoothed = smooth_counts(counts)
        peak = max(smoothed)
        peak_rows = [
            rows[index]
            for index, value in enumerate(smoothed)
            if value >= peak * 0.88
        ]
        weights = [
            smoothed[rows.index(row)]
            for row in peak_rows
        ]
        waist_y = round(sum(row * weight for row, weight in zip(peak_rows, weights)) / sum(weights))
        peak_count = round(peak, 3)
        local_total = sum(counts) / max(1, len(counts))
        confidence = min(1.0, peak / max(1.0, local_total * 1.5))

    return {
        "bbox": list(bbox),
        "scan_window": [scan_x0, zone_y0, scan_x1, zone_y1],
        "waist_y": int(waist_y),
        "confidence": round(confidence, 4),
        "peak_count": peak_count,
    }


def shift_frame_vertical(frame: Image.Image, dy: int) -> Image.Image:
    out = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    out.alpha_composite(frame, (0, dy))
    return out


def save_sheet(frames: list[Image.Image], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    width = sum(frame.width for frame in frames)
    height = frames[0].height
    sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    x = 0
    for frame in frames:
        sheet.alpha_composite(frame, (x, 0))
        x += frame.width
    sheet.save(output)


def checker(size: tuple[int, int], cell: int = 16) -> Image.Image:
    width, height = size
    img = Image.new("RGBA", size, CHECKER_A)
    draw = ImageDraw.Draw(img)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if ((x // cell) + (y // cell)) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=CHECKER_B)
    return img


def draw_guides(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    center_x: int,
    ground_y: int,
    waist_y: int,
    x_offset: int = 0,
) -> None:
    draw.line((x_offset + center_x, 0, x_offset + center_x, height - 1), fill=GUIDE_CENTER, width=1)
    draw.line((x_offset, ground_y, x_offset + width - 1, ground_y), fill=GUIDE_GROUND, width=1)
    draw.line((x_offset, waist_y, x_offset + width - 1, waist_y), fill=GUIDE_WAIST, width=1)


def make_overlay(
    frames: list[Image.Image],
    anchors: list[int],
    output: Path,
    center_x: int,
    ground_y: int,
    waist_y: int,
) -> None:
    base = checker(frames[0].size)
    overlay = Image.new("RGBA", frames[0].size, (0, 0, 0, 0))
    colors = [
        (90, 180, 255, 34),
        (255, 128, 90, 34),
        (180, 255, 120, 34),
        (210, 120, 255, 34),
    ]
    for index, frame in enumerate(frames):
        alpha = frame.getchannel("A").point(lambda value: min(255, value * 2))
        color = colors[index % len(colors)]
        tint = Image.new("RGBA", frame.size, color)
        tint.putalpha(alpha.point(lambda value: min(46, value // 5)))
        overlay.alpha_composite(tint)

    base.alpha_composite(overlay)
    draw = ImageDraw.Draw(base)
    draw_guides(draw, frames[0].width, frames[0].height, center_x, ground_y, waist_y)
    for index, anchor_y in enumerate(anchors, start=1):
        color = (255, 255, 255, 210) if index == 1 else (255, 218, 72, 190)
        draw.ellipse((center_x - 3, anchor_y - 3, center_x + 3, anchor_y + 3), fill=color)
    output.parent.mkdir(parents=True, exist_ok=True)
    base.save(output)


def make_comparison_preview(
    before: list[Image.Image],
    after: list[Image.Image],
    output: Path,
    center_x: int,
    ground_y: int,
    waist_y: int,
) -> None:
    cell_width, cell_height = before[0].size
    preview = checker((cell_width * len(before), cell_height * 2), cell=32)
    draw = ImageDraw.Draw(preview)
    for row, frames in enumerate((before, after)):
        y_offset = row * cell_height
        for index, frame in enumerate(frames):
            x_offset = index * cell_width
            preview.alpha_composite(frame, (x_offset, y_offset))
            draw.rectangle(
                (x_offset, y_offset, x_offset + cell_width - 1, y_offset + cell_height - 1),
                outline=(255, 255, 255, 95),
            )
            draw_guides(
                draw,
                cell_width,
                cell_height,
                center_x,
                y_offset + ground_y,
                y_offset + waist_y,
                x_offset,
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output)


def make_contact_sheet(
    frames: list[Image.Image],
    output: Path,
    center_x: int,
    ground_y: int,
    waist_y: int,
    cols: int = 6,
) -> None:
    cell_width, cell_height = frames[0].size
    tile = 160
    label_h = 20
    rows = math.ceil(len(frames) / cols)
    out = Image.new("RGBA", (cols * tile, rows * (tile + label_h)), (28, 31, 36, 255))
    draw = ImageDraw.Draw(out)
    for index, frame in enumerate(frames, start=1):
        col = (index - 1) % cols
        row = (index - 1) // cols
        x = col * tile
        y = row * (tile + label_h)
        bg = checker((tile, tile), cell=20)
        scaled = frame.copy()
        scaled.thumbnail((tile, tile), Image.Resampling.LANCZOS)
        bg.alpha_composite(scaled, ((tile - scaled.width) // 2, (tile - scaled.height) // 2))
        scale = tile / cell_width
        draw_bg = ImageDraw.Draw(bg)
        draw_bg.line((center_x * scale, 0, center_x * scale, tile), fill=GUIDE_CENTER, width=1)
        draw_bg.line((0, ground_y * scale, tile, ground_y * scale), fill=GUIDE_GROUND, width=1)
        draw_bg.line((0, waist_y * scale, tile, waist_y * scale), fill=GUIDE_WAIST, width=1)
        out.alpha_composite(bg, (x, y + label_h))
        draw.rectangle((x, y, x + 42, y + label_h), fill=(0, 0, 0, 180))
        draw.text((x + 6, y + 3), str(index), fill=(255, 255, 255, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    out.save(output)


def make_review_html(run_dir: Path, report: dict[str, object]) -> None:
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Vertical Alignment Review</title>
  <style>
    :root {{ color-scheme: dark; font-family: system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif; }}
    body {{ margin: 0; background: #171b20; color: #e9eef5; }}
    main {{ max-width: 1160px; margin: 0 auto; padding: 24px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    p {{ color: #aeb8c5; line-height: 1.5; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
    figure {{ margin: 0; background: #20262d; border: 1px solid #38424d; border-radius: 6px; padding: 12px; }}
    figcaption {{ color: #cbd5e1; font-size: 13px; margin-bottom: 10px; }}
    img {{ max-width: 100%; height: auto; image-rendering: auto; background: #11151a; border-radius: 4px; }}
    canvas {{ width: 256px; height: 256px; image-rendering: auto; background: #11151a; border: 1px solid #38424d; border-radius: 4px; }}
    .anim {{ display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-start; }}
    .metric {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 16px 0 24px; }}
    .metric div {{ background: #20262d; border: 1px solid #38424d; border-radius: 6px; padding: 12px; }}
    .metric b {{ display: block; font-size: 12px; color: #8ea0b6; text-transform: uppercase; }}
    .metric span {{ display: block; margin-top: 5px; font-size: 18px; }}
    code {{ color: #f8d86b; }}
  </style>
</head>
<body>
<main>
  <h1>Vertical Alignment Review</h1>
  <p>This is a separate copy-derived artifact. Original final sheet was not edited.</p>
  <div class=\"metric\">
    <div><b>Frames</b><span>{report["frame_count"]}</span></div>
    <div><b>Target waist Y</b><span>{report["target_waist_y"]}</span></div>
    <div><b>Ground Y</b><span>{report["ground_y"]}</span></div>
    <div><b>Max shift</b><span>{report["max_abs_shift_px"]} px</span></div>
    <div><b>Before waist stddev</b><span>{report["waist_y_stddev_before"]}</span></div>
    <div><b>After waist stddev</b><span>{report["waist_y_stddev_after"]}</span></div>
  </div>
  <h2>Animated Check</h2>
  <div class=\"anim\">
    <figure>
      <figcaption>Copied source sheet</figcaption>
      <canvas id=\"before\" width=\"256\" height=\"256\"></canvas>
    </figure>
    <figure>
      <figcaption>Vertical-aligned copy</figcaption>
      <canvas id=\"after\" width=\"256\" height=\"256\"></canvas>
    </figure>
  </div>
  <h2>Shadow Validation</h2>
  <div class=\"grid\">
    <figure><figcaption>Before overlay: onion-skin shadows, center, ground, waist</figcaption><img src=\"overlay_before.png\"></figure>
    <figure><figcaption>After overlay: waist/core rows cluster on the yellow guide</figcaption><img src=\"overlay_after.png\"></figure>
  </div>
  <h2>Frame Review</h2>
  <div class=\"grid\">
    <figure><figcaption>After contact sheet with guides</figcaption><img src=\"aligned_contact.png\"></figure>
  </div>
  <h2>Wide Comparison</h2>
  <figure><figcaption>Top row before, bottom row after</figcaption><img src=\"comparison_before_after.png\"></figure>
  <p>Output: <code>{Path(report["aligned_sheet"]).name}</code></p>
</main>
<script>
const frameCount = {report["frame_count"]};
const beforeImg = new Image();
const afterImg = new Image();
beforeImg.src = "{Path(report["source_copy"]).name}";
afterImg.src = "{Path(report["aligned_sheet"]).name}";
const beforeCanvas = document.getElementById("before");
const afterCanvas = document.getElementById("after");
const bctx = beforeCanvas.getContext("2d");
const actx = afterCanvas.getContext("2d");
let frame = 0;
function drawChecker(ctx) {{
  const size = 16;
  for (let y = 0; y < 256; y += size) {{
    for (let x = 0; x < 256; x += size) {{
      ctx.fillStyle = ((x / size + y / size) % 2) ? "#2b3037" : "#22262b";
      ctx.fillRect(x, y, size, size);
    }}
  }}
}}
function drawFrame(ctx, img) {{
  drawChecker(ctx);
  ctx.drawImage(img, frame * 256, 0, 256, 256, 0, 0, 256, 256);
  ctx.strokeStyle = "rgba(80,218,255,.82)";
  ctx.beginPath(); ctx.moveTo(128, 0); ctx.lineTo(128, 256); ctx.stroke();
  ctx.strokeStyle = "rgba(255,92,92,.9)";
  ctx.beginPath(); ctx.moveTo(0, {report["ground_y"]}); ctx.lineTo(256, {report["ground_y"]}); ctx.stroke();
  ctx.strokeStyle = "rgba(255,218,72,.9)";
  ctx.beginPath(); ctx.moveTo(0, {report["target_waist_y"]}); ctx.lineTo(256, {report["target_waist_y"]}); ctx.stroke();
}}
function tick() {{
  if (beforeImg.complete && afterImg.complete) {{
    drawFrame(bctx, beforeImg);
    drawFrame(actx, afterImg);
    frame = (frame + 1) % frameCount;
  }}
  setTimeout(tick, 1000 / 12);
}}
tick();
</script>
</body>
</html>
"""
    (run_dir / "review.html").write_text(html)


def run(args: argparse.Namespace) -> dict[str, object]:
    input_path = Path(args.input)
    run_dir = Path(args.output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    source_copy = run_dir / f"{input_path.stem}.source_copy{input_path.suffix}"
    shutil.copy2(input_path, source_copy)

    sheet = Image.open(source_copy).convert("RGBA")
    frames = split_sheet(sheet, args.cell_width, args.cell_height)
    center_x = args.cell_width // 2
    first_bbox = alpha_bbox(frames[0])
    ground_y = first_bbox[3]

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
    target_waist_y = int(estimates[0]["waist_y"])
    shifts = [target_waist_y - int(item["waist_y"]) for item in estimates]
    aligned_frames = [shift_frame_vertical(frame, dy) for frame, dy in zip(frames, shifts)]

    after_estimates = [
        estimate_waist_y(
            frame,
            core_center_x=center_x,
            core_half_width=args.core_half_width,
            waist_start_ratio=args.waist_start,
            waist_end_ratio=args.waist_end,
        )
        for frame in aligned_frames
    ]
    before_waists = [int(item["waist_y"]) for item in estimates]
    after_waists = [int(item["waist_y"]) for item in after_estimates]

    aligned_sheet = run_dir / f"{input_path.stem}.vertical_aligned{input_path.suffix}"
    overlay_before = run_dir / "overlay_before.png"
    overlay_after = run_dir / "overlay_after.png"
    comparison = run_dir / "comparison_before_after.png"
    contact = run_dir / "aligned_contact.png"
    report_path = run_dir / "alignment_report.json"

    save_sheet(aligned_frames, aligned_sheet)
    make_overlay(frames, before_waists, overlay_before, center_x, ground_y, target_waist_y)
    make_overlay(aligned_frames, after_waists, overlay_after, center_x, ground_y, target_waist_y)
    make_comparison_preview(frames, aligned_frames, comparison, center_x, ground_y, target_waist_y)
    make_contact_sheet(aligned_frames, contact, center_x, ground_y, target_waist_y)

    records = []
    clipping_warnings: list[str] = []
    for index, (before_item, after_item, shift) in enumerate(zip(estimates, after_estimates, shifts), start=1):
        bbox = after_item["bbox"]
        assert isinstance(bbox, list)
        touches_top = bbox[1] <= 0
        touches_bottom = bbox[3] >= args.cell_height
        if touches_top or touches_bottom:
            clipping_warnings.append(f"Frame {index} touches vertical edge after shift: bbox={bbox}")
        records.append(
            {
                "index": index,
                "source_bbox": before_item["bbox"],
                "waist_y_before": before_item["waist_y"],
                "shift_y": shift,
                "waist_y_after": after_item["waist_y"],
                "waist_confidence": before_item["confidence"],
                "scan_window": before_item["scan_window"],
                "after_bbox": bbox,
            }
        )

    report: dict[str, object] = {
        "input": str(input_path),
        "source_copy": str(source_copy),
        "aligned_sheet": str(aligned_sheet),
        "overlay_before": str(overlay_before),
        "overlay_after": str(overlay_after),
        "comparison_preview": str(comparison),
        "aligned_contact": str(contact),
        "frame_count": len(frames),
        "cell_size": [args.cell_width, args.cell_height],
        "axis": "vertical-only",
        "registration_point": "estimated waist/core row",
        "target_waist_y": target_waist_y,
        "ground_y": ground_y,
        "center_x": center_x,
        "waist_y_before": before_waists,
        "waist_y_after": after_waists,
        "shift_y": shifts,
        "max_abs_shift_px": max(abs(value) for value in shifts),
        "mean_abs_shift_px": round(mean(abs(value) for value in shifts), 3),
        "waist_y_stddev_before": round(pstdev(before_waists), 3) if len(before_waists) > 1 else 0,
        "waist_y_stddev_after": round(pstdev(after_waists), 3) if len(after_waists) > 1 else 0,
        "warnings": clipping_warnings,
        "frames": records,
    }
    report_path.write_text(json.dumps(report, indent=2))
    make_review_html(run_dir, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Vertical-only waist/core registration for a copied sprite sheet.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=256)
    parser.add_argument("--core-half-width", type=int, default=76)
    parser.add_argument("--waist-start", type=float, default=0.34)
    parser.add_argument("--waist-end", type=float, default=0.70)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
