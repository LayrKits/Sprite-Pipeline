from __future__ import annotations

import argparse
import json
import re
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw


"""
Canonical cleaner/repacker for 2D animation sources.

The preferred input is now a directory of frame images extracted from a source
animation video. Treat extracted frames as pose sources that must be normalized
here before promotion into a game.

Supported source layouts:
- frame directory: numbered PNG/JPEG/WebP frames extracted from video and sorted
  by filename.
- components: separated foreground poses on flat #00ff00, sorted by x or
  row-major if an old generated source returned multiple rows.
- grid: fixed row/column guide layouts, useful when dust, wind, or magic effects
  are disconnected from the character and would confuse component extraction.
  This mode can use all cells or only the first N cells from a larger source
  sheet, which is useful for external sprite sheets such as 8x8 atlases.
- equal: last-resort slicing for truly guaranteed horizontal cells.

The pipeline removes chroma and magenta guide pixels, despills green edges while
preserving turquoise staff caps, removes tiny noise, then writes either a
preserved source-canvas 256px cell or a foreground-fitted 256px cell. Preserved
canvas layout is the normal video workflow: it scales the full extracted video
frame into the output cell so idle, attack, and effect-heavy animations keep the
same camera scale. It writes preview artifacts and reports validation warnings
for duplicates, motion pops, scale drift, and clipping.

See docs/ANIMATION_PIPELINE_NOTES.md for the full canonical workflow.
"""


FRAME_SIZE = 256
TARGET_CENTER_X = 128
TARGET_GROUND_Y = 220
SIDE_MARGIN = 2
TOP_MARGIN = 2
BOTTOM_MARGIN = 2
MIN_COMPONENT_AREA = 32
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def natural_sort_key(path: Path) -> list[tuple[int, object]]:
    parts = re.split(r"(\d+)", path.name)
    return [
        (1, int(part)) if part.isdigit() else (0, part.lower())
        for part in parts
    ]


