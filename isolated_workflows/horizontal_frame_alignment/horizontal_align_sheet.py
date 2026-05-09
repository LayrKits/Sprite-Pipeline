from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path
from statistics import mean, pstdev

from PIL import Image, ImageDraw


ALPHA_THRESHOLD = 12
GUIDE_CENTER_X = (80, 218, 255, 210)
GUIDE_CENTER_Y = (255, 118, 118, 210)
GUIDE_CORE = (255, 218, 72, 230)
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


def estimate_core_x(
    frame: Image.Image,
    core_center_y: int,
    core_half_height: int,
    core_y_start_ratio: float,
    core_y_end_ratio: float,
    threshold: int = ALPHA_THRESHOLD,
) -> dict[str, object]:
    bbox = alpha_bbox(frame, threshold)
    x0, y0, x1, y1 = bbox
    height = y1 - y0
    zone_y0 = max(y0, round(y0 + height * core_y_start_ratio))
    zone_y1 = min(y1, round(y0 + height * core_y_end_ratio))
    if zone_y1 <= zone_y0:
        zone_y0, zone_y1 = y0, y1

    if core_half_height > 0:
        scan_y0 = max(zone_y0, core_center_y - core_half_height)
        scan_y1 = min(zone_y1, core_center_y + core_half_height + 1)
        if scan_y1 <= scan_y0:
            scan_y0, scan_y1 = zone_y0, zone_y1
    else:
        scan_y0, scan_y1 = zone_y0, zone_y1

    alpha = frame.getchannel("A")
    px = alpha.load()
    counts: list[int] = []
    cols = list(range(x0, x1))
    for x in cols:
        count = 0
        for y in range(scan_y0, scan_y1):
            if px[x, y] > threshold:
                count += 1
        counts.append(count)

    if not counts or max(counts) == 0:
        core_x = round((x0 + x1) / 2)
        confidence = 0.0
        peak_count = 0
    else:
        smoothed = smooth_counts(counts)
        peak = max(smoothed)
        peak_cols = [
            cols[index]
            for index, value in enumerate(smoothed)
            if value >= peak * 0.88
        ]
        weights = [
            smoothed[cols.index(col)]
            for col in peak_cols
        ]
        core_x = round(sum(col * weight for col, weight in zip(peak_cols, weights)) / sum(weights))
        peak_count = round(peak, 3)
        local_total = sum(counts) / max(1, len(counts))
        confidence = min(1.0, peak / max(1.0, local_total * 1.5))

    return {
        "bbox": list(bbox),
        "scan_window": [x0, scan_y0, x1, scan_y1],
        "bbox_center_x": round((x0 + x1) / 2),
        "core_x": int(core_x),
        "confidence": round(confidence, 4),
        "peak_count": peak_count,
    }


def shift_frame_horizontal(frame: Image.Image, dx: int) -> Image.Image:
    out = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    out.alpha_composite(frame, (dx, 0))
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
    center_y: int,
    core_x: int,
    x_offset: int = 0,
    y_offset: int = 0,
) -> None:
    draw.line((x_offset + center_x, y_offset, x_offset + center_x, y_offset + height - 1), fill=GUIDE_CENTER_X, width=1)
    draw.line((x_offset, y_offset + center_y, x_offset + width - 1, y_offset + center_y), fill=GUIDE_CENTER_Y, width=1)
    draw.line((x_offset + core_x, y_offset, x_offset + core_x, y_offset + height - 1), fill=GUIDE_CORE, width=1)


