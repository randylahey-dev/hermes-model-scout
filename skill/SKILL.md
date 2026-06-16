---
name: model-scout
description: "Scan HuggingFace for new GGUF LLMs your hardware can run, and archive good ones (mainstream + uncensored) to a local drive."
category: skills
---

# model-scout

## What this does
Finds NEW GGUF models on HuggingFace that your box could/should run (set the size
envelope to your GPU's VRAM), dedupes against models you already own, and downloads
a capped batch to a local archive directory. It picks a MIX of mainstream ("std")
and uncensored/abliterated models. Designed to run weekly via cron; can also run
on demand.

This is **archive-only** — it does NOT wire anything into your inference server.
Promote a downloaded model to serving yourself if you want to run it.

## HARD RULES
1. The ONLY way you scan/download models is the tool below. Do NOT improvise raw
   `huggingface-cli`, `wget`, or `git clone`.
2. `run-model-scout.sh` (no arg) = PREVIEW: lists candidates, downloads nothing.
   `run-model-scout.sh run` = the real behavior (report + launch download).
3. When the user asks to "scan for models" without saying "download", run the
   PREVIEW first and show the candidates. Only run `... run` if they confirm or
   it's the scheduled cron.
4. Report the tool output verbatim. Downloads run in the background (a 20-40 GB
   pull takes a while) — results show up in the NEXT report, or in
   `<archive>/.logs/last-summary.txt`.

## Trigger
"scan for new models", "any new models I should grab", "check for new LLMs",
"download a new model for archive", "model scout".

## How to run
  $HERMES_HOME/tools/run-model-scout.sh          # preview (no download)
  $HERMES_HOME/tools/run-model-scout.sh run      # report + launch download

## Tunables (env vars on the worker — see the project README)
- `SCOUT_MAX_FILE_GB`   — biggest single file; set to your largest GPU's VRAM (GB)
- `SCOUT_MAX_DOWNLOADS` — models per run (default 2)
- `SCOUT_MAX_GB_RUN`    — total GB per run (default 50)
- `SCOUT_MIN_FREE_GB`   — hard stop if the drive drops below this
- `SCOUT_RECENT_DAYS`   — how "new" a model must be (default 45)
- `SCOUT_MIN_DOWNLOADS` — quality gate against junk/name-squat repos

## Pitfalls
- "previous download still in progress" is normal — it skips launching a second pull.
- Unauthenticated HF downloads are rate-limited; set `HF_TOKEN` to lift that.
- A model appearing here does NOT mean it's running — it's archived. Promote manually.
