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

For non-prefix cells, the recovered index rules are:

| Cell condition | Pointer-table index |
|---|---:|
| `E < 0x40`, except `E = 0x1F` | use `E - 0x10` if at most `0x64`; otherwise use fallback `0x13` |
| `E = 0x1F` | `0x50 + D` |
| `E = 0x59` | `0x61 + D` |
| `E = 0x4C` | `0x5F + D` |
| `E = 0x56` or `E = 0x42` | adjusted `E + 0x16 + D - 0x1B - 0x10`, clamped as above |
| other `0x40 <= E < 0x5A` | adjusted `E - 0x1B - 0x10`, clamped as above |

`D` values `0xFB`, `0xFC`, `0xFE`, and `0xFF`; `E >= 0x5A`; and the special
cell `D:E = 0x10:0x40` take separate control/prefix paths. Treating all of them
as ordinary table indices is incorrect. [confirmed]

After index selection, `_KeyToString` reads a word from `01:6E05 + 2*index`
and copies the selected counted string. For example, low-byte `E=0x1F` cells
use `index = 0x50 + D`; these occur in root/power handler records and produce
fixed strings through `_PutPSB`. This path has no height input or tall-glyph
stretching primitive. [confirmed]

## Inline `FB` strings

Before the `_KeyToString` fallback, `39:6B66` recognizes several `FB:E` values
and returns local counted strings, including `FBC8`, `FBCA`, `FBCB`, `FBD6`,
`FBD7`, and `FBD8`. Their exact bytes and branch conditions are verified by
`tools/dump-mathprint-layout.py`. [confirmed]

## Scope

The MathPrint path reaches `_KeyToString` at `01:6D10`, with the branch-specific
pointer-table indexing described above. It does not establish an alias with
`_Get_Tok_Strng` or `_GETTOKSTRING`. [confirmed]
