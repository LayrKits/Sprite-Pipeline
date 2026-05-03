from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(description="Resize a horizontal sprite sheet to a smaller per-frame cell size.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-frame-size", type=int, default=256)
    parser.add_argument("--target-frame-size", type=int, required=True)
    parser.add_argument("--resample", choices=("lanczos", "nearest"), default="lanczos")
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    img = Image.open(source).convert("RGBA")
    if img.height != args.source_frame_size:
        raise SystemExit(f"Expected source height {args.source_frame_size}, got {img.height}")
    if img.width % args.source_frame_size != 0:
        raise SystemExit(f"Source width {img.width} is not divisible by {args.source_frame_size}")

    frame_count = img.width // args.source_frame_size
    target_size = (frame_count * args.target_frame_size, args.target_frame_size)
    resample = Image.Resampling.NEAREST if args.resample == "nearest" else Image.Resampling.LANCZOS
    resized = img.resize(target_size, resample)
    output.parent.mkdir(parents=True, exist_ok=True)
    resized.save(output)

    report = {
        "source": str(source),
        "output": str(output),
        "frame_count": frame_count,
        "source_frame_size": args.source_frame_size,
        "target_frame_size": args.target_frame_size,
        "source_size": list(img.size),
        "output_size": list(target_size),
        "resample": args.resample,
    }
    report_path = output.with_suffix(".resize_report.json")
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
