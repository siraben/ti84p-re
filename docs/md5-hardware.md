# MD5 accelerator and boot API

*TI-84 Plus OS 2.55MP — ASIC round assist, streaming digest bcalls, and Rabin hash transformation.*

The TI-84 Plus ASIC evaluates one MD5 compression step through ports `0x18`–`0x1F`. Retail boot code builds the complete streaming MD5 algorithm around that operation. This page reconstructs the port transaction, all 64 table-driven compression steps, the boot bcall state machine, the local counter-width quirk, and the separate `_TransformHash` operation used by application-signature code.

## Evidence layers

The port block is internal to the ASIC, so public descriptions and emulator code cannot prove every electrical or timing detail. Claims below keep the evidence sources separate.

| Layer | Main evidence | What it establishes |
|-------|---------------|---------------------|
| Retail boot ROM | `3F:68ED`–`3F:6BF5` and `3F:723F`–`3F:72EA` | bcall ABI, buffers, descriptor format, exact port order, padding, length accounting, and hash transformation [confirmed] |
| Dynamic execution | `tools/tibasic-samples/MD5TEST.8xp`, a complete resolved TilEm trace, and guarded TilEm, Wabbitemu, and MAME probes | 64 valid operations for `MD5("abc")`, implementing-emulator edge semantics, and MAME's live unmapped-port behavior [confirmed] |
| Independent calculation | `tools/md5_hardware.py` | every recorded result agrees with the 32-bit operation derived from the ROM and RFC 1321 [confirmed] |
| Public hardware notes | WikiTI port `0x18` and MD5 bcall pages | historical port and ABI descriptions checked against the local ROM [standard] |
| Emulator models | TilEm `f56ad63`, Wabbitemu `48c2dc0`, and MAME 0.287 | shift-register policy, masking, reset policy, implemented undefined reads, and MAME's missing port block [standard] |
| Algorithm specification | RFC 1321 | MD5 state, Boolean functions, constants, rotations, padding, and test vectors [standard] |

WikiTI is used as a comparison source, not as proof. For example, its `_MD5Update` page describes an eight-byte length, while the local routine updates only the low four bytes. Its `_TransformHash` page lists the four valid selectors, while the ROM maps every other nonzero low selector byte to the same branch as selector 3. [confirmed]

## What the hardware accelerates

The port block does not hash a message or compress a 64-byte block by itself. It evaluates the arithmetic for one of MD5's 64 steps: [confirmed] for the ROM transaction; [standard] for the algorithm identity.

$$
R = B + \operatorname{ROTL}_{32}\left(A + f(B,C,D) + X + T,\ s\right)
\pmod {2^{32}}
$$

The six 32-bit operands are `A`, `B`, `C`, `D`, one message word `X`, and the additive constant `T`. The rotate count is `s`. Mode `0`–`3` selects the Boolean function. [standard]

| Mode | MD5 name | Function |
|-----:|----------|----------|
| `0` | F | $(B \mathbin{\\&} C) \mathbin{\vert} ((\mathop{\sim}B) \mathbin{\\&} D)$ |
| `1` | G | $(B \mathbin{\\&} D) \mathbin{\vert} (C \mathbin{\\&} \mathop{\sim}D)$ |
| `2` | H | $B \mathbin{\oplus} C \mathbin{\oplus} D$ |
| `3` | I | $C \mathbin{\oplus} (B \mathbin{\vert} \mathop{\sim}D)$ |

All additions and the rotation operate on 32-bit words. The returned word is little-endian across the four read ports. [confirmed]

## Port interface

### Register map

Writes to `0x18`–`0x1D` load six independent 32-bit serial registers. Four bytes are written to one port, least-significant byte first. Reads from `0x1C`–`0x1F` expose the calculated word rather than the values last written to those ports. [confirmed] for the ROM's use; [standard] for the public port contract.

| Port | Write behavior | Read behavior |
|-----:|----------------|---------------|
| `0x18` | serial input for `A` | undefined on physical hardware |
| `0x19` | serial input for `B` | undefined on physical hardware |
| `0x1A` | serial input for `C` | undefined on physical hardware |
| `0x1B` | serial input for `D` | undefined on physical hardware |
| `0x1C` | serial input for message word `X` | result bits 7–0 |
| `0x1D` | serial input for constant `T`, called AC by WikiTI | result bits 15–8 |
| `0x1E` | rotate count `s` | result bits 23–16 |
| `0x1F` | Boolean-function selector | result bits 31–24 |

