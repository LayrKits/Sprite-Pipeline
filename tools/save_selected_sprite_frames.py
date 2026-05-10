from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_file_segment(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "sprite"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    return path.with_name(f"{path.stem}_{timestamp_slug()}{path.suffix}")


def parse_frames(value: str) -> list[int]:
    frames: list[int] = []
    seen: set[int] = set()
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        frame = int(item)
        if frame < 1:
            raise ValueError("Frame numbers must be 1 or greater.")
        if frame not in seen:
            seen.add(frame)
            frames.append(frame)
    if not frames:
        raise ValueError("At least one frame must be selected.")
    return frames


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save selected cells from a horizontal sprite sheet as a new promoted sheet."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--frames", required=True, help="Comma-separated 1-based frame numbers to copy.")
    parser.add_argument("--game", required=True)
    parser.add_argument("--character", required=True)
    parser.add_argument("--animation", required=True)
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=256)
    parser.add_argument("--row-index", type=int, default=0)
    parser.add_argument("--final-root", default="Final Sprite Sheets")
    parser.add_argument("--output-name")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--replace-source", action="store_true")
    args = parser.parse_args()

    selected_frames = parse_frames(args.frames)
    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"Source sheet does not exist: {source}")
    if args.cell_width < 1 or args.cell_height < 1:
        raise SystemExit("Cell size must be positive.")
    if args.row_index < 0:
        raise SystemExit("Row index must be 0 or greater.")

    sheet = Image.open(source).convert("RGBA")
    source_frame_count = sheet.width // args.cell_width
    source_row_count = sheet.height // args.cell_height
    if source_frame_count < 1 or sheet.width % args.cell_width != 0:
        raise SystemExit(f"Sheet width {sheet.width} is not divisible by cell width {args.cell_width}.")
    if source_row_count < 1 or sheet.height % args.cell_height != 0:
        raise SystemExit(f"Sheet height {sheet.height} is not divisible by cell height {args.cell_height}.")
    if args.row_index >= source_row_count:
        raise SystemExit(f"Row {args.row_index + 1} is outside the source sheet.")

    for frame in selected_frames:
        if frame > source_frame_count:
            raise SystemExit(f"Frame {frame} is outside the source sheet.")

    output = Image.new("RGBA", (len(selected_frames) * args.cell_width, args.cell_height), (0, 0, 0, 0))
    source_y = args.row_index * args.cell_height
    output_frames = []
    for output_index, frame_number in enumerate(selected_frames):
        source_index = frame_number - 1
        cell = sheet.crop(
            (
                source_index * args.cell_width,
                source_y,
                (source_index + 1) * args.cell_width,
                source_y + args.cell_height,
            )
        )
        output.alpha_composite(cell, (output_index * args.cell_width, 0))
        output_frames.append(cell)

    frame_tag = f"{len(selected_frames)}f_{args.cell_width}"
    if args.replace_source:
        output_path = source
        sheets_dir = output_path.parent
        final_dir = sheets_dir.parent if sheets_dir.name == "sheets" else sheets_dir
        frames_dir = final_dir / "frames" / frame_tag
    else:
        final_dir = Path(args.final_root) / args.game / args.character / args.animation
        sheets_dir = final_dir / "sheets"
        frames_dir = final_dir / "frames" / frame_tag
    sheets_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    if not args.replace_source:
        if args.output_name:
            output_name = args.output_name
        else:
            output_name = (
                f"{safe_file_segment(args.character)}_"
                f"{safe_file_segment(args.animation)}_"
                f"{frame_tag}.png"
            )
        if not output_name.lower().endswith(".png"):
            raise SystemExit("--output-name must end with .png")

        output_path = sheets_dir / output_name
        if not args.overwrite:
            output_path = unique_path(output_path)
    output.save(output_path)

    frame_prefix = safe_file_segment(output_path.stem)
    frame_paths = []
    for index, frame in enumerate(output_frames, start=1):
        frame_path = frames_dir / f"{frame_prefix}_{index:02d}.png"
        frame.save(frame_path)
        frame_paths.append(str(frame_path))

    report = {
        "source": str(source),
        "output": str(output_path),
        "mode": "replace_source" if args.replace_source else "extract_new_sheet",
        "game": args.game,
        "character": args.character,
        "animation": args.animation,
        "sheets_dir": str(sheets_dir),
        "frames_dir": str(frames_dir),
        "frame_count": len(selected_frames),
        "source_frame_count": source_frame_count,
        "source_frames": selected_frames,
        "row_index": args.row_index,
        "cell_size": [args.cell_width, args.cell_height],
        "sheet_size": list(output.size),
        "frames": frame_paths,
    }
    report_path = sheets_dir / f"{output_path.stem}.selected_frames.json"
    report_path.write_text(json.dumps(report, indent=2))
    report["report"] = str(report_path)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
