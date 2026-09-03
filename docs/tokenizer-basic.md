# Tokenizer and TI-BASIC tokens

TI-BASIC source is stored as a sequence of one- and two-byte tokens, not as the
characters shown in the editor. Tokenization chooses that encoding; execution
walks it; detokenization turns it back into display text.

## Encoded width

Most tokens occupy one byte. `_IsA2ByteTok` (`00:1FE8`) decides whether a byte
introduces a two-byte token by searching `two_byte_token_lead_table`
(`00:1FF6`), an 11-byte list of lead bytes:

| Lead | Group |
|------|-------|
| `5Ch` | Matrices |
| `5Dh` | Lists |
| `5Eh` | Equation variables |
| `60h` | Pictures |
| `61h` | Graph databases |
| `62h` | Output/Y-variable group |
| `63h` | System variables |
| `7Eh` | Graph-format group |
| `BBh` | General extended commands |
| `AAh` | String variables |
| `EFh` | TI-84 Plus extensions |

The first byte selects a group and the second selects an entry in that group.
For example, `5D 00` is `L1`, while `BB 6A` is `Asm(`. The complete second-byte
maps are in [the token tables](token-tables.md). [confirmed]

Encoded width and displayed width are different questions:

- `_IsA2ByteTok` answers whether the stored token uses one or two bytes.
- `_GetTokLen` (`01:66E5`) returns the length of the token's displayed name.
- `_Get_Tok_Strng` (`01:66EA`) returns that display string.

The editor uses the latter two operations to paint source. Parser scanners use
the first operation so they never mistake the second byte for a command or
delimiter. [confirmed]

## Editor conversion and insertion [confirmed]

The token editor tracks four little-endian pointers in one fixed block:

```c
#pragma pack(push, 1)
typedef struct {
    uint16_t top;      /* +0x00, editTop at 0x96F4 */
    uint16_t cursor;   /* +0x02, editCursor at 0x96F6 */
    uint16_t tail;     /* +0x04, editTail at 0x96F8 */
    uint16_t bottom;   /* +0x06, editBtm at 0x96FA */
} EditorBufferState;  /* 8 bytes */
#pragma pack(pop)
```

`_BufClear = 0x4936`, body `ram:222E`, sets `editCursor = editTop` and
`editTail = editBtm`. It does not wipe every byte between those pointers.

`_bufInsert = 0x4909`, body `06:42E5`, accepts a token in `DE`. It first checks
for room at the cursor. When `D = 0`, it inserts the one-byte token from `E`;
when `D != 0`, it performs a second room check and writes the two bytes in
`D,E` order. Success advances `editCursor` and returns NZ. A full buffer or
failed second-byte check returns Z without reporting success. A controlled
trace calls the clear body, calls the insert body with `DE = 0xBB6A` (`Asm(`),
calls the clear body again, and returns from every call. The pointer mutations
above are confirmed from the ROM body; that return-path reducer does not
snapshot the transient buffer contents. [confirmed] under TilEm.

`_ConvKeyToTok = 0x4A02`, body `07:44DE`, converts a cooked key in `A` to a
token in `DE`. Input `0x05` has the dedicated result `DE = 0x003F`. Ordinary
inputs subtract `0x5A` and select a byte from the table beginning at
`07:4000`; special inputs `0xFB`, `0xFC`, and `0xFE` use `keyExtend` at
`ram:8446` and the tables rooted at `07:4426`, `07:422C`, `07:4099`, or
`07:4102`. The latter paths can return two-byte tokens. A controlled trace
confirms `A = 0x05` → `DE = 0x003F`; the special-table cases remain confirmed
from ROM control flow, not exhaustively traced. Reduced results are in
`tools/data/community-manual-bcall-traces.csv` and
`tools/data/community-bcall-semantics.csv`.

## One source line, three representations

The statement

```ti-basic
cumSum(L1)->L2
```

is stored as:

```text
BB 29  5D 00  11  04  5D 01  3F
└───┘  └───┘   │   │   └───┘   └─ EOL
cumSum(  L1    )   →     L2
```

No source spaces or character count are preserved. The editor reconstructs
the spelling from token tables. The interpreter sees typed operations and
names immediately, without reparsing the visible word `cumSum`. [confirmed]

## Token streams and execution

The tokenizer and interpreter meet at the parse cursor. The current byte is
fetched at `38:72DA`; `38:4180` skips logical tokens while respecting two-byte
leads and quoted strings. The expression evaluator then maps the token to a
grammar class and selects a recursive production. [confirmed]

This division explains several behaviors:

- `3Fh` ends a stored line even though no newline character is displayed in
  the token stream.
- bytes resembling `Then` or `End` inside a quoted string are data because the
  quoted-string scanner consumes the whole region.
- a second byte following `5Dh`, `BBh`, or another lead cannot be interpreted
  independently.
- display names can change in width without changing encoded width.

The pointer table at `38:4000` belongs to expression dispatch, not tokenization.
It contains little-endian handler addresses selected after token classification.
See [TI-BASIC execution](sub-tibasic.md#expressions-are-nested-productions) for
the evaluator and [TI-BASIC dynamic tracing](sub-tibasic-tracing.md) for the
bounded token-width and scan models.

## Reproducible samples

`tools/ti84re/tibasic/samples.py` generates readable `.bas`, raw `.tok`, and loadable
`.8xp` forms from one definition. Treat `.bas` as the review form, `.tok` as
the exact interpreter input, and `.8xp` as the calculator fixture. A compact,
diverse subset is used for dynamic coverage; the generator retains the broader
fixture library for targeted subsystem investigations.

```sh
python3 -m ti84re.tibasic.samples --write-dir tools/tibasic-samples
```

The generator's byte assertions catch accidental changes between the readable
source and the token body. Calculator execution is still required to establish
runtime behavior.
