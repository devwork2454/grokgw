#!/bin/bash
set -euo pipefail

BOLD="\033[1m"; GREEN="\033[32m"; RED="\033[31m"; RESET="\033[0m"

echo -e "${BOLD}grokgw installer${RESET}"
echo ""

# --- prerequisites ---
fail() { echo -e "${RED}✗ $1${RESET}"; exit 1; }
ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }

command -v python3 >/dev/null || fail "python3 not found"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' \
  || fail "Python 3.12+ required (got $(python3 --version))"
ok "python3 $(python3 --version | awk '{print $2}')"

command -v curl >/dev/null || fail "curl not found"
ok "curl"

# auth check (warn only, grok login can be done later)
AUTH="${HOME}/.grok/auth.json"
if [ -f "$AUTH" ]; then
  ok "auth.json found"
else
  echo -e "  ${RED}⚠${RESET}  auth.json not found — run 'grok login' before starting"
fi

# proxy check (warn only)
if ss -tlnp 2>/dev/null | grep -q ':2080'; then
  ok "proxy :2080 listening"
else
  echo -e "  ${RED}⚠${RESET}  no proxy on :2080 — set GROKGW_PROXY_URL or fix network"
fi

# --- install ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo ""
echo "installing grokgw from $SCRIPT_DIR ..."
pip3 install -e "$SCRIPT_DIR" --break-system-packages -q 2>/dev/null \
  || pip3 install -e "$SCRIPT_DIR" -q
ok "grokgw installed"

# --- systemd (optional) ---
echo ""
read -p "install systemd service? [Y/n] " -r REPLY
if [[ ! "$REPLY" =~ ^[Nn] ]]; then
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

  systemctl --user daemon-reload
  systemctl --user enable --now grokgw 2>/dev/null && ok "systemd service started" \
    || echo -e "  ${RED}⚠${RESET}  systemd not available; start manually: python -m grokgw"
fi

echo ""
echo -e "${GREEN}✓${RESET} Done. Test it:"
echo "  curl http://127.0.0.1:8787/healthz"
