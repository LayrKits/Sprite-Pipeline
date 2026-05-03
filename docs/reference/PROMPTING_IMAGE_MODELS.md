# Prompting Image Models

Use this reference when creating the first animation-safe pose, a character reference image, or a transition frame before video generation. The first pose becomes the first frame of the animation source footage.

This workflow has been tested with GPT Image 2 and Nano Banana 2, but the rules apply to any image model used before the sprite pipeline.

## First Pose Contract

Create one full-body character image on exact chroma green:

- Hex: `#00FF00`
- RGB: `0,255,0`

The green background must be perfectly flat. Require no shadows, no floor, no gradients, no props, no lighting falloff, and no background objects.

The character design must not use this green anywhere, including clothing, gems, magic, outlines, antialiasing, or glow.

Frame the character for animation, not as a portrait:

- full body visible from head to feet
- full weapon, cape, hair, and loose cloth visible
- no cropping
- character centered in frame
- generous empty margin on all sides
- no part of the character enters the outer 20-30% border area
- for idle/game animation, character height is roughly 40-50% of the canvas unless a larger scale is intentional

Video models often animate wider than the first pose suggests. If a weapon, cape, hand, foot, hair, or effect starts near an edge, it may leave the frame during motion.

## Transition Frames

For non-idle animations, prefer creating a transition pose with the image model before using the video model.

Give the image model the base character reference or idle frame, then ask for the first frame of the new animation as a small transition away from idle. Do not ask for the most extreme action pose first. This helps attack, run, jump, and magic animations flow naturally out of idle and avoids spending video-model seconds on idle.

Use bridge frames when a final pose is good but does not connect well back to idle or into the next animation. Creating one or a few image-model bridge frames is often cheaper than rerunning video.

## Prompt Requirements

Always specify:

- one character only
- full-body 2D game character
- exact starting pose
- camera/view angle
- character centered in frame
- animation-safe margins
- full weapon/effects visible
- clean readable silhouette
- stable design with clear separated limbs
- flat `#00FF00` background only
- no text, watermark, border, shadow, floor, props, or extra effects

## First Pose Prompt Template

```text
Create one full-body 2D game character image for sprite animation source footage.

Character: [describe character, outfit, weapon, proportions, style].
Pose: [exact starting pose].
Camera/view: [side view, 3/4 side view, front view, etc.].

Requirements:
- one character only
- full body visible from head to feet
- full weapon, hair, cape, loose cloth, and accessories visible
- character centered in frame
- generous animation-safe empty margin on all sides
- no part of the character enters the outer 20-30% border area
- character occupies roughly 40-50% of canvas height
- clean readable silhouette with separated limbs
- stable design and proportions
- flat exact chroma green background only: #00FF00, RGB 0,255,0
- do not use #00FF00 anywhere on the character

Do not include text, watermark, border, floor, shadow, props, lighting falloff, gradients, background objects, extra characters, or extra effects.
```

## Transition Frame Prompt Template

```text
Use the uploaded character reference as the exact design reference.

Create the first transition frame for a [animation name] animation. Keep the character centered, keep the same camera angle, keep the same scale, keep the same flat #00FF00 background, and preserve the same generous margins.

The pose should be a small transition away from idle toward [describe action], not the most extreme action pose.

Preserve exact character design, outfit, proportions, weapon, silhouette, and 2D art style. Full body and full weapon must remain visible. No cropping. No text, watermark, border, shadow, floor, props, gradients, or extra effects.
```

## Verification

After generation, verify that the background is exact `#00FF00`. If the model creates a soft green gradient or near-green pixels, flatten the border-connected background to exact `#00FF00` before using it for video animation.

Reject or fix any pose with cropped limbs, cropped weapons, portrait framing, shadows, non-flat background, green on the character, extra props, extra characters, or important pixels near the edge.
