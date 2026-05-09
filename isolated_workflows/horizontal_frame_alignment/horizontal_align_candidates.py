from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from statistics import mean, pstdev

from PIL import Image

from horizontal_align_sheet import (
    alpha_bbox,
    estimate_core_x,
    make_comparison_preview,
    make_frame_sheet,
    make_overlay,
    save_sheet,
    shift_frame_horizontal,
    split_sheet,
)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def apply_edge_and_canvas_limits(
    shift: int,
    bbox: list[int],
    cell_width: int,
    left_padding: int,
    right_padding: int,
) -> int:
    min_left = left_padding - bbox[0]
    max_right = (cell_width - right_padding) - bbox[2]
    return clamp(shift, min_left, max_right)


def compute_candidate_shifts(
    mode: str,
    strict_shifts: list[int],
    bboxes: list[list[int]],
    cell_width: int,
    left_padding: int,
    right_padding: int,
) -> list[int]:
    if mode == "strict_core":
        return strict_shifts

    if mode == "core_edge_clamped":
        return [
            apply_edge_and_canvas_limits(shift, bbox, cell_width, left_padding, right_padding)
            for shift, bbox in zip(strict_shifts, bboxes)
        ]

    if mode.startswith("capped_"):
        cap = int(mode.split("_", 1)[1])
        return [
            apply_edge_and_canvas_limits(
                clamp(shift, -cap, cap),
                bbox,
                cell_width,
                left_padding,
                right_padding,
            )
            for shift, bbox in zip(strict_shifts, bboxes)
        ]

    if mode.startswith("blend_"):
        ratio = int(mode.split("_", 1)[1]) / 100
        return [
            apply_edge_and_canvas_limits(
                round(shift * ratio),
                bbox,
                cell_width,
                left_padding,
                right_padding,
            )
            for shift, bbox in zip(strict_shifts, bboxes)
        ]

    raise ValueError(f"Unknown candidate mode: {mode}")


def compute_local_anchor_repairs(
    core_x: list[int],
    bboxes: list[tuple[int, int, int, int]],
    cell_width: int,
    tolerance: int,
    max_nudge: int,
) -> list[int]:
    """Nudge small local horizontal pops without flattening broad lateral motion."""
    repairs = [0 for _ in core_x]

    for index in range(1, len(core_x) - 1):
        prev_core = core_x[index - 1]
        next_core = core_x[index + 1]
        if abs(prev_core - next_core) > 1:
            continue

        target_core = round((prev_core + next_core) / 2)
        needed = target_core - core_x[index]
        if needed == 0 or abs(needed) > max_nudge:
            continue
        if abs(needed) > tolerance:
            continue

        bbox = bboxes[index]
        if bbox[0] + needed < 0 or bbox[2] + needed > cell_width:
            continue

        repairs[index] = needed

    return repairs


def candidate_metrics(
    shifts: list[int],
    local_repairs: list[int],
    before_estimates: list[dict[str, object]],
    after_estimates: list[dict[str, object]],
    cell_width: int,
    left_padding: int,
    right_padding: int,
) -> dict[str, object]:
    core_before = [int(item["core_x"]) for item in before_estimates]
    core_after = [int(item["core_x"]) for item in after_estimates]
    shifted_source_bboxes = []
    canvas_clips = []

    for after_estimate in after_estimates:
        bbox = after_estimate["bbox"]
        assert isinstance(bbox, list)
        shifted = list(bbox)
        shifted_source_bboxes.append(shifted)
        clip = max(0, left_padding - shifted[0]) + max(0, shifted[2] - (cell_width - right_padding))
        canvas_clips.append(clip)

    core_std_before = round(pstdev(core_before), 3) if len(core_before) > 1 else 0.0
    core_std_after = round(pstdev(core_after), 3) if len(core_after) > 1 else 0.0
    max_canvas_clip = max(canvas_clips)
    total_canvas_clip = sum(canvas_clips)
    mean_abs_shift = round(mean(abs(value) for value in shifts), 3)
    max_abs_shift = max(abs(value) for value in shifts)

    score = (
        core_std_after
        + max_canvas_clip * 50
        + total_canvas_clip * 10
        + mean_abs_shift * 0.2
    )

    warnings = []
    if max_canvas_clip:
        frames_hit = [
            index
            for index, value in enumerate(canvas_clips, start=1)
            if value > 0
        ]
        warnings.append(f"Canvas clipping risk: max {max_canvas_clip}px on frames {frames_hit}")
    if max_abs_shift > 32:
        warnings.append(f"Aggressive horizontal shifts: max {max_abs_shift}px")

    local_repair_frames = [
        index
        for index, value in enumerate(local_repairs, start=1)
        if value
    ]

    return {
        "core_x_before": core_before,
        "core_x_after": core_after,
        "core_x_stddev_before": core_std_before,
        "core_x_stddev_after": core_std_after,
        "shift_x": shifts,
        "local_anchor_repair_shift_x": local_repairs,
        "local_anchor_repair_frames": local_repair_frames,
        "max_abs_shift_px": max_abs_shift,
        "mean_abs_shift_px": mean_abs_shift,
        "canvas_clip_by_frame": canvas_clips,
        "max_canvas_clip_px": max_canvas_clip,
        "total_canvas_clip_px": total_canvas_clip,
        "shifted_source_bboxes": shifted_source_bboxes,
        "score": round(score, 3),
        "valid": max_canvas_clip == 0,
        "warnings": warnings,
    }


