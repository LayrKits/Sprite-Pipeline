# Agent Instructions

This repo is a video-to-sprite-sheet pipeline. Do not infer the operational
workflow from README prose alone.

Start with:

1. `docs/ANIMATION_PIPELINE_NOTES.md`
2. `docs/QUICKSTART.md`
3. `docs/WORKSPACE_CONVENTIONS.md`

Default production path:

- source video
- extracted ordered frames
- optional matting
- `tools/animation_pipeline.py`
- preview/report review
- promote approved outputs

Use `--layout-mode preserve-canvas` for normal video-derived sheets. Use
`fit-foreground` only for legacy recovery or an explicit foreground-normalized
export.

## Prompting References

Use `docs/reference/PROMPTING_IMAGE_MODELS.md` only when the user asks to create
or revise an upstream still image, character reference, first pose, or transition
pose for animation source footage.

Use `docs/reference/PROMPTING_VIDEO_MODELS.md` only when the user asks to write
or refine a prompt for an image-to-video/video model that will produce animation
source footage.

Do not use these prompting references as substitutes for the normal cleanup,
validation, or promotion workflow once source video or extracted frames already
exist.

## README.md Copy

# 2D Animation Pipeline

> Note for agents: this README is written for human readers. For the operational
> workflow, start with `AGENTS.md`, then `docs/ANIMATION_PIPELINE_NOTES.md`.

Standalone cleanup and repack workspace for turning extracted animation frames
into clean horizontal `256 x 256` sprite sheets.

The workflow is shifting away from generating sprite sheets directly. The new
source of truth is video animation: upload or place character animation videos in
`Videos/`, extract the frames you want, then let this pipeline normalize those
frames into game-ready sheets.

## Current Workflow

1. Put source animation videos in `Videos/`.
2. Extract the chosen animation frames into `work/extracted/<character>/<action>/`
   as ordered image files such as `frame_0001.png`, `frame_0002.png`,
   `frame_0003.png`. Crop only watermark/UI bands at this stage; do not crop
   tightly around the character.
3. If the frames are on a light video background, run
   `tools/matte_light_background.py` to create transparent PNGs.
4. Run `tools/animation_pipeline.py` on the transparent frame directory using
   the preserved source-canvas layout.
5. Review the preview image and JSON report.
6. Run the vertical alignment assessment before promotion for jump, fall,
   landing, or any sheet that visually jitters, hovers, sinks, or drifts on the
   ground line. Run alignment only when the assessment says it is needed.
7. Promote only approved sprite sheets and their exact individual `256 x 256`
   cells into `Final Sprite Sheets/<GameName>/<CharacterName>/`.
8. Move the source video into `Videos/Processed/` and move non-promoted scratch
   outputs into `Cleanup/`.

Frame extraction is intentionally outside this tool for now. The extraction step
should output either transparent PNG frames or frames on a clean flat chroma
background.

## What Still Matters

The old generation prompt loop is archived, but the cleaner/repacker is still
the useful core. It still:

- accepts a sequence of source frames
- optionally removes a flat chroma background
- removes tiny noise components
- normalizes every frame into a transparent `256 x 256` cell
- preserves the source video canvas scale so empty space around a character
  stays consistent across idle, attack, and effect-heavy animations
- still supports foreground-fit layout for legacy or one-off recovery work
- writes individual cleaned frames, a horizontal strip, a preview, and a report
- warns about clipping, duplicate-looking frames, motion pops, and scale drift

## Active Files

- `tools/animation_pipeline.py`: the CLI for frame cleanup, layout, validation,
  and sprite-sheet export.
- `tools/extract_frames_ffmpeg.py`: the FFmpeg wrapper for extracting ordered PNG
  frames from Kling MP4s or other source videos.
- `tools/matte_light_background.py`: first-pass light-background matting for
  Kling-style frames before sprite layout.
- `tools/build_sprite_gallery_manifest.py`: refreshes the static viewer's sheet
  catalog from `Final Sprite Sheets/`, skips final per-frame folders so the
  gallery stays sheet-only, and marks the latest ten for the thumbnail picker.
- `isolated_workflows/vertical_frame_alignment/`: copy-derived assessment and
  vertical-only alignment workflow. It does not modify the main pipeline output
  unless a reviewed candidate is explicitly promoted later.
- `docs/QUICKSTART.md`: copy-paste commands for the new frame-directory flow.
- `docs/ANIMATION_PIPELINE_NOTES.md`: canonical workflow notes and validation
  rules.
- `docs/FRAME_EXTRACTION.md`: notes for FFmpeg and OpenCV extraction choices.
- `docs/INTEGRATION_GUIDE.md`: game-side assumptions for using the output.
- `docs/WORKSPACE_CONVENTIONS.md`: folder roles for videos, extracted frames,
  scratch work, and promoted sheets.
- `Videos/`: source videos you upload or collect.
- `Final Sprite Sheets/`: promoted sheets and frame cells ready for game
  integration, grouped by `GameName/CharacterName`.
- `Cleanup/`: gitignored holding area for non-promoted generated artifacts.
- `archive/legacy-sheet-and-generation-workflow/`: preserved old prompt, grid,
  reference, and sample sheet workflow.

## Setup

From this folder:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

You can also use any existing Python environment that has Pillow installed.

## Frame Directory Example

Extract frames from a Kling MP4 at 30 fps:

```bash
python tools/extract_frames_ffmpeg.py \
  --input Videos/hero_run.mp4 \
  --output-dir work/extracted/hero/run \
  --fps 30
```

Add `--crop iw:840:0:0` for a `960 x 960` Kling clip with a bottom-right
watermark.

Create alpha frames from an off-white video background:

```bash
python tools/matte_light_background.py \
  --source-frames-dir work/extracted/hero/run \
  --output-dir work/matted/hero/run
```

