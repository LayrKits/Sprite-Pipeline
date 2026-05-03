from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


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


def parse_indices(value: str) -> list[int]:
    indices: list[int] = []
    for part in value.split(","):
        raw = part.strip()
        if not raw:
            continue
        if "-" in raw:
            start_raw, end_raw = raw.split("-", 1)
            start = int(start_raw)
            end = int(end_raw)
            if end < start:
                raise ValueError(f"Frame range must ascend: {raw}")
            indices.extend(range(start, end + 1))
        else:
            indices.append(int(raw))
    if not indices:
        raise ValueError("No frame indices were provided")
    return indices


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy selected source frames into a new ordered frame folder.")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--indices", required=True, help="1-based frame indices, for example 1,4,8,12-16.")
    parser.add_argument("--frame-prefix", default="frame")
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = source_paths(source_dir)
    if not paths:
        raise SystemExit(f"No image frames found in {source_dir}")

    selected = parse_indices(args.indices)
    records: list[dict[str, object]] = []
    for output_index, source_index in enumerate(selected, start=1):
        if source_index < 1 or source_index > len(paths):
            raise SystemExit(f"Frame index {source_index} is outside 1..{len(paths)}")
        source = paths[source_index - 1]
        output = output_dir / f"{args.frame_prefix}_{output_index:04d}.png"
        shutil.copy2(source, output)
        records.append({"output_index": output_index, "source_index": source_index, "source": str(source), "output": str(output)})

    report = {
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "source_frame_count": len(paths),
        "selected_frame_count": len(records),
        "selected_indices": selected,
        "frames": records,
    }
    (output_dir / "selection_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
