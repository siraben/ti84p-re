#!/usr/bin/env bash
# Reproducible build of the TI-84 Plus Ghidra database.
# Rebuilds ~/Documents/ti84-re/ti84 from scratch: 64 flash pages, symbols,
# bcall naming, BCD floats, and TI-OS data types. Ghidra must be CLOSED.
set -euo pipefail

export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
LX=/opt/homebrew/Cellar/ghidra/12.1/libexec
T="$(cd "$(dirname "$0")" && pwd)"          # this tools/ dir
PROJ="$(dirname "$T")"                        # ~/Documents/ti84-re
NAME=ti84

python3 "$T/resolve_bcalls.py"          # regenerate bcall_targets.txt (page&0x3F)
rm -rf "$PROJ/$NAME.gpr" "$PROJ/$NAME.rep"
"$LX/support/analyzeHeadless" "$PROJ" "$NAME" \
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
  -postScript BuildTypes.java "$T"
echo "Build complete: $PROJ/$NAME.gpr"
# Pipeline: 64-page load + symbols/floats/bcall-fixup (BuildTI84Full)
#  -> name 535 bcall routines at real (page,addr) (ApplyBcalls)
#  -> follow flow + name new bcall sites (DeepenPass)
#  -> apply accumulated manual names (RenameFns)
#  -> TI-OS enums/structs/typed regions (BuildTypes)
