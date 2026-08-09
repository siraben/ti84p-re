#!/usr/bin/env bash
# Reproducible build of the TI-84 Plus Ghidra database.
# Rebuilds ti84.gpr (in the repo root) from scratch: 64 flash pages, symbols,
# bcall naming, BCD floats, and TI-OS data types. Ghidra must be CLOSED.
set -euo pipefail

T="$(cd "$(dirname "$0")" && pwd)"          # this tools/ dir
PROJ="$(dirname "$T")"                        # repo root
NAME=ti84

# Nixpkgs exposes the headless launcher as `ghidra-analyzeHeadless`; the
# upstream archive and Homebrew use `support/analyzeHeadless`.  An explicit
# path remains available for installations with a different layout.
if [[ -n "${GHIDRA_ANALYZE_HEADLESS:-}" ]]; then
  ANALYZE_HEADLESS="$GHIDRA_ANALYZE_HEADLESS"
elif command -v ghidra-analyzeHeadless >/dev/null 2>&1; then
  ANALYZE_HEADLESS="$(command -v ghidra-analyzeHeadless)"
elif command -v analyzeHeadless >/dev/null 2>&1; then
  ANALYZE_HEADLESS="$(command -v analyzeHeadless)"
elif [[ -x /opt/homebrew/Cellar/ghidra/12.1/libexec/support/analyzeHeadless ]]; then
  ANALYZE_HEADLESS=/opt/homebrew/Cellar/ghidra/12.1/libexec/support/analyzeHeadless
  if [[ -z "${JAVA_HOME:-}" && -d /opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home ]]; then
    export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
  fi
else
  echo "Ghidra headless analyzer not found; run through 'nix develop -c tools/build.sh'" >&2
  exit 1
fi

python3 "$T/resolve_bcalls.py"          # regenerate bcall_targets.txt (page&0x3F)
rm -rf "$PROJ/$NAME.gpr" "$PROJ/$NAME.rep"
"$ANALYZE_HEADLESS" "$PROJ" "$NAME" \
  -import "$T/ti84_page00.bin" -processor z80:LE:16:default \
  -loader BinaryLoader -loader-baseAddr 0x0000 \
  -scriptPath "$T" \
  -postScript BuildTI84Full.java "$T" \
  -postScript ApplyBcalls.java "$T" \
  -postScript DeepenPass.java "$T" \
  -postScript RamRoutines.java "$T" \
  -postScript ApplyBjumpTargets.java "$T" \
  -postScript FixInlineBjumps.java "$T" \
  -postScript ParserTable.java "$T" \
  -postScript RenameFns.java "$T" \
  -postScript BuildTypes.java "$T" \
  -postScript RenameVars.java "$T"
echo "Build complete: $PROJ/$NAME.gpr"
# Pipeline: 64-page load + symbols/floats/bcall-fixup (BuildTI84Full)
#  -> name 535 bcall routines at real (page,addr) (ApplyBcalls)
#  -> follow flow + name new bcall sites (DeepenPass)
#  -> apply accumulated manual names (RenameFns)
#  -> TI-OS enums/structs/typed regions (BuildTypes)
#  -> apply decompiler variable names from varnames.txt (RenameVars)
