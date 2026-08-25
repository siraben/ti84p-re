# Community bcall probes

These fixtures exercise numeric bcalls found in the mirrored community source
corpus. They run calculator code only. No contributed host executable is used.

Build and run the custom-error witness with the patched headless TilEm described
in `tools/dynamic-tracing.md`:

```sh
nix develop -c spasm \
  tools/community-bcall-probes/custom-error.asm \
  /tmp/community-custom-error.bin
nix develop -c python3 tools/community-bcall-probes/build.py \
  /tmp/community-custom-error.bin /tmp/community-custom-error-fixture

"$TILEM" --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/community-bcall-probes/custom-error.macro \
  --trace /tmp/community-custom-error.trace --trace-range all \
  --headless-record /tmp/community-custom-error.gif \
  /tmp/community-custom-error-fixture/AERR.8xp \
  /tmp/community-custom-error-fixture/ERRPROBE.8xp

nix develop -c python3 \
  tools/community-bcall-probes/analyze_custom_error.py \
  /tmp/community-custom-error.trace \
  --rom tools/rom.bin --emulator "$TILEM" \
  --payload /tmp/community-custom-error-fixture/ERRPROBE.8xp \
  --wrapper /tmp/community-custom-error-fixture/AERR.8xp \
  --macro tools/community-bcall-probes/custom-error.macro \
  --recording /tmp/community-custom-error.gif \
  --output /tmp/community-custom-error.csv
```

The checked result is in `tools/data/community-custom-error.csv`. The raw trace
and ROM remain outside Git; their SHA-256 identities bind the compact result to
those artifacts.

The symbolic-equate audit adds a return-path fixture for `_lcd_busy`,
`_BufClear`, `_bufInsert`, and `_NZIf83Plus`. It uses `_BufClear` and
`_bufInsert` only with the home-screen edit-buffer state established by direct
`Asm(` launch. Build and capture it with the accepted patched TilEm binary:

```sh
fixture_dir=$(mktemp -d /tmp/community-manual-bcalls.XXXXXX)
nix develop -c spasm \
  tools/community-bcall-probes/manual-valid.asm \
  "$fixture_dir/manual-valid.bin"
nix develop -c python3 tools/community-bcall-probes/build_manual.py \
  "$fixture_dir/manual-valid.bin" "$fixture_dir"

"$TILEM" --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/community-bcall-probes/manual-valid.macro \
  --trace /tmp/community-manual-bcalls.trace --trace-range all \
  "$fixture_dir/AMANUAL.8xp" "$fixture_dir/MANBCALL.8xp"

nix develop -c python3 tools/community-bcall-probes/analyze_manual.py \
  /tmp/community-manual-bcalls.trace /tmp/community-manual-bcalls.ram \
  --rom tools/rom.bin --emulator "$TILEM" \
  --payload "$fixture_dir/MANBCALL.8xp" \
  --wrapper "$fixture_dir/AMANUAL.8xp" \
  --output tools/data/community-manual-bcall-traces.csv
```

The analyzer requires one visit to each fixture-local `rst 28h` site, the
resolved OS targets, and the final return marker. The full symbolic-source
classification, including inactive target-platform branches, is in
`tools/data/community-symbolic-bcall-triage.csv`.

Four additional fixtures separate safe return paths from interactive and error
paths:

| Fixture | Builder | Macro | Analyzer | Reduced result |
|---|---|---|---|---|
| `semantics-safe.asm` | `build_semantics.py` | `semantics-safe.macro` | `analyze_semantics.py` | `tools/data/community-bcall-semantics.csv` |
| `getkey-ret-off.asm` | `build_getkey_ret_off.py` | `getkey-ret-off.macro` | `analyze_getkey_ret_off.py` | `tools/data/community-getkey-ret-off.csv` |
| `string-input.asm` | `build_string_input.py` | `string-input.macro` | `analyze_string_input.py` | `tools/data/community-string-input.csv` |
| `send-packet.asm` | `build_send_packet.py` | `send-packet.macro` | `analyze_send_packet.py` | `tools/data/community-send-packet.csv` |

Build each assembly file with `nix develop -c spasm -N -I .`, pass the raw
machine file to its builder, run the generated wrapper and payload with the
listed macro, and pass the trace, logical-RAM dump, raw machine file, generated
files, ROM, emulator, and macro to the matching analyzer. Each analyzer derives
the fixture-local bcall address from the assembled bytes and rejects missing
ROM bodies or result markers.

The safe fixture saves and restores hook target records and active flag bytes
before halting. The `_GetKeyRetOff` fixture drains an explicit **ENTER**, then
injects **2nd**+**ON**. The string-input fixture reconstructs Elite's
`ioPrompt`/`cleanTmp` setup and submits numeric input. The packet fixture
installs a calculator error handler and deliberately runs without a peer; its
accepted result stops at the header-send error and does not claim payload or
ACK success.

The Cool release supplies the negative case. Build `ACOOL = Asm(prgmCOOL)`,
then capture and reduce the packaged calculator program:

```sh
nix develop -c python3 tools/build_asm_wrapper.py \
  COOL /tmp/ACOOL.8xp --wrapper-name ACOOL

"$TILEM" --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/community-bcall-probes/cool-invalid.macro \
  --trace /tmp/community-cool-invalid.trace --trace-range all \
  --headless-record /tmp/community-cool-invalid.gif \
  /tmp/ACOOL.8xp "$ARCHIVE/extracted/graphics/cool.zip.contents/cool.8xp"

nix develop -c python3 \
  tools/community-bcall-probes/analyze_cool_invalid.py \
  /tmp/community-cool-invalid.trace --rom tools/rom.bin \
  --emulator "$TILEM" \
  --archive "$ARCHIVE/mirror/pub/83plus/asm/graphics/cool.zip" \
  --source "$ARCHIVE/extracted/graphics/cool.zip.contents/cool.asm" \
  --program "$ARCHIVE/extracted/graphics/cool.zip.contents/cool.8xp" \
  --wrapper /tmp/ACOOL.8xp \
  --macro tools/community-bcall-probes/cool-invalid.macro \
  --recording /tmp/community-cool-invalid.gif \
  --output /tmp/community-cool-invalid.csv
```

The checked reduction is `tools/data/community-invalid-bcall-traces.csv`.
It validates the release bytes and overlapping ROM-table bytes before accepting
the dynamic path.