The ROM writes every operand on every step. It does not depend on power-on contents or persistence from a previous operation. It writes the mode first, then `A` through `T`, then the rotate count, and immediately reads the result. There is no busy-bit poll or delay loop. [confirmed]

Both TilEm and Wabbitemu model each operand port as a four-byte sliding register: [standard]

```pseudocode
on write byte v to operand register r:
    r = (r >> 8) | (v << 24)
```

Four writes `b0`, `b1`, `b2`, `b3` therefore leave `r = b0 + 2^8 b1 + 2^16 b2 + 2^24 b3`. A fifth write discards the oldest low byte in both emulators. Physical behavior after fewer or more than four writes has not been measured. [standard] for emulator behavior; [hypothesis] for the physical sliding-register implementation.

TilEm and Wabbitemu also mask a write to `0x1E` with `0x1F` and a write to `0x1F` with `0x03`. Both return zero for reads from `0x18`–`0x1B`. The ROM uses only valid rotate counts and modes and never reads those four ports, so the local image cannot verify the masks or zero values. [standard]

Guarded native TilEm and Wabbitemu runs exercise these edge cases through their
initialized-core port handlers. Neither adapter executes the retail MD5
routine. The Wabbitemu adapter initializes its core with the exact OS 2.55MP
image; the TilEm adapter does not load a ROM. [standard]

| Case | Native result |
|------|---------------|
| Fresh reads from `0x18`–`0x1B` | `00 00 00 00`; the fresh calculated result is `0x00000000` |
| One byte `11` written to operand `A` | `0x11000000` |
| Three bytes `11 22 33` | `0x33221100` |
| Four bytes `11 22 33 44` | `0x44332211` |
| Fifth byte `55` | `0x55443322`; the former low byte `11` is discarded |
| Raw shift and mode writes `FF`, `FF` | `0x00000004`, matching shift 31 and mode 3 for operands 1 through 6 |
| Reads from `0x18`–`0x1B` after operand loads | `00 00 00 00` |
| Mutate `A` between result-byte reads | old result `0xD6D117B4`, new result `0x343F9701`, assembled read `0x343F97B4` |

The mixed result retains the old low byte `B4` read from port `0x1C`, then
uses the new high bytes `97 3F 34` from ports `0x1D`–`0x1F`. Both runs
therefore exercise read-time recalculation. Direct port calls add zero modeled
CPU clocks in both implementations. [standard]

**Native TilEm confirmation.** The TilEm run also reads the stored control
fields as shift 31 and mode 3 after raw `0xFF` writes. A seeded calculator
reset clears all six operands, both controls, and the resulting word. Two
isolated builds produce binary SHA-256
`b461e9720e0c304b26ab95ca814943eddfba670dd7bd1e41b48d53a0f8c689c5`.
Their canonical native JSON has SHA-256
`97921226800da92b585b6d16a390355c157bf9aa5976fe47d183e87bbcbad1b8`.
[standard]

TilEm computes a zero-count rotation as
`(result << s) | (result >> (32 - s))`. With `s = 0`, the second operand shifts
a 32-bit value by 32, which C99 leaves undefined. The locked GCC build produces
the one-, three-, four-, and five-write results in the table. That observation
is a property of this binary, not a portable result guaranteed by TilEm's C
source. [standard]

**Native Wabbitemu confirmation.** The Wabbitemu binary SHA-256 is
`e5c64ec8630b0eaa9d42632ae8f559440678a567c00d0d1ce903fc99815afe81`.
Its initialized-core report matches every table row and advances zero
T-states. [confirmed] for the pinned Wabbitemu run.

MAME's TI-84 Plus I/O map has no handlers for ports `0x18`–`0x1F`.
The ROM transaction therefore reaches unmapped I/O instead of an MD5 assist
block. MAME cannot execute the valid hardware-assisted compression path.
Its TI-84 Plus driver is marked `MACHINE_NOT_WORKING`. [standard]

