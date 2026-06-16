#!/usr/bin/env python3
"""
model-scout.py — weekly local-LLM model scout + archiver.

Scans HuggingFace for NEW GGUF models that YOUR hardware could/should run,
dedupes against models you already have, downloads a capped batch to an archive
directory, and prints a chat-friendly report. Built to be driven on a schedule
(e.g. a Hermes Agent cron) but runs fine standalone.

Archive-only by design: it does NOT wire anything into a server/runtime. Promote
a downloaded model to serving yourself once you've looked at it.

Everything is configured by env vars — see CONFIG below. Sensible defaults mean
`python3 model-scout.py --dry-run` works out of the box.

Requires: huggingface_hub, requests  (pip install huggingface_hub requests)
License: MIT
"""
import os, re, sys, json, time, shutil, argparse, datetime as dt

import requests
from huggingface_hub import hf_hub_download

# ----------------------------- CONFIG (env-overridable) ---------------------
# Where to store downloaded GGUFs.
ARCHIVE_DIR   = os.environ.get("SCOUT_ARCHIVE_DIR", os.path.expanduser("~/models-archive"))
# Optional: an SSH target whose model dir should also count for dedupe, e.g.
# "user@gpu-box". Leave empty to dedupe against the local archive only.
GPU_HOST      = os.environ.get("SCOUT_GPU_HOST", "")
GPU_MODELS_DIR= os.environ.get("SCOUT_GPU_MODELS_DIR", "/srv/models")

MIN_FREE_GB   = float(os.environ.get("SCOUT_MIN_FREE_GB", "100"))   # hard stop if drive below this
MAX_DOWNLOADS = int(os.environ.get("SCOUT_MAX_DOWNLOADS", "2"))     # models per run
MAX_GB_RUN    = float(os.environ.get("SCOUT_MAX_GB_RUN", "50"))     # total GB per run
MIN_FILE_GB   = float(os.environ.get("SCOUT_MIN_FILE_GB", "3.5"))   # ignore tiny/junk
# Biggest single file to grab. Set this to your largest GPU's VRAM (in GB) so
# the model + a little KV cache fits, e.g. 24 for a 24GB card, 16 for 16GB.
MAX_FILE_GB   = float(os.environ.get("SCOUT_MAX_FILE_GB", "24"))
RECENT_DAYS   = int(os.environ.get("SCOUT_RECENT_DAYS", "45"))      # "new" window
MIN_DOWNLOADS = int(os.environ.get("SCOUT_MIN_DOWNLOADS", "150"))   # quality gate (anti-junk)
MIN_LIKES     = int(os.environ.get("SCOUT_MIN_LIKES", "2"))
EXPLORE_CAP   = int(os.environ.get("SCOUT_EXPLORE_CAP", "70"))      # max repos to inspect deeply
HF_TOKEN      = os.environ.get("HF_TOKEN")  # optional; raises rate limits

# Preferred quant filename fragments, best first.
QUANT_PREFS = ["Q4_K_M", "IQ4_XS", "Q4_K_S", "Q5_K_M", "IQ4_NL"]

# Architecture hints (repo id must contain one). Trim/extend for your runtime.
ARCH_ALLOW = ["qwen", "gemma", "llama", "mistral", "mixtral", "phi", "glm",
              "deepseek", "yi-", "yi1", "command-r", "cohere", "granite",
              "nemotron", "hermes", "falcon", "stablelm", "internlm", "olmo",
              "exaone", "minicpm", "smollm", "gpt-oss", "ernie"]

# Skip these (won't fit / not text-gen / too big for a home box).
DENY = ["vl", "vision", "-vl-", "audio", "tts", "whisper", "embed", "rerank",
        "bge", "clip", "diffusion", "flux", "sdxl", "405b", "235b", "253b",
        "480b", "671b", "deepseek-v3", "draft", "0.5b", "1.5b", "1b-",
        "moe-16x", "coder-1", "math-1"]

