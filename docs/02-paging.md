# 02 — Memory paging

The Z80's banked 16 KiB slots are windows onto physical memory selected by I/O ports.

| Slot | Select port | Selects |
|------|-------------|---------|
| `4000–7FFF` (bank A) | **port 6** (`mapBankA`) | a flash page (0–63) — and the bcall mechanism uses this slot to bring routines into view |
| `8000–BFFF` (bank B) | **port 7** (`mapBankB`) | a RAM or flash page; `0x81` observed = 84+ RAM mode |
| `C000–FFFF` (bank C) | **port 5** (`mapBankC`) | a RAM page; `0x00` observed = RAM page `80` |

`0000–3FFF` is hardwired to flash page 0. `C000–FFFF` is RAM in the static OS model and is normally the stack/user-RAM window; the 84+ hardware banks the high RAM slot through MemC/port 5. The dynamic trace in [RAM pages](14-ram-pages.md) confirms port-5 restores to RAM page `80` during normal OS execution. **[confirmed]**

## How code uses it
- **bcalls** set `port_mapBankA` to the target routine's page, run it at `4000+`, then restore the previous page (see [03-bcall-mechanism.md](03-bcall-mechanism.md)). The helper `ram:181c` is the page-set primitive used by the dispatcher.
- A routine that runs banked into `4000` must therefore be written position-fixed for `4000` — which is exactly why every overlay page in Ghidra is based at `4000`.
- `cross_page_jump` (`ram:2b09`) is the common **cross-page jump trampoline**: many page-0 entries and inline OS calls use it with a following `.dw addr; .db page` payload to reach a body on another page. **[confirmed]**

## Modeling in Ghidra
Each physical flash page 1–63 is an overlay block `page_NN` based at `4000`, so the same logical `4000–7FFF` window exists once per page without collision. Bank B/RAM is the single `RAM` block `8000–FFFF`. This loses the runtime "only one page visible" semantics (intentionally) so all code is statically present.
