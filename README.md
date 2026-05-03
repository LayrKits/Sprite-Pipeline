# Sprite Sheet Pipeline

Reusable video-to-sprite-sheet pipeline for turning ordered animation frames into
clean horizontal `256 x 256` sprite strips.

This repo includes reusable workflow docs, processing tools, a static viewer,
and a generic AI-assistant skill. It intentionally excludes generated assets,
videos, scratch outputs, demo sheets, and project-specific art.

## Quick Start

1. If using an AI assistant, give it
   `skills/sprite-sheet-pipeline/SKILL.md` or install that folder in the
   assistant's skill system. Ask it to use the `sprite-sheet-pipeline` skill.
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
3. To create source footage, use:
   - `docs/reference/PROMPTING_IMAGE_MODELS.md` for first poses, character
     references, and transition frames.
   - `docs/reference/PROMPTING_VIDEO_MODELS.md` for Kling or other
     image-to-video prompts.
4. To process footage, follow `docs/QUICKSTART.md`: extract frames, matte if
   needed, build the sprite sheet, review the preview/report, and promote only
   approved outputs.
5. After promotion, run:

   ```bash
   python tools/build_sprite_gallery_manifest.py
   ```

6. Open `sprite_viewer.html` directly in a browser to inspect final sheets.

## Included

- `tools/`: frame extraction, matting, cleanup/repack, contact sheet, resize, and
  viewer manifest utilities.
- `docs/`: active workflow notes, quickstart, folder conventions, extraction
  notes, and game integration guidance.
- `docs/reference/`: text-only image/video prompting references for creating
  clean animation source footage when needed.
- `skills/sprite-sheet-pipeline/`: generic AI-assistant skill that routes
  image prompting, video prompting, processing, validation, and promotion tasks
  to the right docs.
- `sprite_viewer.html`: static browser viewer for horizontal sprite sheets.
- `sprite_gallery_manifest.js`: empty starter manifest for the viewer.
- `sprite_gallery_pins.json`: empty starter pin list for the viewer.
- Empty `Videos/`, `work/`, `Final Sprite Sheets/`, and `Cleanup/` folders with
  `.gitkeep` files so the repo starts with the expected shape.

## Basic Flow

1. Put source animation videos in `Videos/` or `Videos/To Be Processed/`.
2. Extract ordered frames into `work/extracted/<character>/<action>/`.
3. Matte light backgrounds into `work/matted/<character>/<action>/` when needed.
4. Build a sprite strip with `tools/animation_pipeline.py`.
5. Review the preview image and JSON report.
6. Promote only approved sheets and matching cells into
   `Final Sprite Sheets/<GameName>/<CharacterName>/<animation>/`.
7. Run `python tools/build_sprite_gallery_manifest.py`.
8. Open `sprite_viewer.html` directly in a browser.

See `docs/QUICKSTART.md` for copy-paste commands.

## Asset Policy

Keep generated materials out of this repo unless they are tiny, intentional,
text-documented references that are required to explain or test pipeline
behavior. Normal source videos, extracted frames, matted frames, previews,
reports, final sheets, and game/demo art should stay ignored by default.
