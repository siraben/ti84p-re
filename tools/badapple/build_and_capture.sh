#!/usr/bin/env bash
# Build fb39ca4/badapple-ti84, render its tracker music, run it under the TI-84+
# OS in headless TilEm, and extract trace-debug link-port WAVs.
#
# Requires: nix (for spasm-ng), a C compiler (for rabbitsign), python3 with Pillow
# optional, and a 1 MB TI-84+ OS ROM. See README.md for the why behind each step.
#
# Usage: ROM=/path/to/ti84plus.rom ./build_and_capture.sh
set -euo pipefail
ROM="${ROM:?set ROM=/path/to/ti84plus.rom (1 MB TI-84+ OS image)}"
TILEM="${TILEM:-$HOME/Git/tilem-headless/result/bin/tilem2}"
REPO_TOOLS="$(cd "$(dirname "$0")/.." && pwd)"     # ti84-re tools/
WORK="${WORK:-/tmp/badapple-build}"
mkdir -p "$WORK"; cd "$WORK"

# 1. Sources + assemblers ----------------------------------------------------
[ -d badapple-ti84 ] || git clone https://github.com/fb39ca4/badapple-ti84
SPASM="$(nix build --no-link --print-out-paths nixpkgs#spasm-ng)/bin/spasm"
if [ ! -x rabbitsign/src/rabbitsign ]; then
  [ -d rabbitsign ] || git clone https://github.com/abbrev/rabbitsign
  ( cd rabbitsign && [ -f configure ] && ./configure >/dev/null && make >/dev/null )
fi
RS="$WORK/rabbitsign/src/rabbitsign"

# 2. Encode/render music, assemble, join, sign -> badapple.8xk / .bin --------
cd badapple-ti84
mkdir -p bin
export PATH="$PWD/util:$(dirname "$SPASM"):$PATH"
[ -f bin/videopages.bin ] || python3 util/encode.py video/frames.bin.gz bin/videopages.bin
python3 "$REPO_TOOLS/ti84_music.py" encode music/badapple.mmp \
  --asm-dir music --render "$WORK/badapple_music.wav"
spasm badapple.asm bin/codepages.bin
cat bin/codepages.bin bin/videopages.bin > bin/badapple.bin
"$RS" -f -p -o badapple.8xk bin/badapple.bin
cd "$WORK"

# 3. Inject app + launch hook + open flash/RAM exec protection ---------------
python3 "$REPO_TOOLS/badapple_inject.py" "$ROM" badapple-ti84/bin/badapple.bin badapple_rom.bin

# 4. Run headless, trace the run --------------------------------------------
cat > run.macro <<'EOF'
set key_hold 0.15s
wait 3s
key ON
wait 16s
EOF
"$TILEM" --headless --rom badapple_rom.bin --model ti84p --normal-speed --reset \
  --macro run.macro --trace badapple.trace --trace-range all

# 5. Extract link-port (port 0x00) debug audio -> WAV -----------------------
python3 "$REPO_TOOLS/extract_linkport_audio.py" badapple.trace -o badapple_linkport_15mhz.wav
# Pitch/speed-corrected: the app targets the SE's ~33.3 kHz sound ISR; the 84+
# timer here fires it ~7x slower, so compress time to restore the intended pitch.
python3 "$REPO_TOOLS/extract_linkport_audio.py" badapple.trace \
  -o badapple_linkport_pitchcorrected.wav --cpu-hz 107000000
echo "Done: $WORK/badapple_music.wav and $WORK/badapple_linkport_*.wav"
