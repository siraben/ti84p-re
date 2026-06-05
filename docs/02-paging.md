# 02 — Memory Paging

The Z80's two middle 16 KiB slots are windows onto physical memory selected by I/O ports.

| Slot | Select port | Selects |
|------|-------------|---------|
| `4000–7FFF` (bank A) | **port 6** (`mapBankA`) | a flash page (0–63) — and the bcall mechanism uses this slot to bring routines into view |
| `8000–BFFF` (bank B) | **port 7** (`mapBankB`) | a RAM or flash page; `0x81` observed = 84+ RAM mode |

`0000–3FFF` is hardwired to flash page 0; `C000–FFFF` is hardwired RAM. **[standard, consistent with code]**

## How code uses it
- **bcalls** set `port_mapBankA` to the target routine's page, run it at `4000+`, then restore the previous page (see `03-bcall-mechanism.md`). The helper `ram:181c` is the page-set primitive used by the dispatcher.
- A routine that runs banked into `4000` must therefore be written position-fixed for `4000` — which is exactly why every overlay page in Ghidra is based at `4000`.
- `thunk_FUN_ram_2b09` (page 0) is the common **cross-page jump trampoline**: many page-0 bcall entries (e.g. `_FindSym`) just tail-call it to reach a body on another page. Tracing it is the key to the page-0↔banked control flow. **[hypothesis — to verify]**

## Modeling in Ghidra
Each physical flash page 1–63 is an overlay block `page_NN` based at `4000`, so the same logical `4000–7FFF` window exists once per page without collision. Bank B/RAM is the single `RAM` block `8000–FFFF`. This loses the runtime "only one page visible" semantics (intentionally) so all code is statically present.