A guarded MAME 0.287 run reads all eight ports through the main CPU's I/O
address space. Initial reads return eight `00` bytes. Writes of eight distinct
patterns leave the same eight-zero readback. The probe then issues the first
padded-`"abc"` transaction from `3F:6A0F`. Independent arithmetic expects
`0xD6D117B4`; MAME returns `0x00000000`, and a final read of all eight ports
still returns zero. Two isolated runs reproduce the same report. [confirmed]

This zero is MAME's runtime value for the unmapped accesses. It is not a
register-reset value, an MD5 result from the calculator, or evidence about an
electrical open bus. The run invokes MAME's CPU I/O address space through Lua;
it does not execute the retail bcall or physical hardware. [confirmed]

### One ROM transaction

`md5_assist_step` at `3F:6A0F` consumes one ten-byte descriptor through `IX`. The helper routines at `3F:6B7E`–`3F:6BDD` emit four successive bytes from RAM for `A` through `T`. The routine then writes `s` and reads the result into the state word selected by descriptor byte 0. [confirmed]

The I/O sequence is fixed: [confirmed]

```text
OUT 1F                         mode
OUT 18 × 4                    A, little-endian
OUT 19 × 4                    B, little-endian
OUT 1A × 4                    C, little-endian
OUT 1B × 4                    D, little-endian
OUT 1C × 4                    X, little-endian
OUT 1D × 4                    T, little-endian
OUT 1E                         s
IN  1C, 1D, 1E, 1F            R, little-endian
```

This is 30 I/O instructions per MD5 step. One compression block executes 64 steps and therefore produces 1,920 port events: 1,664 writes and 256 reads. [confirmed]

The first operation in the `"abc"` trace uses: [confirmed]

| Operand | Value |
|---------|------:|
| `A` | `0x67452301` |
| `B` | `0xEFCDAB89` |
| `C` | `0x98BADCFE` |
| `D` | `0x10325476` |
| `X` | `0x80636261` |
| `T` | `0xD76AA478` |
| `s` | `7` |
| mode | F |
| result | `0xD6D117B4` |

`X = 0x80636261` is the first little-endian message word: ASCII `61 62 63` followed by the `0x80` padding byte. Independent evaluation of the formula returns `0xD6D117B4`. [confirmed]

### Immediate result and timing boundary

The boot routine reads `0x1C` on the instruction following the rotate-count output. This proves that software does not initiate a separate operation or wait for completion. It does not establish whether the physical ASIC is combinational, completes within the I/O cycle, or inserts an internal wait state. [confirmed] for instruction order; [hypothesis] for the physical circuit.

TilEm and Wabbitemu recalculate the full result on every read. Mutating an operand between result-byte reads can therefore create a word assembled from different calculations in those emulators. The ROM never does this. Physical result latching has not been tested. [standard] for emulator behavior; [hypothesis] for hardware.

## Boot-page MD5 API

The retail boot bcall table exposes three streaming routines. A bcall ID is the word after `rst 28h`; the body executes on page `3F`. [confirmed]

| Bcall | ID | Body | Input | Main output |
|-------|---:|------|-------|-------------|
| `_MD5Init` | `808D` | `3F:68ED` | none | initial state and zero bit length |
| `_MD5Update` | `8090` | `3F:6907` | `HL` data, `BC` byte count | buffered input and updated state |
| `_MD5Final` | `8018` | `3F:6964` | initialized state | padded final digest |

The caller invokes `_MD5Init` once, `_MD5Update` zero or more times, and `_MD5Final` once. `_MD5Update` accepts a 16-bit byte count per call and can process many complete blocks. [confirmed]

### RAM state

The API uses fixed system RAM rather than a caller-owned context structure. Two independent hashes cannot be interleaved without copying this state. [confirmed]

| Address | Size | Meaning |
|---------|-----:|---------|
| `0x8259` | 16 | working words copied from the current state |
| `0x8269` | 8 | message length in bits; only the low four bytes are updated |
| `0x8291` | 1 | compact-big-integer length prefix written by `_MD5Final` |
| `0x8292` | 16 | state words and final digest bytes |
| `0x83A5` | 64 | partial or current message block |

