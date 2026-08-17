# MathPrint cell strings through `_KeyToString`

This note documents how TI-84 Plus OS 2.55MP converts an ordinary page `0x39`
MathPrint cell `D:E` into a counted display string. Addresses use `pp:addr`.
[confirmed]

## Call boundary

The generic string selector begins at `39:6B66`. Selected `FB:E` values use
inline counted strings; all other cells reach `39:6B9C`. The complete bytes at
that address are:

```z80
39:6B9C  EF CA 45    bcall 45CAh   ; _KeyToString
39:6B9F  C9          ret
```

The bcall ID is `_KeyToString = 45CAh`: `CA 45` are its two little-endian
ID bytes, and the following `C9` is a separate `RET`. The page `0x3B` bcall
table resolves `_KeyToString` to `01:6D10`. [confirmed]

## Index selection

`_KeyToString` does not directly index the standard token-name table with
`D:E`. Its branches first derive an index into the word-pointer table at
`01:6E05`. The byte-anchored implementation and structural samples are in
`tools/dump-mathprint-layout.py` (`key_to_string_index` and
`dump_key_string_structural_flow`). [confirmed]

For low-byte, non-prefix cells, the recovered index rules are:

| Cell condition | Pointer-table index |
|---|---:|
| `E < 0x40`, except `E = 0x1F` | use `E - 0x10` if at most `0x64`; otherwise use fallback `0x13` |
| `E = 0x1F` | `0x50 + D` |
| `E = 0x59` | `0x61 + D` |
| `E = 0x4C` | `0x5F + D` |
| `E = 0x56` or `E = 0x42` | adjusted `E + 0x16 + D - 0x1B - 0x10`, clamped as above |
| other `0x40 <= E < 0x5A` | adjusted `E - 0x1B - 0x10`, clamped as above |

Every computed index is an eight-bit value. `01:6D96` replaces values at or
above `0x65` with fallback index `0x13`; this clamp also applies to the
`E=1F`, `E=59`, and `E=4C` additions. The special cell `10:40` instead selects
the literal at `01:6F4D`. [confirmed]

After index selection, `_KeyToString` reads a word from `01:6E05 + 2*index`
and copies the selected counted string. The clamp proves that the main entry
can address exactly 101 words. All 101 pointers and strings are extracted into
`web/mathprint/token-strings.json`. For example, low-byte `E=0x1F` cells occur
in root/power handler records and produce fixed strings through `_PutPSB`.
This path has no height input or tall-glyph stretching primitive. [confirmed]

## Prefix and high-byte paths

`FB` and `FC` cells call `_sOK` at `07:44FE` with `H=2`. `FE` and `FF` cells
enter it with `H=1`; the preserved zero flag makes both select the FE family.
The result passes through the complete `01:6702` token-string selector. The
JavaScript model compares all $4 \times 256$ caller-valid `_sOK` inputs with a
pinned-byte interpreter. [confirmed]

For other cells whose `E` byte is at least `0x5A`, `01:6DBD` first scans 13
key/pointer triples at `01:6DDE`. A match returns that counted string directly.
A miss treats `E` as a classic display byte, calls `07:44DE`, and sends its
result through `01:6702`. The extracted artifact includes all 13 direct
strings. [confirmed]

`settledPage1KeyToStringSelection()` compares every one of the 65,536 `D:E`
pairs against the pinned `01:6D10–6DBC` bytes with both hook flags clear. It
resolves all 447 unique key-string cells present in the decoded handler records
and descriptors. Raw prefix combinations that select beyond a declared token
table stop at that pointer boundary instead of reading adjacent ROM data as a
string. [confirmed]

## Inline `FB` strings

Before the `_KeyToString` fallback, `39:6B66` recognizes several `FB:E` values
and returns local counted strings, including `FBC8`, `FBCA`, `FBCB`, `FBD6`,
`FBD7`, and `FBD8`. Their exact bytes and branch conditions are verified by
`tools/dump-mathprint-layout.py`. `settledPage39CellStringSelection()` covers
all 131,072 combinations of the two `H`-bit entry modes and `D:E`; `FBC8` is
inline only when `H.0` is set. [confirmed]

## Scope

The MathPrint path reaches `_KeyToString` at `01:6D10`, with the complete
normal-ROM selection described above. Font-hook bit `(IY+35h).1` and token-hook
bit `(IY+35h).0` can delegate pointer selection to installed external code;
the translation reports those calls as boundaries. It does not establish an
alias with `_Get_Tok_Strng` or `_GETTOKSTRING`. [confirmed]
