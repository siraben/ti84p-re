# Community link probes

This fixture separates two results from the archived TI-83 Plus link tutorial:

- both shipped calculator files use the `**TI83**` container signature and the
  TI-84 Plus OS rejects the attempted wrapped launch with `ERR:INVALID`;
- a TI-83+ fixture transcribing only the tutorial's initial one-sided wait
  reads idle value `0x03`, writes `0xD1` to port `0x00`, scans the MODE row on
  port `0x01`, and returns when MODE is injected.

The second result is a behavioral witness, not a byte-identical rebuild of the
release. It has no peer and does not establish electrical voltage or polarity.

Build, run, and reduce it with the patched headless TilEm documented in
`tools/notes/dynamic-tracing.md`:

```sh
nix develop -c spasm -E \
  tools/probes/community/link/link-wait.asm /tmp/community-link-wait.bin
nix develop -c python3 tools/probes/community/link/build.py \
  /tmp/community-link-wait.bin /tmp/community-link-wait-fixture

"$TILEM" --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/probes/community/link/run-one-sided.macro \
  --trace /tmp/community-link-wait.trace --trace-range all \
  --headless-record /tmp/community-link-wait.gif \
  /tmp/community-link-wait-fixture/AALINK.8xp \
  /tmp/community-link-wait-fixture/LINKWAIT.8xp
```

The checked compact results are `tools/data/community-link-wait.csv` and
`tools/data/community-linktutorial-release.csv`. Raw traces remain outside Git;
their hashes bind the rows to the exact captures.
