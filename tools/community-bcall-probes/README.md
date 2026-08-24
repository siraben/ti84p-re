# Community bcall probes

These fixtures exercise numeric bcalls found in the mirrored community source
corpus. They run calculator code only. No contributed host executable is used.

Build and run the custom-error witness with the patched headless TilEm described
in `tools/dynamic-tracing.md`:

```sh
nix develop -c spasm -E \
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
  --output /tmp/community-custom-error.csv
```

The checked result is in `tools/data/community-custom-error.csv`. The raw trace
and ROM remain outside Git; their SHA-256 identities bind the compact result to
those artifacts.
