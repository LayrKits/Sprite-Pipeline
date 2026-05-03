# Canonical Video Frame Sprite Pipeline

This file is the active workflow. The older image-generation and prompt-driven
sheet process has been archived under
`archive/legacy-sheet-and-generation-workflow/`.

## Pipeline Contract

The source of truth is now an animation video. Frame extraction is the first
active processing step before cleanup and layout.

Use FFmpeg first:

```bash
python tools/extract_frames_ffmpeg.py \
  --input Videos/hero_run.mp4 \
  --output-dir work/extracted/hero/run \
  --fps 30
```

This cleanup pipeline starts after extraction, with a folder of ordered frame
images:

```text
work/extracted/<character>/<action>/frame_0001.png
work/extracted/<character>/<action>/frame_0002.png
work/extracted/<character>/<action>/frame_0003.png
```

The tool then normalizes those frames into a game-ready horizontal strip.

For Kling clips with an off-white background, run the provisional matte before
cleanup:

```bash
python tools/matte_light_background.py \
  --source-frames-dir work/extracted/hero/run \
  --output-dir work/matted/hero/run
```

Then run the sprite-sheet cleanup on `work/matted/...` with
`--background-mode alpha`.

## What The Extractor Must Provide

The frame extraction step should produce:

- one folder per animation
- one image per intended animation frame
- filenames that sort in playback order
- transparent PNGs when possible
- otherwise, frames on a perfectly flat chroma background such as `#00ff00`
- full character, weapon, cloth, and effects visible in every frame
- the same source canvas for every frame after watermark removal
- no important pixels touching the source frame edge
- consistent camera angle, resolution, and approximate character scale
- an `extraction_report.json` when using `tools/extract_frames_ffmpeg.py`

The extractor should avoid:

- mixed animations in one folder
- frame numbers that sort incorrectly, such as `1.png`, `10.png`, `2.png`
- complex backgrounds unless they have already been removed
- floor shadows, labels, text, watermarks, and UI overlays
- accidental crops of staff tips, limbs, cloth trails, dust, or spell effects
- tight character crops that make each animation choose a different effective
  zoom

## FFmpeg Extraction Notes

The default command we are trying first is equivalent to:

```bash
ffmpeg -i input_video.mp4 -vf "fps=30" -pix_fmt rgb24 frames/frame_%04d.png
```

Use `fps=30` when the Kling MP4 should be sampled as a constant 30 fps animation
timeline. The `fps` filter may duplicate or drop frames to hit the requested
rate. If a later pass needs every decoded source frame exactly as stored, omit
`--fps` in the wrapper.

## Provisional Light Matte

`tools/matte_light_background.py` is a local bridge for light/off-white Kling
backgrounds. It:

- estimates background color from frame corners
- removes pixels near that light background color
- preserves ordered filenames
- writes `matte_report.json`

This is not a full segmentation model. Replace or refine it when the dedicated
matting package is chosen.

## Cleanup And Layout Steps

All extracted frame folders should pass through `tools/animation_pipeline.py`.

The script performs the durable work:

- reads frame files in natural filename order
- optionally removes a flat chroma-key background
- despills green antialiasing when chroma mode is used
- removes tiny noise components
- preserves the source video canvas by default, scaling the full extracted
  frame into a transparent `256 x 256` cell
- keeps empty space around the character so idle, attack, and effect-heavy
  animations retain the same camera scale
- scales consistently across the sheet
- writes a true horizontal `256 x 256` strip
- writes individual cleaned frames
- writes a checker/guide preview
- writes a validation JSON report

`--layout-mode preserve-canvas` is the normal video workflow. Use
`--layout-mode fit-foreground` only for legacy recovery or a deliberate
foreground-normalized export; that older mode recenters each frame to
`TARGET_CENTER_X=128` and grounds it to `TARGET_GROUND_Y=220`.

## Background Modes

Use `--background-mode alpha` when extracted frames already contain useful
transparency.

```bash
python tools/animation_pipeline.py \
  --source-frames-dir work/extracted/hero/run \
  --frames 12 \
  --background-mode alpha \
  --layout-mode preserve-canvas \
  --output work/sheets/hero/run/hero_run_12f_256.png \
  --preview work/previews/hero_run_12f_preview.png \
  --frames-dir work/frames/hero/run_12f_256 \
  --report work/reports/hero_run_12f_report.json \
  --frame-prefix hero_run
```

Use `--background-mode chroma` when frames have a flat key color.

```bash
python tools/animation_pipeline.py \
  --source-frames-dir work/extracted/hero/jump \
  --frames 16 \
  --background-mode chroma \
  --layout-mode preserve-canvas \
  --key "#00ff00" \
  --output work/sheets/hero/jump/hero_jump_16f_256.png \
  --preview work/previews/hero_jump_16f_preview.png \
  --frames-dir work/frames/hero/jump_16f_256 \
  --report work/reports/hero_jump_16f_report.json \
  --frame-prefix hero_jump
```

If the source video has a complex background and the extractor does not output
alpha, remove the background before using this pipeline. This tool is a sprite
layout and validation stage, not a general video segmentation stage.

## What Was Archived

These pieces are no longer active workflow dependencies:

- image-generation prompt recipes
- character reference images used for prompt consistency
- magenta guide-grid templates for generated sheets
- generated raw sheet examples
- old promoted sample outputs

They were moved to `archive/legacy-sheet-and-generation-workflow/` so previous
work can still be inspected or recovered.

## Legacy Input Modes

The script still supports old sheet inputs through `--source`:

- `--split-mode grid` for fixed atlas layouts
- `--split-mode components` for separated poses on a flat background
- `--split-mode equal` as a last resort for truly uniform strips

Keep these modes for recovery and one-off conversions. The default production
path should be extracted frame folders.

## Promotion Rules

Do not promote raw extracted frames directly into a game. Promote only cleaned
pipeline outputs.

Promote only after:

- output size is exactly `frames * 256` by `256`
- validation status is `pass`
- no meaningful animation frame is empty
- source-edge and final-edge warnings are reviewed
- preview shows correct order and no clipped staff/effects from the source video
  or watermark crop
- adjacent-frame warnings have been visually reviewed
- the frame count and timing are reflected in the consuming game

## Validation Rules

Hard fail:

- wrong expected frame count
- wrong final sheet size
- empty frame in foreground-fit layout
- clipped final frame in foreground-fit layout
- source frames have no usable foreground

Warnings to review:

- empty frame in preserve-canvas layout
- final-cell edge contact in preserve-canvas layout
- adjacent silhouette diff too low: duplicate-looking frames
- adjacent silhouette diff too high: motion pop
- high height/width variance: likely scale drift, staff drift, or pose mismatch
- source edge foreground: source frame was crowded before repack

Warnings are not automatic failures, but they must stay visible. Do not silently
ship weak animation sources.
