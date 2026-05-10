# Quickstart

Use this when you have a Kling MP4 or other character animation video and need a
clean horizontal `256 x 256` sprite strip. If no frame count is specified, the
default target is a 24-frame sheet at 256px cells.

If you only have a still image, first create source footage with an
image-to-video model. In that case, ask for or write a video-model prompt based
on the image and desired animation; do not run the cleanup pipeline until a
video or extracted frame folder exists.

If no file is named or attached, check `Videos/To Be Processed/` for queued
videos before asking for a new source.

## Setup

From `2D Animation Pipeline`:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

Use `./.venv/bin/python` in the commands below after setup.

FFmpeg is an external command-line tool, not a Python package. On this machine it
is already installed at `/opt/homebrew/bin/ffmpeg`.

## Step 1: Extract Frames

Use FFmpeg first. This creates ordered RGB PNG frames and an
`extraction_report.json`.

```bash
python tools/extract_frames_ffmpeg.py \
  --input Videos/hero_run.mp4 \
  --output-dir work/extracted/hero/run \
  --fps 30
```

The `--fps 30` option uses FFmpeg's `fps` filter. That is correct when the Kling
video should be sampled as a 30 fps animation timeline. If you need every decoded
source frame without constant-fps resampling, omit `--fps`.

The equivalent direct FFmpeg command is:

```bash
ffmpeg -i Videos/hero_run.mp4 -vf "fps=30" -pix_fmt rgb24 work/extracted/hero/run/frame_%04d.png
```

For bottom-right Kling watermarks on a `960 x 960` clip, crop the bottom band at
extraction time:

```bash
python tools/extract_frames_ffmpeg.py \
  --input Videos/hero_run.mp4 \
  --output-dir work/extracted/hero/run_cropped \
  --fps 30 \
  --crop iw:840:0:0
```

## Step 2: Matte Light Background

Use this when the extracted PNGs are RGB frames on a light/off-white background:

```bash
python tools/matte_light_background.py \
  --source-frames-dir work/extracted/hero/run \
  --output-dir work/matted/hero/run
```

This is a first-pass local matte. It estimates the background color from frame
corners and removes pixels close to that light background. Skip this step if the
extractor already produced transparent PNGs.

## Step 3: Build Sprite Sheet

For video sources, keep the full extracted video canvas. This preserves the
character's size and empty space across idle, attack, and effect-heavy
animations. The pipeline still removes transparent noise, but it should not zoom
into the visible character.

## Transparent Extracted Frames

Use this when frame extraction produced transparent PNGs:

```bash
python tools/animation_pipeline.py \
  --source-frames-dir work/matted/hero/run \
  --frames 24 \
  --background-mode alpha \
  --layout-mode preserve-canvas \
  --output work/sheets/hero/run/hero_run_24f_256.png \
  --preview work/previews/hero_run_24f_preview.png \
  --frames-dir work/frames/hero/run_24f_256 \
  --report work/reports/hero_run_24f_report.json \
  --frame-prefix hero_run
```

## Chroma-Key Extracted Frames

Use this when frame extraction produced frames on a solid chroma background.
The default key is `#00ff00`, but any flat key color can be passed with
`--background-color`:

```bash
python tools/animation_pipeline.py \
  --source-frames-dir work/extracted/hero/jump \
  --frames 16 \
  --background-mode chroma \
  --layout-mode preserve-canvas \
  --background-color "#00ff00" \
  --output work/sheets/hero/jump/hero_jump_16f_256.png \
  --preview work/previews/hero_jump_16f_preview.png \
  --frames-dir work/frames/hero/jump_16f_256 \
  --report work/reports/hero_jump_16f_report.json \
  --frame-prefix hero_jump
```

## Frame Folder Rules

- Put only one animation in each `work/extracted/<character>/<action>/` folder.
- Name frames so natural filename sorting matches playback order, for example
  `0001.png`, `0002.png`, `0003.png`.
- Pass `--frames` as an explicit safety check. Use `--frames 24` when the user
  does not request a specific frame count.
- Crop only watermark/UI bands. Do not crop around the character, or each
  animation can end up with a different effective zoom.
- Use `--background-mode alpha` for already-transparent frames.
- Use `--background-mode chroma` for flat-key backgrounds.
- Use `--background-color "#e80fe3"` or another exact hex value when the source
  was intentionally generated on a non-green key.

## Read The Output

Check these files before promotion:

- output sheet: final horizontal PNG for the game
- preview PNG: visual order, clipping, preserved canvas scale, and timing feel
- individual cleaned frames: precise frame inspection
- report JSON: pass/fail, warnings, silhouette diffs, frame boxes, source paths

Warnings are not automatic failures. They mean inspect before shipping.

## Open The Viewer

After processing finishes, run the live sprite viewer server from the project
root:

```bash
node tools/serve_sprite_viewer.mjs
```

Open the printed URL with the Codex integrated Browser tool first. This is the
required first attempt for local sprite viewer and alignment review pages. Use a
regular desktop browser only after the integrated Browser tool is unavailable or
fails, and note the fallback reason. Do not use Safari, Chrome, macOS `open`,
Computer Use, or Playwright CLI as the first attempt for viewer approval pages.
Use Playwright CLI only for automated diagnostics, not as the default human
review handoff path. For a newly generated sheet that is still in `work/`, open
it with the direct `sheet` query:

```text
http://127.0.0.1:8000/sprite_viewer.html?sheet=work/sheets/hero/run/hero_run_24f_256.png
```

For promoted sheets, use the Game/Character/Animation selectors or a direct
`sheet` query to the promoted sheet path. The server scans `Final Sprite Sheets/`
when the viewer loads, so rebuilding the static manifest is not part of the
normal processing review.

If vertical or horizontal alignment ran and produced a candidate review path,
open the alignment page instead of the plain sheet viewer:

```text
http://127.0.0.1:8000/alignment-review?path=<validation_viewer_path>
```

After the server is running, always include a Markdown link to the exact review
URL in the assistant response so Codex renders the Web preview card with an
`Open` button. Use `open alignment review` for alignment candidate pages and
`open sprite viewer` for plain sheet review pages:

```markdown
[open alignment review](http://127.0.0.1:8000/alignment-review?path=<validation_viewer_path>)
```

Ask the user to approve the viewed sheet or alignment candidate before
promotion, and keep the server running for review.

Refresh the static pinned-gallery manifest only when intentionally updating
`sprite_gallery_manifest.js` from `sprite_gallery_pins.json`:

```bash
python tools/build_sprite_gallery_manifest.py
```

## Promote And Clean Up

After approval, promote only the viable sheets and their exact individual cell
frames. Use this folder shape:

```text
Final Sprite Sheets/<GameName>/<CharacterName>/<animation>/
  sheets/
  frames/<frame-count>f_256/
```

For example:

```text
Final Sprite Sheets/ExampleGame/ExampleCharacter/attack/
  sheets/ExampleCharacter_attack_12f_256.png
  sheets/ExampleCharacter_attack_24f_256.png
  frames/12f_256/
  frames/24f_256/
```

Then move the original video from `Videos/To Be Processed/` to
`Videos/Processed/`. Move every non-promoted generated artifact for that pass
into `Cleanup/`; `Cleanup/` is gitignored.

## Legacy Sheet Inputs

The CLI still supports old sheet and atlas inputs through `--source` plus
`--split-mode grid`, `components`, or `equal`. That path is retained for
recovering archived assets, not for the new default workflow. Use
`--layout-mode fit-foreground` only when you intentionally want the old
recentering and ground-line behavior.
