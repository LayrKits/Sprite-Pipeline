from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"{name} was not found on PATH. Install FFmpeg before running extraction.")
    return path


def parse_rate(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def probe_video(ffprobe: str, source: Path) -> dict[str, object]:
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,duration",
        "-of",
        "json",
        str(source),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise SystemExit(f"No video stream found in {source}")
    stream = streams[0]
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "r_frame_rate": stream.get("r_frame_rate"),
        "avg_frame_rate": stream.get("avg_frame_rate"),
        "avg_fps_float": parse_rate(stream.get("avg_frame_rate")),
        "duration": stream.get("duration"),
        "nb_frames": stream.get("nb_frames"),
    }


def build_command(args: argparse.Namespace, ffmpeg: str) -> list[str]:
    output_pattern = str(Path(args.output_dir) / args.pattern)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "info",
        "-y" if args.overwrite else "-n",
    ]
    if args.start_time:
        command.extend(["-ss", args.start_time])
    command.extend([
        "-i",
        str(args.input),
        "-map",
        "0:v:0",
    ])
    filters: list[str] = []
    if args.crop:
        filters.append(f"crop={args.crop}")
    if args.fps:
        filters.append(f"fps={args.fps}")

    if filters:
        command.extend(["-vf", ",".join(filters)])
    else:
        command.extend(["-fps_mode", "passthrough"])
    command.extend(["-pix_fmt", "rgb24", "-start_number", str(args.start_number), output_pattern])
    return command


def count_extracted(output_dir: Path, pattern: str) -> int:
    prefix = pattern.split("%", 1)[0]
    suffix = Path(pattern).suffix
    return len(sorted(output_dir.glob(f"{prefix}*{suffix}")))


def run(args: argparse.Namespace) -> dict[str, object]:
    source = Path(args.input)
    if not source.exists():
        raise SystemExit(f"Input video does not exist: {source}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = require_tool("ffmpeg")
    ffprobe = require_tool("ffprobe")
    metadata = probe_video(ffprobe, source)
    command = build_command(args, ffmpeg)

    subprocess.run(command, check=True)

    report = {
        "input": str(source),
        "output_dir": str(output_dir),
        "pattern": args.pattern,
        "requested_fps": args.fps,
        "start_time": args.start_time,
        "crop": args.crop,
        "mode": "constant-fps" if args.fps else "source-frame-passthrough",
        "source_metadata": metadata,
        "extracted_frame_count": count_extracted(output_dir, args.pattern),
        "command": command,
    }
    report_path = output_dir / "extraction_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract ordered PNG frames from a video with FFmpeg.")
    parser.add_argument("--input", required=True, help="Input video, usually a Kling MP4 in Videos/.")
    parser.add_argument("--output-dir", required=True, help="Directory for extracted PNG frames.")
    parser.add_argument("--fps", help="Optional constant output fps, for example 30. Omit to keep decoded source frames.")
    parser.add_argument("--crop", help="Optional FFmpeg crop expression such as iw:840:0:0.")
    parser.add_argument("--start-time", help="Optional video start time such as 1 or 00:00:01.")
    parser.add_argument("--pattern", default="frame_%04d.png", help="Output filename pattern.")
    parser.add_argument("--start-number", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true", help="Allow FFmpeg to overwrite matching output files.")
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
