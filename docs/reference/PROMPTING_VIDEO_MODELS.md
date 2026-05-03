# Prompting Video Models

Use this reference when animating an image-model pose into source footage for frame extraction. The output is controlled sprite-pipeline footage, not cinematic video.

Kling is the main target, but the same constraints apply to other image-to-video models.

## Core Prompt Rules

Use the image-model result as the first frame. The video prompt must be strict and mechanical.

Always include:

- use uploaded image as exact first frame
- preserve exact character design, outfit, proportions, weapon, silhouette, and 2D art style
- locked camera
- no zoom, no pan, no rotation, no cuts
- character always centered in frame
- full body, weapon, and all motion fully inside the frame at all times
- no horizontal travel across the screen
- maintain flat chroma green background `#00FF00` with no variation
- no shadows on the ground or background
- no lighting changes or gradients
- no motion blur

Kling tends to drift toward cinematic motion, interpolation shortcuts, and pretty effects. Pull it back toward deterministic motion, sprite readability, and clean frame extraction.

## Animation Constraints

Require motion readable in approximately 12-24 frames:

- each phase is clearly visible: anticipation, action, follow-through, recovery
- no frame skipping
- no pose snapping
- no teleporting between poses
- each frame shows visible progression from the previous frame
- motion stays compact and contained within the frame

Always describe the animation as a step-by-step mechanical sequence, not as a vague action.

Bad:

```text
fast overhead sword slash
```

Good:

```text
Use the uploaded image as the exact first frame. Slight weight shift. Arms raise weapon overhead. Brief anticipation pause. Forward step. Downward strike. Follow-through. Return to ready stance.
```

If using a transition frame, reference the uploaded image as the starting pose rather than saying "start from idle stance".

## Character Control Constraints

Always include:

- do not change anatomy or proportions
- do not add or remove limbs
- do not duplicate weapons or hands
- do not warp hands or fingers
- do not change costume or accessories
- weapon remains consistent in position, ownership, and orientation unless switching hands is intentional

## Style Constraints

Always include:

- maintain 2D sprite readability
- prioritize clear silhouette over realism
- avoid cinematic effects
- avoid depth of field
- avoid particle spam that obscures the character

Non-vertical effects are usually safer than vertical effects. A magic trail during an attack is less likely to cause character drift than landing dust or takeoff wind.

For vertical animations like jump, fall, and landing, generate clean body motion first. Add landing dust, takeoff wind, or other vertical effects separately as their own overlay/effect animation.

## Video Prompt Template

```text
Use the uploaded image as the exact first frame.

Preserve the exact character design, outfit, proportions, weapon, silhouette, and 2D art style. Locked camera. No zoom, no pan, no rotation, no cuts, no camera shake. Character remains centered in frame. Full body, full weapon, hair, cape, cloth, and all motion stay fully inside the frame at all times. No horizontal travel across the screen.

Maintain a flat exact chroma green background: #00FF00, RGB 0,255,0. No background variation, no gradients, no floor, no shadows, no lighting changes, no motion blur.

Animation sequence:
1. [anticipation step]
2. [main action step]
3. [follow-through step]
4. [recovery or return-to-ready step]

Motion must be readable in approximately 12-24 frames. Each frame should show clear progression from the previous frame. No frame skipping, no pose snapping, no teleporting.

Do not change anatomy or proportions. Do not add or remove limbs. Do not duplicate weapons or hands. Do not warp hands or fingers. Do not change costume or accessories. Keep the weapon consistent.

Maintain 2D sprite readability and a clean silhouette. Avoid cinematic effects, depth of field, particle spam, extra props, text, watermark, and extra characters.
```

## Final Frame And Bridge Frames

Using the same image as both first and final video frame can occasionally produce a still video. If that happens, skip the final-frame input and choose a good ending frame from the generated video instead.

If the final pose is good but does not connect well back to idle or into the next animation, use image generation to create one or a few bridge frames. This is often cheaper than rerunning video.

## Review Before Extraction

Reject or rerun footage when the camera moves, the character travels across the screen, the green background changes, shadows appear, the weapon leaves frame, anatomy changes, hands duplicate, motion snaps, or effects obscure the silhouette.

Prefer compact, readable motion over dramatic motion. The video is source material for a sprite pipeline.
