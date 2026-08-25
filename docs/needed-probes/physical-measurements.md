# Measurements needed from physical calculators

The remaining hardware questions fall into three classes: values that a
calculator program can export, electrical behavior that needs external
instruments, and reset or power-loss behavior that starts outside an ordinary
`Asm(` program. Emulator agreement does not resolve any of these physical
questions.

## Audit boundary

The ROM-wide I/O census has no unresolved immediate or computed-port
candidate. Most remaining `[hypothesis]` claims elsewhere in the book concern
software control flow and do not require a calculator. This section contains
only claims for which ROM bytes, traces, and emulator source cannot determine
the physical result. [confirmed] for the ROM audit boundary; [hypothesis] for
each unmeasured hardware result.

No exported `HWP1` AppVar from a physical calculator is present in this
repository. The existing suite therefore supplies tested measurement
artifacts, not physical conclusions. [confirmed]

| Experiment family | Minimum physical setup | Prepared artifact | Remaining output |
|-------------------|------------------------|-------------------|------------------|
| ASIC identity and RAM topology | TI-84 Plus with recorded PCB and ASIC marking | `HWASIC`, `HWPRAM` | AppVars |
| Timer divisors and edge state | TA2 and TA3 calculators | `HWTMR` | AppVar |
| Bus waits and prefixed M1 placement | TA2 and TA3 calculators running OS 2.55MP | `HWBUS`, `HWPFX` | AppVars |
| MD5-assist edge behavior | Silver Edition, TA2, and TA3 ASICs where available | `HWPMD5` | AppVar |
| Execution protection | backed-up test calculator | `HWEF...`, `HWER...` | AppVar plus reset observation |
| Battery comparison | test calculator, current-limited supply, and DMM | `HWBATT`, `HWBRAW` | AppVars plus voltage and load |
| Link and keypad digital settling | test calculator and specified key or disconnected link state | `HWLINK`, `HWKEYS` | AppVars |
| USB control reset state | identified TA2 and TA3 calculators | `HWPUSB` | connected and disconnected AppVars |
| Mapper overlays | backed-up test calculator | `HWPMAP` | AppVar plus displayed verification code |
| LCD controller edges | identified LCD revision and backed-up test calculator | `HWPLCD` | AppVar plus displayed verification code |
| RTC rollover coherence | identified TA2 and TA3 calculators | `HWPRTC` | AppVar plus code after a natural low-byte rollover |
| Interrupt wake edges | identified TA2 and TA3 calculators | `HWPIRQ` | AppVar plus displayed verification code |
| Analog, boot, Flash, and power-loss behavior | calculator plus laboratory fixture | no ordinary standalone artifact | captured waveform, timing, or post-reset image |

The [calculator-readable probes](calculator-readable.md) page names every
currently built artifact. [Guarded mapper, LCD, and interrupt
probes](additional-calculator-probes.md) defines the new digital experiments
and their safety gates. [External
measurements](external-measurements.md) lists the questions that an AppVar
cannot settle.

## Priority order

Run read-only and restoring probes before any probe that can reset or alter
mapped memory:

1. `HWASIC`, `HWPUSB`, and `HWPRAM` establish unit identity and topology.
2. `HWTMR`, `HWBUS`, `HWPFX`, and `HWPMD5` distinguish major emulator models.
3. `HWLINK` and `HWKEYS` collect operator-dependent digital samples.
4. `HWBATT` precedes `HWBRAW` at every controlled-supply voltage.
5. One execution-fetch artifact runs between result exports.
6. `HWPMAP`, `HWPLCD`, and `HWPIRQ` run one at a time on a backed-up test unit;
   record the displayed number and export the AppVar immediately.
7. Flash, reset, and power-loss experiments use an expendable unit and their
   experiment-specific fixture.

This order reduces recovery cost. It does not make a physical run risk-free.

## What counts as a result

An emulator report establishes one implementation's behavior. A calculator
result requires the original exported AppVar, the exact build manifest, and
the unit metadata listed in [Recording a physical result](recording-results.md).
An electrical result also requires the instrument configuration and raw
capture. [standard]
