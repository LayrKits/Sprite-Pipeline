from __future__ import annotations

import argparse
import json
import shutil
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


def split_frames(sheet: Image.Image, cell_width: int, cell_height: int) -> list[Image.Image]:
    if sheet.height != cell_height:
        raise ValueError(f"Expected sheet height {cell_height}, got {sheet.height}")
    if sheet.width % cell_width != 0:
        raise ValueError(f"Sheet width {sheet.width} is not divisible by cell width {cell_width}")
    frame_count = sheet.width // cell_width
    return [
        sheet.crop((index * cell_width, 0, (index + 1) * cell_width, cell_height))
        for index in range(frame_count)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote an approved sprite sheet into Final Sprite Sheets with matching frame cells."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--character", required=True)
    parser.add_argument("--animation", required=True)
    parser.add_argument("--output-name", required=True)
    parser.add_argument("--frame-prefix")
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=256)
    parser.add_argument("--final-root", default="Final Sprite Sheets")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"Source sheet does not exist: {source}")
    if not args.output_name.lower().endswith(".png"):
        raise SystemExit("--output-name must end with .png")

    sheet = Image.open(source).convert("RGBA")
    frames = split_frames(sheet, args.cell_width, args.cell_height)
    frame_tag = f"{len(frames)}f_{args.cell_width}"
    final_dir = Path(args.final_root) / args.game / args.character / args.animation
    sheets_dir = final_dir / "sheets"
    frames_dir = final_dir / "frames" / frame_tag
    sheets_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    output_path = sheets_dir / args.output_name
    if not args.overwrite:
        output_path = unique_path(output_path)
    shutil.copy2(source, output_path)

    frame_prefix = args.frame_prefix or safe_file_segment(output_path.stem)
    frame_paths = []
    for index, frame in enumerate(frames, start=1):
        frame_path = frames_dir / f"{frame_prefix}_{index:02d}.png"
        frame.save(frame_path)
        frame_paths.append(str(frame_path))

    report = {
        "source": str(source),
        "output": str(output_path),
        "game": args.game,
        "character": args.character,
        "animation": args.animation,
        "sheets_dir": str(sheets_dir),
        "frames_dir": str(frames_dir),
        "frame_count": len(frames),
        "cell_size": [args.cell_width, args.cell_height],
        "sheet_size": list(sheet.size),
        "frames": frame_paths,
    }
    report_path = sheets_dir / f"{output_path.stem}.promotion.json"
    report_path.write_text(json.dumps(report, indent=2))
    report["report"] = str(report_path)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