Use `--background-mode alpha` when the extracted frames already have
transparency:

```bash
python tools/animation_pipeline.py \
  --source-frames-dir work/matted/hero/run \
  --frames 12 \
  --background-mode alpha \
  --layout-mode preserve-canvas \
  --output work/sheets/hero/run/hero_run_12f_256.png \
  --preview work/previews/hero_run_12f_preview.png \
  --frames-dir work/frames/hero/run_12f_256 \
  --report work/reports/hero_run_12f_report.json \
  --frame-prefix hero_run
```

Use `--background-mode chroma` when the extracted frames are on a flat key
color:

```bash
python tools/animation_pipeline.py \
  --source-frames-dir work/extracted/hero/jump \
  --frames 16 \
  --background-mode chroma \
  --layout-mode preserve-canvas \
  --key "#00ff00" \
  --output "Final Sprite Sheets/hero_jump_16f_256.png" \
  --preview work/previews/hero_jump_16f_preview.png \
  --frames-dir work/cleaned/hero/jump \
  --report work/reports/hero_jump_16f_report.json \
  --frame-prefix hero_jump
```

## Source Frame Contract

For best results, extracted frame folders should follow these rules:

- one animation per folder
- filenames sort in playback order
- no missing or duplicate frame numbers unless intentional
- full body, weapon, cloth, and effects visible in every frame
- consistent source canvas after watermark crop; do not zoom or crop around the
  visible character
- no important pixels touching the source image edge
- consistent camera angle and approximate scale
- transparent alpha or a clean flat chroma background

## Promotion Checklist

Only promote an output sheet after:

- validation status is `pass`
- output size is exactly `frames * 256` by `256`
- preview order is correct
- no staff, limb, cloth, or effect is clipped by the source frame or watermark
  crop
- duplicate/pop warnings are reviewed
- gameplay timing is updated in the consuming game if frame count or frame
  meaning changed

For normal video outputs, the consuming game should use a consistent cell pivot
or origin across animations because the source canvas scale is preserved. Only
foreground-fit legacy outputs use `TARGET_GROUND_Y`, currently `220`.

## Vertical Alignment Assessment

Before promotion, run the assessment on any vertical-motion sheet such as jump,
fall, landing, knockback, or hover, and on any sheet where the viewer shows
ground jitter, feet floating, fall-through, or waist/core drift. The default
assessment prints compact JSON for the agent and does not write a report:

```bash
./.venv/bin/python isolated_workflows/vertical_frame_alignment/assess_vertical_alignment_need.py \
  --input "work/sheets/hero/jump/hero_jump_24f_256.png"
```

Use the verdict this way:

- `yes_likely` or `yes_but_constrained`: run the automatic alignment workflow.
- `probably_no` or `probably_no_or_minor`: do not align by default; continue
  with normal visual review.
- `review_manually`: inspect the sheet before changing pixels.

The automatic workflow is copy-derived and assessment-first. It skips alignment
unless the verdict says alignment is needed:

```bash
./.venv/bin/python isolated_workflows/vertical_frame_alignment/run_vertical_alignment_workflow.py \
  --input "work/sheets/hero/jump/hero_jump_24f_256.png" \
  --output-dir "isolated_workflows/vertical_frame_alignment/runs/hero_jump_24f_workflow"
```

Request the assessment HTML/images only when a visual report is useful:

```bash
./.venv/bin/python isolated_workflows/vertical_frame_alignment/assess_vertical_alignment_need.py \
  --input "work/sheets/hero/jump/hero_jump_24f_256.png" \
  --output-dir "isolated_workflows/vertical_frame_alignment/runs/hero_jump_24f_assessment" \
  --write-report
```

After alignment, open the candidate review through the server-hosted sprite
viewer and present the alignment candidates to the user before promotion. Ask
the user to pick a candidate and to call out any fixes that are still needed.
The review must show animated loops with guide lines for every method. Candidate
generation writes an immutable candidate sheet set for method review and a
separate `working_copies/` sheet set for user edits. Manual nudges in the hosted
review must save only into the working copy. `Restore from candidate` replaces
the working copy with the immutable candidate and resets offsets. `Finalize`
opens the current working copy in the sprite viewer for final visual checking.
`Attempt automatic cleanup` may replace the selected method's working-copy
offsets by aligning detected frame bottoms to the fixed ground guide line and
then saving the working copy; it is still subject to user review and restore.
Accept a candidate only if it has no floor penetration or canvas clipping,
contact frames sit on the intended ground line, airborne frames still preserve
the jump arc, horizontal placement is unchanged, and the matching individual
frame cells are promoted with the sheet. Do not overwrite the original sheet;
promote an approved aligned result as a new variant unless explicitly told
otherwise. Do not add a second review stage for minor frame nudges; if fixes are
requested, make them as an explicit new candidate or use the hosted review's
manual per-frame save flow, then return to the candidate review gate.

Promoted output should live under:

```text
Final Sprite Sheets/<GameName>/<CharacterName>/<animation>/
  sheets/
  frames/<frame-count>f_256/
```

After promotion, move the original source video to `Videos/Processed/` and move
all rejected or intermediate generated artifacts for that pass into `Cleanup/`.

## Sprite Viewer

Open `sprite_viewer.html` directly in a browser. It reads
`sprite_gallery_manifest.js` and shows the latest ten sprite sheets from
`Final Sprite Sheets/` in the thumbnail picker. It also populates Game,
Character, and Animation selectors from the full `GameName/CharacterName`
folder structure. The manifest skips final `frames/` folders so the gallery
stays sheet-only.

Refresh the gallery after creating new sheets:

```bash
python tools/build_sprite_gallery_manifest.py
```
