# Frame Extraction

This is Step 2 of the video-to-sprite-sheet pipeline: convert a Kling MP4 into
ordered PNG frames so matting, luminance, cleanup, and sprite-sheet layout can
process images one by one.

## Preferred Tool: FFmpeg

FFmpeg is the first extraction tool to use because it is fast, mature, and
already installed on this machine.

Check the local install:

```bash
ffmpeg -version
ffprobe -version
```

Use the wrapper:

```bash
python tools/extract_frames_ffmpeg.py \
  --input Videos/hero_run.mp4 \
  --output-dir work/extracted/hero/run \
  --fps 30
```

If the video has a bottom watermark, crop it out during extraction before any
matting step:

```bash
python tools/extract_frames_ffmpeg.py \
  --input Videos/hero_run.mp4 \
  --output-dir work/extracted/hero/run_cropped \
  --fps 30 \
  --crop iw:840:0:0
```

`--crop` accepts FFmpeg's crop expression in `w:h:x:y` form. For a `960 x 960`
Kling clip with the watermark in the bottom-right corner, `iw:840:0:0` keeps the
full width and removes the bottom 120 pixels.

This crop is only for watermark/UI removal. Keep the rest of the video canvas
intact so every animation preserves the same character scale and empty space.

The wrapper writes:

- `frame_0001.png`, `frame_0002.png`, and so on
- `extraction_report.json` with source metadata, frame count, and exact command

## Direct FFmpeg Command

The direct command is:

```bash
ffmpeg -i input_video.mp4 -vf "fps=30" -pix_fmt rgb24 frames/frame_%04d.png
```

With a crop:

```bash
ffmpeg -i input_video.mp4 -vf "crop=iw:840:0:0,fps=30" -pix_fmt rgb24 frames/frame_%04d.png
```

Use this when you want constant 30 fps output. The `fps` filter converts the
video to a specified constant frame rate, which means FFmpeg may duplicate or
drop frames if the source timestamps do not already match that rate.

For literal decoded source frames, omit the fps filter:

```bash
ffmpeg -i input_video.mp4 -fps_mode passthrough -pix_fmt rgb24 frames/frame_%04d.png
```

## Why PNG

PNG keeps the extracted images lossless. `-q:v 2` is useful for JPEG-style
quality-based image outputs, but it is not needed for PNG quality.

## OpenCV Alternative

OpenCV is still a reasonable fallback when we need custom frame selection logic
inside Python. The basic approach is:

```python
import cv2 as cv

cap = cv.VideoCapture("Videos/hero_run.mp4")
index = 1
while cap.isOpened():
    ok, frame = cap.read()
    if not ok:
        break
    cv.imwrite(f"work/extracted/hero/run/frame_{index:04d}.png", frame)
    index += 1
cap.release()
```

Do not use OpenCV as the first option unless we need Python-side selection,
inspection, or per-frame logic during extraction. OpenCV's own docs note that
video capture depends on a proper FFmpeg or GStreamer install, so using FFmpeg
directly keeps this step simpler.
