# Vertical Frame Alignment Workflow

This is a separate, self-contained workflow for vertical-only alignment tests.
It does not modify the existing sprite pipeline, viewer, final sheets, or
project instructions.

## Research Summary

2D game engines describe frame registration with slightly different terms, but
the same concept shows up across tools:

- Unity calls the sprite pivot the coordinate origin and main anchor point of a
  sprite. Its sprite editor also supports custom pivot locations for sliced
  frames.
- Godot `AnimatedSprite2D` exposes `centered` and `offset`, which means the
  texture's drawn position can be controlled independently from the node.
- Phaser calls this point an origin, also described as an anchor or pivot point,
  and uses it for placement and rotation.
- Aseprite's onion skinning workflow shows several frames at once so a frame can
  be compared against neighboring frames while drawing or adjusting it.

For a hand-built or model-generated sprite sheet, the practical alignment rule
is:

1. Choose a stable registration point for the animation.
2. Keep that point in the same pixel position in every frame.
3. Validate with an onion-skin style overlay, plus guide lines for frame center,
   ground, and the chosen registration point.

For the current Hero jump sheet, the requested operation is vertical-only. The
workflow therefore preserves every frame's horizontal position and only shifts
frames up or down so an estimated waist/core row matches the first frame.

## Method

The script:

1. Copies the source sheet into the run folder first.
2. Splits the copied sheet into fixed-size cells.
3. Finds the first frame's ground line from the bottom of its alpha bounds.
4. Estimates each frame's waist/core row by scanning a central x-window and
   finding the densest row band in the middle of the sprite's alpha bounds.
5. Shifts each frame vertically so that row lands on the first frame's waist row.
6. Reviews the aligned frames for small local baseline errors: if a
   grounded-looking frame sits a few pixels above or below both neighboring
   contact frames, it is nudged vertically within the configured safety limit.
   Airborne frames are ignored.
7. Writes a new aligned sheet, before/after overlays, a comparison preview, a
   JSON report, and a local review HTML page.

The shadow overlay is the validation layer. If the after-overlay has a much
tighter waist-line cluster without top/bottom clipping, the vertical alignment
worked. If a frame uses an unusual pose, the report exposes the detected row and
shift so it can be manually adjusted later.

## Usage

```bash
./.venv/bin/python isolated_workflows/vertical_frame_alignment/vertical_align_sheet.py \
  --input "Final Sprite Sheets/TerschaTD/Hero/jump/sheets/Hero_jump_24f_256.png" \
  --output-dir "isolated_workflows/vertical_frame_alignment/runs/Hero_jump_24f_256" \
  --cell-width 256 \
  --cell-height 256
```

The output sheet is a copy-derived artifact named:

```text
isolated_workflows/vertical_frame_alignment/runs/Hero_jump_24f_256/Hero_jump_24f_256.vertical_aligned.png
```

## Ask Whether Alignment Is Needed

Use this diagnostic before fixing a sheet. It does not change pixels; it copies
the source into the run folder and emits a verdict, metric graph, source overlay,
contact-frame contact sheet, and strict-waist-lock risk overlay.

By default, the diagnostic prints a compact JSON answer for the agent and does
not write an HTML/image report:

```bash
./.venv/bin/python isolated_workflows/vertical_frame_alignment/assess_vertical_alignment_need.py \
  --input "Final Sprite Sheets/TerschaTD/Hero/jump/sheets/Hero_jump_24f_256.png"
```

To request the full visual report, add `--write-report` and `--output-dir`:

```bash
./.venv/bin/python isolated_workflows/vertical_frame_alignment/assess_vertical_alignment_need.py \
  --input "Final Sprite Sheets/TerschaTD/Hero/jump/sheets/Hero_jump_24f_256.png" \
  --output-dir "isolated_workflows/vertical_frame_alignment/runs/Hero_jump_24f_256_assessment" \
  --write-report
```

The main answer is in:

```text
vertical_alignment_assessment.json
vertical_alignment_assessment.html
```

## Automatic Workflow

For normal use, run the orchestrator. It always assesses first. If the verdict is
`yes_likely` or `yes_but_constrained`, it then runs candidate alignment. If the
verdict is `probably_no`, `probably_no_or_minor`, or `review_manually`, it skips
alignment and prints that decision.

```bash
./.venv/bin/python isolated_workflows/vertical_frame_alignment/run_vertical_alignment_workflow.py \
  --input "Final Sprite Sheets/TerschaTD/Hero/jump/sheets/Hero_jump_24f_256.png" \
  --output-dir "isolated_workflows/vertical_frame_alignment/runs/Hero_jump_24f_256_workflow"
```

The orchestrator's stdout is the main output for the AI. Visual reports are
supporting artifacts and should be opened only when requested or when manual
validation is needed.

When stdout reports `needs_vertical_alignment: true`, the orchestrator also
returns a `confirmation_gate` with `status: pending_user_confirmation` and a
`validation_viewer` path. In normal use, open that review through the
server-hosted sprite viewer so the navigation and manual frame-save controls are
available. Present the candidates to the user, and do not promote an aligned
sheet until the user explicitly confirms it. Treat this review page as the
alignment approval gate every time the workflow runs, not only when the
automatic recommendation is rejected. Ask the user to pick the candidate and
call out any remaining fixes. Each method should be visible as a playing
animation with guide lines. Candidate generation writes an immutable method
candidate set under `candidates/` and a separate editable set under
`working_copies/`. Manual frame nudges save only into the working copy. Restore
from candidate replaces the working copy with the immutable candidate and resets
the offset report. Finalize opens the current working copy in the sprite viewer.
Attempt automatic cleanup aligns the selected method's detected frame bottoms to
the fixed ground guide line and saves that result into the working copy, so it
can be reviewed or restored without changing the immutable candidate.
If fixes are requested, make them as an explicit new candidate, use the hosted
review's manual per-frame save flow, or rerun the alignment workflow, then
return to this same candidate review gate. Do not add a second review stage for
minor frame nudges.

By default, the automatic workflow recommends the lowest-scoring candidate that
passes floor and canvas validation. Use `--recommendation-policy cleanest_valid`
when you want a more conservative candidate with no warning flags to be surfaced
as the recommendation instead.

Candidate generation also performs a contact-baseline pass before writing
reports. This catches small frame-level floats or floor sinks that are easy to
miss in aggregate metrics, such as one crouch/contact frame sitting a few pixels
above or below its neighbors.

## Sources

- Unity Manual: Sprite Editor, pivot as coordinate origin/main anchor point:
  https://docs.unity.cn/Manual/sprite-editor-use.html
- Unity Manual: Automatic slicing, default and custom pivots:
  https://docs.unity.cn/Manual/sprite-automatic-slicing.html
- Godot `AnimatedSprite2D`, centered and offset properties:
  https://docs.godotengine.org/en/4.4/classes/class_animatedsprite2d.html
- Phaser Origin Component:
  https://docs.phaser.io/phaser/concepts/gameobjects/components
- Aseprite Onion Skinning:
  https://aseprite.com/docs/onion-skinning/
