from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from vertical_align_sheet import alpha_bbox, save_sheet, shift_frame_vertical, split_sheet


def run(args: argparse.Namespace) -> dict[str, object]:
    input_path = Path(args.input)
    offsets_payload = json.loads(Path(args.offsets_json).read_text())
    offsets = offsets_payload.get("offsets", offsets_payload)
    if not isinstance(offsets, list):
        raise ValueError("Offsets JSON must contain a list or an offsets list.")

    sheet = Image.open(input_path).convert("RGBA")
    frames = split_sheet(sheet, args.cell_width, args.cell_height)
    if len(offsets) != len(frames):
        raise ValueError(f"Expected {len(frames)} offsets, got {len(offsets)}.")

    int_offsets = [int(value) for value in offsets]
    adjusted_frames = [
        shift_frame_vertical(frame, offset)
        for frame, offset in zip(frames, int_offsets)
    ]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_sheet(adjusted_frames, output_path)

    changed_frames = [
        {"frame": index, "dy_px": offset}
        for index, offset in enumerate(int_offsets, start=1)
        if offset
    ]
    report = {
        "source_sheet": str(input_path),
        "output_sheet": str(output_path),
        "frame_count": len(frames),
        "cell_size": [args.cell_width, args.cell_height],
        "manual_offsets_y": int_offsets,
        "changed_frames": changed_frames,
        "output_bboxes": [list(alpha_bbox(frame, threshold=0) or []) for frame in adjusted_frames],
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply manual per-frame vertical offsets to an alignment candidate sheet.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--offsets-json", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=256)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
