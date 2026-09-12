#!/bin/zsh
# refresh_showcase.zsh — re-bake the champions showcase and push it live.
#
# WHY THIS EXISTS: champions/ is a STATIC BAKE of the ladder's top robot per
# weight class. It went four-fifths wrong in two days, and then wrong again
# within three hours, both times because someone actually played. A page whose
# whole claim is "today's champions" cannot be refreshed by hand.
#
# WHY IT DOES NOT CALL publish_site.zsh: that script does `rm -rf .git`,
# re-inits, and force-pushes a single commit with a hard-coded "site v1"
# message. Fine as a human-driven full-site deploy; wrong as a daily robot —
# it would destroy the site's history every night and label a year of data
# refreshes "site v1". This pushes ONE data file, preserves history, and never
# force-pushes. It clones the remote fresh each run, so it is also immune to
# publish_site.zsh having rewritten history since.
#
# FAIL CLOSED. A bad bake must never reach the live site: if the API is down,
# the JSON is short, or classes are missing, the live file is left exactly as
# it was and the run exits non-zero. Publishing an empty champions page is
# worse than publishing yesterday's.
#
# Everything is appended to website/tools/refresh_showcase.log.
# The token is read from .gh_token.local and never printed.

set -e
SITE_DIR="${0:A:h:h}"
PROJ_ROOT="${SITE_DIR:h}"
LIVE="$SITE_DIR/data/showcase.json"
LOG="$SITE_DIR/tools/refresh_showcase.log"
OWNER="du6"; REPO_NAME="cyberduck-club"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

exec >> "$LOG" 2>&1
echo "===== refresh $(date '+%Y-%m-%d %H:%M:%S %Z') ====="

# --- 1. Bake to a SCRATCH path, never over the live file -------------------
NEW="$TMP/showcase.json"
if ! /usr/bin/python3 "$SITE_DIR/tools/bake_showcase.py" --out "$NEW"; then
  echo "ABORT: bake failed (API down or changed) — live file untouched"; exit 1
fi

# --- 2. Gate it. Each of these has a real failure behind it ----------------
/usr/bin/python3 - "$NEW" <<'PY' || { echo "ABORT: bake failed validation — live file untouched"; exit 1; }
import json, sys
d = json.load(open(sys.argv[1]))
champs = d.get("champions") or []
assert len(champs) == 5, f"expected 5 classes, got {len(champs)}"
cats = {c["category"] for c in champs}
assert cats == {"FEATHER","LIGHT","MIDDLE","HEAVY","SUPER"}, f"classes wrong: {cats}"
# A card with no clip renders as a bare name. One is normal (a house-held
# class often has no replay); three would mean the blob store is failing.
withclip = sum(1 for c in champs if (c.get("fight") or {}).get("frames"))
assert withclip >= 3, f"only {withclip}/5 cards have a clip — blob store suspect"
assert all(c.get("robotName") for c in champs), "a champion has no name"
print(f"  validated: 5 classes, {withclip} with clips, generated {d.get('generated')}")
PY

# A real bake is 500-700 KB. Anything tiny means the clips did not make it.
SIZE=$(/usr/bin/stat -f%z "$NEW")
if (( SIZE < 100000 )); then
  echo "ABORT: bake is only ${SIZE} bytes (expect ~500-700 KB) — live file untouched"; exit 1
fi

# --- 3. Adopt the new bake locally ----------------------------------------
# ⚠ THE "HAS ANYTHING CHANGED" TEST BELONGS AGAINST THE REMOTE, NOT THIS FILE.
# An earlier version compared the new bake to the LOCAL copy and exited early
# when they matched — which is exactly what happens after someone re-bakes by
# hand, so it skipped the push and left the LIVE SITE stale while reporting
# "no change". The only copy whose staleness matters is the published one, and
# that is compared in step 4.
/bin/cp "$NEW" "$LIVE"
echo "  updated $LIVE"
/usr/bin/python3 -c "
import json;d=json.load(open('$LIVE'))
for c in d['champions']:
    print('   %-8s %-13s %-10s %.0f'%(c['category'],c['robotName'],c['owner'],c['rating']))"

# --- 4. Push just this file, preserving history ----------------------------
TOKEN=$(grep -oE 'ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+' "$PROJ_ROOT/.gh_token.local" | head -1)
[[ -n "$TOKEN" ]] || { echo "ABORT: no token in .gh_token.local — local file updated, NOT published"; exit 1; }

cd "$TMP"
if ! git clone -q --depth 1 "https://$OWNER:${TOKEN}@github.com/$OWNER/$REPO_NAME.git" pages 2>&1 | sed -E "s/${TOKEN}/***REDACTED***/g"; then
  echo "ABORT: clone failed — local file updated, NOT published"; exit 1
fi
# Compare SEMANTICALLY, not byte-wise: `generated` is a fresh timestamp on
# every run, so a plain diff would commit a no-op change every single night.
if /usr/bin/python3 - "$TMP/pages/data/showcase.json" "$LIVE" <<'PY'
import json, sys
try:
    a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2]))
except Exception:
    sys.exit(1)                      # unreadable remote copy: publish over it
for d in (a, b):
    d.pop("generated", None); d.pop("seasonEndsAt", None)
sys.exit(0 if a == b else 1)
PY
then
  echo "  remote already has these champions — ladder has not moved. Nothing pushed."
  exit 0
fi
/bin/cp "$LIVE" "$TMP/pages/data/showcase.json"
cd "$TMP/pages"
git add data/showcase.json
git -c user.name="showcase bot" -c user.email="admin@cyberduck.club" \
    commit -q -m "Champions refresh $(date '+%Y-%m-%d') — re-baked from the live ladder"
if git push -q origin HEAD:main 2>&1 | sed -E "s/${TOKEN}/***REDACTED***/g"; then
  echo "  PUBLISHED. Pages will rebuild within ~2 min."
else
  echo "ABORT: push rejected (history may have been rewritten) — local file updated, NOT published"
  exit 1
fi