The official equates call these regions `MD5Temp`, `MD5Length`, `MD5Hash`, and `MD5Buffer`. `_TransformHash` later reuses `MD5Buffer` for a different compact-big-integer value. [confirmed]

### Initialization

`_MD5Init` copies 16 bytes from `3F:6615` to `MD5Hash`: [confirmed]

```text
01 23 45 67  89 AB CD EF  FE DC BA 98  76 54 32 10
```

Read as four little-endian words, these are the standard initial state: [standard]

| Word | Value |
|------|------:|
| `A` | `0x67452301` |
| `B` | `0xEFCDAB89` |
| `C` | `0x98BADCFE` |
| `D` | `0x10325476` |

The following eight bytes in ROM are zero, and the same `LDIR` sequence copies them to `MD5Length`. The routine preserves the caller's `HL`, `BC`, and `DE` with stack saves. It does not preserve flags as a distinct API result. [confirmed]

### Buffer index

`md5_buffer_index` at `3F:694F` derives the next byte position from the low 16 bits of the bit counter: [confirmed]

$$
i = \left(\frac{\text{bitLength}}{8}\right) \bmod 64
$$

Only counter bits 3–8 affect this value, so reading two bytes is sufficient even though the nominal counter occupies eight bytes. `_MD5Update` computes `i` before adding the new call's length. [confirmed]

### Length accounting and the 32-bit wrap quirk

`_MD5Update` expands `BC` to four bytes at `0x8251`, shifts that temporary left three times, and adds exactly four bytes to `MD5Length` with the helper at `3F:6592`. The helper stops after address `0x826C`. It does not propagate carry into `0x826D`–`0x8270`. [confirmed]

The implemented update is therefore: [confirmed]

$$
L_{\mathrm{new}} = (L_{\mathrm{old}} + 8\,BC) \bmod 2^{32}
$$

The high four bytes remain zero after `_MD5Init`. Standard MD5 appends the message length modulo $2^{64}$, so this boot implementation diverges once cumulative input reaches $2^{32}$ bits, or 512 MiB. A single call cannot reach the boundary because `BC` is 16-bit, but repeated calls can. WikiTI describes all eight bytes as holding the length and does not identify this local implementation quirk. [confirmed]

### Streaming copy and block compression

After updating the length, `_MD5Update` resumes with the saved `HL` and `BC`. It copies bytes into `MD5Buffer+i`. On reaching byte 64, it calls `md5_compress_block` at `3F:699A`, resets the index to zero, and continues with any remaining source bytes. A call ending mid-block returns with that prefix retained for the next update. [confirmed]

A zero-length call returns from the copy loop without changing the buffer or state. It still executes the index and zero-add setup first. [confirmed]

The routine does not allocate memory and has no bounds metadata for `HL`. A caller that supplies a range crossing unmapped or repaged memory receives ordinary Z80 memory behavior. The public ABI's pointer and count are the only input boundary. [confirmed]

## Table-driven compression

`md5_compress_block` copies the current four state words from `MD5Hash` to `MD5Temp`. It then executes four loops of 16 descriptors before adding the original state into the working state. [confirmed]

| Round | Descriptor base | Mode | Message-word index | Rotate cycle |
|------:|-----------------|------|--------------------|--------------|
| 1 | `3F:662D` | F | $g(j)=j$ | 7, 12, 17, 22 |
| 2 | `3F:66CD` | G | $g(j)=(5j+1)\bmod16$ | 5, 9, 14, 20 |
| 3 | `3F:676D` | H | $g(j)=(3j+5)\bmod16$ | 4, 11, 16, 23 |
| 4 | `3F:680D` | I | $g(j)=7j\bmod16$ | 6, 10, 15, 21 |

Each descriptor occupies ten bytes: [confirmed]

| Offset | Size | Meaning |
|-------:|-----:|---------|
| 0 | 1 | `MD5Temp` offset for operand `A` and result destination |
| 1 | 1 | offset for `B` |
| 2 | 1 | offset for `C` |
| 3 | 1 | offset for `D` |
| 4 | 1 | byte offset of the 32-bit message word in `MD5Buffer` |
| 5 | 1 | rotate count `s` |
| 6 | 4 | additive constant `T`, little-endian |

