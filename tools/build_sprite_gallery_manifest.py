from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_LATEST_LIMIT = 10


def natural_sort_key(path: Path) -> list[tuple[int, object]]:
    parts = re.split(r"(\d+)", str(path))
    return [(1, int(part)) if part.isdigit() else (0, part.lower()) for part in parts]


def image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:
        return None, None


def final_sprite_parts(path: Path, folder: Path) -> tuple[str, str, str]:
    if folder.name != "Final Sprite Sheets":
        return "", "", ""
    parts = path.relative_to(folder).parts
    if len(parts) < 5 or parts[3] != "sheets":
        return "", "", ""
    return parts[0], parts[1], parts[2]


def collect(root: Path, folders: list[Path]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for folder in folders:
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*"), key=natural_sort_key):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if folder.name == "Final Sprite Sheets" and "frames" in path.relative_to(folder).parts:
                continue
            stat = path.stat()
            width, height = image_size(path)
            rel = path.relative_to(root).as_posix()
            game, character, animation = final_sprite_parts(path, folder)
            entries.append(
                {
                    "label": path.stem,
                    "path": rel,
                    "folder": path.parent.relative_to(root).as_posix(),
                    "game": game,
                    "character": character,
                    "animation": animation,
                    "width": width,
                    "height": height,
                    "bytes": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static sprite viewer gallery manifest.")
    parser.add_argument("--output", default="sprite_gallery_manifest.js")
    parser.add_argument("--folder", action="append", default=None)
    parser.add_argument("--limit", type=int, default=0, help="Optional hard cap for manifest entries. 0 writes all sheets.")
    parser.add_argument("--latest-limit", type=int, default=DEFAULT_LATEST_LIMIT)
    args = parser.parse_args()

    root = Path.cwd()
    folders = [root / folder for folder in (args.folder or ["Final Sprite Sheets"])]
    entries = collect(root, folders)
    entries.sort(key=lambda entry: (float(entry.get("modified") or 0), str(entry.get("path") or "")), reverse=True)
    if args.limit > 0:
        entries = entries[:args.limit]
    output = root / args.output
    payload = json.dumps(entries, indent=2)
    latest_limit = max(1, args.latest_limit)
    output.write_text(
        f"window.SPRITE_LATEST_LIMIT = {latest_limit};\n"
        f"window.SPRITE_SHEETS = {payload};\n"
    )
    print(f"Wrote {len(entries)} sheet entries to {output}; latest picker limit is {latest_limit}")


if __name__ == "__main__":
    main()
