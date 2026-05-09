# Horizontal Frame Alignment Workflow

This is a separate, self-contained workflow for horizontal-only alignment tests.
It does not modify the existing sprite pipeline, vertical alignment workflow,
viewer, final sheets, or project instructions.

## Purpose

Use this workflow when a sheet appears to jitter, pop, or drift left/right even
though its vertical placement is acceptable. It is meant for copy-derived review
artifacts, not direct promotion.

The workflow preserves every frame's vertical position and only shifts frames
left or right. It estimates a stable `core/energy` column by scanning alpha
pixels through the middle vertical band of each cell, then compares that column
across frames.

For effects and attacks, review the result carefully. Some lateral travel can
be intentional animation, not a problem to erase.

## Ask Whether Alignment Is Needed

By default, the diagnostic prints compact JSON for the agent and does not write
an HTML/image report:

```bash
./.venv/bin/python isolated_workflows/horizontal_frame_alignment/assess_horizontal_alignment_need.py \
  --input "Final Sprite Sheets/TerschaTD/Wind Mage/wind_blade_effect_fresh/sheets/Wind_Mage_wind_blade_effect_fresh_24f_256.png"
```

To request the full visual report, add `--write-report` and `--output-dir`:

```bash
./.venv/bin/python isolated_workflows/horizontal_frame_alignment/assess_horizontal_alignment_need.py \
  --input "Final Sprite Sheets/TerschaTD/Wind Mage/wind_blade_effect_fresh/sheets/Wind_Mage_wind_blade_effect_fresh_24f_256.png" \
  --output-dir "isolated_workflows/horizontal_frame_alignment/runs/Wind_Mage_wind_blade_effect_fresh_24f_256_assessment" \
  --write-report
```

The main report files are:

```text
horizontal_alignment_assessment.json
horizontal_alignment_assessment.html
```

## Automatic Workflow

For normal use, run the orchestrator. It always assesses first. If the verdict is
`yes_likely` or `yes_but_constrained`, it then writes horizontal alignment
candidates. If the verdict is `probably_no` or `review_manually`, it skips
alignment and prints that decision.

```bash
./.venv/bin/python isolated_workflows/horizontal_frame_alignment/run_horizontal_alignment_workflow.py \
  --input "Final Sprite Sheets/TerschaTD/Wind Mage/wind_blade_effect_fresh/sheets/Wind_Mage_wind_blade_effect_fresh_24f_256.png" \
  --output-dir "isolated_workflows/horizontal_frame_alignment/runs/Wind_Mage_wind_blade_effect_fresh_24f_256_workflow" \
  --write-assessment-report
```

When stdout reports `needs_horizontal_alignment: true`, the orchestrator also
returns a `confirmation_gate` with `status: pending_user_confirmation` and a
`validation_viewer` path. Open that candidate review before promotion and ask
the user to approve a candidate.

Candidate generation writes immutable method candidates under `candidates/` and
matching editable copies under `working_copies/`. Manual offsets in this
workflow are horizontal `dx` offsets. Do not overwrite the original sheet; promote
an approved aligned result as a new variant unless explicitly told otherwise.

## Candidate Modes

The default candidate set is:

- `strict_core`: shifts every frame so the detected core column matches frame 1.
- `core_edge_clamped`: uses the same target but clamps shifts to avoid
  left/right canvas clipping.
- `capped_8`, `capped_12`, `capped_24`: limits per-frame horizontal shift.
- `blend_50`, `blend_35`: applies a partial correction for more conservative
  motion preservation.

By default, the automatic workflow recommends the lowest-scoring valid
candidate. Use `--recommendation-policy cleanest_valid` when you want a
candidate with no warning flags to be surfaced first.

## Output Review

The candidate review page shows:

- an animated loop for every candidate
- an onion-skin overlay with frame center and target core guides
- per-candidate shift warnings
- a frame sheet for still inspection

Accept a candidate only if it fixes unwanted lateral jitter without clipping,
changing vertical placement, or removing intentional attack/effect travel.