# Uncensored signal keywords (used only to balance the picks; remove if you
# only want mainstream models).
UNCENSORED = ["abliterat", "uncensor", "heretic", "dolphin", "neo", "obliterat",
              "lewd", "amoral", "nsfw", "unfiltered", "unhinged"]

UA = "model-scout/1.0 (+https://github.com/randylahey-dev/hermes-model-scout)"
HF_API = "https://huggingface.co/api"


def log(msg):
    print(msg, flush=True)


def hf_get(url, params=None, timeout=30):
    headers = {"User-Agent": UA}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def free_gb(path):
    try:
        return shutil.disk_usage(path).free / 1e9
    except Exception:
        return 0.0


def norm(s):
    """Normalize a model name for dedupe: lowercase, drop quant/gguf noise."""
    s = s.lower()
    s = re.sub(r"\.gguf$", "", s)
    s = re.sub(r"(i?q\d[_\-a-z0-9]*|bf16|fp16|f16|gguf|imat|imatrix|\bmax\b|"
               r"d_au|-it-|instruct|chat)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def existing_basenames():
    """Set of normalized names already present locally (+ optional remote host)."""
    names = set()
    if GPU_HOST:
        try:
            import subprocess
            out = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=6", "-o", "BatchMode=yes", GPU_HOST,
                 f"ls {GPU_MODELS_DIR}/*.gguf 2>/dev/null"],
                capture_output=True, text=True, timeout=20)
            for line in out.stdout.splitlines():
                names.add(norm(os.path.basename(line)))
        except Exception as e:
            log(f"  (warn: could not list {GPU_HOST}:{GPU_MODELS_DIR}: {e})")
    try:
        for f in os.listdir(ARCHIVE_DIR):
            if f.endswith(".gguf"):
                names.add(norm(f))
    except Exception:
        pass
    return {n for n in names if n}


def is_uncensored(text):
    t = text.lower()
    return any(k in t for k in UNCENSORED)


def arch_ok(repo_id):
    t = repo_id.lower()
    if any(d in t for d in DENY):
        return False
    return any(a in t for a in ARCH_ALLOW)


def best_quant_file(repo_id):
    """Return (filename, size_gb) of the best quant GGUF in size range, or None."""
    try:
        tree = hf_get(f"{HF_API}/models/{repo_id}/tree/main",
                      params={"recursive": "true"}, timeout=30)
    except Exception:
        return None
    files = []
    for entry in tree:
        path = entry.get("path", "")
        if not path.lower().endswith(".gguf"):
            continue
        base = os.path.basename(path)
        # skip multi-part shards (handled poorly unattended)
        if re.search(r"-0000\d-of-\d", base) or "split" in base.lower():
            continue
        size = entry.get("size") or (entry.get("lfs") or {}).get("size") or 0
        size_gb = size / 1e9
        if size_gb < MIN_FILE_GB or size_gb > MAX_FILE_GB:
            continue
        files.append((path, size_gb))
    if not files:
        return None

    def qrank(name):
        u = name.upper()
        for i, q in enumerate(QUANT_PREFS):
            if q in u:
                return i
        return len(QUANT_PREFS)
    files.sort(key=lambda f: (qrank(f[0]), f[1]))
    return files[0]


