---
name: runware-api
description: Use when making, reviewing, debugging, or scripting Runware API requests. Follow Runware's raw REST/WebSocket request shape, authentication, UUID, async polling, error, retry, and model-selection rules.
---

# Runware API Skill

Use this skill when working with Runware requests in this repo. Prefer the
current Runware docs for model-specific parameters, because available models and
capabilities change often.

## Docs To Check

- Platform intro: `https://runware.ai/docs/platform/introduction`
- Authentication: `https://runware.ai/docs/platform/authentication`
- Task polling: `https://runware.ai/docs/platform/task-polling`
- Errors: `https://runware.ai/docs/platform/errors`
- Rate limits: `https://runware.ai/docs/platform/rate-limits`
- Model search: `https://runware.ai/docs/platform/model-search`
- Text to image guide: `https://runware.ai/docs/guides/text-to-image`

## Request Rules

- REST endpoint: `https://api.runware.ai/v1`.
- WebSocket endpoint: `wss://ws-api.runware.ai/v1`.
- Raw API request bodies are always a JSON array of task objects, even for one
  task.
- Authenticate REST calls with `Authorization: Bearer <API_KEY>` whenever
  possible. Payload auth is allowed by docs but avoid embedding keys in saved
  JSON.
- For WebSockets, the first message must be an authentication task containing
  the API key; subsequent messages use the same authenticated connection.
- Every task that accepts `taskUUID` must use a fresh UUID v4. Preserve and log
  the UUID for debugging and async polling.
- Match responses to requests by `taskUUID` and `taskType`; do not assume array
  order is enough.

## Local Helper

This workspace has an ignored local helper at `local/runware_request.py`.

Examples:

```bash
export RUNWARE_API_KEY="..."
python3 local/runware_request.py model-search --search "pixel art" --limit 5
python3 local/runware_request.py text-to-image --prompt "a small airship over a forest"
python3 local/runware_request.py raw request.json
python3 local/runware_request.py poll <taskUUID>
```

The helper prints the full JSON response, retries transient REST/capacity
failures with exponential backoff, exits nonzero when `errors` is present, and
uses only Python standard-library modules.

## Async And Polling

- For long-running operations, set `"deliveryMethod": "async"` when the model
  or workflow supports it.
- Poll with a `getResponse` task:

```json
[
  {
    "taskType": "getResponse",
    "taskUUID": "00000000-0000-4000-8000-000000000000"
  }
]
```

- Use exponential backoff when polling. Start around 1-2 seconds, increase the
  delay, and add an initial delay for predictable long tasks such as video.
- `getResponse` can return `processing`, `success`, or `error`; completed
  generations can appear before the whole task is finished.

## Error And Retry Rules

- Runware errors are returned in an `errors` array. Multiple-task requests can
  have some successful `data` entries and some scoped `errors`.
- Log the full `message` and `taskUUID`; the UUID is important for support.
- Retry only transient failures with exponential backoff: HTTP `429`, HTTP
  `5xx`, and capacity/provider codes such as `timeoutProvider` or
  `providerRateLimitExceeded`.
- Do not blindly retry client errors such as invalid parameters, invalid API
  keys, missing balance, or permission failures.
- Keep normal concurrency around 2-4 requests unless the user has a capacity
  agreement or the current docs say otherwise.

## Image Generation Defaults

For `imageInference` text-to-image work:

- Use `taskType: "imageInference"`.
- Include `model`, `positivePrompt`, `width`, `height`, and a UUID v4
  `taskUUID`.
- Use `runware:101@1` only as a quick FLUX.1 Dev starting point; search or
  inspect model docs when style, cost, speed, or capability matters.
- `negativePrompt` is useful for many diffusion models, but FLUX-style models
  may ignore it.
- Check each model's recommended defaults for dimensions, `steps`, scheduler,
  CFG, and supported extras before assuming parameters are valid.

## Secret Handling

- Never commit API keys, `.env` files, generated request payloads containing
  keys, or downloaded private outputs.
- Prefer `RUNWARE_API_KEY` in the shell environment.
- If a command fails because the key is missing, ask the user to provide or set
  the key instead of inventing one.
