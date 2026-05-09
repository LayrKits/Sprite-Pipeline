from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from statistics import mean, pstdev

from PIL import Image

from vertical_align_sheet import (
    alpha_bbox,
    estimate_waist_y,
    make_comparison_preview,
    make_contact_sheet,
    make_overlay,
    save_sheet,
    shift_frame_vertical,
    split_sheet,
)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def apply_floor_and_canvas_limits(
    shift: int,
    bbox: list[int],
    cell_height: int,
    ground_y: int,
    floor_tolerance: int,
    top_padding: int,
) -> int:
    max_down = ground_y + floor_tolerance - bbox[3]
    min_up = top_padding - bbox[1]
    return clamp(shift, min_up, max_down)


def compute_candidate_shifts(
    mode: str,
    strict_shifts: list[int],
    bboxes: list[list[int]],
    cell_height: int,
    ground_y: int,
    floor_tolerance: int,
    top_padding: int,
) -> list[int]:
    if mode == "strict_waist":
        return strict_shifts

    if mode == "waist_floor_clamped":
        return [
            apply_floor_and_canvas_limits(shift, bbox, cell_height, ground_y, floor_tolerance, top_padding)
            for shift, bbox in zip(strict_shifts, bboxes)
        ]

    if mode.startswith("capped_"):
        cap = int(mode.split("_", 1)[1])
        return [
            apply_floor_and_canvas_limits(
                clamp(shift, -cap, cap),
                bbox,
                cell_height,
                ground_y,
                floor_tolerance,
                top_padding,
            )
            for shift, bbox in zip(strict_shifts, bboxes)
        ]

    if mode.startswith("blend_"):
        ratio = int(mode.split("_", 1)[1]) / 100
        return [
            apply_floor_and_canvas_limits(
                round(shift * ratio),
                bbox,
                cell_height,
                ground_y,
                floor_tolerance,
                top_padding,
            )
            for shift, bbox in zip(strict_shifts, bboxes)
        ]

    raise ValueError(f"Unknown candidate mode: {mode}")


def compute_contact_baseline_repairs(
    bboxes: list[tuple[int, int, int, int]],
    contact_tolerance: int,
    max_nudge: int,
) -> list[int]:
    """Nudge small local contact-frame baseline errors without flattening airborne motion."""
    repairs = [0 for _ in bboxes]

    for index in range(1, len(bboxes) - 1):
        bbox = bboxes[index]
        bottom = bbox[3]
        prev_bottom = bboxes[index - 1][3]
        next_bottom = bboxes[index + 1][3]
        if abs(prev_bottom - next_bottom) > 1:
            continue

        target_bottom = round((prev_bottom + next_bottom) / 2)
        needed = target_bottom - bottom
        if needed == 0 or abs(needed) > max_nudge:
            continue
        if abs(needed) > contact_tolerance:
            continue
        if bbox[1] + needed < 0:
            continue

        repairs[index] = needed

    return repairs


