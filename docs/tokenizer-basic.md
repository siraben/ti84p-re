# Tokenizer and TI-BASIC tokens

TI-BASIC source is stored as a sequence of one- and two-byte tokens, not as the
characters shown in the editor. Tokenization chooses that encoding; execution
walks it; detokenization turns it back into display text.

## Encoded width

Most tokens occupy one byte. `_IsA2ByteTok` (`00:1FE8`) decides whether a byte
introduces a two-byte token by searching the 11-byte table at `00:1FF6`:

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

`tools/tibasic_samples.py` generates readable `.bas`, raw `.tok`, and loadable
`.8xp` forms from one definition. Treat `.bas` as the review form, `.tok` as
the exact interpreter input, and `.8xp` as the calculator fixture. A compact,
diverse subset is used for dynamic coverage; the generator retains the broader
fixture library for targeted subsystem investigations.

```sh
tools/tibasic_samples.py --write-dir tools/tibasic-samples
```

The generator's byte assertions catch accidental changes between the readable
source and the token body. Calculator execution is still required to establish
runtime behavior.
