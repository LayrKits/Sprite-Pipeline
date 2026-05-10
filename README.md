# Game-Art Sprite Sheet Kit

Turn AI-generated character motion into reviewable `256 x 256` sprite sheets:
extract frames, matte and clean them, build horizontal strips, inspect them in a
browser viewer, and promote only approved outputs.

This repo is a practical production kit for indie game devs and AI art builders
who have rough generated animation and need assets they can actually evaluate in
a game workflow. It includes prompting references, FFmpeg frame extraction,
cleanup/repack tools, validation reports, a browser viewer, and an AI-assistant
skill for guided runs.

It intentionally excludes generated assets, videos, scratch outputs, demo
sheets, and project-specific art.

> Note for AI agents: this README is written for human readers. For the
> operational workflow, start with `AGENTS.md`, then
> `docs/ANIMATION_PIPELINE_NOTES.md`.

## What It Does

- Starts from AI-generated motion, Kling clips, or other source animation
  videos.
- Extracts ordered PNG frames with an FFmpeg wrapper.
- Removes light or flat chroma backgrounds when needed.
- Packs frames into transparent `256 x 256` cells while preserving the source
  video canvas, so character scale and empty space stay consistent across
  animations.
- Writes a horizontal sprite strip, matching individual frame cells, a preview
  image, and a JSON validation report.
- Lets you inspect generated and final sheets in a browser viewer before
  promotion.

The core before/after is simple: rough character motion in, reviewable game-art
sprite strip out.

## Quick Start

1. Put source animation videos in `Videos/` or `Videos/To Be Processed/`.
2. Set up Python dependencies:

   ```bash
   python3 -m venv .venv
   ./.venv/bin/python -m pip install -r requirements.txt
   ```

   FFmpeg is not installed by `requirements.txt`; install it separately so
   `tools/extract_frames_ffmpeg.py` can call the `ffmpeg` command:

   ```bash
   # macOS
   brew install ffmpeg

   # Windows, with winget
   winget install Gyan.FFmpeg

   # Ubuntu/Debian Linux
   sudo apt install ffmpeg
   ```
3. To create or refine source footage, use:
   - `docs/reference/PROMPTING_IMAGE_MODELS.md` for first poses, character
     references, and transition frames.
   - `docs/reference/PROMPTING_VIDEO_MODELS.md` for Kling or other
     image-to-video prompts.
4. To process footage, follow `docs/QUICKSTART.md`: extract frames, matte if
   needed, build the sprite sheet, review the preview/report, open the viewer,
   and promote only approved outputs.
5. After processing, run the viewer server:

   ```bash
   node tools/serve_sprite_viewer.mjs
   ```

6. Open the printed local URL in a browser to inspect the generated sheet or
   promoted final sheets. Assistants should also return a Markdown link to the
   exact review URL, such as `[open sprite viewer](http://127.0.0.1:8000/...)`
   or `[open alignment review](http://127.0.0.1:8000/alignment-review?path=...)`,
   so Codex shows the Web preview card with an `Open` button.
7. If using an AI assistant, give it
   `skills/sprite-sheet-pipeline/SKILL.md` or install that folder in the
   assistant's skill system. Ask it to use the `sprite-sheet-pipeline` skill.

## Included

- `tools/`: frame extraction, matting, cleanup/repack, contact sheet, resize, and
  viewer manifest utilities.
- `docs/`: active workflow notes, quickstart, folder conventions, extraction
  notes, and game integration guidance.
- `docs/reference/`: text-only image/video prompting references for creating
  clean animation source footage when needed.
- `skills/sprite-sheet-pipeline/`: AI-assistant skill that routes image
  prompting, video prompting, processing, validation, and promotion tasks to the
  right docs.
- `sprite_viewer.html`: browser viewer for horizontal sprite sheets.
- `tools/serve_sprite_viewer.mjs`: local server for live sheet scanning,
  direct work-in-progress sheet review, and alignment candidate review pages.
- `sprite_gallery_manifest.js`: empty starter manifest for the viewer.
- `sprite_gallery_pins.json`: empty starter pin list for the viewer.
- Empty `Videos/`, `work/`, `Final Sprite Sheets/`, and `Cleanup/` folders with
  `.gitkeep` files so the repo starts with the expected shape.

## Basic Flow

1. Put source animation videos in `Videos/` or `Videos/To Be Processed/`.
2. Extract ordered frames into `work/extracted/<character>/<action>/`.
3. Matte light backgrounds into `work/matted/<character>/<action>/` when needed.
4. Build a sprite strip with `tools/animation_pipeline.py`. Default to 24
   frames when no frame count is specified.
5. Review the preview image and JSON report.
6. Run `node tools/serve_sprite_viewer.mjs` and inspect the generated sheet in a
   browser.
7. Promote only approved sheets and matching cells into
   `Final Sprite Sheets/<GameName>/<CharacterName>/<animation>/`.

See `docs/QUICKSTART.md` for copy-paste commands.

## Asset Policy

Keep generated materials out of this repo unless they are tiny, intentional,
text-documented references that are required to explain or test pipeline
behavior. Normal source videos, extracted frames, matted frames, previews,
reports, final sheets, and game/demo art should stay ignored by default.
