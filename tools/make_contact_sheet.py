from __future__ import annotations

import argparse
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
            path for path in source_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ],
        key=natural_sort_key,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a numbered contact sheet from image frames.")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cols", type=int, default=10)
    parser.add_argument("--cell-size", type=int, default=112)
    parser.add_argument("--image-size", type=int, default=96)
    args = parser.parse_args()

    paths = source_paths(Path(args.source_dir))
    if not paths:
        raise SystemExit(f"No image frames found in {args.source_dir}")

    rows = math.ceil(len(paths) / args.cols)
    output = Image.new("RGBA", (args.cols * args.cell_size, rows * args.cell_size), (28, 28, 28, 255))
    draw = ImageDraw.Draw(output)
    inset = max(0, (args.cell_size - args.image_size) // 2)

    for index, path in enumerate(paths, start=1):
        frame = Image.open(path).convert("RGBA")
        frame.thumbnail((args.image_size, args.image_size), Image.Resampling.LANCZOS)
        cell_x = ((index - 1) % args.cols) * args.cell_size
        cell_y = ((index - 1) // args.cols) * args.cell_size
        x = cell_x + inset + (args.image_size - frame.width) // 2
        y = cell_y + inset + (args.image_size - frame.height) // 2
        output.alpha_composite(frame, (x, y))
        label = str(index)
        draw.rectangle((cell_x + 4, cell_y + 4, cell_x + 34, cell_y + 22), fill=(0, 0, 0, 175))
        draw.text((cell_x + 8, cell_y + 6), label, fill=(255, 255, 255, 255))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.save(output_path)


if __name__ == "__main__":
    main()