The first descriptor is: [confirmed]

```text
00 04 08 0C  00 07  78 A4 6A D7
```

It selects the working words at offsets `0`, `4`, `8`, and `12`, message word 0, rotation 7, and `T=0xD76AA478`. The next descriptors rotate the destination offsets through `12`, `8`, and `4`. The table bytes reproduce all standard MD5 word schedules, rotation counts, and constants. [confirmed]

After all 64 operations, `3F:69D9` adds the four original words saved at `MD5Temp` into the four working words at `MD5Hash`. This is the MD5 compression feed-forward step. [confirmed]

### Why the descriptor table matters

The table separates algorithm data from the I/O driver. The four round wrappers at `3F:69FD`, `3F:6A02`, `3F:6A07`, and `3F:6A0C` differ only in the mode written to `0x1F`. `md5_assist_step` handles all operand selection and result placement. Changing one table row would change one message index, rotation, or constant without changing the port code. [confirmed]

The local boot page therefore supplies almost the entire MD5 control structure in software. The ASIC replaces the Boolean expression, five-word addition, rotation, and final addition for one step. It does not replace block scheduling, state rotation, feed-forward, buffering, or padding. [confirmed]

## Finalization

`_MD5Final` obtains the current buffer index `i` and chooses the number of padding bytes needed to stop at byte 56: [confirmed]

$$
p =
\begin{cases}
56-i, & i < 56 \\\\
120-i, & i \ge 56
\end{cases}
$$

The padding source at `3F:68AD` begins with `0x80` and continues with zeros. Finalization enters the copy loop at `3F:692B` rather than calling the public `_MD5Update` entry. Padding therefore does not change the saved message length. If the current index is 56 or greater, this copy compresses one block and continues padding into a second. [confirmed]

The routine then copies the original eight-byte `MD5Length` to `MD5Buffer+56` at `0x83DD` and compresses the final block. The high four length bytes are normally zero because of the 32-bit accounting quirk. [confirmed]

WikiTI warns that early boot versions mishandle messages whose byte length is 55 modulo 64. The local boot 1.03 body does not have that bug: `3F:6968` takes the short branch for index 55 and computes one padding byte. The warning remains relevant to the named older boot versions, not to this ROM. [confirmed] for the local branch; [standard] for the historical report.

### Digest bytes and the prefix at `0x8291`

After compression, `_MD5Final` writes `16` to `0x8291` and jumps to the compact-integer trimming helper at `3F:7014`. That helper decreases the prefix while the highest-address digest bytes are zero. It does not move or rewrite the 16 digest bytes at `0x8292`. [confirmed]

Consumers needing the MD5 byte string should always read all 16 bytes from `MD5Hash`. The byte order in RAM is the conventional digest byte order. For `"abc"` it is: [confirmed]

```text
90 01 50 98 3C D2 4F B0 D6 96 3F 7D 28 E1 7F 72
```

Written as hexadecimal, this is the RFC 1321 vector `900150983cd24fb0d6963f7d28e17f72`. The prefix exists for boot code that treats the same bytes as a little-endian integer. [confirmed]

## Dynamic `"abc"` trace

The `asmmd5` smoke case executes a short assembly payload through TI-BASIC's `Asm(` command. The payload calls `_MD5Init`, passes three bytes at `HL` with `BC=3` to `_MD5Update`, calls `_MD5Final`, and returns. The macro preserves a `ram-logical` dump after the program. [confirmed]

The smoke runner checks both visible execution and the 16 bytes at dump offset `0x0292`, corresponding to logical `MD5Hash` at `0x8292`. This prevents bcall coverage alone from counting as a successful digest test. [confirmed]

Run the fixture and then decode its accelerator operations: [confirmed]

```sh
nix develop -c python tools/tibasic_smoke.py \
  --tilem /path/to/headless/tilem2 \
  --case asmmd5 --keep-trace

nix develop -c python tools/analyze_md5_trace.py \
  /tmp/tibasic-smoke/asmmd5.trace \
  --initial-mapping ti84p-reset \
  --expect-steps 64

nix develop -c python tools/inspect_ram_dump.py \
  /tmp/md5-abc.ram --address 0x8292 \
  --expect 900150983cd24fb0d6963f7d28e17f72 \
  --name MD5Hash
```

