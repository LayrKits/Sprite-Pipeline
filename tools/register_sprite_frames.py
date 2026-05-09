from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def natural_sort_key(path: Path) -> list[tuple[int, object]]:
    parts = re.split(r"(\d+)", path.name)
    return [(1, int(part)) if part.isdigit() else (0, part.lower()) for part in parts]


def source_paths(source_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in source_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ],
        key=natural_sort_key,
    )


def load_frame_dir(source_dir: Path) -> tuple[list[Image.Image], list[dict[str, object]]]:
    paths = source_paths(source_dir)
    if not paths:
        raise ValueError(f"No image frames found in {source_dir}")
    return (
        [Image.open(path).convert("RGBA") for path in paths],
        [{"index": index, "path": str(path)} for index, path in enumerate(paths, start=1)],
    )


def load_sheet(source_sheet: Path, frame_size: int) -> tuple[list[Image.Image], list[dict[str, object]]]:
    sheet = Image.open(source_sheet).convert("RGBA")
    if sheet.height != frame_size:
        raise ValueError(f"Expected sheet height {frame_size}, got {sheet.height}")
    if sheet.width % frame_size != 0:
        raise ValueError(f"Sheet width {sheet.width} is not divisible by frame size {frame_size}")
    frame_count = sheet.width // frame_size
    frames = [
        sheet.crop((index * frame_size, 0, (index + 1) * frame_size, frame_size))
        for index in range(frame_count)
    ]
    return (
        frames,
        [{"index": index + 1, "source_box": [index * frame_size, 0, (index + 1) * frame_size, frame_size]} for index in range(frame_count)],
    )


def threshold_alpha(frame: Image.Image, threshold: int) -> Image.Image:
    return frame.getchannel("A").point(lambda value: 255 if value > threshold else 0)


def eroded_alpha_bbox(frame: Image.Image, threshold: int, iterations: int) -> tuple[int, int, int, int] | None:
    mask = threshold_alpha(frame, threshold)
    for _ in range(iterations):
        mask = mask.filter(ImageFilter.MinFilter(3))
    return mask.getbbox()


def alpha_bbox(frame: Image.Image, threshold: int) -> tuple[int, int, int, int] | None:
    return threshold_alpha(frame, threshold).getbbox()


def bbox_center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def bottom_center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x0, _, x1, y1 = bbox
    return (x0 + x1) / 2, y1


def load_manual_anchors(path: Path | None) -> dict[int, tuple[float, float]]:
    if path is None:
        return {}
    data = json.loads(path.read_text())
    frames = data.get("frames", data)
    anchors: dict[int, tuple[float, float]] = {}
    for key, value in frames.items():
        if isinstance(value, dict):
            raw_anchor = value.get("anchor")
        else:
            raw_anchor = value
        if not raw_anchor or len(raw_anchor) != 2:
            raise ValueError(f"Manual anchor for frame {key!r} must be [x, y]")
        anchors[int(key)] = (float(raw_anchor[0]), float(raw_anchor[1]))
    return anchors


def choose_anchor(
    frame: Image.Image,
    frame_index: int,
    *,
    anchor_mode: str,
    alpha_threshold: int,
    core_erode: int,
    manual_anchors: dict[int, tuple[float, float]],
) -> tuple[float, float, tuple[int, int, int, int] | None, tuple[int, int, int, int] | None, str]:
    full_bbox = alpha_bbox(frame, alpha_threshold)
    if full_bbox is None:
        return math.nan, math.nan, None, None, "empty"

    if frame_index in manual_anchors:
        x, y = manual_anchors[frame_index]
        core_bbox = eroded_alpha_bbox(frame, alpha_threshold, core_erode)
        return x, y, full_bbox, core_bbox, "manual"

    if anchor_mode == "bbox-center":
        x, y = bbox_center(full_bbox)
        return x, y, full_bbox, None, "bbox-center"

    if anchor_mode == "bottom-center":
        x, y = bottom_center(full_bbox)
        return x, y, full_bbox, None, "bottom-center"

    core_bbox = eroded_alpha_bbox(frame, alpha_threshold, core_erode)
    if core_bbox is None:
        x, y = bbox_center(full_bbox)
        return x, y, full_bbox, None, "core-center-fallback"
    x, y = bbox_center(core_bbox)
    return x, y, full_bbox, core_bbox, "core-center"


