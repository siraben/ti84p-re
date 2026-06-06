# Writing Guidelines

How to write pages for this wiki so they read as one consistent voice. These are
authoring rules for contributors; the *reader-facing* conventions — address
notation (`pp:addr`), confidence flags (`[confirmed]`/`[standard]`/`[hypothesis]`),
function-naming, and the KaTeX/pseudocode/Mermaid mechanics — live in
[`docs/conventions.md`](docs/conventions.md). Read both before editing.

These guidelines follow established technical-wiki style (MediaWiki, Wikiversity,
TYPO3, Proxmox); the project-specific rules are called out as such.

## 1. Frame positively — say what a thing *is*

Lead with what something **is** and **does**, then give the evidence. Describing a
mechanism by what it is *not* forces the reader to hold a contrast they had no
reason to expect, and negative sentences are measurably harder to parse.

- **Do:** "The forward log/exp evaluators are a digit-by-digit pseudo-division
  recurrence. The table gives it away: `02:7181`'s 16 rows are exactly
  log₁₀(1+10⁻ᵏ)…"
- **Avoid:** "The forward evaluators are **not** Horner polynomials: …" — the
  reader never assumed Horner, so the negation invents a strawman.

The same applies to feature behaviour: prefer "`StrngObj` is an inert user
variable the string commands manipulate" over "a string is not auto-evaluated."

**When a negation *is* warranted:** use one only to correct a concrete appearance
the disassembly itself presents. Example: a `LD A,n; CALL 0x2362` site genuinely
*looks* like a flash bank switch, so "this is **not** a page switch — `0x2362`
resolves to the page-0x02 coefficient fetcher" earns the negation because it
overturns a reading the reader (and Ghidra) would otherwise make. The test: is
there real evidence pointing the wrong way? If not, just state what is true.

## 2. Voice, person, tense

- **Active voice.** "`_FindSym` scans the VAT" — not "the VAT is scanned."
  Passive is acceptable only when the actor is genuinely unknown or irrelevant.
- **Present tense** for how the ROM behaves ("the loop drives `x` up toward 10").
  Past tense only for what *this RE effort* did ("the table was matched to 14
  digits").
- **No first person.** Avoid "we"/"I". Describe the system or the method, not the
  author. (Methodology pages may say "this RE" as a noun — see `conventions.md`.)
- **Address the reader as "you"** sparingly, and only in how-to-read or build
  instructions — most pages describe the machine, not the reader's actions.

## 3. Be concise

- Keep sentences short; split anything over ~25 words. One idea per sentence.
- Cut padding: "essentially", "basically", "sort of", "in order to", "it should
  be noted that". Every word must carry meaning.
- Lead with the key fact, then elaborate — don't bury the conclusion under setup.
- **Never** use "easy", "simple", "just", "obviously", or "of course" to describe
  ROM behaviour: what is obvious to the author rarely is to the reader, and these
  words add no information.

## 4. Structure

- **One topic per page.** A page answers one question (one subsystem, one
  mechanism). Push feature detail into a `sub-*.md` deep-dive and link to it.
- **Overview first.** Open with a 1–3 sentence summary of what the page covers
  before the first heading, so a reader can tell in seconds if it is relevant.
- **Sentence case headings and page titles** ("Memory map", not "Memory Map";
  "Object types", not "Object Types"). Keep acronyms and proper nouns
  capitalized (VAT, LCD, TI-BASIC, MathPrint, API). A page's H1 and its
  `SUMMARY.md` entry must match. No links inside headings; blank line after each.
- **Tables for enumerations** (routines, IDs, type bytes, bit layouts); **prose
  for mechanism**; **pseudocode for algorithms**; **Mermaid for control/data flow.**
  Do not turn a table dump into the whole article — explain what it *means*.
- Prefer a short bulleted list over a long comma-spliced sentence when the items
  are parallel.

## 5. Word choice & consistency

- **Define a term on first use**, then use it identically every time. Don't
  alternate "jump table" / "dispatch table" / "bcall table" for one thing.
- Match the audience: assume a reader who knows Z80 assembly and calculator
  basics, so don't explain registers or hex — but *do* define TI-specific terms
  (bcall, VAT, OP1, TIFloat) and link to the [Glossary](docs/glossary.md).
- Use the project's canonical names: official TI names as `_CamelCase`, inferred
  names as `snake_case` (see `conventions.md`). Spell addresses as `pp:addr`.
- Be consistent about contractions, serial commas, and units across a page.

## 6. Ground every claim

This is a reverse-engineering wiki; accuracy outranks fluency.

- **Tag confidence** on every non-obvious claim with `[confirmed]` / `[standard]`
  / `[hypothesis]` (definitions in `conventions.md`). When unsure, say so and tag
  it `[hypothesis]` rather than asserting.
- **Cite the address.** Anchor a claim to where it lives — `02:6F80`–`6FEE`, a
  bcall ID, a RAM label — so a reader can verify it in the disassembly.
- **Flag the open piece.** If part of a mechanism is decoded and part is not, name
  the gap plainly ("per-row decoding of `02:7201` is the one piece still open")
  instead of papering over it or silently overclaiming.
- Don't let prose drift from a later finding: when you confirm something new,
  reconcile the older pages that now contradict it.

## 7. Mechanics

See [`docs/conventions.md`](docs/conventions.md) for the details and copy-paste
patterns:

- **Math** — LaTeX in `$…$`/`$$…$$`, KaTeX-rendered. Inside math, **double** any
  backslash-before-punctuation escape (`\\,`, `\\%`, `\\\\`) — mdBook eats one
  pass before KaTeX. Backslash-before-letter macros (`\frac`, `\sum`) are safe.
- **Algorithms** — ` ```pseudocode ` blocks (pseudocode.js `\begin{algorithm}`),
  verbatim, no escape doubling.
- **Diagrams** — ` ```mermaid ` blocks, rendered to SVG.
- **Code** — fenced blocks with a language tag; Z80 uses the custom highlighter.

Build before committing: `nix shell nixpkgs#mdbook nixpkgs#mdbook-mermaid -c
mdbook build`. A clean build confirms math, pseudocode, and diagram fences are
balanced and parse.