def candidate_metrics(
    frames: list[Image.Image],
    shifts: list[int],
    baseline_repairs: list[int],
    before_estimates: list[dict[str, object]],
    after_estimates: list[dict[str, object]],
    cell_height: int,
    ground_y: int,
    floor_tolerance: int,
) -> dict[str, object]:
    waist_before = [int(item["waist_y"]) for item in before_estimates]
    waist_after = [int(item["waist_y"]) for item in after_estimates]
    shifted_source_bboxes = []
    floor_penetrations = []
    canvas_clips = []

    for index, after_estimate in enumerate(after_estimates, start=1):
        bbox = after_estimate["bbox"]
        assert isinstance(bbox, list)
        shifted = list(bbox)
        shifted_source_bboxes.append(shifted)
        penetration = max(0, shifted[3] - (ground_y + floor_tolerance))
        floor_penetrations.append(penetration)
        clip = max(0, -shifted[1]) + max(0, shifted[3] - cell_height)
        canvas_clips.append(clip)

    waist_std_before = round(pstdev(waist_before), 3) if len(waist_before) > 1 else 0.0
    waist_std_after = round(pstdev(waist_after), 3) if len(waist_after) > 1 else 0.0
    max_floor_penetration = max(floor_penetrations)
    total_floor_penetration = sum(floor_penetrations)
    max_canvas_clip = max(canvas_clips)
    mean_abs_shift = round(mean(abs(value) for value in shifts), 3)
    max_abs_shift = max(abs(value) for value in shifts)

    score = (
        waist_std_after
        + max_floor_penetration * 25
        + total_floor_penetration * 5
        + max_canvas_clip * 50
        + mean_abs_shift * 0.2
    )

    warnings = []
    if max_floor_penetration:
        frames_hit = [
            index
            for index, value in enumerate(floor_penetrations, start=1)
            if value > 0
        ]
        warnings.append(
            f"Floor penetration: max {max_floor_penetration}px on frames {frames_hit}"
        )
    if max_canvas_clip:
        frames_hit = [
            index
            for index, value in enumerate(canvas_clips, start=1)
            if value > 0
        ]
        warnings.append(f"Canvas clipping risk: max {max_canvas_clip}px on frames {frames_hit}")
    if max_abs_shift > 32:
        warnings.append(f"Aggressive vertical shifts: max {max_abs_shift}px")

    baseline_repair_frames = [
        index
        for index, value in enumerate(baseline_repairs, start=1)
        if value
    ]

    return {
        "waist_y_before": waist_before,
        "waist_y_after": waist_after,
        "waist_y_stddev_before": waist_std_before,
        "waist_y_stddev_after": waist_std_after,
        "shift_y": shifts,
        "contact_baseline_repair_shift_y": baseline_repairs,
        "contact_baseline_repair_frames": baseline_repair_frames,
        "max_abs_shift_px": max_abs_shift,
        "mean_abs_shift_px": mean_abs_shift,
        "floor_penetration_by_frame": floor_penetrations,
        "max_floor_penetration_px": max_floor_penetration,
        "total_floor_penetration_px": total_floor_penetration,
        "canvas_clip_by_frame": canvas_clips,
        "max_canvas_clip_px": max_canvas_clip,
        "shifted_source_bboxes": shifted_source_bboxes,
        "score": round(score, 3),
        "valid": max_floor_penetration == 0 and max_canvas_clip == 0,
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
        <div><b>Waist stddev</b><span>{candidate['waist_y_stddev_after']}</span></div>
        <div><b>Floor penetration</b><span>{candidate['max_floor_penetration_px']} px</span></div>
        <div><b>Baseline fixes</b><span>{len(candidate['contact_baseline_repair_frames'])}</span></div>
        <div><b>Max shift</b><span>{candidate['max_abs_shift_px']} px</span></div>
      </div>
      <div class=\"anim-row\">
        <figure><figcaption>Animated candidate</figcaption><canvas id=\"canvas-{index}\" width=\"256\" height=\"256\"></canvas></figure>
        <figure><figcaption>Overlay</figcaption><img src=\"{rel_dir}/overlay_after.png\"></figure>
      </div>
      <details>
        <summary>Warnings and shifts</summary>
        <pre>{json.dumps({'warnings': candidate['warnings'], 'shift_y': candidate['shift_y']}, indent=2)}</pre>
      </details>
      <figure><figcaption>Contact sheet</figcaption><img src=\"{rel_dir}/aligned_contact.png\"></figure>
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
  <title>Vertical Alignment Candidate Review</title>
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
  <h1>Vertical Alignment Candidate Review</h1>
  <p><b>Confirmation required:</b> if vertical alignment is needed, open this validation viewer and get user approval before promoting any aligned candidate.</p>
  <p>A candidate is not valid unless it improves alignment without pushing any frame below the red ground guide or outside the cell.</p>
  <div class=\"top\">
    <div><b>Recommended</b><span>{report['recommended_candidate']}</span></div>
    <div><b>Lowest score</b><span>{report['best_valid_candidate']}</span></div>
    <div><b>Ground Y</b><span>{report['ground_y']}</span></div>
    <div><b>Baseline rule</b><span>local neighbors</span></div>
    <div><b>Target waist Y</b><span>{report['target_waist_y']}</span></div>
    <div><b>Frames</b><span>{report['frame_count']}</span></div>
  </div>
  <figure><figcaption>Original copied sheet overlay</figcaption><img src=\"overlay_source.png\"></figure>
  {''.join(candidate_cards)}
</main>
<script>
const frameCount = {report['frame_count']};
const groundY = {report['ground_y']};
const waistY = {report['target_waist_y']};
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
  ctx.strokeStyle = "rgba(255,92,92,.9)";
  ctx.beginPath(); ctx.moveTo(0, groundY); ctx.lineTo(256, groundY); ctx.stroke();
  ctx.strokeStyle = "rgba(255,218,72,.9)";
  ctx.beginPath(); ctx.moveTo(0, waistY); ctx.lineTo(256, waistY); ctx.stroke();
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
    first_bbox = alpha_bbox(frames[0])
    ground_y = first_bbox[3]

    before_estimates = [
        estimate_waist_y(
            frame,
            core_center_x=center_x,
            core_half_width=args.core_half_width,
            waist_start_ratio=args.waist_start,
            waist_end_ratio=args.waist_end,
        )
        for frame in frames
    ]
    target_waist_y = int(before_estimates[0]["waist_y"])
    waist_before = [int(item["waist_y"]) for item in before_estimates]
    bboxes = [item["bbox"] for item in before_estimates]
    assert all(isinstance(item, list) for item in bboxes)
    strict_shifts = [target_waist_y - value for value in waist_before]

    make_overlay(frames, waist_before, run_dir / "overlay_source.png", center_x, ground_y, target_waist_y)

    candidate_reports = []
    for mode in args.modes.split(","):
        name = mode.strip()
        if not name:
            continue
        shifts = compute_candidate_shifts(
            name,
            strict_shifts,
            bboxes,  # type: ignore[arg-type]
            args.cell_height,
            ground_y,
            args.floor_tolerance,
            args.top_padding,
        )
        aligned_frames = [shift_frame_vertical(frame, shift) for frame, shift in zip(frames, shifts)]
        aligned_bboxes = [alpha_bbox(frame, threshold=0) for frame in aligned_frames]
        baseline_repairs = compute_contact_baseline_repairs(
            aligned_bboxes,
            args.contact_baseline_tolerance,
            args.max_contact_baseline_nudge,
        )
        if any(baseline_repairs):
            shifts = [
                shift + repair
                for shift, repair in zip(shifts, baseline_repairs)
            ]
            aligned_frames = [shift_frame_vertical(frame, shift) for frame, shift in zip(frames, shifts)]
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
                    "offsets": [0 for _ in aligned_frames],
                    "source": str(aligned_sheet),
                    "working_sheet": str(working_sheet),
                },
                indent=2,
            )
        )
        metrics = candidate_metrics(
            frames,
            shifts,
            baseline_repairs,
            before_estimates,
            after_estimates,
            args.cell_height,
            ground_y,
            args.floor_tolerance,
        )
        after_waists = [int(item["waist_y"]) for item in after_estimates]
        make_overlay(aligned_frames, after_waists, candidate_dir / "overlay_after.png", center_x, ground_y, target_waist_y)
        make_comparison_preview(frames, aligned_frames, candidate_dir / "comparison_before_after.png", center_x, ground_y, target_waist_y)
        make_contact_sheet(aligned_frames, candidate_dir / "aligned_contact.png", center_x, ground_y, target_waist_y)
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
        "axis": "vertical-only",
        "target_waist_y": target_waist_y,
        "ground_y": ground_y,
        "contact_baseline_rule": "local_neighbor_bottom",
        "contact_baseline_tolerance": args.contact_baseline_tolerance,
        "max_contact_baseline_nudge": args.max_contact_baseline_nudge,
        "floor_tolerance": args.floor_tolerance,
        "top_padding": args.top_padding,
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
    parser = argparse.ArgumentParser(description="Generate and validate vertical alignment candidates.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=256)
    parser.add_argument("--core-half-width", type=int, default=76)
    parser.add_argument("--waist-start", type=float, default=0.34)
    parser.add_argument("--waist-end", type=float, default=0.70)
    parser.add_argument("--floor-tolerance", type=int, default=2)
    parser.add_argument("--top-padding", type=int, default=0)
    parser.add_argument(
        "--contact-baseline-tolerance",
        type=int,
        default=4,
        help="Near-contact frames within this many pixels of the contact target can be reviewed for local floating dips.",
    )
    parser.add_argument(
        "--max-contact-baseline-nudge",
        type=int,
        default=4,
        help="Maximum automatic downward nudge for a locally floating grounded-looking frame.",
    )
    parser.add_argument(
        "--modes",
        default="strict_waist,waist_floor_clamped,capped_12,capped_24,blend_50,blend_35",
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