def make_overlay(
    frames: list[Image.Image],
    anchors: list[int],
    output: Path,
    center_x: int,
    center_y: int,
    target_core_x: int,
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
    draw_guides(draw, frames[0].width, frames[0].height, center_x, center_y, target_core_x)
    for index, anchor_x in enumerate(anchors, start=1):
        color = (255, 255, 255, 210) if index == 1 else (255, 218, 72, 190)
        draw.ellipse((anchor_x - 3, center_y - 3, anchor_x + 3, center_y + 3), fill=color)
    output.parent.mkdir(parents=True, exist_ok=True)
    base.save(output)


def make_comparison_preview(
    before: list[Image.Image],
    after: list[Image.Image],
    output: Path,
    center_x: int,
    center_y: int,
    target_core_x: int,
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
                center_y,
                target_core_x,
                x_offset,
                y_offset,
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output)


def make_frame_sheet(
    frames: list[Image.Image],
    output: Path,
    center_x: int,
    center_y: int,
    target_core_x: int,
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
        scale_x = tile / cell_width
        scale_y = tile / cell_height
        draw_bg = ImageDraw.Draw(bg)
        draw_bg.line((center_x * scale_x, 0, center_x * scale_x, tile), fill=GUIDE_CENTER_X, width=1)
        draw_bg.line((0, center_y * scale_y, tile, center_y * scale_y), fill=GUIDE_CENTER_Y, width=1)
        draw_bg.line((target_core_x * scale_x, 0, target_core_x * scale_x, tile), fill=GUIDE_CORE, width=1)
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
  <title>Horizontal Alignment Review</title>
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
  <h1>Horizontal Alignment Review</h1>
  <p>This is a separate copy-derived artifact. Original final sheet was not edited.</p>
  <div class=\"metric\">
    <div><b>Frames</b><span>{report["frame_count"]}</span></div>
    <div><b>Target core X</b><span>{report["target_core_x"]}</span></div>
    <div><b>Center Y</b><span>{report["center_y"]}</span></div>
    <div><b>Max shift</b><span>{report["max_abs_shift_px"]} px</span></div>
    <div><b>Before core stddev</b><span>{report["core_x_stddev_before"]}</span></div>
    <div><b>After core stddev</b><span>{report["core_x_stddev_after"]}</span></div>
  </div>
  <h2>Animated Check</h2>
  <div class=\"anim\">
    <figure>
      <figcaption>Copied source sheet</figcaption>
      <canvas id=\"before\" width=\"256\" height=\"256\"></canvas>
    </figure>
    <figure>
      <figcaption>Horizontal-aligned copy</figcaption>
      <canvas id=\"after\" width=\"256\" height=\"256\"></canvas>
    </figure>
  </div>
  <h2>Shadow Validation</h2>
  <div class=\"grid\">
    <figure><figcaption>Before overlay: onion-skin shadows, center lines, target core column</figcaption><img src=\"overlay_before.png\"></figure>
    <figure><figcaption>After overlay: estimated core columns cluster on the yellow guide</figcaption><img src=\"overlay_after.png\"></figure>
  </div>
  <h2>Frame Review</h2>
  <div class=\"grid\">
    <figure><figcaption>After frame sheet with guides</figcaption><img src=\"aligned_frames.png\"></figure>
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
  ctx.strokeStyle = "rgba(255,118,118,.88)";
  ctx.beginPath(); ctx.moveTo(0, {report["center_y"]}); ctx.lineTo(256, {report["center_y"]}); ctx.stroke();
  ctx.strokeStyle = "rgba(255,218,72,.9)";
  ctx.beginPath(); ctx.moveTo({report["target_core_x"]}, 0); ctx.lineTo({report["target_core_x"]}, 256); ctx.stroke();
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
    center_y = args.cell_height // 2

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
    target_core_x = int(estimates[0]["core_x"])
    shifts = [target_core_x - int(item["core_x"]) for item in estimates]
    aligned_frames = [shift_frame_horizontal(frame, dx) for frame, dx in zip(frames, shifts)]

    after_estimates = [
        estimate_core_x(
            frame,
            core_center_y=center_y,
            core_half_height=args.core_half_height,
            core_y_start_ratio=args.core_y_start,
            core_y_end_ratio=args.core_y_end,
        )
        for frame in aligned_frames
    ]
    before_cores = [int(item["core_x"]) for item in estimates]
    after_cores = [int(item["core_x"]) for item in after_estimates]

    aligned_sheet = run_dir / f"{input_path.stem}.horizontal_aligned{input_path.suffix}"
    overlay_before = run_dir / "overlay_before.png"
    overlay_after = run_dir / "overlay_after.png"
    comparison = run_dir / "comparison_before_after.png"
    frames_preview = run_dir / "aligned_frames.png"
    report_path = run_dir / "alignment_report.json"

    save_sheet(aligned_frames, aligned_sheet)
    make_overlay(frames, before_cores, overlay_before, center_x, center_y, target_core_x)
    make_overlay(aligned_frames, after_cores, overlay_after, center_x, center_y, target_core_x)
    make_comparison_preview(frames, aligned_frames, comparison, center_x, center_y, target_core_x)
    make_frame_sheet(aligned_frames, frames_preview, center_x, center_y, target_core_x)

    records = []
    clipping_warnings: list[str] = []
    for index, (before_item, after_item, shift) in enumerate(zip(estimates, after_estimates, shifts), start=1):
        bbox = after_item["bbox"]
        assert isinstance(bbox, list)
        touches_left = bbox[0] <= 0
        touches_right = bbox[2] >= args.cell_width
        if touches_left or touches_right:
            clipping_warnings.append(f"Frame {index} touches horizontal edge after shift: bbox={bbox}")
        records.append(
            {
                "index": index,
                "source_bbox": before_item["bbox"],
                "core_x_before": before_item["core_x"],
                "bbox_center_x_before": before_item["bbox_center_x"],
                "shift_x": shift,
                "core_x_after": after_item["core_x"],
                "core_confidence": before_item["confidence"],
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
        "aligned_frames": str(frames_preview),
        "frame_count": len(frames),
        "cell_size": [args.cell_width, args.cell_height],
        "axis": "horizontal-only",
        "registration_point": "estimated core/energy column",
        "target_core_x": target_core_x,
        "center_x": center_x,
        "center_y": center_y,
        "core_x_before": before_cores,
        "core_x_after": after_cores,
        "shift_x": shifts,
        "max_abs_shift_px": max(abs(value) for value in shifts),
        "mean_abs_shift_px": round(mean(abs(value) for value in shifts), 3),
        "core_x_stddev_before": round(pstdev(before_cores), 3) if len(before_cores) > 1 else 0,
        "core_x_stddev_after": round(pstdev(after_cores), 3) if len(after_cores) > 1 else 0,
        "warnings": clipping_warnings,
        "frames": records,
    }
    report_path.write_text(json.dumps(report, indent=2))
    make_review_html(run_dir, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Horizontal-only core/energy-column registration for a copied sprite sheet.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=256)
    parser.add_argument("--core-half-height", type=int, default=76)
    parser.add_argument("--core-y-start", type=float, default=0.30)
    parser.add_argument("--core-y-end", type=float, default=0.74)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
