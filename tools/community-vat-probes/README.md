# Community VAT probes

These fixtures dynamically check the community VAT and archive behaviors
documented in `docs/sub-vat-archive.md`. They run only calculator-side `.8xp`
artifacts under patched TilEm. The build script reads archive members as data;
it never executes contributed host programs.

Build the fixtures under the repository development environment:

```sh
fixture_dir=$(mktemp -d /tmp/community-vat-fixtures.XXXXXX)
nix develop --command python3 tools/community-vat-probes/build.py \
  --corpus "$COMMUNITY_ARCHIVE/mirror/pub/83plus/asm" \
  --out-dir "$fixture_dir"
```

Use the patched TilEm build documented in `tools/dynamic-tracing.md`. Each
macro names its `/tmp` trace-adjacent RAM, ROM, and screenshot outputs. Load
files in the order shown so the BASIC launcher runs first while the community
selector retains a deterministic VAT order:

```sh
TILEM=/path/to/patched/tilem2

$TILEM --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/community-vat-probes/prgmhide-archive.macro \
  --trace /tmp/community-prgmhide-final.trace --trace-range all \
  "$fixture_dir/ZTARGET.8xp" "$fixture_dir/PRGMHIDE.8xp" \
  "$fixture_dir/APHIDE.8xp"

$TILEM --headless --rom /tmp/community-prgmhide-archive.rom \
  --model ti84p --normal-speed --reset \
  --macro tools/community-vat-probes/prgmhide-cold-reset.macro \
  --trace /tmp/community-prgmhide-cold-reset.trace --trace-range all
```

The remaining macros use the same command shape. `prgmappv-convert.macro` and
`prgmappv-archived-refusal.macro` load their target, `PRGMAPPV.8xp`, then
`AAPPV.8xp`. `hide-type-write.macro` loads `STR0.8xs`, `ZTARGET.8xp`,
`HIDE.8xp`, then `AHIDE.8xp`. The scan and live/dead Archive Utility macros use
`archive-live-dead.rom` and load `ARCHUTIL.8xp` followed by `AARCHUT.8xp`.
`archive-extract-cross-page.macro` uses `archive-cross-page.rom` with the same
two calculator files.
`numeric-bcalls.macro` loads `NUMBCALL.8xp` and `ANUMCALL.8xp`.

After collecting every trace, validate the RAM/Flash results and write the
machine-readable table:

```sh
nix develop --command python3 tools/community-vat-probes/analyze.py \
  --fixture-dir "$fixture_dir" --rom tools/rom.bin --emulator "$TILEM" \
  --output tools/data/community-vat-dynamic-observations.csv
```

The archive image contains one live `ProgObj` record at `08:4001` and one
deleted `ProtProgObj` record at `08:4013`. It is a controlled fresh-sector
fixture, not a claim that the deleted state arose from the OS delete UI. The
unmodified Archive Utility code performs both recoveries. Its final ROM dumps
must remain byte-identical to the input image.

The separate cross-page image places a `ProgObj` record at `08:7FE0`. Its
34-byte size-and-data field begins at `08:7FEF` and reaches page `09`. The
extraction assertion requires every payload byte and an unchanged Flash image.

The numeric-bcall fixture safely calls `5011h` (`_FillBasePageTable`) and
`5014h` (`_ArcChk`). It leaves `50C8h` (`_UngroupVar`) unexecuted because that
routine requires an authentic `GroupObj` and caller state. The community sites
are `programs/2dca.zip:source/Cherries.z80`,
`libs/rage.zip:RAGE/RAGE.asm`, and
`libs/c3asm.zip:C3ASM/_CELTIC/CELTIC3.ASM`, respectively.