The decoder reports 64 complete operations, 16 in each mode. It reconstructs every operand from the actual little-endian writes and compares every read word with an independent calculation in `tools/md5_hardware.py`. All 64 match. [confirmed]

| Event | Per step | Whole block |
|-------|---------:|------------:|
| four-byte operand writes to `0x18`–`0x1D` | 24 | 1,536 |
| mode and rotate writes | 2 | 128 |
| result-byte reads | 4 | 256 |
| total | 30 | 1,920 |

The resolved port instructions execute at the named helpers on page `3F`. The first mode write is at `3F:6BE4`, operand writes span `3F:6B7F`–`3F:6BDB`, the rotate write is at `3F:6BDF`, and reads are at `3F:6A66`–`3F:6A72`. [confirmed]

## `_TransformHash` is a separate operation

`_TransformHash = 80A5` has body `3F:723F`. It performs compact-big-integer preparation for Rabin application-signature verification. It does not call `_MD5Init`, `_MD5Update`, `_MD5Final`, `md5_compress_block`, or any MD5-assist port helper. [confirmed]

### Compact integer representation

The routine reads a one-byte length at `0x8291` followed by little-endian digest bytes at `0x8292`. It constructs this value at `MD5Buffer`: [confirmed]

$$
m = 256 \times \operatorname{integer}(\text{digest bytes}) + 1
$$

The output byte layout is: [confirmed]

```text
MD5Buffer+0  = digest_length + 1
MD5Buffer+1  = 0x01
MD5Buffer+2… = digest bytes, low byte first
```

The leading data byte `0x01` makes the represented integer odd and nonzero. It is unrelated to MD5 padding. [confirmed]

The modulus `n` begins at `0x8000` in the same compact format. The selector `f` begins at `0x83E6`. A zero length represents selector 0. For a nonzero length, the ROM reads only the first payload byte at `0x83E7`. [confirmed]

### Selector branches

The byte branches at `3F:7261`–`3F:7297` and the subtractor at `3F:7299` implement: [confirmed]

| Selector representation | Output under the valid signing preconditions |
|-------------------------|----------------------------------------------|
| zero length | $n-2m$ |
| nonzero, first byte `1` | $n-m$ |
| nonzero, first byte `2` | $m$ |
| nonzero, any other first byte | $2m$ |

Valid certificate data uses selectors 0 through 3, which gives the four transformations described by WikiTI. The final ROM branch is broader than `f=3`: malformed values `4`–`255`, and multi-byte values whose low byte is neither 1 nor 2, also take the `2m` path. [confirmed]

The doubling paths call `bigint_modular_multiply` at `3F:6D2C` with a compact constant 2 stored at `0x8144`. That engine uses the modulus at `0x8000`. For valid signature parameters, `m` is much smaller than `n`, so the modular result is the ordinary `2m` used in the table. [confirmed] for the call and buffers; [standard] for the signing precondition.

`transform_hash_subtract_modulus` at `3F:7299` copies the intermediate value, then subtracts it byte by byte from `n` from low address to high address while propagating borrow. It trims high zero bytes before returning. This directly verifies the `n-m` and `n-2m` interpretation rather than relying on the bcall name. [confirmed]

### Output guard and malformed inputs

After a multiply or subtraction, `3F:7270` reads the compact result length at `0x86EC`. A length of `0x41` or greater returns without copying that result to `MD5Buffer`. Lengths below 65 are copied there. Selector 2 returns earlier because `MD5Buffer` already contains `m`. [confirmed]

The routine has no explicit error code for an oversized result, malformed selector length, or inconsistent input buffers. Its normal callers supply certificate structures constrained to the 64-byte arithmetic workspace. Callers outside that context must not treat every return as a validated transformation. [confirmed]

### Relationship to `_SigModR`

`_SigModR = 80A2` at `3F:7225` copies the same input integer into both multiplication operands, invokes `bigint_modular_multiply`, and returns the modular square. Signature verification can compare that square with the transformed hash. `_TransformHash` itself does not perform the comparison or square a signature. [confirmed]