def translated(frame: Image.Image, dx: int, dy: int, frame_size: int) -> Image.Image:
    out = Image.new("RGBA", (frame_size, frame_size), (0, 0, 0, 0))
    src_x0 = max(0, -dx)
    src_y0 = max(0, -dy)
    src_x1 = min(frame.width, frame_size - dx)
    src_y1 = min(frame.height, frame_size - dy)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return out
    out.alpha_composite(frame.crop((src_x0, src_y0, src_x1, src_y1)), (max(0, dx), max(0, dy)))
    return out


def save_frames(frames: list[Image.Image], frames_dir: Path, frame_prefix: str) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames, start=1):
        frame.save(frames_dir / f"{frame_prefix}_{index:02d}.png")


def save_sheet(frames: list[Image.Image], output: Path, frame_size: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGBA", (frame_size * len(frames), frame_size), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        sheet.alpha_composite(frame, (index * frame_size, 0))
    sheet.save(output)


def draw_cross(draw: ImageDraw.ImageDraw, x: float, y: float, color: tuple[int, int, int, int], radius: int = 6) -> None:
    xi = round(x)
    yi = round(y)
    draw.line((xi - radius, yi, xi + radius, yi), fill=color, width=1)
    draw.line((xi, yi - radius, xi, yi + radius), fill=color, width=1)
    draw.ellipse((xi - 2, yi - 2, xi + 2, yi + 2), outline=color, width=1)


def save_preview(frames: list[Image.Image], output: Path, frame_size: int, target: tuple[int, int]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGBA", (frame_size * len(frames), frame_size), (42, 45, 50, 255))
    draw = ImageDraw.Draw(sheet)
    target_x, target_y = target
    for index, frame in enumerate(frames):
        x0 = index * frame_size
        for y in range(0, frame_size, 32):
            for x in range(x0, x0 + frame_size, 32):
                fill = (50, 54, 60, 255) if ((x // 32 + y // 32) % 2) else (36, 39, 44, 255)
                draw.rectangle((x, y, min(x + 31, x0 + frame_size - 1), min(y + 31, frame_size - 1)), fill=fill)
        draw.line((x0 + target_x, 0, x0 + target_x, frame_size - 1), fill=(120, 180, 255, 120))
        draw.line((x0, target_y, x0 + frame_size - 1, target_y), fill=(120, 255, 160, 120))
        sheet.alpha_composite(frame, (x0, 0))
        draw.rectangle((x0, 0, x0 + frame_size - 1, frame_size - 1), outline=(255, 255, 255, 100))
    sheet.save(output)


def save_proof(
    frames: list[Image.Image],
    records: list[dict[str, object]],
    output: Path,
    *,
    cols: int,
    cell_size: int,
    image_size: int,
) -> None:
    rows = math.ceil(len(frames) / cols)
    proof = Image.new("RGBA", (cols * cell_size, rows * cell_size), (28, 28, 28, 255))
    draw = ImageDraw.Draw(proof)
    inset = max(0, (cell_size - image_size) // 2)
    scale = image_size / frames[0].width
    for index, (frame, record) in enumerate(zip(frames, records), start=1):
        cell_x = ((index - 1) % cols) * cell_size
        cell_y = ((index - 1) // cols) * cell_size
        preview = frame.copy()
        preview.thumbnail((image_size, image_size), Image.Resampling.LANCZOS)
        x = cell_x + inset + (image_size - preview.width) // 2
        y = cell_y + inset + (image_size - preview.height) // 2
        proof.alpha_composite(preview, (x, y))

        def map_point(px: float, py: float) -> tuple[float, float]:
            return x + px * scale, y + py * scale

        full_bbox = record.get("source_bbox")
        if full_bbox:
            bx0, by0 = map_point(float(full_bbox[0]), float(full_bbox[1]))  # type: ignore[index]
            bx1, by1 = map_point(float(full_bbox[2]), float(full_bbox[3]))  # type: ignore[index]
            draw.rectangle((bx0, by0, bx1, by1), outline=(255, 220, 80, 220), width=1)
        core_bbox = record.get("core_bbox")
        if core_bbox:
            cx0, cy0 = map_point(float(core_bbox[0]), float(core_bbox[1]))  # type: ignore[index]
            cx1, cy1 = map_point(float(core_bbox[2]), float(core_bbox[3]))  # type: ignore[index]
            draw.rectangle((cx0, cy0, cx1, cy1), outline=(80, 220, 255, 220), width=1)
        anchor = record.get("source_anchor")
        if anchor:
            ax, ay = map_point(float(anchor[0]), float(anchor[1]))  # type: ignore[index]
            draw_cross(draw, ax, ay, (255, 80, 80, 255), radius=5)
        draw.rectangle((cell_x + 4, cell_y + 4, cell_x + 38, cell_y + 22), fill=(0, 0, 0, 175))
        draw.text((cell_x + 8, cell_y + 6), str(index), fill=(255, 255, 255, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    proof.save(output)


def edge_touch(bbox: tuple[int, int, int, int], frame_size: int, margin: int) -> bool:
    return bbox[0] <= margin or bbox[1] <= margin or bbox[2] >= frame_size - margin or bbox[3] >= frame_size - margin


def register_frames(
    frames: list[Image.Image],
    *,
    frame_size: int,
    anchor_mode: str,
    target: tuple[int, int],
    alpha_threshold: int,
    core_erode: int,
    edge_margin: int,
    manual_anchors: dict[int, tuple[float, float]],
) -> tuple[list[Image.Image], list[dict[str, object]], list[str]]:
    out_frames: list[Image.Image] = []
    records: list[dict[str, object]] = []
    warnings: list[str] = []
    target_x, target_y = target

    for index, frame in enumerate(frames, start=1):
        if frame.size != (frame_size, frame_size):
            raise ValueError(f"Frame {index} expected {frame_size}x{frame_size}, got {frame.size}")
        anchor_x, anchor_y, full_bbox, core_bbox, anchor_source = choose_anchor(
            frame,
            index,
            anchor_mode=anchor_mode,
            alpha_threshold=alpha_threshold,
            core_erode=core_erode,
            manual_anchors=manual_anchors,
        )
        if full_bbox is None:
            warnings.append(f"Frame {index} is empty")
            out_frames.append(frame)
            records.append({"index": index, "empty": True})
            continue
        dx = round(target_x - anchor_x)
        dy = round(target_y - anchor_y)
        registered = translated(frame, dx, dy, frame_size)
        final_bbox = alpha_bbox(registered, alpha_threshold)
        if final_bbox is None:
            warnings.append(f"Frame {index} became empty after registration")
        elif edge_touch(final_bbox, frame_size, edge_margin):
            warnings.append(f"Frame {index} touches edge after registration: bbox={final_bbox}")
        final_anchor = (anchor_x + dx, anchor_y + dy)
        out_frames.append(registered)
        records.append(
            {
                "index": index,
                "source_bbox": list(full_bbox),
                "core_bbox": list(core_bbox) if core_bbox else None,
                "anchor_source": anchor_source,
                "source_anchor": [round(anchor_x, 3), round(anchor_y, 3)],
                "source_offset_from_target": [round(anchor_x - target_x, 3), round(anchor_y - target_y, 3)],
                "translation": [dx, dy],
                "final_bbox": list(final_bbox) if final_bbox else None,
                "final_anchor": [round(final_anchor[0], 3), round(final_anchor[1], 3)],
                "final_offset_from_target": [round(final_anchor[0] - target_x, 3), round(final_anchor[1] - target_y, 3)],
            }
        )
    return out_frames, records, warnings


def max_abs_offset(records: list[dict[str, object]], key: str) -> list[float]:
    values = [record.get(key) for record in records if key in record and not record.get("empty")]
    if not values:
        return [0.0, 0.0]
    xs = [abs(float(value[0])) for value in values]  # type: ignore[index]
    ys = [abs(float(value[1])) for value in values]  # type: ignore[index]
    return [round(max(xs), 3), round(max(ys), 3)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register sprite frames to a chosen pivot/root anchor and emit proof sheets for review."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-frames-dir")
    source.add_argument("--source-sheet")
    parser.add_argument("--output", required=True)
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--preview", required=True)
    parser.add_argument("--proof", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--frame-prefix", default="sprite")
    parser.add_argument("--frame-size", type=int, default=256)
    parser.add_argument("--target-x", type=int, default=128)
    parser.add_argument("--target-y", type=int, default=128)
    parser.add_argument("--anchor-mode", choices=("core-center", "bbox-center", "bottom-center"), default="core-center")
    parser.add_argument("--core-erode", type=int, default=4)
    parser.add_argument("--manual-anchors")
    parser.add_argument("--alpha-threshold", type=int, default=20)
    parser.add_argument("--edge-margin", type=int, default=0)
    parser.add_argument("--proof-cols", type=int, default=12)
    parser.add_argument("--proof-cell-size", type=int, default=136)
    parser.add_argument("--proof-image-size", type=int, default=118)
    args = parser.parse_args()

    if args.source_frames_dir:
        source_path = Path(args.source_frames_dir)
        frames, source_cells = load_frame_dir(source_path)
        source_type = "frame-directory"
    else:
        source_path = Path(args.source_sheet)
        frames, source_cells = load_sheet(source_path, args.frame_size)
        source_type = "sheet"

    manual_anchors = load_manual_anchors(Path(args.manual_anchors) if args.manual_anchors else None)
    registered, records, warnings = register_frames(
        frames,
        frame_size=args.frame_size,
        anchor_mode=args.anchor_mode,
        target=(args.target_x, args.target_y),
        alpha_threshold=args.alpha_threshold,
        core_erode=args.core_erode,
        edge_margin=args.edge_margin,
        manual_anchors=manual_anchors,
    )

    output = Path(args.output)
    frames_dir = Path(args.frames_dir)
    preview = Path(args.preview)
    proof = Path(args.proof)
    save_frames(registered, frames_dir, args.frame_prefix)
    save_sheet(registered, output, args.frame_size)
    save_preview(registered, preview, args.frame_size, (args.target_x, args.target_y))
    save_proof(
        frames,
        records,
        proof,
        cols=args.proof_cols,
        cell_size=args.proof_cell_size,
        image_size=args.proof_image_size,
    )

    hard_fail = any("touches edge" in warning or "became empty" in warning for warning in warnings)
    report = {
        "status": "fail" if hard_fail else "pass",
        "warnings": warnings,
        "source": str(source_path),
        "source_type": source_type,
        "output": str(output),
        "preview": str(preview),
        "proof": str(proof),
        "frames_dir": str(frames_dir),
        "frame_count": len(registered),
        "frame_size": args.frame_size,
        "sheet_size": [args.frame_size * len(registered), args.frame_size],
        "anchor_mode": args.anchor_mode,
        "target": [args.target_x, args.target_y],
        "core_erode": args.core_erode,
        "manual_anchor_count": len(manual_anchors),
        "max_abs_offset_before": max_abs_offset(records, "source_offset_from_target"),
        "max_abs_offset_after": max_abs_offset(records, "final_offset_from_target"),
        "frames": records,
        "source_cells": source_cells,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
