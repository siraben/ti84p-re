# System overview

This wiki documents how TI-84 Plus OS 2.55MP uses the Z80, banked memory,
calculator hardware, and its internal software subsystems. It keeps direct ROM
evidence, emulator observations, public hardware behavior, and unresolved
inferences distinct.

The target is a validated 1 MiB Flash image whose OS identifies itself as
2.55MP. [Conventions and methodology](conventions.md) defines the address
notation and confidence flags used throughout the book.

## Machine and OS

The TI-84 Plus is a Z80 machine that can only see 64 KiB at once. The target has
1 MiB of Flash and eight RAM selector values. Community hardware reports assign
eight independent 16 KiB RAM blocks to early units. They assign 48 KiB to later
units, with selectors `82`–`87` sharing one block. No physical result is recorded
for the calculator used by this project. A four-slot paging scheme and a
system-call (bcall) mechanism expose code and data beyond the current address
space. The OS is a single-tasking monitor. Its boot/kernel core occupies Flash
page `0`, other OS routines span banked Flash pages, and fixed RAM windows hold
system state. See [RAM pages](ram-pages.md) for the revision evidence.

Four mechanisms connect most user-facing OS behavior:

| Mechanism | Role |
|-----------|------|
| [Paging](paging.md) and [bcalls](bcall-mechanism.md) | Reach code and data outside the current 64 KiB address space. |
| [Floating-point engine](floating-point.md) | Store real and complex values in the `OP1`–`OP6` registers and perform arithmetic. |
| [Variable Allocation Table (VAT)](variables-vat.md) | Catalog named reals, lists, matrices, strings, programs, and AppVars. |
| [Tokenizer and parser](tokenizer-basic.md) | Store TI-BASIC as one- and two-byte tokens and execute the resulting token stream. |

Around those sit the I/O subsystems: the [Flash command path and boot write APIs](flash-memory.md); the IM1 interrupt dispatcher ([interrupts.md](interrupts.md)); the standard timers, RTC, and low-power state machine ([clock-timers-power.md](clock-timers-power.md)); the [MD5 round accelerator](md5-hardware.md); the LCD driver; the keypad scanner; and the link port.

## Subsystem index

Each row maps a documentation page to the subsystem it covers.

| Page | Subsystem |
|------|-----------|
| [Memory map](memory-map.md) | Address space, ports, and RAM layout |
| [Flash memory](flash-memory.md) | Flash geometry, protection, command sequences, boot write APIs, archive traces, and emulator differences |
| [Paging](paging.md) | Paired and independent Flash/RAM mapping, extended selectors, boot transition, and forced overlays |
| [Bus timing and wait states](bus-timing.md) | CPU-speed-selected Flash, RAM, LCD, and timer wait-state registers |
| [ASIC status, identity, protection, and GPIO](asic-status-gpio.md) | ASIC status and identity, battery comparison, protection mode, and GPIO |
| [The bcall mechanism](bcall-mechanism.md) | `rst 28h` system calls and the jump table |
| [Interrupts](interrupts.md) | IM1 entry, USB and legacy routing, masks, status, acknowledgement, priority, and wake |
| [Clock, timers, and power](clock-timers-power.md) | Clock domains, programmable timer API, RTC, APD cadence, and power-off |
| [MD5 accelerator and boot API](md5-hardware.md) | MD5-assist ports, boot digest API, round descriptors, and Rabin hash transformation |
| [Variables and the VAT](variables-vat.md) | Variable Allocation Table and object types |
| [Floating-point engine](floating-point.md) | BCD floating-point format and OP registers |
| [Tokenizer and TI-BASIC tokens](tokenizer-basic.md) | Token tables, parser, and interpreter |
| [Display and LCD](display-lcd.md) | LCD ports and screen buffers |
| [Keyboard and link port](keyboard-link.md) | Keyboard and link overview |
| [Keypad and ON-key hardware](keypad-on-hardware.md) | Matrix electrical behavior, scan timing, debounce, repeat, ON interrupts, and wake |
| [Subsystem map](subsystem-map.md) | Bcall API surface and the system through-line |
| [Boot, contexts, and errors](boot-contexts-errors.md) | Boot, the context system, `_JError`, and `onSP` |
| [Memory management](memory-management.md) | RAM heap, VAT, `userMem`, Flash archive, and garbage collection |
| [Flash page map](flash-page-map.md) | Contents of each of the 64 Flash pages |
| [RAM pages](ram-pages.md) | RAM page selectors, page `83`, and restore rules |
| [Open questions and roadmap](open-questions.md) | Prioritized future work |

The sidebar groups subsystem deep dives beneath their parent pages. The
[Glossary](glossary.md) defines TI-specific terms, and the [bcall
index](bcall-index.md) is the alphabetical system-call reference.