This separation matters when tracing ports: only the earlier MD5 compression routines touch `0x18`–`0x1F`. The signature transformation and modular square are software big-integer operations on page `3F`. [confirmed]

## Emulator comparison and fidelity limits

| Behavior | TilEm `f56ad63` | Wabbitemu `48c2dc0` | MAME 0.287 | jsTIfied `20170706a` |
|----------|-----------------|----------------------|------------|-----------------------|
| Ports `0x18`–`0x1F` | mapped | mapped | absent; live reads return `00` | mapped |
| Operand writes | six 32-bit sliding registers | same | unmapped | implemented |
| Control writes | shift masked to five bits; mode masked to two | same | unmapped | implemented |
| Result reads | recalculated on each read from `0x1C`–`0x1F` | same | unmapped; live reads return `00` | implemented |
| Reads from `0x18`–`0x1B` | zero | zero | unmapped; live reads return `00` | modeled by the port block |
| Reset and state | fields cleared on reset and serialized | fields serialized | no MD5 state | emulator fields are reset and serialized |
| Driver status | usable implementation | usable implementation | TI-84 Plus marked `MACHINE_NOT_WORKING` | browser emulator source model |

TilEm and Wabbitemu agree on the implemented behaviors below: [standard]

- six 32-bit operand registers;
- byte writes implemented as right shift plus insertion at bit 24;
- rotate count masked to five bits;
- mode masked to two bits;
- result bytes read from `0x1C`–`0x1F`;
- reads from `0x18`–`0x1B` returning zero;
- immediate calculation with no busy state or modeled latency.

TilEm explicitly clears all six operands, the rotate count, and the mode on calculator reset. Its save-state format serializes every field. The guarded direct-core run reproduces the complete reset clearing. Wabbitemu also serializes these fields, but the local ROM writes them all before use. [standard]

Agreement between two emulators is useful corroboration, not independent physical measurement. Both projects may derive edge behavior from the same public notes. The dynamic trace proves that TilEm handles the ROM's valid transaction correctly and produces the standard digest. It does not prove invalid-write behavior on a TA2 or TA3 ASIC. [confirmed] for the exercised path; [hypothesis] for unmeasured hardware edges.

MAME's source map and guarded runtime agree that the driver omits the block.
The runtime's all-zero reads explain why a valid assist transaction yields
zero there. This evidence applies only to MAME 0.287. It does not weaken the
ROM trace or imply that a physical TI-84 Plus lacks the accelerator.
[confirmed] for the guarded MAME run; [standard] for the driver source.

## Reusable implementation model

`tools/md5_hardware.py` separates the independent arithmetic and trace decoder
from pinned emulator I/O profiles. Its shared edge-case oracle derives both
implementing-emulator reports. `Md5AssistImplementation` models the six
sliding registers, control masks, read-time recalculation, undefined operand
reads, and unmapped MAME writes. [standard]

The comparison CLI defaults to the first compression step for `"abc"` and
accepts replacement operands, mode, and rotate count. Its JSON report keeps
unmapped ports distinct from a numeric read value:

```sh
nix develop -c python tools/describe_md5_hardware.py
nix develop -c python tools/describe_md5_hardware.py --json
nix develop -c python tools/describe_md5_hardware.py \
  --profile tilem --mode 3 --shift 0x1F --a 0x01234567
```

TilEm and Wabbitemu return `0xD6D117B4` for the default step. The MAME profile
reports all eight ports as unmapped rather than assigning a portable open-bus
byte. `tools/mame_md5.py` separately parses and validates MAME 0.287's observed
zero reads against the pinned I/O map and the independent arithmetic model.

The guarded TilEm CLI validates the exact source commit, Git tree, and native
binary. It records the shared edge matrix, reset state, modeled clock delta,
compiler-specific binary identity, and physical-scope exclusion:

