from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw


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


def alpha_bbox(frame: Image.Image, alpha_threshold: int) -> tuple[int, int, int, int] | None:
    alpha = frame.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > alpha_threshold else 0)
    return mask.getbbox()


def anchor_for_bbox(bbox: tuple[int, int, int, int], anchor_mode: str) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    if anchor_mode == "bottom-center":
        return (x0 + x1) / 2, y1
    return (x0 + x1) / 2, (y0 + y1) / 2


def translated(frame: Image.Image, dx: int, dy: int, size: tuple[int, int]) -> Image.Image:
    width, height = size
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    src_x0 = max(0, -dx)
    src_y0 = max(0, -dy)
    src_x1 = min(frame.width, width - dx)
    src_y1 = min(frame.height, height - dy)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return out
    crop = frame.crop((src_x0, src_y0, src_x1, src_y1))
    out.alpha_composite(crop, (max(0, dx), max(0, dy)))
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


def save_preview(
    frames: list[Image.Image],
    output: Path,
    frame_size: int,
    target_x: int,
    target_y: int,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGBA", (frame_size * len(frames), frame_size), (42, 45, 50, 255))
    draw = ImageDraw.Draw(sheet)
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


def edge_touch(bbox: tuple[int, int, int, int], frame_size: int, margin: int) -> bool:
    return bbox[0] <= margin or bbox[1] <= margin or bbox[2] >= frame_size - margin or bbox[3] >= frame_size - margin


def center_frames(
    frames: list[Image.Image],
    *,
    frame_size: int,
    target_x: int,
    target_y: int,
    anchor_mode: str,
    alpha_threshold: int,
    edge_margin: int,
) -> tuple[list[Image.Image], list[dict[str, object]], list[str]]:
    centered: list[Image.Image] = []
    records: list[dict[str, object]] = []
    warnings: list[str] = []

    for index, frame in enumerate(frames, start=1):
        if frame.size != (frame_size, frame_size):
            raise ValueError(f"Frame {index} expected {frame_size}x{frame_size}, got {frame.size}")
        bbox = alpha_bbox(frame, alpha_threshold)
        if bbox is None:
            warnings.append(f"Frame {index} is empty")
            centered.append(frame)
            records.append({"index": index, "empty": True})
            continue

        anchor_x, anchor_y = anchor_for_bbox(bbox, anchor_mode)
        dx = round(target_x - anchor_x)
        dy = round(target_y - anchor_y)
        out = translated(frame, dx, dy, (frame_size, frame_size))
        final_bbox = alpha_bbox(out, alpha_threshold)
        if final_bbox is None:
            warnings.append(f"Frame {index} became empty after centering")
        elif edge_touch(final_bbox, frame_size, edge_margin):
            warnings.append(f"Frame {index} touches edge after centering: bbox={final_bbox}")

        final_anchor = anchor_for_bbox(final_bbox, anchor_mode) if final_bbox else (math.nan, math.nan)
        centered.append(out)
        records.append(
            {
                "index": index,
                "source_bbox": list(bbox),
                "source_anchor": [round(anchor_x, 3), round(anchor_y, 3)],
                "source_offset_from_target": [round(anchor_x - target_x, 3), round(anchor_y - target_y, 3)],
                "translation": [dx, dy],
                "final_bbox": list(final_bbox) if final_bbox else None,
                "final_anchor": [round(final_anchor[0], 3), round(final_anchor[1], 3)],
                "final_offset_from_target": [
                    round(final_anchor[0] - target_x, 3),
                    round(final_anchor[1] - target_y, 3),
                ],
            }
        )
    return centered, records, warnings


def max_abs_offset(records: list[dict[str, object]], key: str) -> list[float]:
    values = [record.get(key) for record in records if key in record and not record.get("empty")]
    if not values:
        return [0.0, 0.0]
    xs = [abs(float(value[0])) for value in values]  # type: ignore[index]
    ys = [abs(float(value[1])) for value in values]  # type: ignore[index]
    return [round(max(xs), 3), round(max(ys), 3)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate each transparent sprite frame so its foreground anchor is centered in the cell."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-frames-dir")
    source.add_argument("--source-sheet")
    parser.add_argument("--output", required=True)
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--preview", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--frame-prefix", default="sprite")
    parser.add_argument("--frame-size", type=int, default=256)
    parser.add_argument("--target-x", type=int, default=128)
    parser.add_argument("--target-y", type=int, default=128)
    parser.add_argument("--anchor-mode", choices=("bbox-center", "bottom-center"), default="bbox-center")
    parser.add_argument("--alpha-threshold", type=int, default=20)
    parser.add_argument("--edge-margin", type=int, default=0)
    args = parser.parse_args()

    if args.source_frames_dir:
        source_path = Path(args.source_frames_dir)
        frames, source_cells = load_frame_dir(source_path)
        source_type = "frame-directory"
    else:
        source_path = Path(args.source_sheet)
        frames, source_cells = load_sheet(source_path, args.frame_size)
        source_type = "sheet"

    centered, records, warnings = center_frames(
        frames,
        frame_size=args.frame_size,
        target_x=args.target_x,
        target_y=args.target_y,
        anchor_mode=args.anchor_mode,
        alpha_threshold=args.alpha_threshold,
        edge_margin=args.edge_margin,
    )

    output = Path(args.output)
    frames_dir = Path(args.frames_dir)
    preview = Path(args.preview)
    save_frames(centered, frames_dir, args.frame_prefix)
    save_sheet(centered, output, args.frame_size)
    save_preview(centered, preview, args.frame_size, args.target_x, args.target_y)

    report = {
        "status": "pass" if not any("touches edge" in warning or "became empty" in warning for warning in warnings) else "fail",
        "warnings": warnings,
        "source": str(source_path),
        "source_type": source_type,
        "output": str(output),
        "preview": str(preview),
        "frames_dir": str(frames_dir),
        "frame_count": len(centered),
        "frame_size": args.frame_size,
        "sheet_size": [args.frame_size * len(centered), args.frame_size],
        "anchor_mode": args.anchor_mode,
        "target": [args.target_x, args.target_y],
        "alpha_threshold": args.alpha_threshold,
        "edge_margin": args.edge_margin,
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
