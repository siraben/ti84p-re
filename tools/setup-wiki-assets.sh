#!/usr/bin/env bash
# Vendor the client-side web assets the wiki needs that mdBook can't supply:
#   - KaTeX (offline math rendering)   <- $KATEX_DIR  (…/node_modules/katex)
#   - pseudocode.js (algorithm blocks) <- $PSEUDOCODE_JS / $PSEUDOCODE_CSS (files)
# All copied files are gitignored; the flake regenerates them on build/serve, and a
# dev can run:  KATEX_DIR=$(nix build --no-link --print-out-paths nixpkgs#katex)/lib/node_modules/katex \
#               tools/setup-wiki-assets.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"

if [ -n "${KATEX_DIR:-}" ]; then
  install -m 0644 "$KATEX_DIR/dist/katex.min.css"              "$root/katex.min.css"
  install -m 0644 "$KATEX_DIR/dist/katex.min.js"               "$root/katex.min.js"
  install -m 0644 "$KATEX_DIR/dist/contrib/auto-render.min.js" "$root/katex-auto-render.min.js"
  mkdir -p "$root/docs/fonts"
  install -m 0644 "$KATEX_DIR"/dist/fonts/* "$root/docs/fonts/"
  echo "setup-wiki-assets: vendored KaTeX from $KATEX_DIR"
fi

if [ -n "${PSEUDOCODE_JS:-}" ] && [ -n "${PSEUDOCODE_CSS:-}" ]; then
  install -m 0644 "$PSEUDOCODE_JS"  "$root/pseudocode.min.js"
  install -m 0644 "$PSEUDOCODE_CSS" "$root/pseudocode.min.css"
  echo "setup-wiki-assets: vendored pseudocode.js"
fi