def gather_candidates(have):
    """Return ranked list of candidate dicts not already owned."""
    pool = {}
    queries = [
        {"filter": "gguf", "sort": "lastModified", "direction": -1, "limit": 100},
        {"filter": "gguf", "sort": "trendingScore", "direction": -1, "limit": 60},
        {"filter": "gguf", "sort": "downloads", "direction": -1, "limit": 40},
    ]
    for q in queries:
        try:
            for m in hf_get(f"{HF_API}/models", params=q, timeout=30):
                pool.setdefault(m["id"], m)
        except Exception as e:
            log(f"  (warn: query {q.get('sort')} failed: {e})")

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RECENT_DAYS)
    cands, inspected = [], 0
    for repo_id, m in pool.items():
        if inspected >= EXPLORE_CAP:
            break
        if not arch_ok(repo_id):
            continue
        dls = int(m.get("downloads", 0) or 0)
        likes = int(m.get("likes", 0) or 0)
        if dls < MIN_DOWNLOADS and likes < MIN_LIKES:
            continue
        lm = m.get("lastModified") or m.get("createdAt") or ""
        try:
            lmd = dt.datetime.fromisoformat(lm.replace("Z", "+00:00"))
        except Exception:
            lmd = None
        if lmd and lmd < cutoff:
            continue
        if norm(repo_id.split("/")[-1]) in have:
            continue
        inspected += 1
        qf = best_quant_file(repo_id)
        if not qf:
            continue
        fname, size_gb = qf
        if norm(fname) in have:
            continue
        unc = is_uncensored(repo_id + " " + " ".join(m.get("tags", []) or []))
        recency_bonus = 0
        if lmd:
            age_days = (dt.datetime.now(dt.timezone.utc) - lmd).days
            recency_bonus = max(0, (RECENT_DAYS - age_days)) * 50
        score = dls + likes * 200 + recency_bonus
        cands.append({
            "repo": repo_id, "file": fname, "size_gb": round(size_gb, 1),
            "downloads": dls, "likes": likes, "uncensored": unc,
            "last_modified": lm[:10], "score": score,
        })
    cands.sort(key=lambda c: c["score"], reverse=True)
    return cands


def pick_batch(cands):
    """Pick up to MAX_DOWNLOADS within MAX_GB_RUN, balancing the two flavors."""
    picks, used_gb = [], 0.0
    order = []
    unc = [c for c in cands if c["uncensored"]]
    cen = [c for c in cands if not c["uncensored"]]
    if cen:
        order.append(cen[0])
    if unc:
        order.append(unc[0])
    for c in cands:
        if c not in order:
            order.append(c)
    for c in order:
        if len(picks) >= MAX_DOWNLOADS:
            break
        if used_gb + c["size_gb"] > MAX_GB_RUN:
            continue
        picks.append(c)
        used_gb += c["size_gb"]
    return picks


def download(c):
    log(f"  ↓ {c['repo']} :: {c['file']} ({c['size_gb']}G)")
    return hf_hub_download(repo_id=c["repo"], filename=c["file"],
                           local_dir=ARCHIVE_DIR, token=HF_TOKEN)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="scan + rank, no download")
    args = ap.parse_args()

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    fgb = free_gb(ARCHIVE_DIR)

    log(f"🛰  Model Scout — {stamp}  (archive free: {fgb:,.0f} GB)")
    log(f"   envelope: {MIN_FILE_GB}-{MAX_FILE_GB} GB GGUF · new≤{RECENT_DAYS}d · "
        f"cap {MAX_DOWNLOADS} dl / {MAX_GB_RUN:.0f} GB")

    have = existing_basenames()
    log(f"   dedupe against {len(have)} models already owned")

    cands = gather_candidates(have)
    if not cands:
        log("\nNo new qualifying models this week. (Nothing fit the envelope / all already owned.)")
        return

    log(f"\nTop candidates ({len(cands)} found):")
    for c in cands[:8]:
        flag = "🔓unc" if c["uncensored"] else "🔒std"
        log(f"  • {flag} {c['repo']}  [{c['size_gb']}G] "
            f"⬇{c['downloads']:,} ♥{c['likes']} ({c['last_modified']})")

    if args.dry_run:
        log("\n(dry-run: no downloads)")
        return

    if fgb < MIN_FREE_GB:
        log(f"\n⛔ Archive free space {fgb:,.0f} GB < floor {MIN_FREE_GB:.0f} GB — skipping downloads.")
        return

    picks = pick_batch(cands)
    log(f"\nDownloading {len(picks)} this run:")
    got, total_gb = [], 0.0
    for c in picks:
        try:
            p = download(c)
            got.append(c)
            total_gb += c["size_gb"]
            log(f"  ✅ {os.path.basename(p)}")
        except Exception as e:
            log(f"  ❌ {c['repo']}: {e}")

    log(f"\nDone: {len(got)} model(s), {total_gb:.1f} GB → {ARCHIVE_DIR}")


if __name__ == "__main__":
    main()
