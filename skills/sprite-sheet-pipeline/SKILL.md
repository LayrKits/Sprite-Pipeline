---
name: sprite-sheet-pipeline
description: Guide an AI assistant through this repo's 2D animation sprite-sheet workflow. Use when creating animation-safe character image prompts, writing image-to-video prompts, extracting frames from animation videos, matting backgrounds, building and validating horizontal 256 x 256 sprite sheets, promoting final outputs, or explaining game integration.
---

# Sprite Sheet Pipeline Skill

Use this skill as a routing guide for the repo. Keep detailed rules in the
project docs; read only the document needed for the current task.

## Start Here

- Repo overview and folder map: `README.md`
- Copy-paste processing commands: `docs/QUICKSTART.md`
- Folder roles and cleanup rules: `docs/WORKSPACE_CONVENTIONS.md`
- Active pipeline contract and validation rules: `docs/ANIMATION_PIPELINE_NOTES.md`
- Frame extraction details: `docs/FRAME_EXTRACTION.md`
- Game-side usage assumptions: `docs/INTEGRATION_GUIDE.md`

## Prompting Tasks

For a new character image, first pose, character reference, or transition frame,
read `docs/reference/PROMPTING_IMAGE_MODELS.md`.

Default image-prompt goal:

- one full-body 2D game character
- animation-safe margins
- full weapon, hair, cape, cloth, and effects visible
- centered character
- flat exact `#00FF00` background
- no shadow, floor, text, watermark, border, props, or background objects

For image-to-video, Kling, or source-footage animation prompts, read
`docs/reference/PROMPTING_VIDEO_MODELS.md`.

Default video-prompt goal:

- uploaded image is the exact first frame
- footage is for 2D game animation, not cinematic video
- define an invisible core registration anchor, usually belt/pelvis/torso core
- keep that body anchor locked to the same screen-space point
- do not let the model center on weapon, cloth, hair, effects, or bounding-box extremes
- locked camera with no zoom, pan, rotation, cuts, or shake
- character remains registered/centered with all motion inside frame
- no horizontal screen travel
- flat exact `#00FF00` background with no variation
- timestamped step-by-step visible motion
- preserve character design, anatomy, proportions, weapon, and 2D style

For image-to-video jobs, use the context-engineered prompt pattern in
`docs/reference/PROMPTING_VIDEO_MODELS.md`: task, production context, subject
scope, fixed registration rule, chroma matte rule, locked camera rule,
character preservation, facing/framing rules, timestamped timeline, and failure
conditions. Keep the reusable non-motion control block at 2500 characters or
less and the motion description at 500 characters or less, including labels.

Return one copy-paste prompt by default. Include avoid/negative constraints
inside that prompt unless the target tool explicitly has a separate negative
prompt field.

## Processing Tasks

Use the current frame-directory workflow. The source of truth is an animation
video or ordered frame folder, not a generated grid sheet.

Normal processing order:

1. Put one source animation video in `Videos/` or `Videos/To Be Processed/`.
2. Extract ordered PNG frames into `work/extracted/<character>/<action>/`.
3. Matte light/off-white backgrounds into `work/matted/<character>/<action>/`
   when needed.
4. Build a horizontal `256 x 256` sprite strip with
   `tools/animation_pipeline.py`.
5. Review the preview PNG, individual cleaned frames, and JSON report.
6. Promote only approved sheets and matching cell frames into
   `Final Sprite Sheets/<GameName>/<CharacterName>/<animation>/`.
7. Refresh `sprite_gallery_manifest.js`.
8. Open `sprite_viewer.html` to inspect final sheets.

Use `--layout-mode preserve-canvas` for normal video-derived animations. Use
`--layout-mode fit-foreground` only for legacy recovery or an explicitly
foreground-normalized export.

## Validation And Promotion

Do not promote raw extracted frames. Promote only cleaned pipeline outputs.

Before promotion, verify:

- output sheet is exactly `frames * 256` by `256`
- report status is `pass`
- warnings have been visually reviewed
- no important source or final pixels are clipped
- preview order and timing feel correct
- apparent character scale stays consistent across animations
- final sheet and individual cell frames match exactly

After approval, move the source video to `Videos/Processed/` and move
non-promoted generated artifacts for that pass into `Cleanup/`.