def pick_recommended_candidate(
    valid_candidates: list[dict[str, object]],
    clean_candidates: list[dict[str, object]],
    policy: str,
) -> dict[str, object] | None:
    best_valid = min(valid_candidates, key=lambda item: item["score"]) if valid_candidates else None
    if policy == "lowest_valid":
        return best_valid
    if policy == "cleanest_valid":
        return min(clean_candidates, key=lambda item: item["score"]) if clean_candidates else best_valid
    raise ValueError(f"Unknown recommendation policy: {policy}")


def write_candidate_review(run_dir: Path, report: dict[str, object]) -> None:
    candidates = report["candidates"]
    assert isinstance(candidates, list)
    candidate_cards = []
    animation_scripts = []
    for index, candidate in enumerate(candidates):
        assert isinstance(candidate, dict)
        name = str(candidate["name"])
        rel_dir = f"candidates/{name}"
        valid_text = "valid" if candidate["valid"] else "invalid"
        candidate_cards.append(
            f"""
    <section class=\"candidate {'valid' if candidate['valid'] else 'invalid'}\">
      <h2>{name.replace('_', ' ')}</h2>
      <div class=\"metrics\">
        <div><b>Status</b><span>{valid_text}</span></div>
        <div><b>Score</b><span>{candidate['score']}</span></div>
        <div><b>Core stddev</b><span>{candidate['core_x_stddev_after']}</span></div>
        <div><b>Canvas clip</b><span>{candidate['max_canvas_clip_px']} px</span></div>
        <div><b>Local fixes</b><span>{len(candidate['local_anchor_repair_frames'])}</span></div>
        <div><b>Max shift</b><span>{candidate['max_abs_shift_px']} px</span></div>
      </div>
      <div class=\"anim-row\">
        <figure><figcaption>Animated candidate</figcaption><canvas id=\"canvas-{index}\" width=\"256\" height=\"256\"></canvas></figure>
        <figure><figcaption>Overlay</figcaption><img src=\"{rel_dir}/overlay_after.png\"></figure>
      </div>
      <details>
        <summary>Warnings and shifts</summary>
        <pre>{json.dumps({'warnings': candidate['warnings'], 'shift_x': candidate['shift_x']}, indent=2)}</pre>
      </details>
      <figure><figcaption>Frame sheet</figcaption><img src=\"{rel_dir}/aligned_frames.png\"></figure>
    </section>
"""
        )
        animation_scripts.append(
            f"""
const img{index} = new Image();
img{index}.src = "candidates/{name}/{Path(str(candidate['aligned_sheet'])).name}";
const canvas{index} = document.getElementById("canvas-{index}");
const ctx{index} = canvas{index}.getContext("2d");
animated.push([img{index}, ctx{index}]);
"""
        )

    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Horizontal Alignment Candidate Review</title>
  <style>
    :root {{ color-scheme: dark; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #15191e; color: #eef3f8; }}
    main {{ max-width: 1220px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px; }}
    h2 {{ margin: 0 0 12px; text-transform: capitalize; }}
    p {{ color: #b5c0ce; line-height: 1.5; }}
    .top {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 16px 0 22px; }}
    .top div, .metrics div {{ background: #20262d; border: 1px solid #39434f; border-radius: 6px; padding: 12px; }}
    b {{ display: block; font-size: 12px; color: #93a4b8; text-transform: uppercase; }}
    span {{ display: block; margin-top: 5px; font-size: 18px; }}
    .candidate {{ margin: 20px 0; padding: 16px; border: 1px solid #3a4552; border-radius: 8px; background: #1c2229; }}
    .candidate.valid {{ border-color: #4fb58f; }}
    .candidate.invalid {{ border-color: #b75b5b; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 16px; }}
    .anim-row {{ display: grid; grid-template-columns: minmax(270px, 330px) minmax(270px, 1fr); gap: 16px; align-items: start; }}
    figure {{ margin: 0 0 16px; }}
    figcaption {{ color: #cbd5e1; font-size: 13px; margin-bottom: 8px; }}
    canvas, img {{ max-width: 100%; background: #101419; border: 1px solid #39434f; border-radius: 4px; }}
    canvas {{ width: 256px; height: 256px; }}
    pre {{ white-space: pre-wrap; color: #dce7f3; background: #11161c; border: 1px solid #39434f; border-radius: 4px; padding: 10px; }}
    code {{ color: #f8d86b; }}
  </style>
</head>
<body>
<main>
  <h1>Horizontal Alignment Candidate Review</h1>
  <p><b>Confirmation required:</b> if horizontal alignment is needed, open this validation viewer and get user approval before promoting any aligned candidate.</p>
  <p>A candidate is not valid unless it improves alignment without pushing any frame outside the left or right cell edge.</p>
  <div class=\"top\">
    <div><b>Recommended</b><span>{report['recommended_candidate']}</span></div>
    <div><b>Lowest score</b><span>{report['best_valid_candidate']}</span></div>
    <div><b>Target core X</b><span>{report['target_core_x']}</span></div>
    <div><b>Baseline rule</b><span>local neighbors</span></div>
    <div><b>Center Y</b><span>{report['center_y']}</span></div>
    <div><b>Frames</b><span>{report['frame_count']}</span></div>
  </div>
  <figure><figcaption>Original copied sheet overlay</figcaption><img src=\"overlay_source.png\"></figure>
  {''.join(candidate_cards)}
</main>
<script>
const frameCount = {report['frame_count']};
const centerY = {report['center_y']};
const targetCoreX = {report['target_core_x']};
const animated = [];
{''.join(animation_scripts)}
let frame = 0;
function checker(ctx) {{
  const size = 16;
  for (let y = 0; y < 256; y += size) {{
    for (let x = 0; x < 256; x += size) {{
      ctx.fillStyle = ((x / size + y / size) % 2) ? "#2b3037" : "#22262b";
      ctx.fillRect(x, y, size, size);
    }}
  }}
}}
function drawGuides(ctx) {{
  ctx.strokeStyle = "rgba(80,218,255,.82)";
  ctx.beginPath(); ctx.moveTo(128, 0); ctx.lineTo(128, 256); ctx.stroke();
  ctx.strokeStyle = "rgba(255,118,118,.88)";
  ctx.beginPath(); ctx.moveTo(0, centerY); ctx.lineTo(256, centerY); ctx.stroke();
  ctx.strokeStyle = "rgba(255,218,72,.9)";
  ctx.beginPath(); ctx.moveTo(targetCoreX, 0); ctx.lineTo(targetCoreX, 256); ctx.stroke();
}}
function tick() {{
  for (const [img, ctx] of animated) {{
    if (!img.complete) continue;
    checker(ctx);
    ctx.drawImage(img, frame * 256, 0, 256, 256, 0, 0, 256, 256);
    drawGuides(ctx);
  }}
  frame = (frame + 1) % frameCount;
  setTimeout(tick, 1000 / 12);
}}
tick();
</script>
</body>
</html>
"""
    (run_dir / "candidate_review.html").write_text(html)


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

    before_estimates = [
        estimate_core_x(
            frame,
            core_center_y=center_y,
            core_half_height=args.core_half_height,
            core_y_start_ratio=args.core_y_start,
            core_y_end_ratio=args.core_y_end,
        )
        for frame in frames
    ]
    target_core_x = int(before_estimates[0]["core_x"])
    core_before = [int(item["core_x"]) for item in before_estimates]
    bboxes = [item["bbox"] for item in before_estimates]
    assert all(isinstance(item, list) for item in bboxes)
    strict_shifts = [target_core_x - value for value in core_before]

    make_overlay(frames, core_before, run_dir / "overlay_source.png", center_x, center_y, target_core_x)

    candidate_reports = []
    for mode in args.modes.split(","):
        name = mode.strip()
        if not name:
            continue
        shifts = compute_candidate_shifts(
            name,
            strict_shifts,
            bboxes,  # type: ignore[arg-type]
            args.cell_width,
            args.left_padding,
            args.right_padding,
        )
        aligned_frames = [shift_frame_horizontal(frame, shift) for frame, shift in zip(frames, shifts)]
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
        aligned_cores = [int(item["core_x"]) for item in after_estimates]
        aligned_bboxes = [alpha_bbox(frame, threshold=0) for frame in aligned_frames]
        local_repairs = compute_local_anchor_repairs(
            aligned_cores,
            aligned_bboxes,
            args.cell_width,
            args.local_anchor_tolerance,
            args.max_local_anchor_nudge,
        )
        if any(local_repairs):
            shifts = [
                shift + repair
                for shift, repair in zip(shifts, local_repairs)
            ]
            aligned_frames = [shift_frame_horizontal(frame, shift) for frame, shift in zip(frames, shifts)]
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
        candidate_dir = run_dir / "candidates" / name
        candidate_dir.mkdir(parents=True, exist_ok=True)
        aligned_sheet = candidate_dir / f"{input_path.stem}.{name}.png"
        save_sheet(aligned_frames, aligned_sheet)
        working_dir = run_dir / "working_copies" / name
        working_dir.mkdir(parents=True, exist_ok=True)
        working_sheet = working_dir / f"{input_path.stem}.{name}.work.png"
        working_offsets = working_dir / f"{input_path.stem}.{name}.work.offsets.json"
        shutil.copy2(aligned_sheet, working_sheet)
        working_offsets.write_text(
            json.dumps(
                {
                    "method": name,
                    "axis": "x",
                    "offsets": [0 for _ in aligned_frames],
                    "source": str(aligned_sheet),
                    "working_sheet": str(working_sheet),
                },
                indent=2,
            )
        )
        metrics = candidate_metrics(
            shifts,
            local_repairs,
            before_estimates,
            after_estimates,
            args.cell_width,
            args.left_padding,
            args.right_padding,
        )
        after_cores = [int(item["core_x"]) for item in after_estimates]
        make_overlay(aligned_frames, after_cores, candidate_dir / "overlay_after.png", center_x, center_y, target_core_x)
        make_comparison_preview(frames, aligned_frames, candidate_dir / "comparison_before_after.png", center_x, center_y, target_core_x)
        make_frame_sheet(aligned_frames, candidate_dir / "aligned_frames.png", center_x, center_y, target_core_x)
        candidate_report = {
            "name": name,
            "aligned_sheet": str(aligned_sheet),
            "working_sheet": str(working_sheet),
            "working_offsets": str(working_offsets),
            **metrics,
        }
        (candidate_dir / "candidate_report.json").write_text(json.dumps(candidate_report, indent=2))
        candidate_reports.append(candidate_report)

    valid_candidates = [item for item in candidate_reports if item["valid"]]
    clean_candidates = [
        item for item in valid_candidates
        if not item["warnings"]
    ]
    best_valid = min(valid_candidates, key=lambda item: item["score"]) if valid_candidates else None
    recommendation_policy = getattr(args, "recommendation_policy", "lowest_valid")
    recommended = pick_recommended_candidate(valid_candidates, clean_candidates, recommendation_policy)
    sorted_candidates = sorted(candidate_reports, key=lambda item: item["score"])
    if recommended:
        sorted_candidates = [
            item for item in sorted_candidates
            if item["name"] != recommended["name"]
        ]
        sorted_candidates.insert(0, recommended)

    report = {
        "input": str(input_path),
        "source_copy": str(source_copy),
        "frame_count": len(frames),
        "cell_size": [args.cell_width, args.cell_height],
        "axis": "horizontal-only",
        "target_core_x": target_core_x,
        "center_x": center_x,
        "center_y": center_y,
        "local_anchor_rule": "local_neighbor_core_x",
        "local_anchor_tolerance": args.local_anchor_tolerance,
        "max_local_anchor_nudge": args.max_local_anchor_nudge,
        "left_padding": args.left_padding,
        "right_padding": args.right_padding,
        "recommendation_policy": recommendation_policy,
        "best_valid_candidate": best_valid["name"] if best_valid else None,
        "best_valid_sheet": best_valid["aligned_sheet"] if best_valid else None,
        "recommended_candidate": recommended["name"] if recommended else None,
        "recommended_sheet": recommended["aligned_sheet"] if recommended else None,
        "candidates": sorted_candidates,
    }
    (run_dir / "candidate_summary.json").write_text(json.dumps(report, indent=2))
    write_candidate_review(run_dir, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and validate horizontal alignment candidates.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=256)
    parser.add_argument("--core-half-height", type=int, default=76)
    parser.add_argument("--core-y-start", type=float, default=0.30)
    parser.add_argument("--core-y-end", type=float, default=0.74)
    parser.add_argument("--left-padding", type=int, default=0)
    parser.add_argument("--right-padding", type=int, default=0)
    parser.add_argument(
        "--local-anchor-tolerance",
        type=int,
        default=4,
        help="Frames within this many pixels of a local-neighbor core target can receive a small repair nudge.",
    )
    parser.add_argument(
        "--max-local-anchor-nudge",
        type=int,
        default=4,
        help="Maximum automatic sideways nudge for a locally drifting frame.",
    )
    parser.add_argument(
        "--modes",
        default="strict_core,core_edge_clamped,capped_8,capped_12,capped_24,blend_50,blend_35",
    )
    parser.add_argument(
        "--recommendation-policy",
        choices=["lowest_valid", "cleanest_valid"],
        default="lowest_valid",
        help="Choose the candidate exposed as recommended in the machine-readable summary.",
    )
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