def source_frame_paths(frame_dir: Path) -> list[Path]:
    if not frame_dir.exists():
        raise ValueError(f"Source frame directory does not exist: {frame_dir}")
    if not frame_dir.is_dir():
        raise ValueError(f"--source-frames-dir must point to a directory: {frame_dir}")
    paths = [
        path for path in frame_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    if not paths:
        raise ValueError(f"No frame images found in {frame_dir}")
    return sorted(paths, key=natural_sort_key)


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def parse_hex_color(value: str) -> tuple[int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"Expected 6-digit hex color, got {value!r}")
    return int(raw[:2], 16), int(raw[2:4], 16), int(raw[4:], 16)


def is_chroma(rgb: tuple[int, int, int], key: tuple[int, int, int], tolerance: int) -> bool:
    r, g, b = rgb
    if color_distance(rgb, key) <= tolerance:
        return True
    key_is_green = key[1] > 200 and key[0] < 80 and key[2] < 80
    if key_is_green:
        return g >= 170 and r <= 120 and b <= 130 and g >= r + 70 and g >= b + 55
    return False


def is_layout_guide(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return r >= 190 and b >= 190 and g <= 90


def remove_chroma_background(img: Image.Image, key: tuple[int, int, int], tolerance: int) -> Image.Image:
    rgba = img.convert("RGBA")
    px = rgba.load()
    width, height = rgba.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if is_chroma((r, g, b), key, tolerance) or is_layout_guide((r, g, b)):
                px[x, y] = (0, 0, 0, 0)
                continue
            # Soft despill for chroma-edge pixels without eating cyan staff tips.
            if key[1] > 200 and g > r + 35 and g > b + 18 and r < 150 and b < 180:
                px[x, y] = (r, min(g, max(r, b) + 24), b, a)
    return rgba


def clean_source_image(
    img: Image.Image,
    background_mode: str,
    key: tuple[int, int, int],
    tolerance: int,
) -> Image.Image:
    if background_mode == "alpha":
        return img.convert("RGBA")
    return remove_chroma_background(img, key, tolerance)


def component_bboxes(img: Image.Image) -> list[dict[str, object]]:
    rgba = img.convert("RGBA")
    width, height = rgba.size
    alpha = rgba.getchannel("A")
    a_px = alpha.load()
    visited = bytearray(width * height)
    components: list[dict[str, object]] = []

    def index(x: int, y: int) -> int:
        return y * width + x

    for y in range(height):
        for x in range(width):
            idx = index(x, y)
            if visited[idx] or a_px[x, y] == 0:
                continue
            visited[idx] = 1
            queue: deque[tuple[int, int]] = deque([(x, y)])
            pixels: list[tuple[int, int]] = [(x, y)]
            min_x = max_x = x
            min_y = max_y = y
            while queue:
                cx, cy = queue.popleft()
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    nidx = index(nx, ny)
                    if visited[nidx] or a_px[nx, ny] == 0:
                        continue
                    visited[nidx] = 1
                    queue.append((nx, ny))
                    pixels.append((nx, ny))
            components.append(
                {
                    "area": len(pixels),
                    "bbox": (min_x, min_y, max_x + 1, max_y + 1),
                    "pixels": pixels,
                }
            )
    return components


def remove_noise(img: Image.Image, min_area: int = MIN_COMPONENT_AREA) -> Image.Image:
    rgba = img.convert("RGBA")
    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    out_px = out.load()
    in_px = rgba.load()
    for comp in component_bboxes(rgba):
        if int(comp["area"]) < min_area:
            continue
        for x, y in comp["pixels"]:  # type: ignore[index]
            out_px[x, y] = in_px[x, y]
    return out


def union_box(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def foreground_bbox(img: Image.Image) -> tuple[int, int, int, int]:
    components = [
        comp for comp in component_bboxes(img)
        if int(comp["area"]) >= MIN_COMPONENT_AREA
    ]
    if not components:
        bbox = img.getbbox()
        if not bbox:
            raise ValueError("Frame has no foreground after cleanup")
        return bbox
    largest_area = max(int(comp["area"]) for comp in components)
    kept = [
        comp["bbox"] for comp in components
        if int(comp["area"]) >= max(MIN_COMPONENT_AREA, int(largest_area * 0.018))
    ]
    return union_box(kept)  # type: ignore[arg-type]


def lower_body_anchor_x(img: Image.Image, bbox: tuple[int, int, int, int]) -> float:
    x0, y0, x1, y1 = bbox
    alpha = img.getchannel("A")
    px = alpha.load()
    width, _ = alpha.size
    counts = [0] * width
    total = 0
    start_y = round(y0 + (y1 - y0) * 0.45)
    for y in range(start_y, y1):
        for x in range(x0, x1):
            if px[x, y] > 20:
                counts[x] += 1
                total += 1
    if total == 0:
        return (x0 + x1) / 2
    target = total // 2
    running = 0
    for x, count in enumerate(counts):
        running += count
        if running > target:
            return x + 0.5
    return (x0 + x1) / 2


def split_equal_cells(img: Image.Image, frame_count: int) -> list[Image.Image]:
    width, height = img.size
    return [
        img.crop((round(i * width / frame_count), 0, round((i + 1) * width / frame_count), height))
        for i in range(frame_count)
    ]


def split_grid_cells(
    img: Image.Image,
    cols: int,
    rows: int,
    inset: int = 0,
    take_first: int | None = None,
) -> tuple[list[Image.Image], list[dict[str, object]]]:
    width, height = img.size
    cells: list[Image.Image] = []
    metadata: list[dict[str, object]] = []
    max_cells = cols * rows if take_first is None else min(take_first, cols * rows)
    for row in range(rows):
        for col in range(cols):
            if len(cells) >= max_cells:
                return cells, metadata
            box = (
                round(col * width / cols) + inset,
                round(row * height / rows) + inset,
                round((col + 1) * width / cols) - inset,
                round((row + 1) * height / rows) - inset,
            )
            cells.append(img.crop(box))
            metadata.append({"index": len(cells), "row": row + 1, "col": col + 1, "source_box": list(box)})
    return cells, metadata


def component_center(comp: dict[str, object]) -> tuple[float, float]:
    x0, y0, x1, y1 = comp["bbox"]  # type: ignore[assignment]
    return (x0 + x1) / 2, (y0 + y1) / 2


def sort_components_row_major(components: list[dict[str, object]]) -> list[dict[str, object]]:
    if not components:
        return []
    heights = [comp["bbox"][3] - comp["bbox"][1] for comp in components]  # type: ignore[index]
    row_threshold = max(24.0, sorted(heights)[len(heights) // 2] * 0.72)
    rows: list[list[dict[str, object]]] = []
    for comp in sorted(components, key=lambda item: component_center(item)[1]):
        _, cy = component_center(comp)
        for row in rows:
            row_cy = sum(component_center(item)[1] for item in row) / len(row)
            if abs(cy - row_cy) <= row_threshold:
                row.append(comp)
                break
        else:
            rows.append([comp])
    ordered: list[dict[str, object]] = []
    for row in sorted(rows, key=lambda items: sum(component_center(item)[1] for item in items) / len(items)):
        ordered.extend(sorted(row, key=lambda item: component_center(item)[0]))
    return ordered


def split_component_cells(
    img: Image.Image,
    frame_count: int,
    pad: int = 8,
    min_area: int = MIN_COMPONENT_AREA * 8,
    sort_order: str = "x",
) -> list[Image.Image]:
    components = [
        comp for comp in component_bboxes(img)
        if int(comp["area"]) >= min_area
    ]
    if len(components) != frame_count:
        raise ValueError(f"Expected {frame_count} foreground components, found {len(components)}")

    width, height = img.size
    in_px = img.load()
    cells: list[Image.Image] = []
    if sort_order == "row-major":
        ordered_components = sort_components_row_major(components)
    else:
        ordered_components = sorted(components, key=lambda item: component_center(item)[0])

    for comp in ordered_components:
        x0, y0, x1, y1 = comp["bbox"]  # type: ignore[assignment]
        cell_x0 = max(0, x0 - pad)
        cell_y0 = max(0, y0 - pad)
        cell_x1 = min(width, x1 + pad)
        cell_y1 = min(height, y1 + pad)
        cell = Image.new("RGBA", (cell_x1 - cell_x0, cell_y1 - cell_y0), (0, 0, 0, 0))
        cell_px = cell.load()
        for x, y in comp["pixels"]:  # type: ignore[index]
            cell_px[x - cell_x0, y - cell_y0] = in_px[x, y]
        cells.append(cell)
    return cells


def alpha_edge_counts(img: Image.Image) -> dict[str, int]:
    alpha = img.getchannel("A")
    width, height = alpha.size
    px = alpha.load()
    return {
        "left": sum(1 for y in range(height) if px[0, y] > 0),
        "right": sum(1 for y in range(height) if px[width - 1, y] > 0),
        "top": sum(1 for x in range(width) if px[x, 0] > 0),
        "bottom": sum(1 for x in range(width) if px[x, height - 1] > 0),
    }


def silhouette_difference(a: Image.Image, b: Image.Image) -> float:
    aa = a.getchannel("A").point(lambda value: 255 if value > 20 else 0)
    bb = b.getchannel("A").point(lambda value: 255 if value > 20 else 0)
    width, height = aa.size
    apx = aa.load()
    bpx = bb.load()
    changed = 0
    total = 0
    for y in range(height):
        for x in range(width):
            av = apx[x, y] > 0
            bv = bpx[x, y] > 0
            total += int(av or bv)
            changed += int(av != bv)
    return changed / max(1, total)


def layout_frames(cells: list[Image.Image], anchor_mode: str = "bbox") -> tuple[list[Image.Image], list[dict[str, object]], float]:
    crops: list[dict[str, object]] = []
    for cell in cells:
        cleaned = remove_noise(cell)
        bbox = foreground_bbox(cleaned)
        crop = cleaned.crop(bbox)
        if anchor_mode == "lower-body":
            anchor_x = lower_body_anchor_x(cleaned, bbox)
        else:
            anchor_x = (bbox[0] + bbox[2]) / 2
        anchor_y = bbox[3]
        crops.append({"image": cleaned, "bbox": bbox, "crop": crop, "anchor_x": anchor_x, "anchor_y": anchor_y})

    max_scale = 99.0
    for record in crops:
        bbox = record["bbox"]  # type: ignore[assignment]
        anchor_x = float(record["anchor_x"])
        anchor_y = float(record["anchor_y"])
        left = anchor_x - bbox[0]
        right = bbox[2] - anchor_x
        top = anchor_y - bbox[1]
        bottom = bbox[3] - anchor_y
        max_scale = min(
            max_scale,
            (TARGET_CENTER_X - SIDE_MARGIN) / max(1.0, left),
            (FRAME_SIZE - TARGET_CENTER_X - SIDE_MARGIN) / max(1.0, right),
            (TARGET_GROUND_Y - TOP_MARGIN) / max(1.0, top),
            (FRAME_SIZE - TARGET_GROUND_Y - BOTTOM_MARGIN) / max(1.0, bottom),
        )
    scale = min(1.0, max(0.05, max_scale * 0.98))

    frames: list[Image.Image] = []
    records: list[dict[str, object]] = []
    for index, record in enumerate(crops):
        crop = record["crop"]  # type: ignore[assignment]
        bbox = record["bbox"]  # type: ignore[assignment]
        anchor_x = float(record["anchor_x"])
        anchor_y = float(record["anchor_y"])
        scaled = crop.resize(
            (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
            Image.Resampling.LANCZOS,
        )
        anchor_in_crop_x = (anchor_x - bbox[0]) * scale
        anchor_in_crop_y = (anchor_y - bbox[1]) * scale
        paste_x = round(TARGET_CENTER_X - anchor_in_crop_x)
        paste_y = round(TARGET_GROUND_Y - anchor_in_crop_y)
        canvas = Image.new("RGBA", (FRAME_SIZE, FRAME_SIZE), (0, 0, 0, 0))
        canvas.alpha_composite(scaled, (paste_x, paste_y))
        canvas = remove_noise(canvas)
        final_bbox = canvas.getbbox()
        if not final_bbox:
            raise ValueError(f"Frame {index + 1} is empty after layout")
        frames.append(canvas)
        records.append(
            {
                "index": index + 1,
                "source_bbox": list(bbox),
                "final_bbox": list(final_bbox),
                "anchor_x": round(anchor_x, 3),
                "anchor_y": round(anchor_y, 3),
                "source_edge_alpha": alpha_edge_counts(record["image"]),  # type: ignore[arg-type]
            }
        )
    return frames, records, scale


def layout_canvas_frames(cells: list[Image.Image]) -> tuple[list[Image.Image], list[dict[str, object]], float]:
    if not cells:
        raise ValueError("No frames provided")

    canvas_width = max(cell.width for cell in cells)
    canvas_height = max(cell.height for cell in cells)
    scale = min(FRAME_SIZE / max(1, canvas_width), FRAME_SIZE / max(1, canvas_height))
    scaled_width = max(1, round(canvas_width * scale))
    scaled_height = max(1, round(canvas_height * scale))
    paste_x = 0
    paste_y = 0

    frames: list[Image.Image] = []
    records: list[dict[str, object]] = []
    for index, cell in enumerate(cells):
        cleaned = remove_noise(cell)
        source_bbox = cleaned.getbbox()
        scaled = cleaned.resize(
            (max(1, round(cleaned.width * scale)), max(1, round(cleaned.height * scale))),
            Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGBA", (FRAME_SIZE, FRAME_SIZE), (0, 0, 0, 0))
        canvas.alpha_composite(scaled, (paste_x, paste_y))
        final_bbox = canvas.getbbox()
        frames.append(canvas)
        records.append(
            {
                "index": index + 1,
                "source_bbox": list(source_bbox) if source_bbox else None,
                "final_bbox": list(final_bbox) if final_bbox else None,
                "source_canvas": [cell.width, cell.height],
                "scaled_canvas": [scaled_width, scaled_height],
                "paste": [paste_x, paste_y],
                "anchor_x": None,
                "anchor_y": None,
                "source_edge_alpha": alpha_edge_counts(cleaned),
            }
        )
    return frames, records, scale


def save_sheet(frames: list[Image.Image], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGBA", (FRAME_SIZE * len(frames), FRAME_SIZE), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        sheet.alpha_composite(frame, (index * FRAME_SIZE, 0))
    sheet.save(output)


def save_preview(frames: list[Image.Image], output: Path, show_alignment_guides: bool = False) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGBA", (FRAME_SIZE * len(frames), FRAME_SIZE), (42, 45, 50, 255))
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames):
        x0 = index * FRAME_SIZE
        for y in range(0, FRAME_SIZE, 32):
            for x in range(x0, x0 + FRAME_SIZE, 32):
                fill = (50, 54, 60, 255) if ((x // 32 + y // 32) % 2) else (36, 39, 44, 255)
                draw.rectangle((x, y, min(x + 31, x0 + FRAME_SIZE - 1), min(y + 31, FRAME_SIZE - 1)), fill=fill)
        if show_alignment_guides:
            draw.line((x0, TARGET_GROUND_Y, x0 + FRAME_SIZE - 1, TARGET_GROUND_Y), fill=(120, 180, 140, 150))
            draw.line((x0 + TARGET_CENTER_X, 0, x0 + TARGET_CENTER_X, FRAME_SIZE - 1), fill=(120, 160, 220, 90))
        sheet.alpha_composite(frame, (x0, 0))
        draw.rectangle((x0, 0, x0 + FRAME_SIZE - 1, FRAME_SIZE - 1), outline=(255, 255, 255, 100))
    sheet.save(output)


def validate(
    frames: list[Image.Image],
    records: list[dict[str, object]],
    scale: float,
    allow_empty: bool = False,
    edge_touch_is_warning: bool = False,
) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    bboxes = []
    alpha_ratios = []
    for index, frame in enumerate(frames):
        bbox = frame.getbbox()
        if not bbox:
            if allow_empty:
                warnings.append(f"Frame {index + 1} is empty")
                alpha_ratios.append(1.0)
            else:
                errors.append(f"Frame {index + 1} is empty")
            continue
        bboxes.append(bbox)
        if bbox[0] <= 0 or bbox[1] <= 0 or bbox[2] >= FRAME_SIZE or bbox[3] >= FRAME_SIZE:
            message = f"Frame {index + 1} touches the 256px cell edge: bbox={bbox}"
            if edge_touch_is_warning:
                warnings.append(message)
            else:
                errors.append(message)
        zero_ratio = frame.getchannel("A").histogram()[0] / (FRAME_SIZE * FRAME_SIZE)
        alpha_ratios.append(zero_ratio)
        if zero_ratio < 0.35:
            warnings.append(f"Frame {index + 1} is visually crowded in cell: transparent ratio={zero_ratio:.3f}")
        edge_counts = records[index]["source_edge_alpha"]  # type: ignore[index]
        for side, count in edge_counts.items():  # type: ignore[union-attr]
            if int(count) > 2:
                warnings.append(f"Source frame {index + 1} has foreground on {side} edge before repack ({count}px)")

    diffs = [
        silhouette_difference(frames[i], frames[(i + 1) % len(frames)])
        for i in range(len(frames))
    ]
    if diffs:
        for index, diff in enumerate(diffs):
            if diff < 0.12:
                warnings.append(f"Frames {index + 1}->{(index + 1) % len(frames) + 1} may be too similar: diff={diff:.3f}")
            if diff > 0.58:
                warnings.append(f"Frames {index + 1}->{(index + 1) % len(frames) + 1} may pop: diff={diff:.3f}")
    if bboxes:
        heights = [box[3] - box[1] for box in bboxes]
        widths = [box[2] - box[0] for box in bboxes]
        if max(heights) / max(1, min(heights)) > 1.35:
            warnings.append("Frame height variance is high; review pose consistency.")
        if max(widths) / max(1, min(widths)) > 1.55:
            warnings.append("Frame width variance is high; long staff or stride may cause scale/readability issues.")
    return {
        "status": "fail" if errors else "pass",
        "errors": errors,
        "warnings": warnings,
        "scale": round(scale, 6),
        "adjacent_silhouette_diffs": [round(value, 4) for value in diffs],
        "alpha_zero_ratio_avg": round(sum(alpha_ratios) / max(1, len(alpha_ratios)), 4),
        "frames": records,
    }


def run(args: argparse.Namespace) -> dict[str, object]:
    if bool(args.source) == bool(args.source_frames_dir):
        raise ValueError("Provide exactly one source: --source or --source-frames-dir")

    key = parse_hex_color(args.key)

    if args.source_frames_dir:
        source = Path(args.source_frames_dir)
        paths = source_frame_paths(source)
        if args.frames is not None and len(paths) != args.frames:
            raise ValueError(f"Expected {args.frames} source frames, found {len(paths)} in {source}")
        cells = [
            clean_source_image(Image.open(path), args.background_mode, key, args.tolerance)
            for path in paths
        ]
        frame_count = len(cells)
        source_type = "frame-directory"
        source_cells: list[dict[str, object]] = [
            {"index": index, "path": str(path)}
            for index, path in enumerate(paths, start=1)
        ]
    else:
        if args.frames is None:
            raise ValueError("--frames is required when using --source")
        frame_count = args.frames
        source = Path(args.source)
        img = Image.open(source).convert("RGBA")
        cleaned = clean_source_image(img, args.background_mode, key, args.tolerance)
        if args.split_mode == "components":
            cells = split_component_cells(
                cleaned,
                frame_count,
                min_area=args.component_min_area,
                sort_order=args.component_sort,
            )
            source_cells = []
        elif args.split_mode == "grid":
            if args.take_first is None and args.grid_cols * args.grid_rows != frame_count:
                raise ValueError("--grid-cols * --grid-rows must equal --frames unless --take-first is set")
            take_first = args.take_first if args.take_first is not None else frame_count
            if take_first != frame_count:
                raise ValueError("--take-first must match --frames so output metadata and validation stay explicit")
            cells, source_cells = split_grid_cells(
                cleaned,
                args.grid_cols,
                args.grid_rows,
                args.grid_inset,
                take_first=take_first,
            )
            if len(cells) != frame_count:
                raise ValueError(f"Expected {frame_count} grid cells, got {len(cells)}")
        else:
            cells = split_equal_cells(cleaned, frame_count)
            source_cells = []
        source_type = "sheet"

    if args.layout_mode == "preserve-canvas":
        frames, records, scale = layout_canvas_frames(cells)
    else:
        frames, records, scale = layout_frames(cells, anchor_mode=args.anchor_mode)
    output = Path(args.output)
    preview = Path(args.preview)
    frames_dir = Path(args.frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames, start=1):
        frame.save(frames_dir / f"{args.frame_prefix}_{index:02d}.png")
    save_sheet(frames, output)
    save_preview(frames, preview, show_alignment_guides=args.layout_mode == "fit-foreground")
    report = validate(
        frames,
        records,
        scale,
        allow_empty=args.layout_mode == "preserve-canvas",
        edge_touch_is_warning=args.layout_mode == "preserve-canvas",
    )
    report.update(
        {
            "source": str(source),
            "output": str(output),
            "preview": str(preview),
            "frames_dir": str(frames_dir),
            "frame_count": frame_count,
            "frame_size": FRAME_SIZE,
            "sheet_size": [FRAME_SIZE * frame_count, FRAME_SIZE],
            "split_mode": "frames" if source_type == "frame-directory" else args.split_mode,
            "source_type": source_type,
            "background_mode": args.background_mode,
            "anchor_mode": args.anchor_mode,
            "layout_mode": args.layout_mode,
            "source_cells": source_cells,
        }
    )
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean, repack, and validate 2D animation frame sources.")
    parser.add_argument("--source", help="Legacy sheet/atlas source image.")
    parser.add_argument("--source-frames-dir", help="Directory of extracted frame images, sorted naturally by filename.")
    parser.add_argument("--frames", type=int, default=None, help="Expected frame count. Required for --source; optional check for --source-frames-dir.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--preview", required=True)
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--background-mode", choices=("chroma", "alpha"), default="chroma")
    parser.add_argument("--anchor-mode", choices=("bbox", "lower-body"), default="bbox")
    parser.add_argument(
        "--layout-mode",
        choices=("preserve-canvas", "fit-foreground"),
        default="preserve-canvas",
        help="preserve-canvas keeps the full source video frame scale; fit-foreground recenters and grounds the visible sprite.",
    )
    parser.add_argument("--key", default="#00ff00")
    parser.add_argument("--tolerance", type=int, default=70)
    parser.add_argument("--split-mode", choices=("components", "equal", "grid"), default="components")
    parser.add_argument("--grid-cols", type=int, default=1)
    parser.add_argument("--grid-rows", type=int, default=1)
    parser.add_argument("--grid-inset", type=int, default=0)
    parser.add_argument("--take-first", type=int, default=None)
    parser.add_argument("--component-sort", choices=("x", "row-major"), default="x")
    parser.add_argument("--component-min-area", type=int, default=MIN_COMPONENT_AREA * 8)
    parser.add_argument("--frame-prefix", default="run")
    args = parser.parse_args()
    if bool(args.source) == bool(args.source_frames_dir):
        parser.error("provide exactly one source: --source or --source-frames-dir")
    if args.source and args.frames is None:
        parser.error("--frames is required when using --source")
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
