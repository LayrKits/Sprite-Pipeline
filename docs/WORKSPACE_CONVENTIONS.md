# Workspace Conventions

Use these folders for the video-to-sprite-sheet workflow:

- `Videos/`: source animation videos. Keep originals here.
- `work/extracted/<character>/<action>/`: frame images extracted from one video
  animation, plus the extraction report.
- `work/matted/<character>/<action>/`: transparent PNGs produced by the light
  background matte or a future matting package.
- `work/frames/<character>/<action>_<frame-count>f_256/`: individual frames written by the
  cleanup pipeline.
- `work/previews/`: checker/guide preview sheets for inspection.
- `work/reports/`: JSON validation reports.
- `Final Sprite Sheets/<GameName>/<CharacterName>/<animation>/sheets/`:
  promoted sprite sheets ready for game integration.
- `Final Sprite Sheets/<GameName>/<CharacterName>/<animation>/frames/`:
  individual `256 x 256` PNG cells used by the promoted sheets.
- `Videos/Processed/`: original videos after their approved sprites are
  promoted.
- `Cleanup/`: old scratch outputs, rejected experiments, and non-promoted
  generated artifacts. This folder is ignored by git.
- `archive/legacy-sheet-and-generation-workflow/`: preserved old prompt/grid
  workflow.

The `work/` folder is scratch output. The durable deliverables are the source
videos in `Videos/Processed/`, promoted final sprite sheets, and the individual
frame cells that exactly match those promoted sheets. Once an animation is
approved, move every other generated artifact for that pass into `Cleanup/`.
