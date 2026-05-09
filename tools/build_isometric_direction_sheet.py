from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

import animation_pipeline
import extract_frames_ffmpeg


"""
Build a multi-row isometric direction sprite sheet from a video that contains
multiple separated direction poses in every frame.

This is intentionally separate from animation_pipeline.py. The existing cleaner
expects one animation per source frame folder; this script first splits each
source video frame into direction-specific frame folders, then invokes the
normal cleaner once per direction and stacks the cleaned rows.
"""


DEFAULT_SOURCE_DIRECTIONS = "north,north_east,east,south_east,south"
DEFAULT_MIRROR_MAP = "north_west:north_east,west:east,south_west:south_east"
DEFAULT_EIGHT_WAY_ORDER = [
    "north",
    "north_east",
    "east",
    "south_east",
    "south",
    "south_west",
    "west",
    "north_west",
]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
FRAME_SIZE = animation_pipeline.FRAME_SIZE


def parse_directions(value: str) -> list[str]:
    directions = [item.strip() for item in value.split(",") if item.strip()]
    if not directions:
        raise ValueError("--directions must contain at least one direction label")
    if len(set(directions)) != len(directions):
        raise ValueError("--directions contains duplicate labels")
    return directions


def parse_mirror_map(value: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    if not value.strip():
        return pairs
    for raw_pair in value.split(","):
        pair = raw_pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise ValueError(f"Mirror pair must use target:source format, got {pair!r}")
        target, source = [item.strip() for item in pair.split(":", 1)]
        if not target or not source:
            raise ValueError(f"Mirror pair must use target:source format, got {pair!r}")
        if target in pairs:
            raise ValueError(f"Duplicate mirror target {target!r}")
        pairs[target] = source
    return pairs


def natural_frame_paths(frame_dir: Path) -> list[Path]:
    paths = [
        path
        for path in frame_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(paths, key=animation_pipeline.natural_sort_key)


def sample_evenly(paths: list[Path], frame_count: int) -> list[tuple[int, Path]]:
    if frame_count <= 0:
        raise ValueError("--frames must be greater than 0")
    if len(paths) < frame_count:
        raise ValueError(f"Need {frame_count} extracted frames, found {len(paths)}")
    if frame_count == 1:
        return [(0, paths[0])]
    indexes = [round(index * (len(paths) - 1) / (frame_count - 1)) for index in range(frame_count)]
    return [(index, paths[index]) for index in indexes]


def clean_for_split(
    image: Image.Image,
    background_mode: str,
    key: tuple[int, int, int],
    tolerance: int,
) -> Image.Image:
    return animation_pipeline.clean_source_image(image, background_mode, key, tolerance)


def component_center(component: dict[str, Any]) -> tuple[float, float]:
    x0, y0, x1, y1 = component["bbox"]
    return (x0 + x1) / 2, (y0 + y1) / 2


def largest_components(
    image: Image.Image,
    expected_count: int,
    min_area: int,
) -> list[dict[str, Any]]:
    components = [
        component
        for component in animation_pipeline.component_bboxes(image)
        if int(component["area"]) >= min_area
    ]
    if len(components) < expected_count:
        raise ValueError(f"Expected at least {expected_count} direction components, found {len(components)}")
    return sorted(components, key=lambda item: int(item["area"]), reverse=True)[:expected_count]


def order_pentagon_slots(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(components) != 5:
        raise ValueError("--slot-layout pentagon requires exactly 5 directions")
    ordered_y = sorted(components, key=lambda item: component_center(item)[1])
    top = sorted(ordered_y[:2], key=lambda item: component_center(item)[0])
    middle = ordered_y[2]
    bottom = sorted(ordered_y[3:], key=lambda item: component_center(item)[0])
    return [*top, middle, *bottom]


def order_row_major_slots(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return animation_pipeline.sort_components_row_major(components)


def order_reference_slots(
    components: list[dict[str, Any]],
    slot_layout: str,
) -> list[dict[str, Any]]:
    if slot_layout == "pentagon":
        return order_pentagon_slots(components)
    return order_row_major_slots(components)


def assign_to_slots(
    components: list[dict[str, Any]],
    slot_centers: dict[str, tuple[float, float]],
) -> dict[str, dict[str, Any]]:
    remaining = components[:]
    assigned: dict[str, dict[str, Any]] = {}
    for direction, center in slot_centers.items():
        if not remaining:
            raise ValueError(f"No component available for direction {direction}")
        best = min(
            remaining,
            key=lambda item: math.dist(component_center(item), center),
        )
        assigned[direction] = best
        remaining.remove(best)
    return assigned


def union_box(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def centered_box(
    center: tuple[float, float],
    size: tuple[int, int],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    width, height = size
    image_width, image_height = image_size
    x0 = round(center[0] - width / 2)
    y0 = round(center[1] - height / 2)
    x0 = max(0, min(x0, image_width - width))
    y0 = max(0, min(y0, image_height - height))
    return (x0, y0, x0 + width, y0 + height)


def crop_boxes_for_directions(
    boxes_by_direction: dict[str, list[tuple[int, int, int, int]]],
    image_size: tuple[int, int],
    padding: int,
) -> dict[str, tuple[int, int, int, int]]:
    unions = {
        direction: union_box(boxes)
        for direction, boxes in boxes_by_direction.items()
    }
    crop_width = min(
        image_size[0],
        max(box[2] - box[0] for box in unions.values()) + padding * 2,
    )
    crop_height = min(
        image_size[1],
        max(box[3] - box[1] for box in unions.values()) + padding * 2,
    )
    crop_size = (crop_width, crop_height)
    return {
        direction: centered_box(
            ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2),
            crop_size,
            image_size,
        )
        for direction, box in unions.items()
    }


def isolate_component(image: Image.Image, component: dict[str, Any]) -> Image.Image:
    source = image.convert("RGBA")
    isolated = Image.new("RGBA", source.size, (0, 0, 0, 0))
    source_px = source.load()
    isolated_px = isolated.load()
    for x, y in component["pixels"]:
        isolated_px[x, y] = source_px[x, y]
    return isolated


def box_intersects(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def assign_components_to_nearest_slot(
    components: list[dict[str, Any]],
    slot_centers: dict[str, tuple[float, float]],
) -> dict[str, list[dict[str, Any]]]:
    assigned = {direction: [] for direction in slot_centers}
    for component in components:
        center = component_center(component)
        direction = min(
            slot_centers,
            key=lambda item: math.dist(center, slot_centers[item]),
        )
        assigned[direction].append(component)
    return assigned


def isolate_components(image: Image.Image, components: list[dict[str, Any]]) -> Image.Image:
    source = image.convert("RGBA")
    isolated = Image.new("RGBA", source.size, (0, 0, 0, 0))
    source_px = source.load()
    isolated_px = isolated.load()
    for component in components:
        for x, y in component["pixels"]:
            isolated_px[x, y] = source_px[x, y]
    return isolated


def remove_green_fringe(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    px = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = px[x, y]
            if a == 0:
                px[x, y] = (0, 0, 0, 0)
                continue
            strongest_non_green = max(r, b)
            green_excess = g - strongest_non_green
            is_yellow_green_residue = (
                g >= 70
                and b <= 205
                and g >= b + 18
                and b + 8 <= r <= g + 42
            )
            is_pale_matte_residue = (
                r >= 150
                and g >= 145
                and 115 <= b <= 225
                and abs(r - g) <= 45
                and g >= b - 2
                and r <= b + 85
            )
            if not (is_yellow_green_residue or is_pale_matte_residue) and (g <= 35 or green_excess <= 8):
                continue
            matte_strength = min(1.0, max(0.0, (green_excess - 4) / 55))
            if g >= r - 6 and g >= b + 18 and b <= 190:
                matte_strength = max(matte_strength, min(1.0, (g - b - 18) / 60))
            if is_yellow_green_residue:
                matte_strength = max(matte_strength, 0.9)
            if is_pale_matte_residue:
                matte_strength = max(matte_strength, 0.92)
            new_alpha = round(a * (1.0 - matte_strength * 0.88))
            if new_alpha <= 6:
                px[x, y] = (0, 0, 0, 0)
                continue
            px[x, y] = (r, min(g, strongest_non_green + 4), b, new_alpha)
    return rgba


def clear_output_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS | {".json"}:
            child.unlink()


def postprocess_cleaned_direction(frames_dir: Path, output: Path, preview: Path) -> None:
    frames: list[Image.Image] = []
    for path in natural_frame_paths(frames_dir):
        cleaned = remove_green_fringe(Image.open(path))
        cleaned.save(path)
        frames.append(cleaned)
    if frames:
        animation_pipeline.save_sheet(frames, output)
        animation_pipeline.save_preview(frames, preview)


def extract_video_frames(args: argparse.Namespace, raw_dir: Path) -> dict[str, Any]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    if args.overwrite:
        clear_output_dir(raw_dir)
    return extract_frames_ffmpeg.run(
        argparse.Namespace(
            input=Path(args.input),
            output_dir=raw_dir,
            fps=args.extract_fps,
            crop=args.crop,
            start_time=args.start_time,
            pattern="frame_%04d.png",
            start_number=1,
            overwrite=args.overwrite,
        )
    )


def split_direction_sources(
    args: argparse.Namespace,
    sampled_paths: list[tuple[int, Path]],
    split_dir: Path,
    directions: list[str],
) -> dict[str, Any]:
    key = animation_pipeline.parse_hex_color(args.key)
    reference_path = sampled_paths[args.reference_sample - 1][1]
    reference_img = clean_for_split(Image.open(reference_path), args.background_mode, key, args.tolerance)
    reference_components = largest_components(reference_img, len(directions), args.component_min_area)
    reference_slots = order_reference_slots(reference_components, args.slot_layout)
    slot_centers = {
        direction: component_center(component)
        for direction, component in zip(directions, reference_slots)
    }

    boxes_by_direction: dict[str, list[tuple[int, int, int, int]]] = {
        direction: []
        for direction in directions
    }
    assignment_records: list[dict[str, Any]] = []

    for output_index, (source_index, path) in enumerate(sampled_paths, start=1):
        cleaned = clean_for_split(Image.open(path), args.background_mode, key, args.tolerance)
        primary_components = largest_components(cleaned, len(directions), args.component_min_area)
        assigned = assign_to_slots(primary_components, slot_centers)
        effect_components = [
            component
            for component in animation_pipeline.component_bboxes(cleaned)
            if int(component["area"]) >= args.effect_min_area
        ]
        components_by_direction = assign_components_to_nearest_slot(effect_components, slot_centers)
        frame_record = {
            "output_index": output_index,
            "source_frame_index": source_index + 1,
            "source": str(path),
            "directions": {},
        }
        for direction in directions:
            box = assigned[direction]["bbox"]
            for component in components_by_direction[direction]:
                boxes_by_direction[direction].append(component["bbox"])
            frame_record["directions"][direction] = {
                "bbox": list(box),
                "center": list(component_center(assigned[direction])),
                "area": int(assigned[direction]["area"]),
                "component_count": len(components_by_direction[direction]),
            }
        assignment_records.append(frame_record)

    crop_boxes = crop_boxes_for_directions(
        boxes_by_direction,
        reference_img.size,
        args.crop_padding,
    )

    for direction in directions:
        direction_dir = split_dir / direction
        direction_dir.mkdir(parents=True, exist_ok=True)
        if args.overwrite:
            clear_output_dir(direction_dir)

    for output_index, (_, path) in enumerate(sampled_paths, start=1):
        cleaned = clean_for_split(Image.open(path), args.background_mode, key, args.tolerance)
        primary_components = largest_components(cleaned, len(directions), args.component_min_area)
        assigned = assign_to_slots(primary_components, slot_centers)
        effect_components = [
            component
            for component in animation_pipeline.component_bboxes(cleaned)
            if int(component["area"]) >= args.effect_min_area
        ]
        components_by_direction = assign_components_to_nearest_slot(effect_components, slot_centers)
        for direction in directions:
            crop_box = crop_boxes[direction]
            components = [
                component
                for component in components_by_direction[direction]
                if box_intersects(component["bbox"], crop_box)
            ]
            if assigned[direction] not in components:
                components.append(assigned[direction])
            isolated = isolate_components(cleaned, components)
            cropped = remove_green_fringe(isolated.crop(crop_boxes[direction]))
            cropped.save(split_dir / direction / f"frame_{output_index:04d}.png")

    return {
        "reference_sample": args.reference_sample,
        "reference_frame": str(reference_path),
        "slot_layout": args.slot_layout,
        "slot_centers": {direction: [round(x, 3), round(y, 3)] for direction, (x, y) in slot_centers.items()},
        "crop_padding": args.crop_padding,
        "crop_boxes": {direction: list(box) for direction, box in crop_boxes.items()},
        "assignments": assignment_records,
    }


def run_direction_cleaner(
    args: argparse.Namespace,
    directions: list[str],
    split_dir: Path,
    action_dir: Path,
) -> dict[str, Any]:
    direction_outputs: dict[str, Any] = {}
    for direction in directions:
        frame_prefix = f"{args.character}_{args.action}_{direction}"
        output = action_dir / "sheets" / "directions" / f"{frame_prefix}_{args.frames}f_256.png"
        preview = action_dir / "previews" / f"{frame_prefix}_{args.frames}f_preview.png"
        frames_dir = action_dir / "frames" / direction / f"{args.frames}f_256"
        report = action_dir / "reports" / f"{frame_prefix}_{args.frames}f_report.json"
        if args.overwrite:
            clear_output_dir(frames_dir)
            for artifact in (output, preview, report):
                if artifact.exists():
                    artifact.unlink()

        cleaner_report = animation_pipeline.run(
            argparse.Namespace(
                source=None,
                source_frames_dir=str(split_dir / direction),
                frames=args.frames,
                output=str(output),
                preview=str(preview),
                frames_dir=str(frames_dir),
                report=str(report),
                background_mode="alpha",
                anchor_mode=args.anchor_mode,
                layout_mode=args.layout_mode,
                key=args.key,
                tolerance=args.tolerance,
                split_mode="components",
                grid_cols=1,
                grid_rows=1,
                grid_inset=0,
                take_first=None,
                component_sort="x",
                component_min_area=args.component_min_area,
                frame_prefix=frame_prefix,
            )
        )
        postprocess_cleaned_direction(frames_dir, output, preview)
        direction_outputs[direction] = {
            "sheet": str(output),
            "preview": str(preview),
            "frames_dir": str(frames_dir),
            "report": str(report),
            "status": cleaner_report["status"],
            "warning_count": len(cleaner_report["warnings"]),
            "error_count": len(cleaner_report["errors"]),
        }
    return direction_outputs


def mirror_direction_outputs(
    args: argparse.Namespace,
    mirror_map: dict[str, str],
    action_dir: Path,
    direction_outputs: dict[str, Any],
) -> dict[str, Any]:
    mirrored_outputs: dict[str, Any] = {}
    for target, source in mirror_map.items():
        if source not in direction_outputs:
            raise ValueError(f"Cannot mirror {target} from missing source direction {source}")
        if target in direction_outputs or target in mirrored_outputs:
            raise ValueError(f"Mirror target {target} already exists")

        frame_prefix = f"{args.character}_{args.action}_{target}"
        output = action_dir / "sheets" / "directions" / f"{frame_prefix}_{args.frames}f_256.png"
        preview = action_dir / "previews" / f"{frame_prefix}_{args.frames}f_preview.png"
        frames_dir = action_dir / "frames" / target / f"{args.frames}f_256"
        report = action_dir / "reports" / f"{frame_prefix}_{args.frames}f_report.json"

        frames_dir.mkdir(parents=True, exist_ok=True)
        if args.overwrite:
            clear_output_dir(frames_dir)
            for artifact in (output, preview, report):
                if artifact.exists():
                    artifact.unlink()

        source_paths = natural_frame_paths(Path(direction_outputs[source]["frames_dir"]))
        if len(source_paths) != args.frames:
            raise ValueError(f"Expected {args.frames} source frames for {source}, found {len(source_paths)}")

        mirrored_frames = [
            Image.open(path).convert("RGBA").transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            for path in source_paths
        ]
        for index, frame in enumerate(mirrored_frames, start=1):
            frame.save(frames_dir / f"{frame_prefix}_{index:02d}.png")

        animation_pipeline.save_sheet(mirrored_frames, output)
        animation_pipeline.save_preview(mirrored_frames, preview)

        mirror_report = {
            "status": "pass",
            "mirrored_from": source,
            "direction": target,
            "output": str(output),
            "preview": str(preview),
            "frames_dir": str(frames_dir),
            "frame_count": args.frames,
            "frame_size": FRAME_SIZE,
            "sheet_size": [FRAME_SIZE * args.frames, FRAME_SIZE],
        }
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(mirror_report, indent=2))
        mirrored_outputs[target] = {
            "sheet": str(output),
            "preview": str(preview),
            "frames_dir": str(frames_dir),
            "report": str(report),
            "status": "pass",
            "warning_count": 0,
            "error_count": 0,
            "mirrored_from": source,
        }
    return mirrored_outputs


def resolve_row_order(
    requested_row_order: str | None,
    source_directions: list[str],
    mirror_map: dict[str, str],
    available_outputs: dict[str, Any],
) -> list[str]:
    if requested_row_order:
        row_order = parse_directions(requested_row_order)
    elif all(direction in available_outputs for direction in DEFAULT_EIGHT_WAY_ORDER):
        row_order = DEFAULT_EIGHT_WAY_ORDER
    else:
        row_order = source_directions[:]
        for target in mirror_map:
            if target not in row_order:
                row_order.append(target)

    missing = [direction for direction in row_order if direction not in available_outputs]
    if missing:
        raise ValueError(f"Row order references missing directions: {', '.join(missing)}")
    return row_order


def checker_color(x: int, y: int) -> tuple[int, int, int, int]:
    return (50, 54, 60, 255) if ((x // 32 + y // 32) % 2) else (36, 39, 44, 255)


def compose_combined_sheet(
    args: argparse.Namespace,
    row_order: list[str],
    direction_outputs: dict[str, Any],
    combined_output: Path,
    combined_preview: Path,
) -> None:
    sheet = Image.new("RGBA", (FRAME_SIZE * args.frames, FRAME_SIZE * len(row_order)), (0, 0, 0, 0))
    preview = Image.new("RGBA", sheet.size, (42, 45, 50, 255))
    preview_draw = ImageDraw.Draw(preview)

    for row, direction in enumerate(row_order):
        paths = natural_frame_paths(Path(direction_outputs[direction]["frames_dir"]))
        if len(paths) != args.frames:
            raise ValueError(f"Expected {args.frames} cleaned frames for {direction}, found {len(paths)}")
        row_y = row * FRAME_SIZE
        for col, path in enumerate(paths):
            cell_x = col * FRAME_SIZE
            for y in range(row_y, row_y + FRAME_SIZE, 32):
                for x in range(cell_x, cell_x + FRAME_SIZE, 32):
                    preview_draw.rectangle(
                        (x, y, min(x + 31, cell_x + FRAME_SIZE - 1), min(y + 31, row_y + FRAME_SIZE - 1)),
                        fill=checker_color(x, y),
                    )
            frame = Image.open(path).convert("RGBA")
            sheet.alpha_composite(frame, (cell_x, row_y))
            preview.alpha_composite(frame, (cell_x, row_y))
            preview_draw.rectangle(
                (cell_x, row_y, cell_x + FRAME_SIZE - 1, row_y + FRAME_SIZE - 1),
                outline=(255, 255, 255, 90),
            )
        preview_draw.rectangle((4, row_y + 4, 160, row_y + 28), fill=(0, 0, 0, 165))
        preview_draw.text((12, row_y + 9), direction, fill=(255, 255, 255, 255))

    combined_output.parent.mkdir(parents=True, exist_ok=True)
    combined_preview.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(combined_output)
    preview.save(combined_preview)


def run(args: argparse.Namespace) -> dict[str, Any]:
    directions = parse_directions(args.directions)
    mirror_map = parse_mirror_map(args.mirror_map) if args.mirror_missing else {}
    if args.reference_sample < 1 or args.reference_sample > args.frames:
        raise ValueError("--reference-sample must be between 1 and --frames")

    root = Path(args.work_root)
    action_dir = root / args.character / args.action
    raw_dir = action_dir / "extracted_raw"
    split_dir = action_dir / "split_directions"
    action_dir.mkdir(parents=True, exist_ok=True)

    extraction_report = extract_video_frames(args, raw_dir)
    raw_paths = natural_frame_paths(raw_dir)
    sampled_paths = sample_evenly(raw_paths, args.frames)
    split_report = split_direction_sources(args, sampled_paths, split_dir, directions)
    direction_outputs = run_direction_cleaner(args, directions, split_dir, action_dir)
    if mirror_map:
        direction_outputs.update(mirror_direction_outputs(args, mirror_map, action_dir, direction_outputs))
    row_order = resolve_row_order(args.row_order, directions, mirror_map, direction_outputs)

    combined_output = action_dir / "sheets" / f"{args.character}_{args.action}_{len(row_order)}dir_{args.frames}f_256.png"
    combined_preview = action_dir / "previews" / f"{args.character}_{args.action}_{len(row_order)}dir_{args.frames}f_preview.png"
    if args.overwrite:
        for artifact in (combined_output, combined_preview):
            if artifact.exists():
                artifact.unlink()
    compose_combined_sheet(args, row_order, direction_outputs, combined_output, combined_preview)

    status = "pass"
    if any(output["status"] == "fail" for output in direction_outputs.values()):
        status = "fail"
    report = {
        "status": status,
        "input": str(Path(args.input)),
        "frames": args.frames,
        "source_directions": directions,
        "row_order": row_order,
        "mirror_map": mirror_map,
        "background_mode": args.background_mode,
        "layout_mode": args.layout_mode,
        "raw_dir": str(raw_dir),
        "split_dir": str(split_dir),
        "combined_sheet": str(combined_output),
        "combined_preview": str(combined_preview),
        "extraction": extraction_report,
        "selected_frames": [
            {
                "output_index": output_index,
                "source_frame_index": source_index + 1,
                "source": str(path),
            }
            for output_index, (source_index, path) in enumerate(sampled_paths, start=1)
        ],
        "split": split_report,
        "direction_outputs": direction_outputs,
    }
    report_path = action_dir / "reports" / f"{args.character}_{args.action}_{len(row_order)}dir_{args.frames}f_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    report["report"] = str(report_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split a multi-direction isometric video into per-direction rows and a combined sheet."
    )
    parser.add_argument("--input", required=True, help="Input MP4/video containing separated direction poses.")
    parser.add_argument("--character", default="gorilla", help="Character/output name.")
    parser.add_argument("--action", default="walk", help="Action/output name.")
    parser.add_argument("--frames", type=int, default=24, help="Number of frames per direction row.")
    parser.add_argument(
        "--directions",
        default=DEFAULT_SOURCE_DIRECTIONS,
        help="Comma-separated labels/order for the source directions present in the video.",
    )
    parser.add_argument(
        "--mirror-map",
        default=DEFAULT_MIRROR_MAP,
        help="Comma-separated target:source rows to create by horizontal mirroring.",
    )
    parser.add_argument("--no-mirror-missing", dest="mirror_missing", action="store_false")
    parser.set_defaults(mirror_missing=True)
    parser.add_argument("--row-order", help="Optional comma-separated final package row order.")
    parser.add_argument("--work-root", default="work/isometric_directions", help="Root folder for generated artifacts.")
    parser.add_argument("--background-mode", choices=("chroma", "alpha"), default="chroma")
    parser.add_argument("--key", default="#00ff00", help="Chroma key used for detection when background mode is chroma.")
    parser.add_argument("--tolerance", type=int, default=70)
    parser.add_argument("--component-min-area", type=int, default=1000)
    parser.add_argument("--effect-min-area", type=int, default=48)
    parser.add_argument("--crop-padding", type=int, default=24)
    parser.add_argument("--slot-layout", choices=("pentagon", "row-major"), default="pentagon")
    parser.add_argument("--reference-sample", type=int, default=1, help="1-based sampled frame used to label slots.")
    parser.add_argument("--layout-mode", choices=("preserve-canvas", "fit-foreground"), default="preserve-canvas")
    parser.add_argument("--anchor-mode", choices=("bbox", "lower-body"), default="bbox")
    parser.add_argument("--extract-fps", help="Optional FFmpeg fps filter before even sampling.")
    parser.add_argument("--crop", help="Optional FFmpeg crop expression before splitting.")
    parser.add_argument("--start-time", help="Optional video start time such as 1 or 00:00:01.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite generated artifacts for this run.")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args), indent=2))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
