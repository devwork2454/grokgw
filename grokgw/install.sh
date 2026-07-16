#!/bin/bash
set -euo pipefail

BOLD="\033[1m"; GREEN="\033[32m"; RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"
fail() { echo -e "${RED}✗ $1${RESET}"; exit 1; }
ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }

echo -e "${BOLD}grokgw installer${RESET}"
echo ""

# --- prerequisites ---
command -v python3 >/dev/null || fail "python3 not found"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' \
  || fail "Python 3.12+ required (got $(python3 --version))"
ok "python3 $(python3 --version | awk '{print $2}')"

command -v curl >/dev/null || fail "curl not found"
ok "curl"

command -v git >/dev/null || warn "git not found (skip auto-clone)" || true

# --- source ---
REPO_URL="https://github.com/devwork2454/grokgw.git"
if [ -f "${BASH_SOURCE[0]:-}" ] && [ -d "$(dirname "${BASH_SOURCE[0]}")/../grokgw" ] 2>/dev/null; then
  # running from cloned repo
  SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  ok "local source: $SRC"
elif [ -d "./grokgw" ] && [ -f "./grokgw/pyproject.toml" ]; then
  SRC="$(pwd)/grokgw"
  ok "local source: $SRC"
else
  # clone from GitHub
  echo "  cloning $REPO_URL ..."
  git clone --depth 1 "$REPO_URL" /tmp/grokgw-install 2>/dev/null || fail "git clone failed"
  SRC="/tmp/grokgw-install/grokgw"
  ok "cloned to $SRC"
fi

# --- auth check ---
AUTH="${HOME}/.grok/auth.json"
[ -f "$AUTH" ] && ok "auth.json found" || warn "not found — run 'grok login' before starting"

# --- proxy check ---
ss -tlnp 2>/dev/null | grep -q ':2080' && ok "proxy :2080" || warn "no proxy — set GROKGW_PROXY_URL"

# --- install ---
echo ""
echo "installing ..."
pip3 install -e "$SRC" --break-system-packages -q 2>/dev/null \
  || pip3 install -e "$SRC" -q
ok "grokgw installed"

# --- systemd ---
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/grokgw.service" << UNIT
[Unit]
Description=grokgw — Grok OpenAI-compatible API gateway
After=network-online.target

[Service]
Type=simple
ExecStart=$(which python3) -m grokgw
Environment="PATH=${PATH}"
Environment="HOME=${HOME}"
Environment="ALL_PROXY=socks5h://127.0.0.1:2080"
Environment="all_proxy=socks5h://127.0.0.1:2080"
Environment="GROKGW_BACKEND=cli"
Environment="GROKGW_HOST=127.0.0.1"
Environment="GROKGW_PORT=8787"
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload 2>/dev/null || true
if systemctl --user enable --now grokgw 2>/dev/null; then
  ok "systemd service started"
else
  warn "systemd unavailable — start manually:"
  echo "  ALL_PROXY=socks5h://127.0.0.1:2080 all_proxy=socks5h://127.0.0.1:2080 GROKGW_BACKEND=cli python -m grokgw &"
fi

echo ""
echo -e "${GREEN}✓ Done${RESET}"
echo "  healthz: curl http://127.0.0.1:8787/healthz"
echo "  chat:    curl http://127.0.0.1:8787/v1/chat/completions -H 'Content-Type: application/json' -d '{\"model\":\"grok-4.5\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}'"
