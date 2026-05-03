# Game Integration Guide

Use this after the pipeline creates a cleaned horizontal sprite sheet from
extracted animation frames.

## Output Assumptions

Pipeline outputs are horizontal strips:

- frame width: `256`
- frame height: `256`
- transparent background
- normal video outputs preserve the source canvas scale across animations

For normal video outputs, use the same draw origin or pivot for every animation
of a character. The empty transparent space is intentional; it keeps idle,
attack, and effect-heavy animations from changing apparent zoom.

## Canvas Draw Formula

For a `256 x 256` frame:

```js
const scale = renderWidth / frameWidth;
const drawX = actorPivotX - characterPivotX * scale;
const drawY = actorPivotY - characterPivotY * scale;
```

Then draw the animation at `drawX`, `drawY`, `renderWidth`, `renderHeight`.
Keep `characterPivotX` and `characterPivotY` constant for every animation of
the same character.

If a sheet was intentionally exported with `--layout-mode fit-foreground`, then
use the legacy guide values instead:

```js
const spriteGroundY = 220;
const spriteGroundRatio = spriteGroundY / frameHeight;
const drawX = actorCenterX - renderWidth / 2;
const drawY = actorFeetY - renderHeight * spriteGroundRatio;
```

## Frame Count And FPS

Cycle duration is:

```text
durationSeconds = frameCount / fps
```

If extraction changes the frame count but FPS stays the same, the visual cycle
changes speed.

Example:

```text
12 frames at 16 fps = 0.75s
10 frames at 16 fps = 0.625s
```

To preserve the old duration after changing frame count:

```text
newFps = newFrameCount / oldDurationSeconds
```

## Promotion Checklist

Before copying an output into a game:

- Preview the sheet and any animation preview you generate from it.
- Confirm the JSON report `status` is `pass`.
- Review duplicate-frame warnings.
- Review motion-pop warnings.
- Check that every animation uses the same apparent character scale.
- Update animation `frameWidth`, `frameHeight`, `frameCount`, and `fps`.
- Update cache-busting query strings if the game uses them.
- Update special frame logic if gameplay depends on frame numbers.

## Frame Meaning

Video extraction makes frame selection explicit. If the game maps gameplay state
to particular frame numbers, write down the new meaning before promotion.

For example, a jump sheet might reserve:

- early frames for crouch and liftoff
- middle frames for rising, apex, and falling
- final frames for landing and recovery

Keep those mappings in sync with the final promoted sheet.
