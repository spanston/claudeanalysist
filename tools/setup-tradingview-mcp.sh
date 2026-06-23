#!/usr/bin/env bash
# Install the TradingView MCP server so .mcp.json can launch it.
#
# WHAT THIS IS: tradesdontlie/tradingview-mcp is an MCP bridge to the
# *TradingView Desktop app* over Chrome DevTools Protocol (localhost:9222).
# It is a LOCAL, INTERACTIVE confirmation layer only:
#   - requires the TradingView Desktop app installed and running,
#   - launched with --remote-debugging-port=9222,
#   - and (for full data) a paid TradingView subscription.
# It does NOT work in the unattended Claude Code web/cloud routine — there is
# no desktop app or :9222 endpoint there. Run this on the machine where you
# do interactive analysis, then launch Claude Code there.
#
# Usage:  bash tools/setup-tradingview-mcp.sh [install_dir]
# Default install_dir = <repo>/vendor/tradingview-mcp (matches .mcp.json).
set -euo pipefail

REPO="https://github.com/tradesdontlie/tradingview-mcp.git"
DEST="${1:-$(git rev-parse --show-toplevel)/vendor/tradingview-mcp}"

mkdir -p "$(dirname "$DEST")"

if [ -d "$DEST/.git" ]; then
  echo "==> Updating existing clone at $DEST"
  git -C "$DEST" pull --ff-only
elif [ -d "$DEST/src" ]; then
  echo "==> Source already present at $DEST (not a git clone); skipping fetch"
else
  echo "==> Cloning $REPO -> $DEST"
  if ! git clone --depth 1 "$REPO" "$DEST"; then
    echo "    git clone failed (proxy/network?); falling back to tarball"
    tmp="$(mktemp -d)"
    curl -sSL --max-time 60 -o "$tmp/tv.tar.gz" \
      "https://codeload.github.com/tradesdontlie/tradingview-mcp/tar.gz/refs/heads/main"
    tar -xzf "$tmp/tv.tar.gz" -C "$tmp"
    mkdir -p "$DEST"
    cp -a "$tmp"/tradingview-mcp-main/. "$DEST"/
    rm -rf "$tmp"
  fi
fi

echo "==> npm install in $DEST"
( cd "$DEST" && npm install --no-audit --no-fund )

echo "==> Verifying server entry"
node --check "$DEST/src/server.js" && echo "    src/server.js OK"

cat <<EOF

Done. The TradingView MCP is installed at:
  $DEST

.mcp.json already points here via \${TRADINGVIEW_MCP_PATH:-<repo>/vendor/tradingview-mcp}.
Next steps for INTERACTIVE use:
  1. Launch TradingView Desktop with remote debugging:
       Linux: /opt/TradingView/tradingview --remote-debugging-port=9222
       Mac:   /Applications/TradingView.app/Contents/MacOS/TradingView --remote-debugging-port=9222
       Win:   %LOCALAPPDATA%\\TradingView\\TradingView.exe --remote-debugging-port=9222
  2. Restart Claude Code so it loads the 'tradingview' MCP server.
  3. Run the tv_health_check tool — expect cdp_connected: true.
See CLAUDE.md "TradingView MCP (local confirmation layer)" for which tools to use.
EOF