```sh
tilem_md5_tmp=$(mktemp -d /tmp/ti84-tilem-md5.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_md5_tmp/tilem"
git -C "$tilem_md5_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python tools/build_tilem_md5_probe.py \
  --source "$tilem_md5_tmp/tilem" \
  --output "$tilem_md5_tmp/tilem-md5-probe" --json

tilem_md5_parent=$(mktemp -d /tmp/ti84-tilem-md5-report.XXXXXX)
python tools/run_tilem_md5_probe.py \
  --binary "$tilem_md5_tmp/tilem-md5-probe" \
  --expected-binary-sha256 \
    b461e9720e0c304b26ab95ca814943eddfba670dd7bd1e41b48d53a0f8c689c5 \
  --output-dir "$tilem_md5_parent/run" --json
```

The guarded CLI requires the exact MAME executable hash and OS 2.55MP image.
It retains the native output, error log, input identities, and parsed report:

```sh
mame_md5_parent=$(mktemp -d /tmp/ti84-mame-md5.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_md5_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_md5_parent/run" --json
```

## Security context

MD5 no longer provides collision resistance and should not be selected for a new security design. The calculator's boot code uses it as one component of a historical application-signature format. This page describes compatibility behavior, not a recommendation to use MD5 for modern authentication. [standard]

The accelerator does not make the hash construction stronger. It only reduces the Z80 work required for the 64 compression steps. The 32-bit length-wrap quirk further distinguishes this boot API from a general RFC-conforming implementation for very large inputs. [confirmed]

## Open physical tests

The ROM, trace, and two implementing emulator models close the valid software
path. MAME omits the block. These ASIC questions require a physical TI-83 Plus
Silver Edition or TI-84 Plus test harness:

- read `0x18`–`0x1B` after reset and after operand writes;
- write one, three, four, and five bytes to one operand and recover its effect through a controlled calculation;
- test high bits in mode and rotate-count writes;
- change an operand between result-byte reads to determine whether the result is latched;
- measure whether reads or writes add wait states at 6 MHz and 15 MHz;
- determine reset and low-power retention across TA2 and TA3 revisions;
- compare port availability on standard TI-83 Plus, Silver Edition, and TI-84 Plus ASICs.

The [physical hardware probe](hardware-probes.md#md5-edge-probe)
records undefined reads, a fifth operand write, high control bits, and a
mid-read mutation in a versioned AppVar. Its calculator-side source and host
decoder are prepared, but no physical result is recorded. [confirmed] for the
probe bytes; [hypothesis] for all pending hardware results.

A calculator schematic can identify the ASIC revision and external buses, but it cannot expose this internal datapath. Logic-level tests must infer the remaining behavior through I/O instructions and cycle measurements. [hypothesis]

## Sources

| Source | Use |
|--------|-----|
| [RFC 1321](https://www.rfc-editor.org/rfc/rfc1321) | MD5 algorithm, padding, constants, and test vectors |
| [WikiTI ports `0x18`–`0x1F`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:18) | historical port register description, checked against ROM and emulators |
| [WikiTI `_MD5Init`](https://wikiti.brandonw.net/index.php?title=83Plus:BCALLs:808D), [`_MD5Update`](https://wikiti.brandonw.net/index.php?title=83Plus:BCALLs:8090), and [`_MD5Final`](https://wikiti.brandonw.net/index.php?title=83Plus:BCALLs:8018) | public ABI and historical finalization-bug report |
| [WikiTI `_TransformHash`](https://wikiti.brandonw.net/index.php?title=83Plus:BCALLs:80A5) | historical Rabin transformation description, checked and narrowed against `3F:723F` |
| [TilEm `md5.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/md5.c) and [`x4_io.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c) | emulator arithmetic, shift registers, masks, reads, and reset |
| [Wabbitemu `83psehw.c`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/83psehw.c) | second emulator implementation of the same port block |
| [MAME 0.287 `ti85.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85.cpp) | TI-84 Plus I/O map, absent MD5 ports, and driver status |
| [jsTIfied deployed `20170706a` artifact](https://www.cemetech.net/projects/jstified/jstified_compressed.js?20170706a) and [readable mirror](https://github.com/Quuxplusone/ti83/blob/56246a1181f90123a843ea17eb9e0f2fcda65113/jstified.js) | fourth implementation of the ports `0x18`–`0x1F` arithmetic block |
| [Datamath TI-84 Plus hardware](http://www.datamath.org/Graphing/TI-84PLUS.htm) | calculator hardware and ASIC identification context |
