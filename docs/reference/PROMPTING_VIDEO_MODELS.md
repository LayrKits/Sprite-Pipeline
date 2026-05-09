# Prompting Video Models

Use this reference for image-to-video prompts that become sprite-sheet source
footage. The output is controlled 2D game animation, not cinematic video.

## Budget Contract

For Seedance and other 3000-character prompt fields, split the prompt into:

- control block: 2500 characters or less, including labels and newlines
- motion block: 500 characters or less, including its label

The control block carries reusable rules: exact first frame, production context,
registration anchor, camera, background, identity, framing, and failures. The
motion block only describes the visible action.

If over budget, cut motion detail and long identity lists before cutting the
registration, camera, background, or edge-framing rules.

## Core Rules

Always include:

- uploaded image is the exact first frame
- footage is for 2D game animation, not cinematic video
- game engine handles movement; video shows pose animation only
- fixed invisible registration anchor, usually belt, pelvis, torso core, chest
  core, or root of body mass
- anchor stays locked to the same screen-space point every frame
- model must not center on weapons, cloth, hair, effects, hands, feet, or bbox
  extremes
- locked camera and same on-screen size
- flat exact chroma matte background, usually `#00FF00`
- full body, weapons, cloth, hair, and effects inside frame
- identity, outfit, anatomy, equipment, silhouette, and 2D style preserved
- direct "do not" failure conditions

## Template

Copy this full prompt and replace bracketed placeholders. The first block must
stay at or below 2500 characters. The motion block must stay at or below 500.

```text
<control>
Generate a [DURATION]s image-to-video animation from the uploaded [SUBJECT] image. Use it as the exact first frame. [FINAL_FRAME_RULE]

This is 2D game sprite footage, not cinematic video. The game engine handles movement, so animate pose changes only. [ACTION_CONTEXT]

Fixed registration: choose [CORE_ANCHOR] in the first frame as an invisible anchor. Keep that exact body point locked to [TARGET_POSITION] for every frame, like onion-skin frames with the core lined up. The body may squash, stretch, bend, and pose around this fixed point, but the whole character must not slide, drift, rise, fall, or recenter. Do not center on [PROP_OR_EXTREMES], hair, cloth, cape, effects, hands, feet, or silhouette extremes. Do not draw guides, markers, grids, or anchor points.

Locked camera. No zoom, pan, rotation, cuts, shake, dolly, parallax, tracking, depth drift, scale change, or apparent camera movement. Same on-screen size.

Background: flat chroma matte only, a pure color plate, not a room, floor, sky, wall, or environment. Every uncovered background pixel remains exact [KEY_HEX]. No gradients, texture, noise, shadows, floor, glow, dust, lighting shifts, or moving background pixels.

Preserve exact [CHARACTER_IDENTITY]. Preserve [ART_STYLE]. Keep original facing direction: [FACING_DIRECTION]. Do not rotate, yaw, flip, mirror, or turn toward/away from camera.

Keep [VISIBLE_PARTS] fully inside frame with [SAFETY_MARGIN]. Nothing touches any edge. [ACTION_FRAMING_LIMITS]

Do not crop [CROP_RISKS]. Do not move the character around the canvas. Do not change the background. No floor, shadows, dust, text, props, extra characters, motion blur, glowing eyes, warped hands, missing limbs, extra fingers, duplicated hands or weapons, broken equipment, redesign, camera motion, or scale drift. [ACTION_FAILURES]
</control>

<motion>
[MOTION_DESCRIPTION_IN_500_CHARS_OR_LESS]
</motion>
```

## Example

Control block:

```text
<control>
Generate a 5s image-to-video animation from the uploaded monk warrior green-screen image. Use it as the exact first frame. Final frame returns to standing guard.

This is 2D game sprite footage, not cinematic video. The game engine handles movement, so animate pose changes only. Make a contained low hop, not a high jump.

Fixed registration: choose the belt / pelvis / torso-core point in the first frame as an invisible anchor. Keep that exact body point locked to the exact frame center for every frame, like onion-skin frames with the core lined up. The body may squash, stretch, bend, and pose around this fixed point, but the whole character must not slide, drift, rise, fall, or recenter. Do not center on the quarterstaff, scarf, sash, cloth tips, hands, feet, or silhouette extremes. Do not draw guides, markers, grids, or anchor points.

Locked camera. No zoom, pan, rotation, cuts, shake, dolly, parallax, tracking, depth drift, scale change, or apparent camera movement. Same on-screen size.

Background: flat chroma matte only, a pure color plate, not a room, floor, sky, wall, or environment. Every uncovered background pixel remains exact #00FF00. No gradients, texture, noise, shadows, floor, glow, dust, lighting shifts, or moving background pixels.

Preserve exact monk warrior: bald head, black beard, stern face, muscular body, shoulder guard, blue scarf, purple sash, navy pants, sandals, wraps, pendant, wooden quarterstaff. Preserve 2D game-art style, thick outlines, flat cel shading, colors, proportions, hands, outfit, and staff design. Keep original three-quarter side-facing direction toward screen right. Do not rotate, yaw, flip, mirror, or turn toward/away from camera.

Keep full body, full quarterstaff, staff tips, fists, fingers, feet, scarf tips, sash tips, and cloth tips fully inside frame with clear green margin. Nothing touches any edge. Free fist never rises above the head. Scarf and sash trail sideways or downward.

Do not crop body, fist, staff, feet, scarf, sash, or cloth. Do not move the character around the canvas. Do not change the background. No floor, shadows, dust, text, props, extra characters, motion blur, glowing eyes, warped hands, missing limbs, extra fingers, duplicated hands or weapons, broken staff, bent staff, redesign, camera motion, or scale drift.
</control>
```

Motion block:

```text
<motion>
0.0-0.7s prepare: knees bend, hips lower, torso leans, staff shifts toward one-hand control. 0.7-1.2s squash crouch, core fixed. 1.2-2.0s low launch pose only: modest stretch, one knee lifts, free arm near chest. 2.0-2.8s contained airborne pose, cloth follows. 2.8-3.4s prepare to land. 3.4-4.3s landing squash, no sliding feet. 4.3-5.0s recover to standing guard, staff two-hand diagonal.
</motion>
```

## Review Before Extraction

Before selecting sprite frames, create a source-timeline contact sheet. Reject or
rerun footage when the camera moves, the registration anchor drifts, the
character travels, the green background changes, shadows appear, important parts
leave frame, anatomy changes, hands duplicate, motion snaps, or the generated
timeline contains repeated phases, early landing poses, reversals, or timing
pockets.
