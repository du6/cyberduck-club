#!/bin/zsh
# Publish the Cyberduck Club site to GitHub Pages.
# Run from anywhere:  zsh "/Users/leondu/Setup Guide In-Editor Tutorial/website/publish_site.zsh"
# Everything is logged to website/publish_log.txt (token never printed).
set -e
SITE_DIR="${0:A:h}"
PROJ_ROOT="${SITE_DIR:h}"
LOG="$SITE_DIR/publish_log.txt"
REPO_NAME="cyberduck-club"
OWNER="du6"
API="https://api.github.com"

exec > >(tee "$LOG") 2>&1
echo "== Cyberduck Club site publish · $(date) =="

TOKEN=$(grep -oE 'ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+' "$PROJ_ROOT/.gh_token.local" | head -1)
[[ -n "$TOKEN" ]] || { echo "ERROR: no token found in .gh_token.local"; exit 1; }
auth=(-H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json")

# --- 1. Ensure the repo exists (create if the token is allowed to) ---------
code=$(curl -s -o /tmp/cc_repo.json -w '%{http_code}' "${auth[@]}" "$API/repos/$OWNER/$REPO_NAME")
if [[ "$code" != "200" ]]; then
  echo "Repo $OWNER/$REPO_NAME not accessible (HTTP $code) — trying to create it…"
  code=$(curl -s -o /tmp/cc_create.json -w '%{http_code}' -X POST "${auth[@]}" "$API/user/repos" \
    -d "{\"name\":\"$REPO_NAME\",\"description\":\"cyberduck.club — Cyberduck Club studio site\",\"homepage\":\"https://cyberduck.club\",\"private\":false,\"has_issues\":false,\"has_wiki\":false,\"has_projects\":false}")
  if [[ "$code" != "201" ]]; then
    echo ""
    echo "The token cannot create repositories (HTTP $code)."
    echo "Create a PUBLIC repo named '$REPO_NAME' at https://github.com/new (no README),"
    echo "then re-run this script. If the token is fine-grained and repo-scoped, also add"
    echo "$REPO_NAME to its repository list (github.com → Settings → Developer settings)."
    exit 1
  fi
  echo "Repo created."
fi

# --- 2. Push the site ------------------------------------------------------
cd "$SITE_DIR"
rm -rf .git
git init -q -b main
git add -A
git -c user.name="owen" -c user.email="leondu167@gmail.com" commit -q -m "Cyberduck Club site v1 — home, Robot Brawl page + leaderboard, support, privacy"
if git push -q -f "https://$OWNER:${TOKEN}@github.com/$OWNER/$REPO_NAME.git" main 2>/dev/null; then
  echo "Pushed with token."
else
  echo "Token push refused — falling back to your normal git credentials…"
  git push -f "https://github.com/$OWNER/$REPO_NAME.git" main
fi

# --- 3. Enable GitHub Pages on main branch root ----------------------------
code=$(curl -s -o /tmp/cc_pages.json -w '%{http_code}' -X POST "${auth[@]}" "$API/repos/$OWNER/$REPO_NAME/pages" \
  -d '{"source":{"branch":"main","path":"/"}}')
echo "Pages enable: HTTP $code (201 created / 409 already enabled — both fine)"
code=$(curl -s -o /tmp/cc_cname.json -w '%{http_code}' -X PUT "${auth[@]}" "$API/repos/$OWNER/$REPO_NAME/pages" \
  -d '{"cname":"cyberduck.club","source":{"branch":"main","path":"/"}}')
echo "Custom domain set: HTTP $code (204 = ok)"
echo ""
echo "== DONE. Site will build at https://$OWNER.github.io/$REPO_NAME/ within ~2 min =="
echo "It goes live at https://cyberduck.club once DNS points at GitHub Pages:"
echo ""
echo "  At your DNS provider for cyberduck.club ADD:"
echo "    A     @    185.199.108.153"
echo "    A     @    185.199.109.153"
echo "    A     @    185.199.110.153"
echo "    A     @    185.199.111.153"
echo "    CNAME www  $OWNER.github.io"
echo ""
echo "  DO NOT touch the MX records or existing TXT/SPF records — they are"
echo "  Google Workspace mail (admin@cyberduck.club depends on them)."
echo ""
echo "  Then: repo Settings → Pages → tick 'Enforce HTTPS' once the certificate is issued (~1h after DNS)."
