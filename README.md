# hermes-model-scout

A weekly **model scout** for self-hosted LLM rigs. It scans HuggingFace for *new*
GGUF models your hardware can actually run, dedupes against what you already have,
and downloads a small capped batch to an archive drive — a mix of mainstream and
uncensored models. Ships as a [Hermes Agent](https://github.com/NousResearch/hermes-agent)
skill + cron, but the worker is a plain Python script that runs anywhere.

> **Archive-only.** It downloads and files models away. It never touches your
> inference server / `llama-swap` / Ollama config. You promote a model to serving
> yourself once you've looked at it.

## Why

If you run local models, good new GGUFs drop constantly, but most are too big for
your GPU, duplicates of what you have, or junk repos. Checking by hand is a chore.
This automates the boring part: "once a week, find a couple of genuinely new models
that fit my box, grab them for the archive, and tell me what you got."

## How it works

```
HuggingFace API ──> model-scout.py (on your storage host)
                     • query new + trending + popular GGUF repos
                     • filter to your size envelope + arch allowlist
                     • dedupe vs models you already own
                     • rank, balance mainstream/uncensored, cap the batch
                     • download to the archive dir
                          │
                          ▼
                  <archive>/*.gguf   (+ .logs/)
```

- **`worker/model-scout.py`** — the brain. Pure Python (`huggingface_hub`, `requests`).
  `--dry-run` scans and ranks without downloading.
- **`worker/scout-cron.sh`** — weekly wrapper: prints last run + this week's scan,
  then launches the download **detached** (big pulls outlast most agent timeouts).
- **`tools/run-model-scout.sh`** + **`scripts/model-scout.sh`** + **`skill/SKILL.md`**
  — the Hermes Agent integration (tool, cron script, skill).

## The "hardware envelope"

The scout only keeps models whose chosen GGUF file fits your GPU. Set
`SCOUT_MAX_FILE_GB` to your **largest GPU's VRAM in GB** (e.g. `24` for a 24 GB
card, `16` for 16 GB) — that leaves the weights room plus a little KV cache. It
prefers `Q4_K_M`/`IQ4_XS` quants, skips vision/embedding/audio repos and anything
absurdly large, and gates on a minimum download count so name-squat repos don't
slip in.

## Quick start (standalone)

```bash
git clone https://github.com/randylahey-dev/hermes-model-scout
cd hermes-model-scout/worker
python3 -m venv venv && ./venv/bin/pip install huggingface_hub requests

# preview only — nothing is downloaded
SCOUT_ARCHIVE_DIR=~/models-archive SCOUT_MAX_FILE_GB=24 ./venv/bin/python model-scout.py --dry-run

# real run (downloads the capped batch)
SCOUT_ARCHIVE_DIR=~/models-archive SCOUT_MAX_FILE_GB=24 ./venv/bin/python model-scout.py
```

Want downloads to egress a VPN? Run the worker on a host whose default route is
your VPN tunnel — no per-app config needed.

## Install into Hermes Agent

1. Put the worker somewhere with disk space (the archive host). Create the venv as above.
2. Copy the integration files into your profile (`$HERMES_HOME`):
   - `skill/SKILL.md` → `$HERMES_HOME/skills/model-scout/SKILL.md`
   - `tools/run-model-scout.sh` → `$HERMES_HOME/tools/`  (`chmod +x`)
   - `scripts/model-scout.sh` → `$HERMES_HOME/scripts/` (`chmod +x`)
3. If the worker is on another machine, set `SCOUT_HOST=user@archive-box` (and
   `SCOUT_DIR`) in the environment the tool runs in. Otherwise it runs locally.
4. Add the cron job: append `examples/cron-job.json` (give it a fresh `id`, set
   `deliver`) to your profile's `cron/jobs.json` `jobs` array, then restart the
   gateway. Runs Sundays 05:00 in `no_agent` script mode.
5. (Optional) add a row to your skill registry/wiki so the agent routes to it.

Then ask the agent: **"scan for new models"** (preview) or let the weekly cron run.

## Configuration

All env vars, with defaults:

| Var | Default | Meaning |
|---|---|---|
| `SCOUT_ARCHIVE_DIR` | `~/models-archive` | where GGUFs are saved |
| `SCOUT_MAX_FILE_GB` | `24` | biggest single file — **set to your GPU VRAM** |
| `SCOUT_MIN_FILE_GB` | `3.5` | ignore tiny/junk files |
| `SCOUT_MAX_DOWNLOADS` | `2` | models per run |
| `SCOUT_MAX_GB_RUN` | `50` | total GB per run |
| `SCOUT_MIN_FREE_GB` | `100` | hard stop if the drive drops below this |
| `SCOUT_RECENT_DAYS` | `45` | how "new" a model must be |
| `SCOUT_MIN_DOWNLOADS` | `150` | quality gate (anti-junk) |
| `SCOUT_MIN_LIKES` | `2` | quality gate |
| `SCOUT_GPU_HOST` | _(empty)_ | optional SSH target whose model dir also counts for dedupe |
| `SCOUT_GPU_MODELS_DIR` | `/srv/models` | model dir on that host |
| `HF_TOKEN` | _(empty)_ | optional; lifts HuggingFace rate limits |

Tune the `ARCH_ALLOW` / `DENY` / `UNCENSORED` / `QUANT_PREFS` lists at the top of
`model-scout.py` for your runtime and taste.

## Example output

```
🛰  Model Scout — 2026-06-15 15:15  (archive free: 7,563 GB)
   envelope: 3.5-24.0 GB GGUF · new≤45d · cap 2 dl / 50 GB
   dedupe against 19 models already owned

Top candidates (25 found):
  • 🔒std unsloth/Qwen3.6-35B-A3B-MTP-GGUF  [22.7G] ⬇751,212 ♥521 (2026-05-11)
  • 🔓unc HauhauCS/Gemma4-26B-A4B-Uncensored-...-Balanced  [16.8G] ⬇161,747 ♥173 (2026-05-14)
  ...
```

## License

MIT — see [LICENSE](LICENSE).
