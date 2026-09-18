#!/usr/bin/env python3
"""refresh_showcase_cloud.py — the cloud half of the champions refresh.

Runs as a Cloud Run Job (rb-showcase), started daily by Cloud Scheduler. It
does what website/tools/refresh_showcase.zsh does on a laptop, minus the
laptop: bake the champions showcase from the live ladder, refuse to publish a
bad one, and push the single data file to the GitHub Pages repo.

WHY IT EXISTS IN THE CLOUD: champions/ is a STATIC BAKE and goes stale the
moment anyone plays — it went four-fifths wrong in two days, then wrong again
in three hours. The laptop version only ran when the Mac was awake and logged
in, which is exactly the machine you cannot depend on.

WHAT IT IS NOT ALLOWED TO DO:
  · publish a bake that failed validation (fail closed — yesterday's page
    beats an empty one)
  · force-push, or rewrite the site's history (it pushes ONE file onto
    whatever main currently is; a rejected push is an error, not a --force)
  · print the token, ever, including in a git remote URL on a failure path

The token arrives as GH_TOKEN from Secret Manager. It is written only into a
credential file inside the container's scratch dir and never into argv, a
remote URL that could surface in an error, or a log line.
"""

import json, os, subprocess, sys, tempfile, urllib.request
from datetime import datetime, timezone

OWNER = os.environ.get("SITE_OWNER", "du6")
REPO = os.environ.get("SITE_REPO", "cyberduck-club")
API = os.environ.get("RB_API_URL", "https://rb-api-902243335343.us-central1.run.app")
TOKEN = os.environ.get("GH_TOKEN", "")
REQUIRED = {"FEATHER", "LIGHT", "MIDDLE", "HEAVY", "SUPER"}


def log(msg):
    print(f"[showcase] {msg}", flush=True)


def die(msg, code=1):
    log(f"ABORT: {msg}")
    sys.exit(code)


def run(args, cwd=None, check=True):
    """Run a command. Never let a token reach the output on any path."""
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    if TOKEN:
        out = out.replace(TOKEN, "***REDACTED***")
    if check and p.returncode != 0:
        die(f"{args[0]} failed ({p.returncode}): {out.strip()[:400]}")
    return p.returncode, out


def validate(path):
    """Every one of these gates has a real failure behind it."""
    try:
        d = json.load(open(path))
    except Exception as e:
        die(f"bake is not valid JSON: {e}")
    champs = d.get("champions") or []
    if len(champs) != 5:
        die(f"expected 5 classes, got {len(champs)}")
    cats = {c.get("category") for c in champs}
    if cats != REQUIRED:
        die(f"classes wrong: {sorted(cats)}")
    if not all(c.get("robotName") for c in champs):
        die("a champion has no name")
    # A card with no clip renders as a bare name. One is normal (a house-held
    # class often has no replay yet); three missing means the blob store is
    # failing and this page should not be republished from it.
    withclip = sum(1 for c in champs if (c.get("fight") or {}).get("frames"))
    if withclip < 3:
        die(f"only {withclip}/5 cards have a clip — blob store suspect")
    size = os.path.getsize(path)
    if size < 100_000:
        die(f"bake is only {size} bytes (expect ~500-700 KB)")
    log(f"validated: 5 classes, {withclip} with clips, {size//1024} KB, generated {d.get('generated')}")
    return d


def same_champions(a_path, b_path):
    """Semantic compare. `generated` is a fresh timestamp every run, so a
    byte-wise diff would commit a no-op change every single night."""
    try:
        a = json.load(open(a_path))
        b = json.load(open(b_path))
    except Exception:
        return False                    # unreadable remote copy: publish over it
    for d in (a, b):
        d.pop("generated", None)
        d.pop("seasonEndsAt", None)
    return a == b


def main():
    if not TOKEN:
        die("GH_TOKEN is empty — is the secret bound to this job?")

    # Fail fast and loudly if the ladder is unreachable, rather than letting
    # the baker write a half-empty file we then have to catch downstream.
    try:
        with urllib.request.urlopen(f"{API}/v1/leaderboard", timeout=30) as r:
            entries = json.load(r).get("entries") or []
        log(f"ladder reachable: {len(entries)} rated entries")
    except Exception as e:
        die(f"ladder API unreachable: {e}")

    tmp = tempfile.mkdtemp()
    new = os.path.join(tmp, "showcase.json")

    log("baking…")
    rc, out = run([sys.executable, "/app/bake_showcase.py", "--out", new, "--api", API], check=False)
    for line in out.strip().splitlines():
        log("  " + line)
    if rc != 0:
        die("bake failed")
    validate(new)

    # --- push just this file, preserving history --------------------------
    # The token goes in a credential store, NOT the remote URL: a URL with a
    # secret in it leaks through git's own error messages.
    cred = os.path.join(tmp, ".git-credentials")
    with open(cred, "w") as f:
        f.write(f"https://{OWNER}:{TOKEN}@github.com\n")
    os.chmod(cred, 0o600)
    env_args = ["-c", "credential.helper=store --file=" + cred]

    clone = os.path.join(tmp, "pages")
    log(f"cloning {OWNER}/{REPO}…")
    run(["git"] + env_args + ["clone", "--depth", "1", "-q",
         f"https://github.com/{OWNER}/{REPO}.git", clone])

    target = os.path.join(clone, "data", "showcase.json")
    if os.path.exists(target) and same_champions(target, new):
        log("remote already has these champions — ladder has not moved. Nothing pushed.")
        return

    d = json.load(open(new))
    for c in d["champions"]:
        log(f"  {c['category']:<8} {c['robotName']:<13} {c['owner']:<10} {c['rating']:.0f}")

    os.replace(new, target)
    run(["git", "add", "data/showcase.json"], cwd=clone)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run(["git", "-c", "user.name=showcase bot",
         "-c", "user.email=admin@cyberduck.club",
         "commit", "-q", "-m",
         f"Champions refresh {stamp} — re-baked from the live ladder"], cwd=clone)
    # NO --force. If this is rejected, main moved under us (publish_site.zsh
    # rewrites history) and the right answer is to fail and run again, not to
    # overwrite whatever landed.
    rc, out = run(["git"] + env_args + ["push", "-q", "origin", "HEAD:main"], cwd=clone, check=False)
    if rc != 0:
        die(f"push rejected — nothing published: {out.strip()[:300]}")
    log("PUBLISHED. Pages will rebuild within ~2 min.")


if __name__ == "__main__":
    main()
