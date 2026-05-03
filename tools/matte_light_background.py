from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def natural_sort_key(path: Path) -> list[tuple[int, object]]:
    parts = re.split(r"(\d+)", path.name)
    return [(1, int(part)) if part.isdigit() else (0, part.lower()) for part in parts]


def frame_paths(frame_dir: Path) -> list[Path]:
    paths = [
        path for path in frame_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(paths, key=natural_sort_key)


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def estimate_background(img: Image.Image, sample: int) -> tuple[int, int, int]:
    rgb = img.convert("RGB")
    width, height = rgb.size
    px = rgb.load()
    samples: list[tuple[int, int, int]] = []
    for y in range(min(sample, height)):
        for x in range(min(sample, width)):
            samples.append(px[x, y])
        for x in range(max(0, width - sample), width):
            samples.append(px[x, y])
    for y in range(max(0, height - sample), height):
        for x in range(min(sample, width)):
            samples.append(px[x, y])
        for x in range(max(0, width - sample), width):
            samples.append(px[x, y])
    if not samples:
        return (255, 255, 255)
    channels = list(zip(*samples))
    return tuple(sorted(channel)[len(channel) // 2] for channel in channels)  # type: ignore[return-value]


def matte_frame(
    img: Image.Image,
    bg: tuple[int, int, int],
    luma_threshold: int,
    distance_threshold: int,
    softness: int,
) -> Image.Image:
    rgba = img.convert("RGBA")
    px = rgba.load()
    width, height = rgba.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            rgb = (r, g, b)
            distance = color_distance(rgb, bg)
            is_light_background = luminance(rgb) >= luma_threshold and distance <= distance_threshold + softness
            is_near_background = distance <= distance_threshold + softness
            if not (is_light_background or is_near_background):
                continue
            if distance <= distance_threshold or luminance(rgb) >= 250:
                alpha = 0
            else:
                alpha = round(255 * min(1.0, (distance - distance_threshold) / max(1, softness)))
            px[x, y] = (r, g, b, min(a, alpha))
    return rgba


def run(args: argparse.Namespace) -> dict[str, object]:
    source_dir = Path(args.source_frames_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = frame_paths(source_dir)
    if not paths:
        raise SystemExit(f"No image frames found in {source_dir}")

    records: list[dict[str, object]] = []
    for index, path in enumerate(paths, start=1):
        img = Image.open(path)
        bg = estimate_background(img, args.corner_sample)
        matted = matte_frame(img, bg, args.luma_threshold, args.distance_threshold, args.softness)
        output_path = output_dir / f"{args.frame_prefix}_{index:04d}.png"
        matted.save(output_path)
        records.append(
            {
                "index": index,
                "source": str(path),
                "output": str(output_path),
                "estimated_background": list(bg),
            }
        )

    report = {
        "source_frames_dir": str(source_dir),
        "output_dir": str(output_dir),
        "frame_count": len(records),
        "luma_threshold": args.luma_threshold,
        "distance_threshold": args.distance_threshold,
        "softness": args.softness,
        "corner_sample": args.corner_sample,
        "frames": records,
    }
    (output_dir / "matte_report.json").write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Create alpha PNGs from frames on a light background.")
    parser.add_argument("--source-frames-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--frame-prefix", default="frame")
    parser.add_argument("--luma-threshold", type=int, default=210)
    parser.add_argument("--distance-threshold", type=int, default=42)
    parser.add_argument("--softness", type=int, default=35)
    parser.add_argument("--corner-sample", type=int, default=48)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
