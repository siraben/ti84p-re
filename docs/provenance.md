# Build and evidence provenance

Reverse-engineering results are meaningful only when their ROM, hardware or
emulator profile, include file, and analysis tools are identifiable. This
repository uses SHA-256 identities rather than filenames as the primary
provenance boundary.

## Two local OS 2.55MP images

The repository recognizes two complete-image identities. Their OS pages are
the same, but their boot support differs. [confirmed]

| Image | SHA-256 | Page `0x2F` | Page `0x3F` |
|---|---|---|---|
| Canonical retail analysis image | `7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d` | `D84PBE2` USB boot page | Retail boot 1.03 |
| BootFree runtime-trace image | `dbb47afae091ab36f9abe74e32083013fbeff3d7e0516bbf5d1abf4ee57adc09` | Patched-base page | BootFree 11.259 |

The canonical image starts from `ti84plus_patched.rom`, whose SHA-256 is
`90472848b5f56902287fd5d8b455e62d60e9ab054647c9a03c1c91a67fc1a95a`.
`D84PBE2.8Xv` supplies page `0x2F`; `D84PBE1.8Xv` supplies page `0x3F`, although
that decoded retail page is byte-identical to the base image's page `0x3F`.
The exact AppVar and decoded-page identities are pinned in
`tools/rom_signatures.py`. [confirmed]

The BootFree image matches the patched base on pages `0x00`–`0x3E`. Only page
`0x3F` differs, with SHA-256
`b3ae75aa81231de15e5931746d79834863132d5e4dca01010e3a8e24aabd3003`.
Its acquisition artifact is not pinned, so this is a page-identity statement,
not a physical-capture provenance claim. [confirmed]

Use the retail image for boot-table, USB boot, reset, recovery, certificate,
and page-`0x3F` claims. A BootFree trace can establish behavior confined to
unchanged pages, provided the result records the complete-image hash and the
relevant page identity. It cannot establish retail boot behavior. [standard]

## BootFree callable surface and reset path

`tools/data/boot-page-comparison.csv` compares all 87 populated `0x8xxx`
table entries. Every target address differs. BootFree implements 38 entries,
maps 45 entries to a bare `RET`, and maps four entries to small constant-return
stubs. The six retail entries whose bodies live on USB boot page `0x2F` all map
to BootFree's bare-`RET` stub. [confirmed]

The reset paths also differ before any OS code runs: [confirmed]

| Step | Retail boot 1.03 | BootFree 11.259 |
|---|---|---|
| Reset stub | Writes ports `0x04`, `0x06`, and `0x0E`, then jumps to `0x812C` | Maps page `0x3F` through ports `0x06` and `0x07`, then jumps to `0x812C` |
| Installed-OS test | Scans the keypad; DEL and STAT select recovery; otherwise tests byte `0x0038` and marker `0xA55A` at `0x0056` | Does not scan a recovery key; tests only marker `0xA55A` at `0x0056` |
| Missing or rejected OS | Enters serial or USB-assisted recovery and can receive an OS | Displays `No OS Loaded` and halts |
| Boot services | Certificate, validation, serial receive, USB receive, installer display, and error paths | Smaller Flash/certificate utility set; signature, receive, USB, and most installer-display entries are stubs |

The CSV classifies every public callable table slot, not every internal helper
entry in either page. A complete internal-routine comparison still requires
matched function-entry recovery for both images. [confirmed]

## Generate a manifest

`tools/rom_provenance.py` records the complete ROM identity, target model,
ASIC revision, OS version, boot-page classification, component page ranges,
the 2007 include-file identity, Ghidra version, Git revision, dirty-tree state,
and a digest over the top-level analysis scripts.

```sh
nix develop -c python3 tools/rom_provenance.py manifest \
  --rom tools/rom.bin --model 'TI-84 Plus' --asic 'TilEm x4' \
  --output /tmp/ti84p-provenance.json
```

The generated manifest reports an unknown component map for an unrecognized
ROM rather than silently assigning it a known OS identity. [confirmed]

## Reject stale results

Checked CSV result tables use a `rom_sha256` column. JSON reports use either a
`rom_sha256` field or a `rom.sha256` object. Verify them against the current
manifest before reuse:

```sh
nix develop -c python3 tools/rom_provenance.py verify \
  --manifest /tmp/ti84p-provenance.json \
  tools/data/launch-boundary-results.csv \
  tools/data/resident-launch-snapshot.csv
```

The command rejects missing, mixed, or mismatched identities. Raw TLMT traces
do not embed a ROM hash, so they require a JSON provenance sidecar; verify the
sidecar rather than treating the trace filename as evidence. [confirmed]

## Audit the Ghidra database

`tools/DatabaseHealth.java` makes database coverage and cleanup debt
machine-readable. Run it against the existing project without analysis or
writes:

```sh
nix develop -c ghidra-analyzeHeadless "$PWD" ti84 \
  -process -noanalysis -readOnly -scriptPath "$PWD/tools" \
  -postScript DatabaseHealth.java tools/data/database-health.json
```

The checked report identifies the BootFree runtime-trace image by its complete
ROM hash. It records 64 loaded Flash pages, 27,995 instructions, 2,413
functions, and 94.081086 percent of instructions inside functions. The listing
has no overlapping instructions. It also lists each of the 163 unresolved
inline cross-page jumps and 45 primary symbols that have neither an instruction
nor typed storage at their address. [confirmed]

The 989,125 undefined Flash bytes are addresses with no defined Ghidra code or
data unit. That number measures database coverage; it does not imply that those
bytes are unused or safe to overwrite. Likewise, an unresolved jump is a
specific analysis task, not evidence that the ROM's control flow is invalid.
[standard]

The health report is deterministic for a given database, script revision, and
Ghidra version. Its `rom_sha256` field can be checked with
`tools/rom_provenance.py verify`; use a separately rebuilt retail project when
auditing retail boot and USB pages. [standard]

## Evidence limit

A matching hash proves byte identity, not how the image was obtained. The ASIC
field distinguishes a physical revision from an emulator profile but does not
turn emulator behavior into hardware evidence. Git and script-tree identities
make an analysis run reproducible; they do not by themselves validate the
analysis conclusion.
