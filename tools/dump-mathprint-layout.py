#!/usr/bin/env python3
"""Dump page-0x39 MathPrint handler records, descriptors, and xrefs from a ROM."""
import argparse
from pathlib import Path

PAGE = 0x39
HANDLER_TABLE = 0x5E45
HANDLER_COUNT = 0x44
DESCRIPTORS = [0x686F, 0x6880, 0x6893, 0x689C, 0x68A5]
TEMPLATE_ACTIONS = {
    # eqdisp_layout_token_geom (39:68AE) maps these row actions through
    # eqdisp_menu_tok_jp (39:6773) to the 0x85E8 kind byte, but only after
    # the template state has forced 0x85DE to the special geometry state 0x48.
    0x49: 0x10,
    0x48: 0x11,
    0x2E: 0x12,
    0x5A: 0x13,
}

TEMPLATE_DESCRIPTOR_KIND_LABELS = {
    0x10: "fraction menu descriptor",
    0x11: "root/function template descriptor",
    0x12: "measured fraction editor path",
    0x13: "matrix/vector/list descriptor family",
}

CONTROL_FLOW_OPS = {
    0xC3: "JP",
    0xC2: "JP NZ",
    0xCA: "JP Z",
    0xD2: "JP NC",
    0xDA: "JP C",
    0xE2: "JP PO",
    0xEA: "JP PE",
    0xF2: "JP P",
    0xFA: "JP M",
    0xCD: "CALL",
    0xC4: "CALL NZ",
    0xCC: "CALL Z",
    0xD4: "CALL NC",
    0xDC: "CALL C",
    0xE4: "CALL PO",
    0xEC: "CALL PE",
    0xF4: "CALL P",
    0xFC: "CALL M",
}

OPERAND_FLOW_ANCHORS = [
    (
        0x5167,
        "21e0853ae285b7caa2523dbe",
        "multi-argument walker: 85E0=current arg slot, 85E2=arg count",
    ),
    (
        0x5177,
        "cd4959f5200a34",
        "forward path class guard through 5949 before incrementing 85E0",
    ),
    (
        0x51B8,
        "cd105b3ae0854fcd465bcdfe66",
        "forward/overflow path emits saved-E7 operand then resyncs cursor state",
    ),
    (
        0x51E0,
        "cd105b1809",
        "forward/in-row path emits saved-E7 operand",
    ),
    (
        0x523C,
        "cd49593a4b842005",
        "reverse path class guard through 5949 after decrementing 85E0",
    ),
    (
        0x5257,
        "cd385b3828",
        "reverse/overflow path tries saved-F2 variable emitter",
    ),
    (
        0x5273,
        "cd1d5b3ae085",
        "reverse/overflow path emits saved-E7 variable operand",
    ),
    (
        0x529F,
        "cd1d5bc34754",
        "reverse/in-row path emits saved-E7 variable operand and returns via 5447",
    ),
    (
        0x52B3,
        "cd675118ea",
        "action-4 path recursively drains remaining argument slots through 5167",
    ),
    (
        0x5955,
        "21e285bed0f5cdca4d",
        "load argument cell: bounds-check A against 85E2, then use 4DCA row cells",
    ),
    (
        0x5949,
        "3ade85fe06c03e02bed897c9",
        "argument-kind guard: class 06 with slot <= 2 reports zero, others preserve compare result",
    ),
    (
        0x595F,
        "7823b72804232310fc7ecdb648200c2a11935f160019e7",
        "scan selected argument cell: skip two bytes per B slot and optionally chase menu-token indirection",
    ),
    (
        0x597B,
        "2b7e4ffeff20057806ff1819fefe20057806fe1810fefc20057806fc1807fefb20037806fb3246847837c9",
        "argument-cell prefix normalizer: FF/FE/FC/FB prefixes move to B, low byte saved in 8446",
    ),
    (
        0x59E0,
        "cd175a28caafcd533a",
        "normal operand emitter path after class-2 check",
    ),
    (
        0x59F9,
        "cd175a28b8afcd6f30",
        "variable operand emitter path after class-2 check",
    ),
    (
        0x5A17,
        "3ade85fe02c9",
        "class-2 check used by normal/variable operand emitters before parser bjump fallback",
    ),
    (
        0x5AD2,
        "21788418e8",
        "save OP1 at 8478 into scratch slot 85E7 through the Mov9B tail",
    ),
    (
        0x5AE1,
        "117884180a",
        "restore scratch slot 85E7 into OP1 through the Mov9B tail",
    ),
    (
        0x5B00,
        "11788421f28518ba",
        "restore scratch slot 85F2 into OP1 through the Mov9B tail",
    ),
    (
        0x5B08,
        "21788411f28518b2",
        "save OP1 at 8478 into scratch slot 85F2 through the Mov9B tail",
    ),
    (
        0x5B10,
        "fdcb116ec8cde15acde059180b",
        "saved-E7 normal operand wrapper: gated by (IY+11) bit 5",
    ),
    (
        0x5B1D,
        "fdcb116ec8cde15acdf959d818a7",
        "saved-E7 variable operand wrapper: gated by (IY+11) bit 5",
    ),
    (
        0x5B2B,
        "fdcb116ec8cd005bcde059180b",
        "saved-F2 normal operand wrapper: gated by (IY+11) bit 5",
    ),
    (
        0x5B38,
        "fdcb116ec8cd005bcdf959d818c2",
        "saved-F2 variable operand wrapper: gated by (IY+11) bit 5",
    ),
]

OPERAND_FLOW_XREF_TARGETS = [0x5167, 0x5B10, 0x5B1D, 0x5B2B, 0x5B38]

OPERAND_DISPLAY_BJUMP_ANCHORS = [
    (
        0x00,
        0x3C81,
        "cd092b",
        "fixed-bank display/cursor bjump used by 5167 forward overflow; raw Ghidra maps it to page 01:5FF1",
    ),
    (
        0x00,
        0x3C93,
        "cd092b",
        "fixed-bank display/cursor bjump used by 5167 reverse overflow; raw Ghidra maps it to page 01:6076",
    ),
    (
        0x00,
        0x3DE9,
        "cd092b",
        "fixed-bank clear/display bjump reached by row reset paths; raw Ghidra maps it to page 01:60E4",
    ),
    (
        0x00,
        0x3FDB,
        "cd092b",
        "fixed-bank character-output bjump used by 4E0A and 6712; raw Ghidra maps it to page 01:5B4C",
    ),
    (
        0x01,
        0x5FF1,
        "f5c5d5e5dde5dd21a597cd79",
        "page-1 j_cursor_left_edge target: saves registers and enters the cursor span helper with IX=97A5",
    ),
    (
        0x01,
        0x6076,
        "f5c5d5e5dde5cd3165fdcb05d6dd21a597dd7e01",
        "page-1 cursor_home_scroll target: run-indicator/display-row scroll and clear handling",
    ),
    (
        0x01,
        0x60E4,
        "f521028ae57ee601f5cb8606803eb81824f5",
        "page-1 _ClrLCDFull target: display clear loop, not expression layout",
    ),
    (
        0x01,
        0x5B4C,
        "f5e5fed62012cdc561cd4a5f3aa6976f3a4b",
        "page-1 _PutC target: character output through _PutMap with 844C advance",
    ),
]

OPERAND_DISPLAY_BJUMP_XREF_TARGETS = [0x3C81, 0x3C93, 0x3DE9, 0x3FDB]

MULTIARG_PLACEMENT_FLOW_ANCHORS = [
    (
        0x4E0A,
        "97324c843ae085b92004fdcb05de0631795ffe09383d200c",
        "argument-index glyph helper: clear 844C, set cursor bit when C/param equals current 85E0, then emit '1'..",
    ),
    (
        0x4C5A,
        "214a983a4b8496473ae0859038154fc5cdca4d3a4a983d324b84c1fdcb116e2064182dcd",
        "overflow/subexpr helper: compute visible slot from 85E0 and 844B-984A, call 4DCA, then emit arglist",
    ),
    (
        0x4CA4,
        "fdcb116e203a3ae285b7281579cb275f160019cde64d3a4a9818023e01324b84c93a",
        "subexpr helper tail: emit arglist at row-cell pointer + 2*slot, restore 844B to baseline 984A",
    ),
    (
        0x507C,
        "fe08c212513ae28521e08596214b8486fe09380f3ae085214b8496c60732e085c332513e06324d84cd6751214d843520f7c3",
        "action-08 window advance: if next args do not fit in seven rows, adjust 85E0; otherwise run six 5167 steps",
    ),
    (
        0x50CF,
        "cd274c3ae085f5cd0e4bf121e285be38057eb728013d32e085d6063001aff53a4484fe0420073ae285fe083803cde93df1c9cd884c3ae0853cfe0838023e07324b84",
        "argument-window clamp: classify current token, clamp 85E0 below 85E2, clear display if needed, map slot to 844B",
    ),
    (
        0x5112,
        "fe07c2f1513ade85fe06280d3ae085214b8496c601d6073003af1810214a988632e085cdcf50af32f285180632e085cdcf503ae085cd01513a4a98324b84c3475421df857eb720093ae185fe01ca47547735c3c05021",
        "action-07 window back/direct remap: compute previous visible arg window, clamp through 50CF, then restore 844B",
    ),
    (
        0x51CB,
        "3c4e0dcd0a4e21e0854e214b84f120013434cd0a4ecd105b1809e1",
        "forward in-row multiarg placement: emit previous slot index, bump 844B by one or two rows, emit current slot, then 5B10",
    ),
    (
        0x51F1,
        "fe03c2a55221e0857eb7203efdcb1d4620eb3ae285fe08daa150af32f2853ae2853d32e085d607214a98864fc5cdca4d3a4a983d324b84c1cda44c210700224b843ae0854fcd144e",
        "action-03 last-visible-arg path: for 85E2>=8, set 85E0 to last arg and emit it at row 7",
    ),
    (
        0x5286,
        "21e0854e0ccd0a4e21e0854ecd4959214b8420013535cd0a4ecd1d5b",
        "reverse in-row multiarg placement: emit next slot index, consult 5949, decrement 844B by one or two rows, then 5B1D",
    ),
    (
        0x52A5,
        "fe04201821e0853ae2853d962805cd675118eafdcb1d4620e4c33e51",
        "action-04 drain path: repeatedly call 5167 until the current slot reaches the last argument",
    ),
    (
        0x5CF6,
        "9021e285bed2475432e085cd175a200921e085afbeca965b35af324b84cdd059180434cde0593809214b843ae085be20f1cd",
        "saved-OP direct-slot placement: subtract action base, require slot < 85E2, write 85E0, render operands until 844B == 85E0",
    ),
    (
        0x5949,
        "3ade85fe06c03e02bed897c9",
        "row-step classifier: only class 06 with 85E0 <= 2 returns zero; all other slots/classes take the one-row path",
    ),
]

MULTIARG_PLACEMENT_XREF_TARGETS = [
    0x4C5A, 0x4CA4, 0x4E0A, 0x4E14, 0x507C, 0x50CF, 0x5112,
    0x5167, 0x51F1, 0x52A5, 0x5949, 0x5CF6,
]

SAVED_OP_FLOW_ANCHORS = [
    (
        0x52D3,
        "fdcb116ec28c5bfe05c2f8533ae085cd5559",
        "saved-OP flag gate: when (IY+11) bit 5 is set, non-05 actions jump to 5B8C",
    ),
    (
        0x5B8C,
        "fe05c2415ccd235a200b3e823246844f3e4dc3e55211bf8421e885cd941a973246843e58fdcb26462073cd3a5c20093e013246843e591865cd2e5c3e46285e3efd3246843ade",
        "saved-OP action-05 path: copy saved state, clear 8446, and route list/named/menu-token handling",
    ),
    (
        0x5C41,
        "068ffe8f3805fe98daf65c0685fe8ecaf65c0690fe9ada2154feb4380706a8feccc22154d69ac641fe5b38023e5b32f2853e01324b84",
        "saved-OP token-range classifier: 8F..97/8E enter slot-subtraction, 9A..B3/CC map through 85F2",
    ),
    (
        0x5C77,
        "cd175a2028cdc55a3af2853d3279843eff327a84cdaf5938021806cdb659380705214b847886",
        "saved-OP 85F2 path: class-2 guard, optional prefix scan, then operand emission loop setup",
    ),
    (
        0x5CF6,
        "9021e285bed2475432e085cd175a200921e085afbeca965b35af324b84cdd059180434cde0593809214b843ae085be20f1cdd25ac3a1",
        "saved-OP slot-subtraction path: A-B must be below 85E2 before writing 85E0 and emitting operands",
    ),
]

SAVED_OP_FLOW_XREF_TARGETS = [0x5B8C, 0x5C41, 0x5CF6, 0x5B96, 0x5BA1]

RECORD_FLOW_ANCHORS = [
    (
        0x4C27,
        "3e00fdcb3676c4bb2cc03ade8521455ecb2716005f19c33300",
        "load handler record pointer: 0x5E45 + 2*(85DE), then _LdHLind",
    ),
    (
        0x4D92,
        "cd274c462310fd230e00",
        "row-title loop: load record, read row_count, skip counts to actions",
    ),
    (
        0x4DA7,
        "3e02fdcb3676c4bb2c20047ecd2b3b",
        "emit current row action/title byte through the 3B2B indexed-string bjump",
    ),
    (
        0x4DCA,
        "cd274c3adf85b7477e4f",
        "current-row cell pointer: load record, read row index 85DF and row count",
    ),
    (
        0x4DDC,
        "cb279186235f160019c9",
        "current-row cell pointer tail: skip counts/actions and prior row cells",
    ),
    (
        0x4DE6,
        "3a4a98324b84cd0a4e56235e23e5c5cd8e4e",
        "emit decoded row cells as two-byte display tokens through 4E8E",
    ),
    (
        0x4DFA,
        "0c3ae285b9c8d83a4b84fe07c83c18df",
        "row-cell emit loop: advance C until 85E2 cells or row 7",
    ),
    (
        0x4CB7,
        "cde64d3a4a9818023e01324b84c9",
        "record display path calls 4DE6, then restores the row baseline",
    ),
]

RECORD_FLOW_XREF_TARGETS = [0x4C27, 0x4D21, 0x4DCA, 0x4DE6]
FNINT_ROW_ACTIONS = [0x35, 0x3B, 0x25, 0x43]

ROW_ACTION_FLOW_ANCHORS = [
    (
        0x4D92,
        "cd274c462310fd230e003adf85b92004fdcb05dee53e02fdcb3676c4bb2c20047ecd2b3b",
        "row-action/title loop: load record, skip arg counts, display row_action bytes through 3B2B",
    ),
    (
        0x4DCA,
        "cd274c3adf85b7477e4f2806e5238610fce1cb279186235f160019c9",
        "current-row cell pointer: skip row counts and row_action bytes to reach two-byte display cells",
    ),
    (
        0x4DE6,
        "3a4a98324b84cd0a4e56235e23e5c5cd8e4ec1e10c3ae285b9c8d83a4b84fe07c83c18df",
        "row-cell emitter: walks the display-cell array and calls 4E8E, not the row_action array",
    ),
    (
        0x4F9A,
        "fdcb36664728233a9a85fe402006fdcb495e2016efca51300cc53ae085cd5559c1fefb28053e01cd073b3ade85fe49cac16cfe4878200bfe092807fe40281ec3ae68",
        "layout dispatcher entry: save incoming A in B; only 85DE=48 routes non-09/40 incoming actions to 68AE",
    ),
    (
        0x68AE,
        "21e8850e10fe4928100cfe48280b0cfe2ecad0680cfe5a200f79c37367cd336837c979cd736737c9",
        "geometry action mapper: incoming 49/48/2E/5A choose kinds 10/11/12/13 after geometry state is active",
    ),
]

ROW_ACTION_FLOW_XREF_TARGETS = [0x4D21, 0x4DCA, 0x4DE6, 0x4F9A, 0x68AE]

RECORD_CELL_STREAM_FLOW_ANCHORS = [
    (
        0x4DCA,
        "cd274c3adf85b7477e4f2806e5238610fce1cb279186235f160019c9",
        "current-row cell pointer: load handler record, sum prior row counts, return packed cell base",
    ),
    (
        0x4DE6,
        "3a4a98324b84cd0a4e56235e23e5c5cd8e4ec1e10c3ae285b9c8d83a4b84fe07c83c18df",
        "row cell stream: set baseline row, emit gutter label/separator, then pass each D:E cell to 4E8E",
    ),
    (
        0x4E0A,
        "97324c843ae085b92004fdcb05de0631795ffe09383d200c3e3018383e2018343e5b1830",
        "gutter label prologue: highlight selected slot, choose 1..9/0/A..Z/[ or space",
    ),
    (
        0x4E54,
        "7b0637fe2428cf30c980cddb3fc53a4a98473a4b84b8c120087bb728133e1e1811",
        "gutter label tail: emit label, then choose separator from baseline row and last-visible-slot state",
    ),
    (
        0x4E75,
        "fe07200b3ae2853dbb3e1f280230023e3acddb3ffdcb059ec9",
        "row-7 separator tail: choose 1F for continuation or ':' at the final visible slot",
    ),
]

RECORD_CELL_STREAM_XREF_TARGETS = [0x4DCA, 0x4DE6, 0x4E0A, 0x4E5E, 0x4E86, 0x4E8E]

ARG_GUTTER_CALLER_FLOW_ANCHORS = [
    (
        0x4DEC,
        "cd0a4e56235e23e5c5cd8e4e",
        "record-row cell stream: emit gutter label/separator, then load D:E and call 4E8E",
    ),
    (
        0x51A1,
        "3ae0853d4fcd0a4ecd12673aa597f53e0132a597cd813ccd105b",
        "forward row-7 overflow path: emit previous slot gutter before scroll/recovery and saved operand",
    ),
    (
        0x51CB,
        "3c4e0dcd0a4e21e0854e214b84f120013434cd0a4ecd105b",
        "forward in-row path: emit previous slot gutter, step row, emit current slot gutter, then saved operand",
    ),
    (
        0x525C,
        "3ae0853c4fcd0a4ecd12673aa597f53e0132a597cd933ccd1d5b",
        "reverse row-7 overflow path: emit next slot gutter before scroll/recovery and saved variable",
    ),
    (
        0x5286,
        "21e0854e0ccd0a4e21e0854ecd4959214b8420013535cd0a4ecd1d5b",
        "reverse in-row path: emit next slot gutter, step row backward, emit current slot gutter, then saved variable",
    ),
    (
        0x5232,
        "3ae0854fcd144e18b3",
        "action-03 last-visible-slot path: call 4E14 to emit a highlighted row-7 current-slot gutter",
    ),
    (
        0x5B46,
        "cd0a4e3ae085b92003cded5a3ade85fe10280dcd235ac2ae6516821e4dc38e4e",
        "saved operand tail: emit current slot gutter, optional selected-slot OP restore, then string/control cell",
    ),
]

ARG_GUTTER_CALLER_EXPECTED = {
    0x4DEC: "record-row cell stream",
    0x51A6: "forward row-7 overflow previous-slot gutter",
    0x51CE: "forward in-row previous-slot gutter",
    0x51DD: "forward in-row current-slot gutter",
    0x5261: "reverse row-7 overflow next-slot gutter",
    0x528B: "reverse in-row next-slot gutter",
    0x529C: "reverse in-row current-slot gutter",
    0x5B46: "saved operand tail current-slot gutter",
}

ARG_GUTTER_MID_ENTRY_EXPECTED = {
    0x5236: "action-03 last-visible-slot highlighted current-slot gutter",
}

SETUP_FLOW_ANCHORS = [
    (
        0x4AFD,
        "fdcb16ae22df8532de85cd274c",
        "record setup: clear render flag, store 85DF=row word and 85DE=class, load handler record",
    ),
    (
        0x4B0A,
        "7e32e1853adf85be3018",
        "store row_count into 85E1 and bounds-check current row 85DF",
    ),
    (
        0x4B24,
        "042310fd7e32e2859732e085fdcb11ae",
        "select arg_count[row] into 85E2, zero current arg slot 85E0, clear saved-OP flag",
    ),
    (
        0x4B34,
        "3ae285b7c03ade85fe32c8fe41c8",
        "nonzero arg_count returns; zero-arg classes 32/41 return without operand setup",
    ),
    (
        0x4B42,
        "fe102005cda6591844fe02202ccdc55afdcb11ee",
        "zero-arg class 10/02 special setup enters OP/saved-OP operand path",
    ),
    (
        0x4B74,
        "21e285348677c9",
        "list/named operand setup adjusts 85E2 after measuring sub-argument count",
    ),
    (
        0x50CF,
        "cd274c3ae085f5cd0e4bf121e285be3805",
        "clamp current argument slot 85E0 against current row arg_count 85E2",
    ),
    (
        0x5101,
        "cd884c3ae0853cfe0838023e07324b84c9",
        "map current argument slot to display row 844B, capped at row 7",
    ),
    (
        0x513E,
        "32e085cdcf503ae085cd01513a4a98324b84c34754",
        "layout requested argument: set 85E0, clamp, map to row, restore baseline, return",
    ),
]

SETUP_FLOW_XREF_TARGETS = [0x50CF, 0x5101, 0x513E, 0x4CE9]

ROW_PLACEMENT_FLOW_ANCHORS = [
    (
        0x49A8,
        "cd6a67cdbd66cdca04cd744a184c",
        "recursive token-display entry: set template flags, peek/match token, clear cursor flags, dispatch token, then enter 4A02",
    ),
    (
        0x4A02,
        "cd404cfdcb0ce6cde94ccdb648280237",
        "render wrapper: call 4C40, set (IY+0C) bit 4, call raised-row helper 4CE9, then test terminal state",
    ),
    (
        0x4A18,
        "cd1b3fcd45022808cd0158cd293d1812fe09ca184afe",
        "render-loop setup: page/display services, then continue or fall into action dispatch tests",
    ),
    (
        0x4A28,
        "fe09ca184afe403804fe5a38e3cd9a4f38de3ef0327784c9",
        "render-loop action gate: action 09 redraws, 40..59 dispatch through 4F9A, then mark 8477=F0",
    ),
    (
        0x4CE9,
        "3ade85fe243820fe29301c2a4b84e5210400d624fe0420022e03224b84c616cd2b3b",
        "raised-row helper prologue: classes 24..28 save 844B and force row 4, except class 28 uses row 3",
    ),
    (
        0x4D10,
        "fe39c02a4b84e5210400224b843e1b18e7",
        "raised-row helper class-39 path: force row 4 and emit indexed string 1B",
    ),
    (
        0x5447,
        "37f5cde94cf1c9",
        "return wrapper: preserve carry around the raised-row helper",
    ),
]

ROW_PLACEMENT_FLOW_XREF_TARGETS = [0x49A8, 0x4A02, 0x4CE9, 0x4F9A, 0x5447]
ROW_PLACEMENT_CLASSES = [0x24, 0x25, 0x26, 0x27, 0x28, 0x39]

LAYOUT_FLOW_ANCHORS = [
    (
        0x4F9A,
        "fdcb36664728233a9a85fe402006",
        "layout dispatcher entry: save incoming action in B, optional draw-pass preload",
    ),
    (
        0x4FC4,
        "3ade85fe49cac16cfe4878200bfe092807fe40281ec3ae68",
        "template-class gate: class 49 jumps to 6CC1; class 48 routes non-09/40 actions to 68AE",
    ),
    (
        0x5021,
        "fe0120233ade85fe10280bfe2b2807fdcb116ec2b050",
        "internal action 01: advance row unless terminal/saved-OP path handles it",
    ),
    (
        0x5048,
        "fe0220303ade85fe10280bfe2b2807fdcb116ec25351",
        "internal action 02: move to previous row or saved-OP reverse path",
    ),
    (
        0x507C,
        "fe08c212513ae28521e08596214b8486fe09",
        "internal action 08: wide argument-list continuation before six-pass 5167 loop",
    ),
    (
        0x50A1,
        "324d84cd6751214d843520f7c34754",
        "six-pass continuation loop: call 5167 while 844D counts down from 6",
    ),
    (
        0x5112,
        "fe07c2f1513ade85fe06280d3ae085214b8496",
        "internal action 07: map current argument position back toward a visible row",
    ),
    (
        0x51F1,
        "fe03c2a55221e0857eb7203efdcb1d4620eb",
        "internal action 03: jump to first/last wide-argument page or fall into reverse walker",
    ),
    (
        0x52A5,
        "fe04201821e0853ae2853d962805cd675118ea",
        "internal action 04: drain remaining argument slots through 5167, then lay out selected arg",
    ),
    (
        0x52C1,
        "fe5a200ecd2d5dca114acdb648ca114a",
        "internal action 5A: close/menu guard before normal token handling",
    ),
    (
        0x52DA,
        "fe05c2f8533ae085cd5559cdb648ca6654",
        "internal action 05: load current argument cell and enter token/menu handling",
    ),
    (
        0x53AD,
        "fefb202b3a4684fec72810fec8201e3e07",
        "FB C7/C8 square-marker handling before restarting dispatcher with action 09",
    ),
    (
        0x53D5,
        "3e09c39a4f",
        "square-marker path restarts layout dispatcher with internal action 09",
    ),
]

LAYOUT_FLOW_XREF_TARGETS = [0x4F9A, 0x5021, 0x5112, 0x51F1, 0x52A5, 0x52F9, 0x53AD]

EMIT_BOUNDARY_FLOW_ANCHORS = [
    (
        0x4C40,
        "3ade85fe48f5fe213e0120013c324a98f1ca2a68",
        "draw/emit boundary: 85DE=48 enters geometry redraw; other classes continue record/operand emission",
    ),
    (
        0x4CDF,
        "cd915a18dbcd3c5a18d6",
        "saved-OP boundary: bit-5 path chooses 5A91 or named-argument bridge 5A3C after record-cell decision",
    ),
    (
        0x59D0,
        "3ade85fe1028cffe2928f13e05cdd95acd175a28caafcd533a",
        "normal operand emitter selector: class 10 finds symbol, class 29 uses token 17, otherwise token 05",
    ),
    (
        0x59E0,
        "cd175a28caafcd533a",
        "normal operand emitter: class-2 special path or parser token fetch via 3A53",
    ),
    (
        0x59F9,
        "cd175a28b8afcd6f30",
        "variable operand emitter: class-2 special path or parser variable fetch via 306F",
    ),
    (
        0x5A3C,
        "c53ade85fe102005cda659181ccd1d5a20073e17cddd591812cd175a2008",
        "named-argument bridge: class-specific seed then optional counted normal-operand loop",
    ),
    (
        0x5A91,
        "c51803cd005b3af285b720053e0532f285cd693ccdd25a",
        "saved-OP bridge tail: optional 85F2 restore, default 85F2=05, then store OP1 in 85E7",
    ),
    (
        0x6A8A,
        "3aee85b7c8211112114c35cdf56a1617215b6bcd2d6b162221546bcd2d6b",
        "fraction-only dynamic geometry path: requires 85EE, draws box, emits labels before rule helpers",
    ),
    (
        0x6ABF,
        "f5ed4bdf85cb482808212a2b11343318132615cb4028022620793ccd1c6b",
        "fraction-bar helper: row flags in 85DF choose y geometry before 6B1C endpoint math",
    ),
]

EMIT_BOUNDARY_FLOW_XREF_TARGETS = [0x5A3C, 0x5A91, 0x59D0, 0x59E0, 0x59F9, 0x6ABF, 0x6B1C]

OPERAND_SERVICE_FLOW_ANCHORS = [
    (
        0x39,
        0x59E0,
        "cd175a28caafcd533ad8",
        "normal operand emitter: class-2 check, then fixed-bank cross-page service 3A53",
    ),
    (
        0x39,
        0x59F9,
        "cd175a28b8afcd6f30d8",
        "variable operand emitter: class-2 check, then fixed-bank cross-page service 306F",
    ),
    (
        0x39,
        0x5A3C,
        "c53ade85fe102005cda659181ccd1d5a20073e17cddd591812cd175a2008cd273fcdc55a1805cddb5938d3",
        "named-argument bridge: class-specific OP setup, optional 3F27 service, then counted 59E0 loop",
    ),
    (
        0x39,
        0x5A91,
        "c51803cd005b3af285b720053e0532f285cd693ccdd25ac10cc50dcd465b",
        "saved-OP bridge tail: optional 85F2 restore, default token 05, cross-page 3C69, then save OP1",
    ),
    (
        0x07,
        0x50B5,
        "371802373fe53e00f5cd0f1acd4219cddc2020063a79843c2807",
        "page-7 operand service entries: carry variants at 50B5/50B8, then parser/expression scan setup",
    ),
    (
        0x07,
        0x5104,
        "cd4219cd475247b713ed52da8e511922e3847ee61fcd4752b8282d",
        "page-7 scanner loop: call token helpers, compare 982E/9830 range, store current scan pointer 84E3",
    ),
    (
        0x07,
        0x5199,
        "218b840608af0e001a9e20010c1b2b10f7c9",
        "page-7 scratch comparator: compare eight-byte values against 848B while updating C",
    ),
]

OPERAND_SERVICE_SCANNER_CONTEXT_ANCHORS = [
    (
        0x50B5,
        "371802373fe53e00f5cd0f1acd4219cddc2020063a79843c2807cdce203e052012cd350e2a3098ed5b2e98473e089028141807ed5b30982166fee5218184472b360010fbe1f1c11803f1c1d1d5c5f5cd4219cd475247b713ed52da8e511922e3847ee61fcd4752b8282d110900cd4520280dcddc202808fe092016fe0a2812cd",
        "unsplit page-7 scanner entry: setup, compare 982E/9830 expression range, then loop token spans",
    ),
    (
        0x51BE,
        "7ee61f2b2b2b2b2b46c50603cddc202805cd452020172bf57efe722004f123180cfe3a28f8f146cd",
        "scanner backstep helper: mask token class, move five bytes back, then test token-kind helpers",
    ),
    (
        0x5544,
        "cdb550380acd600e38f0cdd91218ebcd0028cd441ac93e01",
        "page-7 non-display caller: call 50B5 in a parser/evaluator loop, not a page-39 renderer",
    ),
    (
        0x6361,
        "cdb550c9fdcb074ec22d27dfcd9716cdc11dcd8d16cd061fcdec19cd8719f5cd",
        "page-7 non-display caller: call 50B5 and return before FPS/evaluator setup",
    ),
    (
        0x70D6,
        "cdb550302df1cd3571d8327884e521798436fee1c0fe142812cd4520280d06ffed43798418833e00327884af327984c3",
        "page-7 non-display caller: call 50B5, then classify parser token kinds and update 8478/8479",
    ),
    (
        0x7207,
        "cdb850d24e72f1cd5572d8327884e521798436fee1c0fe0c2804fe00200a06000e5ced43798418a8fe0520123efe3279",
        "page-7 sibling caller: call 50B8 carry variant, then classify token kinds and update 8478/8479",
    ),
]

OPERAND_SERVICE_XREF_TARGETS = [
    (0x39, 0x3A53),
    (0x39, 0x306F),
    (0x39, 0x3F27),
    (0x39, 0x3C69),
    (0x07, 0x50B5),
    (0x07, 0x50B8),
    (0x07, 0x5199),
]

GEOMETRY_FLOW_ANCHORS = [
    (
        0x67A0,
        "cd3348cdac67cd2248c3c869",
        "geometry entry wrapper: draw window setup/teardown, then enter 69C8 descriptor walker",
    ),
    (
        0x682A,
        "cda0673ae885fe12c8cd3d682d3aeb858518e4ed",
        "draw/update helper calls 67A0 and, except kind 12, maps current cell to pixels via 683D",
    ),
    (
        0x683D,
        "ed5be985ed4bdf857a05fa4e68c60718f85721eb857b0dfa5c6886c60218f76f62c9",
        "cell-to-pixel mapper: 85E9 base + 7*col, then row heights at 85EB plus 2 px gaps",
    ),
    (
        0x69C8,
        "21000022df8521e8857ee60f116f682823118068fe02381cca8a6ac610119c",
        "descriptor selector: kind 0 -> 686F, kind 1 -> 6880, kind 2 jumps to fraction path 6A8A",
    ),
    (
        0x69E3,
        "c610119c68cd5e02200fc61011a568cd54022005e60f119368c61077eb",
        "descriptor-family cascade for kind >= 3: choose 689C/68A5/6893 and store normalized kind",
    ),
    (
        0x6A00,
        "cde26bd5141c1ced53e985cde26be3cdf56ae17e32eb8523cde26bed53e185cde26beb22ec85",
        "descriptor reader: 6BE2 words seed 85E9, draw descriptor box, row height 85EB, dims 85E1, cells 85EC",
    ),
    (
        0x6A27,
        "cd3d6822d7863ae885cb4f20173ae085c631cddb3c3e3acddb3c3e20cddb3c3e20cddb3ce156235e23e5d5cd626b",
        "descriptor cell loop: map 85DF to pixels, then load a two-byte display cell and route FB strings through 6B62",
    ),
    (
        0x6A4B,
        "e156235e23e5d5cd626bcde76bd1cd444f280b3ad8863d061d1646cd6c4fed5be18521e0857e3cba28037718af3600",
        "descriptor cell emit tail: measure cell/string width, test FB C7/C8 markers, advance 85E0",
    ),
    (
        0x6A8A,
        "3aee85b7c8211112114c35cdf56a1617215b6bcd2d6b162221546bcd2d6b3e4f212c2c22d786cddb3c3e4bcddb3ccd0e6bcd076bb7",
        "kind-2 fraction path: requires 85EE, draws fraction box, emits row labels, then enters rule/operand helpers",
    ),
    (
        0x6ABF,
        "f5ed4bdf85cb482808212a2b11343318132615cb4028022620793ccd1c6b2d141414141cf1cd33483805ef7d4d1803ef864dcd2248c9",
        "fraction-bar rectangle: choose row geometry, use 6B1C endpoint math, call 4833/4822 draw-window helpers",
    ),
    (
        0x6AF5,
        "cd3348ef8c4d18f4",
        "descriptor/fraction box draw wrapper: call 4833, bcall 4D8C, then restore via the 4822 tail",
    ),
    (
        0x6B1C,
        "2e07473e1b8510fd6fc6045f7cc60657c9",
        "rule endpoint math: start at 0x1B, add 7 px per cell, set right endpoint +4 and y +6",
    ),
    (
        0x6B62,
        "2600180226017afefb202f7bcb442807fec821b26b2827feca21a96b2820fecb21ad6b2819fed621bf6b2812fed821cb6b280bfed721d76b2804efca45c911f297d5cd2b19e1c903",
        "FB string loader: only known FB menu/answer strings are copied to 97F2 for measurement/emission",
    ),
    (
        0x6BE2,
        "5e235623c9",
        "descriptor word reader: load little-endian DE from HL and advance",
    ),
    (
        0x6BE7,
        "462378b7c87efe20280818017ecddb3c18002310f7c9",
        "descriptor string/cell width helper: consume counted bytes and measure non-space glyphs",
    ),
]

GEOMETRY_FLOW_XREF_TARGETS = [
    0x67A0, 0x682A, 0x683D, 0x68AE, 0x69C8, 0x6A8A, 0x6ABF,
    0x6AF5, 0x6B1C, 0x6B62, 0x6BE2, 0x6BE7,
]

GEOMETRY_SELECTOR_CLOSED_RANGE = (0x69C8, 0x6BFE)

GEOMETRY_SELECTOR_CLOSED_ANCHORS = [
    item for item in GEOMETRY_FLOW_ANCHORS
    if GEOMETRY_SELECTOR_CLOSED_RANGE[0] <= item[0] <= GEOMETRY_SELECTOR_CLOSED_RANGE[1]
]

GEOMETRY_SELECTOR_CALL_TARGETS = [
    0x683D, 0x6A8A, 0x6ABF, 0x6AF5, 0x6AFD, 0x6B1C, 0x6B2D,
    0x6B62, 0x6BE2, 0x6BE7, 0x3CDB, 0x4833, 0x4822, 0x4F44, 0x4F6C,
]

GEOMETRY_SELECTOR_STATE_WORDS = [
    (0x85E8, "template kind/state byte"),
    (0x85DF, "descriptor row/col cursor pair"),
    (0x85E0, "descriptor column cursor"),
    (0x85E1, "descriptor cols/rows pair"),
    (0x85E9, "descriptor pixel base"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x9D27, "saved measured fraction pair"),
    (0x86D7, "graph text/rectangle coordinate pair"),
]

TEMPLATE_DESCRIPTOR_ALGORITHM_ANCHORS = [
    (
        0x6761,
        "32e8853e4832de85c9",
        "template kind setter: store selected kind in 85E8, force 85DE=48 geometry state",
    ),
    (
        0x6773,
        "f5cd6a67cddb6d2805cd546d1803",
        "template action wrapper: set box/menu flags, restore action, set kind, then menu redraw",
    ),
    (
        0x68AE,
        "21e8850e10fe4928100cfe48280b0cfe2ecad0680cfe5a200f79c37367cd33",
        "geometry action selector: actions 49/48/2E/5A select template kinds 10/11/12/13",
    ),
    (
        0x69C8,
        "21000022df8521e8857ee60f116f682823118068fe02381cca8a6ac610119c",
        "descriptor selector: clear row/col, choose descriptor 686F/6880 or kind-2 fraction path",
    ),
    (
        0x6A00,
        "cde26bd5141c1ced53e985cde26be3cdf56ae17e32eb8523cde26bed53e185",
        "descriptor ABI reader: base word, box word, row height, cols/rows, cell pointer",
    ),
    (
        0x683D,
        "ed5be985ed4bdf857a05fa4e68c60718f85721eb857b0dfa5c6886c60218f76f62c9",
        "cell-to-pixel mapper: descriptor base plus 7 px columns and row-height+2 stacking",
    ),
    (
        0x6A27,
        "cd3d6822d7863ae885cb4f20173ae085c631cddb3c3e3acddb3c3e20cddb3c",
        "descriptor cell loop: map current cell, optionally emit slot labels, then read display cell",
    ),
    (
        0x6A4B,
        "e156235e23e5d5cd626bcde76bd1cd444f280b3ad8863d061d1646cd6c4f",
        "descriptor cell tail: load/string-measure cell, test marker gate, advance descriptor column",
    ),
    (
        0x6B62,
        "2600180226017afefb202f7bcb442807fec821b26b2827feca21a96b2820",
        "descriptor string loader: only selected FB menu/answer strings become measured strings",
    ),
    (
        0x6BE7,
        "462378b7c87efe20280818017ecddb3c18002310f7c9",
        "descriptor width helper: counted string/cell width scan for non-space glyphs",
    ),
]

TEMPLATE_PIXEL_DESCRIPTOR_EXPECTED = {
    0x686F: {
        "base": 0x1801,
        "box": 0x3535,
        "row_height": 0x06,
        "cols": 4,
        "rows": 1,
        "cells_ptr": 0x6878,
    },
    0x6880: {
        "base": 0x1115,
        "box": 0x3555,
        "row_height": 0x06,
        "cols": 5,
        "rows": 1,
        "cells_ptr": 0x6889,
    },
    0x6893: {
        "base": 0x113A,
        "box": 0x354E,
        "row_height": 0x08,
        "cols": 5,
        "rows": 2,
        "cells_ptr": 0x63EE,
    },
    0x689C: {
        "base": 0x0A3A,
        "box": 0x3556,
        "row_height": 0x0C,
        "cols": 6,
        "rows": 2,
        "cells_ptr": 0x6405,
    },
    0x68A5: {
        "base": 0x1F3A,
        "box": 0x354E,
        "row_height": 0x08,
        "cols": 3,
        "rows": 2,
        "cells_ptr": 0x6420,
    },
}

TEMPLATE_PIXEL_DESCRIPTOR_SAMPLES = [
    (0x686F, 0, 0, 0x01, 0x18, (0xFB, 0xCA), "kind-10 n/d menu cell"),
    (0x6880, 0, 3, 0x2A, 0x11, (0x00, 0xC8), "kind-11 fnInt( descriptor cell"),
    (0x6880, 0, 4, 0x31, 0x11, (0xFB, 0xC7), "kind-11 square-down marker"),
    (0x6893, 1, 2, 0x48, 0x1B, (0xFC, 0x0A), "kind-13 two-row cell family A"),
    (0x689C, 1, 5, 0x5D, 0x18, (0xFC, 0x18), "kind-13 six-column lower-right cell"),
    (0x68A5, 1, 2, 0x48, 0x29, (0xFC, 0x1E), "kind-13 three-column lower-right cell"),
]

CELL_PIXEL_MAPPER_FLOW_ANCHORS = [
    (
        0x682A,
        "cda0673ae885fe12c8cd3d682d3aeb858518e4ed",
        "current-cell redraw helper: call 67A0, skip kind 12, then map current cell through 683D",
    ),
    (
        0x6833,
        "cd3d682d3aeb858518e4",
        "draw-indented helper: call 683D, decrement x, add row height, then continue to row-6 draw",
    ),
    (
        0x683D,
        "ed5be985ed4bdf857a05fa4e68c60718f85721eb857b0dfa5c6886c60218f76f62c9",
        "cell-to-pixel mapper: 85E9 base + 7*col, then row heights at 85EB plus 2 px gaps",
    ),
    (
        0x68AE,
        "21e8850e10fe4928100cfe48280b0cfe2ecad0680cfe5a200f79c37367cd336837c979cd",
        "geometry action dispatcher entry: kind select and visible-cell actions call 6833",
    ),
    (
        0x6A27,
        "cd3d6822d7863ae885cb4f20173ae085c631cddb3c3e3acddb3c3e20cddb3c3e20cddb3ce156235e23e5d5cd626b",
        "descriptor cell loop: call 683D, write 86D7, then emit descriptor strings/cells",
    ),
]

CELL_PIXEL_MAPPER_EXPECTED_CALLERS = {
    0x682A: {0x4C51: "85DE=48 setup-state jump into redraw/update helper"},
    0x6833: {
        0x68CB: "kind-select path draws the indented current-cell cue",
        0x68FB: "descriptor visible-slot path draws the indented current-cell cue",
    },
    0x683D: {
        0x6833: "draw-indented wrapper maps cursor to pixels before row-6 draw",
        0x6A27: "descriptor cell loop maps each descriptor grid cell to 86D7",
    },
}

CELL_PIXEL_MAPPER_WINDOWS = [
    (0x682A, 0x685D, "current-cell redraw helper plus 683D mapper"),
    (0x68AE, 0x6951, "geometry action path before kind-2 measured fraction edits"),
    (0x6A27, 0x6A5D, "descriptor cell loop using mapped 86D7 coordinates"),
]

CELL_PIXEL_MAPPER_STATE_WORDS = [
    (0x85DF, "descriptor row/col cursor pair"),
    (0x85E0, "descriptor column cursor"),
    (0x85E1, "descriptor cols/rows pair"),
    (0x85E8, "template kind/state byte"),
    (0x85E9, "descriptor pixel base"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph text coordinate pair"),
    (0x9D27, "saved measured fraction pair"),
]

CELL_PIXEL_MAPPER_DRAW_PATTERNS = [
    ("CALL 67A0 geometry draw wrapper", "cda067"),
    ("CALL 683D cell-to-pixel mapper", "cd3d68"),
    ("CALL 6833 draw-indented helper", "cd3368"),
    ("CALL 6B62 descriptor string loader", "cd626b"),
    ("CALL 6BE7 descriptor width helper", "cde76b"),
    ("CALL 4F44 square-marker gate", "cd444f"),
    ("CALL 3555 _DarkLine", "cd5535"),
    ("CALL 3B37 display-byte mapper", "cd373b"),
    ("CALL 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL 3CDB VPutMap", "cddb3c"),
    ("CALL 4833 graph-window setup", "cd3348"),
    ("CALL 6AF5 descriptor/fraction box", "cdf56a"),
    ("CALL 6ABF fraction row/rule", "cdbf6a"),
    ("RST28 _ClearRect", "ef5c4d"),
    ("RST28 _InvertRect", "ef5f4d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
]

DESCRIPTOR_MARKER_FLOW_ANCHORS = [
    (
        0x6A4B,
        "e156235e23e5d5cd626bcde76bd1cd444f280b3ad8863d061d1646cd6c4f",
        "descriptor cell tail: load DE cell, route string, measure width, then test FB C7/C8 marker cells",
    ),
    (
        0x4F44,
        "21c8fbcdbb2120063e07cd9138c021c7fbcdbb212802afc93e06cd9138c9",
        "descriptor square-marker gate: compare DE with FB C8/FB C7 and dispatch page-3D actions 7/6",
    ),
    (
        0x4F6C,
        "ed44c63bc5d5cd0f22d1c14f5fcd60203af289f5fdcb02cecd5535",
        "post-marker display helper: normalize split/display state before page-1 draw service",
    ),
]

DESCRIPTOR_MARKER_CELLS = [
    (0xFB, 0xC8, "square-up marker"),
    (0xFB, 0xC7, "square-down marker"),
    (0x00, 0xC8, "fnInt display cell"),
    (0x00, 0xC7, "nDeriv display cell"),
]

DESCRIPTOR_MARKER_FLOW_XREF_TARGETS = [0x4F44, 0x4F6C, 0x3891, 0x6A4B, 0x6B62, 0x6BE7]

FRACTION_TEMPLATE_FLOW_ANCHORS = [
    (
        0x6A8A,
        "3aee85b7c8211112114c35cdf56a1617215b6bcd2d6b162221546bcd2d6b3e4f212c2c22d786cddb3c3e4bcddb3ccd0e6bcd076bb7",
        "kind-2 fraction template: require 85EE, draw fixed box, print ROW/COL/OK labels, then focus numerator/denominator",
    ),
    (
        0x6B2D,
        "1e13ed53d786cde76b0631180f3e20cddb3c3e20cddb3c3e20cddb3c78cddb3c0478fe37c818e6",
        "ROW/COL label printer: set 86D7 to x=13,y=D, measure counted label, then print labels 1..6",
    ),
    (
        0x6B54,
        "06434f4c3a2020",
        "counted label string 'COL:  '",
    ),
    (
        0x6B5B,
        "06524f573a2020",
        "counted label string 'ROW:  '",
    ),
    (
        0x6AFD,
        "21e085cb4ec0cb46200726173aee85180526223aef85c5cd1c6bef5f4dc1c9",
        "focused-cell inverter: 85E0 bit0 selects 85EE/85EF and y=17/22, then _InvertRect",
    ),
    (
        0x6ABF,
        "f5ed4bdf85cb482808212a2b11343318132615cb4028022620793ccd1c6b2d141414141cf1cd33483805ef7d4d1803ef864dcd2248c9",
        "fraction row rectangle: carry selects draw/erase, 85DF selects whole box vs numerator/denominator row",
    ),
    (
        0x6B1C,
        "2e07473e1b8510fd6fc6045f7cc60657c9",
        "shared endpoint math: x_left=0x1B+7*n, x_right=x_left+4, y=H+6",
    ),
]

FRACTION_TEMPLATE_FLOW_XREF_TARGETS = [0x6A8A, 0x6ABF, 0x6AFD, 0x6B07, 0x6B0E, 0x6B1C, 0x6B2D]

TEMPLATE_CHROME_FLOW_ANCHORS = [
    (
        0x67A0,
        "cd3348cdac67cd2248c3c869",
        "geometry redraw wrapper: save graph-window state, draw template chrome, restore, then enter 69C8",
    ),
    (
        0x67AC,
        "fdcb02ce210035115e3eef5c4d3e04215f68110337010801f5ed53d786",
        "template chrome prologue: set graph draw flag, clear the template rectangle, and set up the four-tab loop",
    ),
    (
        0x67CE,
        "11fe85d5cd9c1aaf12e3cdf93ce1c1e5501e02cd5535",
        "tab-label loop body: copy one 4-byte label to 85FE, terminate it, draw text, then draw separator lines",
    ),
    (
        0x67F8,
        "ed5bd786f15ff13d20c23aee85b7010529110537cc5535",
        "tab-label loop tail: advance the tab rectangle; when no saved geometry exists, draw the empty-template cue",
    ),
    (
        0x680F,
        "3ae885e60f3c473eefc61310fc6f2637c6105f3e068457ef5f4d",
        "active-tab highlighter: (85E8 & 0F) selects x={02,15,28,3B}, then inverts that tab rectangle",
    ),
    (
        0x682A,
        "cda0673ae885fe12c8cd3d682d3aeb858518e4ed",
        "current-cell redraw: repaint chrome, skip kind 12 fraction-only geometry, otherwise map current cell to pixels",
    ),
    (
        0x683D,
        "ed5be985ed4bdf857a05fa4e68c60718f85721eb857b0dfa5c6886c60218f76f62c9",
        "cell-to-pixel mapper: x=base_x+7*col; y=base_y+sum(row_height+2) for previous rows",
    ),
    (
        0x685F,
        "4652414346554e434d54525859564152",
        "literal tab-label data: FRAC FUNC MTRX YVAR",
    ),
]

TEMPLATE_CHROME_BCALLS = [
    (0x67B6, 0x4D5C, "_ClearRect", "clear the whole template/menu rectangle"),
    (0x6826, 0x4D5F, "_InvertRect", "invert the active tab rectangle"),
    (0x6AF8, 0x4D8C, "_DrawRectBorderClear", "draw a cleared descriptor/fraction box border"),
    (0x6AE9, 0x4D7D, "_DrawRectBorder", "draw the fraction-bar rectangle in set mode"),
    (0x6AEE, 0x4D86, "_EraseRectBorder", "draw the fraction-bar rectangle in erase mode"),
    (0x6B17, 0x4D5F, "_InvertRect", "invert the focused fraction endpoint/cell rectangle"),
]

TEMPLATE_CHROME_FLOW_XREF_TARGETS = [0x67A0, 0x67AC, 0x682A, 0x683D, 0x69C8, 0x6AF5, 0x6ABF, 0x6B1C]

TEMPLATE_STATE_FLOW_ANCHORS = [
    (
        0x4C40,
        "3ade85fe48f5fe213e0120013c324a98f1ca2a68",
        "draw/indent entry: special 85DE=48 state jumps to 682A geometry redraw",
    ),
    (
        0x4FC4,
        "3ade85fe49cac16cfe4878200bfe092807fe40281ec3ae68",
        "layout dispatcher: when 85DE=48, non-09/40 actions route to 68AE",
    ),
    (
        0x6753,
        "21000018032a279d22ee853ae88532e8853e4832de85c9",
        "template-state seed: clear/copy 85EE, mirror 85E8, then force 85DE=48",
    ),
    (
        0x6761,
        "32e8853e4832de85c9",
        "set template kind: A -> 85E8, then force 85DE=48",
    ),
    (
        0x676A,
        "fdcb1df6fdcb1dfec9",
        "template box flags: set bits 6 and 7 of (IY+1D)",
    ),
    (
        0x6773,
        "f5cd6a67cddb6d2805cd546d1803cd6654cd6a67f1cd6167cddb6dcae749",
        "menu-action wrapper: box flags, menu update, restore action, set 85E8/85DE via 6761",
    ),
    (
        0x6791,
        "cd024a3e4832de85c9",
        "post-menu redraw path: call 4A02, then force 85DE=48",
    ),
    (
        0x68AE,
        "21e8850e10fe4928100cfe48280b0cfe2ecad0680cfe5a200f79c373",
        "geometry action mapper: 49/48/2E/5A choose kind 10/11/12/13, otherwise edit current cell",
    ),
]

TEMPLATE_STATE_FLOW_XREF_TARGETS = [0x4C40, 0x6761, 0x676A, 0x6773, 0x682A, 0x68AE, 0x69C8]

TEMPLATE_DRAW_BRIDGE_FLOW_ANCHORS = [
    (
        0x49A8,
        "cd6a67cdbd66cdca04cd744a184c",
        "recursive template-cell path: set box flags, normalize state, dispatch token/action, then fall into 4A02",
    ),
    (
        0x4A02,
        "cd404cfdcb0ce6cde94ccdb648280237c93eaa327784",
        "draw/emit wrapper: call 4C40, set draw/geometry-committed flag, place row title, then continue display update",
    ),
    (
        0x4C40,
        "3ade85fe48f5fe213e0120013c324a98f1ca2a68",
        "draw bridge: only special state 85DE=48 jumps to 682A; ordinary classes continue row/cell emission",
    ),
    (
        0x682A,
        "cda0673ae885fe12c8cd3d68",
        "geometry redraw tail: draw window/template chrome, then return only for kind 12; otherwise map focused cell",
    ),
    (
        0x67A0,
        "cd3348cdac67cd2248c3c869",
        "geometry draw window: save graph-window state, draw template chrome, restore, then jump to 69C8",
    ),
]

TEMPLATE_DRAW_BRIDGE_FLOW_XREF_TARGETS = [0x49A8, 0x4A02, 0x4C40, 0x682A, 0x67A0, 0x69C8]

TEMPLATE_DRAW_BRIDGE_CALLER_ANCHORS = [
    (
        0x4FC4,
        "3ade85fe49cac16cfe4878200bfe092807fe40281ec3ae68",
        "class-state gate: 85DE=48 routes non-09/non-40 actions to 68AE before generic action dispatch",
    ),
    (
        0x5021,
        "fe0120233ade85fe10280bfe2b2807fdcb116ec2b050",
        "generic action 01 row-advance path reached only after the class-48 geometry gate",
    ),
    (
        0x5048,
        "fe0220303ade85fe10280bfe2b2807fdcb116ec25351",
        "generic action 02 row-retreat path reached only after the class-48 geometry gate",
    ),
    (
        0x506E,
        "cd274ccd0e4bcd4e54cd404c1831",
        "generic action 01/02 redraw tail: reload handler, refresh menu state, call 4C40, return",
    ),
]

TEMPLATE_DRAW_BRIDGE_4C40_CALLERS = {
    0x4A02: "normal draw wrapper before row placement",
    0x5077: "generic action 01/02 row-navigation redraw tail",
}

TEMPLATE_DRAW_BRIDGE_RAW_REF_ANCHORS = [
    (
        0x650D,
        "01024a1040034e",
        "class 27 handler record: rows=1, count=02, action=4A, cells 1040/034E",
    ),
]

TEMPLATE_DRAW_BRIDGE_RAW_REF_EXPECTED = {
    0x4A02: {
        0x650E: "class 27 record count/action bytes 02 4A, not executable control flow",
    },
}

TEMPLATE_EMISSION_CLOSURE_ANCHORS = [
    (
        0x4F9A,
        "fdcb36664728233a9a85fe402006",
        "layout dispatcher entry: save incoming action, optional draw-pass preload, then class-state gate",
    ),
    (
        0x4FC4,
        "3ade85fe49cac16cfe4878200bfe092807fe40281ec3ae68",
        "class-state gate: class 49 menu/editor branch, class 48 routes non-09/non-40 actions to geometry",
    ),
    (
        0x4FD9,
        "c3ae68",
        "the only direct page-39 control-flow entry into eqdisp_layout_token_geom (68AE)",
    ),
    (
        0x4DE6,
        "3a4a98324b84cd0a4e56235e23e5c5cd8e4e",
        "record-row cell emitter loop: load each decoded cell and call 4E8E",
    ),
    (
        0x4DF5,
        "cd8e4e",
        "record-row display-cell call into eqdisp_emit_glyph",
    ),
    (
        0x5B63,
        "c38e4e",
        "saved-operand display-cell tail jumps into eqdisp_emit_glyph",
    ),
    (
        0x6692,
        "cd373b",
        "delimiter classifier's only page-39 call into the page-7 display-byte classifier",
    ),
]

TEMPLATE_EMISSION_CLOSURE_TARGETS = [
    (0x68AE, "geometry action dispatcher"),
    (0x69C8, "descriptor/fraction geometry selector"),
    (0x4E8E, "decoded record/descriptor cell emitter"),
    (0x4F1A, "direct large-glyph cell mapper"),
    (0x3B37, "page-7 display-byte classifier bjump"),
    (0x3B3D, "page-7 large-font blitter bjump"),
    (0x3CDB, "page-1 _VPutMap graph/small-font bjump"),
    (0x4833, "graph-window setup helper"),
    (0x4822, "graph-window restore helper"),
    (0x6AF5, "descriptor/fraction box draw helper"),
    (0x6ABF, "fraction row/rule rectangle helper"),
    (0x6B1C, "fraction endpoint coordinate helper"),
]

GEOMETRY_ACTION_FLOW_ANCHORS = [
    (
        0x68AE,
        "21e8850e10fe4928100cfe48280b0cfe2ecad0680cfe5a200f79c37367cd336837c979cd",
        "eqdisp_layout_token_geom entry: actions 49/48/2E/5A select template kinds 10/11/12/13 through 6773",
    ),
    (
        0x68D6,
        "ed4bdf852ae185573ae885e60ffe025f7aca5169fe05283efe03201205f2fa6844051815c5cd3368e122df8518c7fe0420120478bc20ed06007dfe0128e679ee014f18e0cb4b2029fe8f3820fe98301cd68fbc301a471e0079b728047ccb275f2aec85160019cd5f59c3ad53c3215437c9",
        "non-fraction geometry edit path: row up/down, action-05/current cell dispatch, and direct 8F..97 slot actions",
    ),
    (
        0x6951,
        "473aee85b778282ced4bdf85fe052026cb4828093ed03246843efb18d1cdfd6a793ccb4021ee85280123772aee8522279dcdfd6a37c9",
        "kind-2 measured fraction action-05 path: require 85EE, update 85EE/85EF, copy pair to 9D27, redraw focus",
    ),
    (
        0x6987,
        "cb482025fe01201679fe0528f13c4fc537cdbf6ae122df85b7cdbf6a18e0fe022007793dfa856918e5fe032008783dfa85694718dafe04208278fe0228c03c18f1",
        "kind-2 measured fraction navigation path: actions 1/2 adjust columns and 3/4 adjust rows through 6ABF",
    ),
]

GEOMETRY_ACTION_FLOW_XREF_TARGETS = [0x6773, 0x6833, 0x68AE, 0x68D6, 0x692C, 0x693F, 0x6951, 0x696E, 0x6987, 0x6ABF, 0x6AFD]

GEOMETRY_HANDOFF_FLOW_ANCHORS = [
    (
        0x4A74,
        "fe3dca2e67",
        "dispatch special case: incoming token/action byte 3D jumps to 672E before class-table setup",
    ),
    (
        0x672E,
        "cdbd66cd7720281dcdff3628073a9a85fe402011cddb6d200cfdcb456e2806fdcb444e20052100001803",
        "special token path: after context/menu guards, choose zero geometry or reload previous 9D27 measurement",
    ),
    (
        0x6753,
        "21000018032a279d22ee853ae88532e8853e48",
        "handoff seed: either HL=0000 or HL=(9D27), then store 85EE and force 85DE=48",
    ),
    (
        0x6951,
        "473aee85b778282ced4bdf85fe052026cb4828093ed03246843efb18d1cdfd6a793ccb",
        "geometry kind-2 action handler: requires 85EE before updating fraction row/column counts",
    ),
    (
        0x696E,
        "cdfd6a793ccb4021ee85280123772aee852227",
        "fraction count update: call 6AFD, write 85EE/85EF, copy measured pair to 9D27",
    ),
    (
        0x6AFD,
        "21e085cb4ec0cb46200726173aee85180526223aef85c5cd1c6bef5f4d",
        "fraction/radicand endpoint helper: inspect 85E0 flags and use 85EE/85EF with 6B1C",
    ),
]

GEOMETRY_HANDOFF_FLOW_XREF_TARGETS = [0x672E, 0x6753, 0x6951, 0x696E, 0x697C, 0x6AFD]

TEMPLATE_HANDOFF_GUARD_FLOW_ANCHORS = [
    (
        0x00,
        0x2077,
        "fdcb446ec9",
        "RAM/page-0 helper: BIT 5,(IY+44), the MathPrintActive test used by 672E and page-4 guard",
    ),
    (
        0x00,
        0x36FF,
        "cd092b",
        "RAM/page-0 bjump stub used by 672E, raw Ghidra resolves it to page_04:7FBA",
    ),
    (
        0x04,
        0x7FBA,
        "c5473a9a85fe4978c1c0cd77202009fdcb028eb7c0fe01c9fdcb4476c0fdcb3566c8c547e521989bcd0333e178c128e3",
        "page-4 guard: checks 859A=49, MathPrintActive, IY+44 bit 6, IY+35 bit 4, and 9B98 state",
    ),
    (
        0x39,
        0x672E,
        "cdbd66cd7720281dcdff3628073a9a85fe402011cddb6d200cfdcb456e2806fdcb444e200521000018032a279d22ee853ae88532e8853e4832de85",
        "page-39 token-3D handoff guard: choose HL=0000 or HL=(9D27), then store 85EE and force 85DE=48",
    ),
    (
        0x39,
        0x676A,
        "fdcb1df6fdcb1dfec9",
        "template box flag helper: set bits 6 and 7 of (IY+1D), then return",
    ),
    (
        0x39,
        0x6773,
        "f5cd6a67cddb6d2805cd546d1803cd6654cd6a67f1cd6167cddb6dcae749cd024a3e4832de85c9",
        "menu-action wrapper: set box flags, run menu/editor path, set 85E8/85DE, then redraw or re-enter render loop",
    ),
]

TEMPLATE_HANDOFF_GUARD_XREF_TARGETS = [0x2077, 0x36FF, 0x672E, 0x6761, 0x676A, 0x6773, 0x49E7, 0x4A02]

MEASURED_STATE_WORDS = [
    (0x85E9, "descriptor base/origin pair"),
    (0x85EB, "descriptor row-height byte and adjacent geometry state"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "fraction/template measured column count"),
    (0x85EF, "fraction/template measured row count"),
    (0x86D7, "graph pen position pair"),
    (0x86D8, "graph pen y/next byte"),
    (0x9D27, "saved measured fraction pair"),
    (0x984B, "display/menu state byte"),
    (0x984C, "display/menu state byte"),
]

MEASURED_STATE_FLOW_ANCHORS = [
    (
        0x5BA1,
        "11bf8421e885cd941a973246843e58fdcb26462073",
        "saved-OP/list-token tail: copy 85E8.. state to 84BF, clear 8446, seed token/menu handling",
    ),
    (
        0x5BD0,
        "3ade85fe1020503ae985fe06300fc6773246843efecddb6dc2b96c",
        "only non-geometry 85E9 read: when class 10 and 85E9 < 6, set 8446=85E9+77 and query menu flag FE",
    ),
    (
        0x5BED,
        "21c684cd1e1c21c684cd1e1c3e29cddb6d2829cd546dfdcb0ca6",
        "class-10 85E9 >= 6 branch: shift 84C6 twice, query menu flag 29, maybe force class-49 editor state",
    ),
    (
        0x6A00,
        "cde26bd5141c1ced53e985cde26be3cdf56ae17e32eb8523cde26bed53e185cde26beb22ec85",
        "descriptor geometry producer: seed 85E9, row height 85EB, dims 85E1, and cell pointer 85EC",
    ),
    (
        0x683D,
        "ed5be985ed4bdf857a05fa4e68c60718f85721eb857b0dfa5c6886c60218f76f62c9",
        "descriptor geometry consumer: map 85E9/85EB and 85DF to pixel coordinates",
    ),
    (
        0x696E,
        "cdfd6a793ccb4021ee85280123772aee852227",
        "fraction measured-state writer: update 85EE/85EF and copy the pair to 9D27",
    ),
]

MEASURED_STATE_FLOW_XREF_TARGETS = [0x5BA1, 0x683D]

CLASS10_SAVED_TAIL_FLOW_ANCHORS = [
    (
        0x5B52,
        "3ade85fe10280dcd235ac2ae6516821e4dc38e4e",
        "saved operand tail: class 10 takes the special symbol/list path; other classes emit string/control cell 824D",
    ),
    (
        0x5B66,
        "21e885e5cdab66e17efe31caa265fe5dc2a265237efe062bd2a2653ccb275feff751cdb73cc9",
        "class-10 special path: call 66AB, check 85E8/85E9 bounds, bcall 51F7, then erase-to-EOL",
    ),
    (
        0x66AB,
        "c5cd600ec1d8cd85177eb7c83e2acddb3fc9",
        "symbol-presence helper: _ChkFindSym, ret/no-op check, output '*' through _PutC-style bjump if found",
    ),
    (
        0x65A2,
        "3ade85fe1028012b06051837",
        "string/list fallback setup: class 10 keeps HL, other classes back up once, then print up to five bytes",
    ),
    (
        0x65AE,
        "cd4d20280cfe142026afcd9138282318173e02effc522817c5cd600ec13822cd85177eb73e18",
        "non-class-10 fallback: type/menu tests, _ChkFindSym and optional string marker output",
    ),
]

CLASS10_SAVED_TAIL_XREF_TARGETS = [0x5B46, 0x5B66, 0x66AB, 0x65A2, 0x65AE]

CLASS10_DYNAMIC_SELECTOR_FLOW_ANCHORS = [
    (
        0x39,
        0x5BA1,
        "11bf8421e885cd941a973246843e58fdcb26462073cd3a5c20093e013246843e591865cd2e5c3e46285e3efd3246843ade",
        "action-5 saved-operand branch: copy 85E8 state, derive menu/list token state, then enter class-10 selector",
    ),
    (
        0x39,
        0x5BD0,
        "3ade85fe1020503ae985fe06300fc6773246843efecddb6dc2b96c183c",
        "class 10 and 85E9 < 6: generate FE(85E9+77), test menu flag, then possibly enter class-49 state",
    ),
    (
        0x39,
        0x5BED,
        "21c684cd1e1c21c684cd1e1c3e29cddb6d2829cd546dfdcb0ca63e7fcdc26c060821be84237eb7280fc5e516005fcd3f3fcdc26ce1c110ec37c93e28cd5b54b7c9",
        "class 10 and 85E9 >= 6: shift saved token buffer twice, query class-29/menu state, then dispatch/restore",
    ),
    (
        0x39,
        0x6CB9,
        "fe402809cd546d4778fe40200dcd966dcdd56d3e96cd665437c9",
        "class-49 post-menu state path reached from the selector only on nonzero menu/app flag result",
    ),
    (
        0x39,
        0x6DDB,
        "e521db9ccb7ee1c9",
        "menu/app flag test used by FE and class-29 selector paths; it does not draw or consume geometry",
    ),
    (
        0x07,
        0x411E,
        "5d005d015d025d035d045d05",
        "page-7 FE pair-table outputs for FE77..FE7C generated by the class-10 selector",
    ),
]

CLASS10_DYNAMIC_SELECTOR_STATE_WORDS = [
    (0x85E8, "saved template/menu kind byte"),
    (0x85E9, "selector index byte used as FE low-byte offset"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x9D27, "saved measured fraction pair"),
    (0x86D7, "graph pen coordinate pair"),
]

CLASS10_BCALL_51F7_ANCHORS = [
    (
        0x3B,
        0x51F7,
        "856475",
        "bcall table entry 51F7 -> addr 6485, page byte 75 masked to page 35",
    ),
    (
        0x35,
        0x6485,
        "cd8a60cd1d22cd853ec9",
        "51F7 target wrapper: select string pointer, copy 18 bytes to keyForStr, call _PutS trampoline, return",
    ),
    (
        0x35,
        0x608A,
        "160021d26319c333",
        "string-pointer selector: D=0, HL=63D2+E, then _LdHLind loads the selected pointer",
    ),
    (
        0x00,
        0x221D,
        "f5c5d511769dd5011200edb0e1d1c1f1c9",
        "fixed-page copy18_to_9d76 helper: copy 18 bytes from HL to keyForStr (9D76)",
    ),
    (
        0x00,
        0x3E85,
        "cd092b395c01",
        "RAM trampoline entry: CALL cross_page_jump; inline target 01:5C39 (_PutS)",
    ),
    (
        0x01,
        0x5C39,
        "c5f53aa697477e23b7372809cd4c5b3a4b84b838f1c178c1c9",
        "_PutS target: read NUL-terminated string from HL and output chars through _PutC",
    ),
]

ENTRY_DISPATCH_FLOW_ANCHORS = [
    (
        0x4851,
        "fe3e2002b7c9fe2e2009473ade85fe48782806cd3249da3949",
        "outer entry filter: bytes below 3E enter the page-39 dispatch path before class remap",
    ),
    (
        0x4932,
        "fe3ed0fe2b3fc9",
        "range predicate: accept incoming bytes 2B..3D, reject 3E and above",
    ),
    (
        0x4939,
        "473ade85fe4978cc326dfdcb2a8efdcb2686cd2d5dca114a",
        "accepted-byte dispatcher: preserve A, apply context flags, then continue toward token dispatch",
    ),
    (
        0x496C,
        "fe3d2020cdbd663ade85fe493e3d282c3a4b98f53e09cd5148",
        "incoming byte 3D special path: menu/context guard before re-emitting 3D",
    ),
    (
        0x49A8,
        "cd6a67cdbd66cdca04cd744a",
        "recursive token display path: set template box flags, then call 4A74",
    ),
    (
        0x49B6,
        "cd6a67f5af324b9832bf84cd404a380ccdf765f1cdca04cd744a",
        "alternate recursive path: clear transient state, redraw setup, then call 4A74",
    ),
    (
        0x4A74,
        "fe3dca2e67d62a",
        "class remap boundary: 3D jumps to 672E; ordinary path subtracts 2A into 85DE class space",
    ),
]

ENTRY_DISPATCH_FLOW_XREF_TARGETS = [0x4932, 0x4939, 0x496C, 0x49A8, 0x49B6, 0x4A74, 0x672E]

DISPATCH_CONTEXT_FLOW_ANCHORS = [
    (
        0x4A74,
        "fe3dca2e67d62afe112016fdcb02662010c629fdcb02762008",
        "4A74 dispatch: 3D special-case, ordinary A-2A class, then raw 3B exponent-context bias",
    ),
    (
        0x4A8D,
        "3cfdcb026e20013cfdcb0946281afe032814fe062810fe05280cfe072808fe082804fe042002c628",
        "4A8D/4A95 context bias: exponent bits can increment again; fraction/argument context maps classes 03..08 to 2B..30",
    ),
    (
        0x4AFD,
        "fdcb16ae22df8532de85cd274c7e32e1853adf85be3018",
        "post-dispatch setup: store computed class in 85DE, load handler record, store row count",
    ),
    (
        0x4C27,
        "3e00fdcb3676c4bb2cc03ade8521455ecb2716005f19c333003ade85fe48",
        "handler lookup: pointer = 5E45 + 2*85DE, then _LdHLind",
    ),
]

DISPATCH_CONTEXT_SAMPLES = [
    (0x3B, 0x10, 0x00, "raw 3B, exponent bit4 set: ordinary class 11"),
    (0x3B, 0x00, 0x00, "raw 3B, exponent bits 4/6/5 all reset: final class 3C"),
    (0x2D, 0x10, 0x00, "raw 2D, no fraction/argument context: class 03"),
    (0x2D, 0x10, 0x01, "raw 2D, fraction/argument context: class 2B"),
    (0x32, 0x10, 0x01, "raw 32, fraction/argument context: class 30"),
    (0x3D, 0x10, 0x00, "raw 3D: special handoff, not a normalized class"),
]

FNINT_TOKEN_FLOW_ANCHORS = [
    (
        0x01,
        0x4921,
        "c806666e496e7428c7076e4465726976",
        "page-1 token-name strings: C8 len 06 'fnInt(', then C7 len 07 'nDeriv'",
    ),
    (
        0x07,
        0x42E8,
        "632f63306331bb20bb21bb22bb23bb24bb00bb01bb02bb03",
        "page-7 menu/token table contains BB24 after BB22/BB23 in the extended-command group",
    ),
    (
        0x02,
        0x68F3,
        "fe24200ddfcd381b3e7b327984ef834a",
        "page-2 evaluator branch recognises second byte 24 for tFnInt",
    ),
    (
        0x02,
        0x6904,
        "fe252007cd2d21cdf36ac9",
        "page-2 evaluator branch recognises second byte 25 for tNDeriv",
    ),
    (
        0x02,
        0x6AF6,
        "f5dfcd381b3e7d327984cd8316dfcd8d16cd",
        "shared numeric-calculus prologue: parse/default setup before argument handling",
    ),
    (
        0x39,
        0x6049,
        "00c8fbc8fbc700c9fe09fe1dfe1efe1ffe20fe34fe35fc32fc33fbcefbccfbcd",
        "page-39 class 30 row cells include fnInt display cell 00C8 and square markers",
    ),
    (
        0x39,
        0x60A4,
        "00c8fbc8fbc70054fe09fe1dfe1efe1ffe20fe34fe35fc32fc33fbcefbccfbcd",
        "page-39 class 08 row cells include fnInt display cell 00C8 and square markers",
    ),
    (
        0x39,
        0x6889,
        "fe09fbc800c700c8fbc7",
        "descriptor 6880 cells include nDeriv/fnInt display cells and square markers",
    ),
]

EXTENDED_TOKEN_TABLE_FLOW_ANCHORS = [
    (
        0x07,
        0x428A,
        "bb25bb26bb28bb08bb09bb0abb1fbb30bb2f",
        "page-7 extended-command/token run containing the only BB25 (tNDeriv) bytes",
    ),
    (
        0x07,
        0x42EE,
        "bb20bb21bb22bb23bb24bb00bb01bb02bb03bb04",
        "page-7 extended-command/token run containing the only BB24 (tFnInt) bytes",
    ),
    (
        0x07,
        0x50B5,
        "371802373fe53e00f5cd0f1acd4219cddc20",
        "page-7 carry-set scanner entry reached through fixed-bank service 3A53",
    ),
    (
        0x07,
        0x5104,
        "cd4219cd475247b713ed52da8e511922e384",
        "page-7 scanner loop: token helper 5247, expression pointer range checks, save 84E3",
    ),
    (
        0x07,
        0x5247,
        "fe0d20023e01fe0620013dfe0b20023e03cdc421d8afc9",
        "page-7 token-kind normalizer used by the scanner, not a display emitter",
    ),
]

EXTENDED_TOKEN_TABLE_XREF_TARGETS = [
    (0x07, 0x42EE),
    (0x07, 0x42F6),
    (0x07, 0x428A),
    (0x07, 0x50B5),
    (0x07, 0x50B8),
    (0x07, 0x5247),
    (0x07, 0x5199),
]

FNINT_TEMPLATE_FLOW_ANCHORS = [
    (
        0x01,
        0x7183,
        "5f160021a1711919cd3300c5fdcb354e28073e07cd1f3e2803cd735cc1c9",
        "page-1 indexed-string printer used by row-action/menu-title bytes",
    ),
    (
        0x02,
        0x68F3,
        "fe24200ddfcd381b3e7b327984ef834ac9",
        "tFnInt evaluator branch: second byte 24 pushes a seeded OP1 constant through _FPSPushReal",
    ),
    (
        0x02,
        0x6904,
        "fe252007cd2d21cdf36ac9",
        "tNDeriv evaluator branch: second byte 25 runs zero/domain guard, then shared constant push path",
    ),
    (
        0x02,
        0x6AF3,
        "f5180a",
        "shared numeric-calculus constant push shim: preserve A, then jump into the 6AF6 constant setup tail",
    ),
    (
        0x02,
        0x6AF6,
        "f5dfcd381b3e7d327984cd8316dfcd8d16cd061f",
        "nDeriv constant setup tail: push OP1, set OP1=1 with exponent 7D, copy through FPS slots, validate real",
    ),
]

FNINT_EVAL_FLOW_ANCHORS = [
    (
        0x02,
        0x68F3,
        "fe24200ddfcd381b3e7b327984ef834ac9",
        "page-2 tFnInt branch: recognise second byte 24, seed OP1, push real through _FPSPushReal",
    ),
    (
        0x02,
        0x6AF6,
        "f5dfcd381b3e7d327984cd8316dfcd8d16cd061f",
        "shared numeric-calculus default setup: set OP1=1e-3-ish exponent 7D and copy into FPS defaults",
    ),
    (
        0x33,
        0x4D00,
        "cd3f16cd9c16cd9722cd8223cdec19cd3f16cd8d16cd97222183843e60cd651bcd4125cdfe19",
        "fnInt body prologue: load parsed FPS3/FPS2 endpoint slots, subtract, halve, set scale 0x60, divide",
    ),
    (
        0x33,
        0x4DEA,
        "111b00cd2a15cde91d2813cfcd4e1acd4125cd0117cd",
        "fnInt loop frame update: dealloc 0x1B-byte FPS work frame, test OP1 zero, update accumulated estimate",
    ),
    (
        0x33,
        0x4E74,
        "3a7984fe74300ef1f1cd0f15112400cd2a15",
        "fnInt convergence/finalization: compare tolerance exponent 8479 against 0x74, pop result, dealloc 0x24-byte frame",
    ),
    (
        0x00,
        0x163F,
        "1183841806cd9716",
        "page-0 helper _CpyTo2FPS3: copy parsed FPS slot 3 into OP2",
    ),
    (
        0x00,
        0x169C,
        "1178842a24980e1b18",
        "page-0 helper _CpyTo1FPS2: copy parsed FPS slot 2 into OP1",
    ),
    (
        0x00,
        0x168D,
        "1178842a24980e1218",
        "page-0 helper _CpyTo1FPS1: copy parsed FPS slot 1 into OP1",
    ),
]

FNINT_ARGUMENT_ORDER_FLOW_ANCHORS = [
    (
        0x39,
        0x5167,
        "21e0853ae285b7caa2523dbe28543852cd4959f520",
        "multi-argument walker: compare current slot 85E0 against argument count 85E2",
    ),
    (
        0x39,
        0x51CB,
        "3c4e0dcd0a4e21e0854e214b84f120013434cd0a4ecd105b",
        "forward in-row path: emit previous slot index, bump row, emit current slot index, then 5B10",
    ),
    (
        0x39,
        0x5286,
        "21e0854e0ccd0a4e21e0854ecd4959214b8420013535cd0a4ecd1d5b",
        "reverse in-row path: emit next slot index, step row backward, then 5B1D",
    ),
    (
        0x39,
        0x5CF6,
        "9021e285bed2475432e085cd175a200921e085afbeca965b35af324b84cdd059",
        "saved-OP direct slot path: selected slot writes 85E0, then emits operands until 844B reaches that slot",
    ),
    (
        0x39,
        0x5B10,
        "fdcb116ec8cde15acde059180b",
        "saved-E7 normal operand wrapper: restore saved OP, then call the normal operand emitter",
    ),
    (
        0x39,
        0x5B1D,
        "fdcb116ec8cde15acdf959d818a7",
        "saved-E7 variable operand wrapper: restore saved OP, then call the variable operand emitter",
    ),
    (
        0x39,
        0x59E0,
        "cd175a28caafcd533ad8",
        "normal operand emitter: class-2 check, then page-7 parser scanner via fixed-bank service 3A53",
    ),
    (
        0x39,
        0x59F9,
        "cd175a28b8afcd6f30d8",
        "variable operand emitter: class-2 check, then page-7 parser scanner via fixed-bank service 306F",
    ),
    (
        0x07,
        0x50B5,
        "371802373fe53e00f5cd0f1acd4219cddc2020063a79843c2807",
        "page-7 parser scanner entry reached by page-39 normal operand service",
    ),
    (
        0x33,
        0x4D00,
        "cd3f16cd9c16cd9722cd8223cdec19cd3f16cd8d16cd97222183843e60cd651bcd4125cdfe19",
        "fnInt evaluator prologue: consume parsed FPS3/FPS2 endpoints, halve interval, then use FPS1",
    ),
]

FNINT_ARGUMENT_SLOTS = [
    (0, "integrand/expression", "ordinary operand slot displayed to the right of the integral"),
    (1, "differential variable", "variable operand slot displayed as d<var>"),
    (2, "lower bound", "numeric evaluator consumes FPS slot 2 as one interval endpoint"),
    (3, "upper bound", "numeric evaluator consumes FPS slot 3 as the other interval endpoint"),
    (4, "optional tolerance", "numeric evaluator has the shared default-tolerance path"),
]

FNINT_ROW_WINDOW_FLOW_ANCHORS = [
    (
        0x50CF,
        "cd274c3ae085f5cd0e4bf121e285be38057eb728013d32e085d6063001aff53a4484fe0420073ae285fe083803cde93df1c9",
        "argument-window clamp: preserve 85E0, refresh setup, clamp it below 85E2, compute 85E0-6 overflow window",
    ),
    (
        0x5101,
        "cd884c3ae0853cfe0838023e07324b84c9",
        "visible-row mapper: row 844B = min(85E0 + 1, 7)",
    ),
    (
        0x513E,
        "32e085cdcf503ae085cd01513a4a98324b84c34754",
        "layout requested arg: set 85E0, clamp/map row, restore 844B from baseline 984A, return",
    ),
    (
        0x4C5A,
        "214a983a4b8496473ae0859038154fc5cdca4d3a4a983d324b84c1fdcb116e2064",
        "subexpression helper: visible slot = 85E0 - (844B - 984A), then compute row-cell base",
    ),
    (
        0x4CA4,
        "fdcb116e203a3ae285b7281579cb275f160019cde64d3a4a9818023e01324b84c9",
        "subexpression emit tail: emit row cells at base + 2*slot, then restore 844B to baseline or row 1",
    ),
    (
        0x5949,
        "3ade85fe06c03e02bed897c9",
        "row-step classifier: only class 06 slots 0..2 are two-row slots; fnInt classes take one-row steps",
    ),
]

FNINT_CLASS_ROWS = (0x08, 0x30)

FNINT_SLOT_FLOW_ANCHORS = [
    (
        0x52DA,
        "fe05c2f8533ae085cd5559",
        "normal action-05 path: load selected argument/menu cell through 5955 before token/menu dispatch",
    ),
    (
        0x53F8,
        "068ffe8f3804fe9838160685fe8e28100690fe9a3813feb4380606a8fecc200990cd5559dae552",
        "normal action-byte slot mapper: 8F..97, 8E, 9A..B3, and CC subtract a base and call 5955",
    ),
    (
        0x5955,
        "21e285bed0f5cdca4dc17823b72804232310fc7ecdb648200c2a11935f160019e7",
        "slot loader/scanner: require slot < 85E2, compute current row cells through 4DCA, then skip 2*slot",
    ),
    (
        0x5C41,
        "068ffe8f3805fe98daf65c0685fe8ecaf65c0690fe9ada2154feb4380706a8feccc22154",
        "saved-OP action-byte classifier: 8F..97 and 8E enter slot-subtraction; 9A..B3/CC take the named/list path",
    ),
    (
        0x5CF6,
        "9021e285bed2475432e085cd175a200921e085afbeca965b35af324b84cdd059",
        "saved-OP slot-subtraction path: A-B must be below 85E2 before writing 85E0 and emitting operands",
    ),
]

FNINT_DIRECT_SLOT_ACTIONS = [
    (0x8F, 0x97, 0x8F, "normal direct row slots 0..8"),
    (0x8E, 0x8E, 0x85, "normal direct slot 9"),
    (0x9A, 0xB3, 0x90, "normal direct slots 10..35"),
    (0xCC, 0xCC, 0xA8, "normal direct slot 36"),
]

FNINT_SAVED_SLOT_ACTIONS = [
    (0x8F, 0x97, 0x8F, "saved-OP slot-subtraction slots 0..8"),
    (0x8E, 0x8E, 0x85, "saved-OP slot-subtraction slot 9"),
]
PAGE1_INDEXED_STRING_TABLE = 0x71A1
PAGE1_INDEXED_STRING_LABELS = {
    0x25: "CPX",
    0x35: "MATH",
    0x3B: "NUM",
    0x43: "PRB",
}

BJUMP_FLOW_ANCHORS = [
    (
        0x01,
        0x7183,
        "5f160021a1711919cd3300c5fdcb354e28073e07cd1f3e2803cd735c",
        "bjump 3B2B target: put indexed string from page-1 pointer table 71A1",
    ),
    (
        0x07,
        0x44DE,
        "fefe283cfefc2830fefb281efe0520051e3f1600c9d65a2100405f160019",
        "bjump 3B37 target: classify/map token display bytes before large-font output",
    ),
    (
        0x07,
        0x4588,
        "fdcb356e2808473e01cde73678c8fdcb354e2808473e76cd1f3e78c811ff45eb19cdeb45115a84cd941a215a84c9",
        "bjump 3B3D target: put_glyph_large, adjusts to 7-byte stride then copies an 8-byte render record into 845A",
    ),
    (
        0x01,
        0x6293,
        "fdcbff86c547ed57eaa062ed57f578f3e5cd6762e5dde1dd5e00160021456419",
        "bjump 3CDB target: _VPutMap graph/small-font pixel blitter",
    ),
]

BJUMP_FLOW_VECTORS = [0x3B2B, 0x3B37, 0x3B3D, 0x3CDB]

PAGE39_EXTERNAL_ENTRY_VECTORS = [
    (0x3B01, 0x48A6, "eqdisp_set_tok46 / structural predicate cluster"),
    (0x3B0D, 0x53AD, "eqdisp_menu_or_emit"),
    (0x3B13, 0x4F9A, "eqdisp_layout_main action dispatcher"),
    (0x3B19, 0x5421, "eqdisp_token_menu_emit"),
    (0x3B1F, 0x6B66, "eqdisp_load_glyph18b2 string/cell loader"),
    (0x3B67, 0x5DD8, "_SaveDisp LCD capture"),
]

PAGE39_EXTERNAL_ENTRY_ANCHORS = [
    (
        0x48A6,
        "3e4632de85c9",
        "bjump 3B01 target: set 85DE=46 and return",
    ),
    (
        0x48AC,
        "473ade85b72001af78c9",
        "entry-adjacent predicate: preserve A while setting flags from 85DE zero/nonzero",
    ),
    (
        0x48B6,
        "473ade85fe1478c9473ade85fe41283efe2a183a473ade85fe211832473ade85fe42282afe442826fe372822fe36281efe35281afe342816fe432812fe38280efe39280afe332806fe322802fe3178c9",
        "structural class predicate chain: tests 14/41/2A/21/42/44/37/36/35/34/43/38/39/33/32/31",
    ),
    (
        0x4F9A,
        "fdcb36664728233a9a85fe402006fdcb495e2016efca51300cc53ae085cd5559",
        "bjump 3B13 target: layout/action dispatcher, including class-48 geometry and class-49 menu state",
    ),
    (
        0x53AD,
        "fefb202b3a4684fec72810fec8201e3e07cd91387828163e08180a3e06cd913878280a3e07efff523e09c39a4f",
        "bjump 3B0D target: FB C7/C8 marker branch and action-09 redispatch",
    ),
    (
        0x5421,
        "fe5a280ffe40381e2809cd2d5d2817fe5a3013cddb6d280bcd966dcdd56dfe40cacc6cc3f95237f5cde94cf1c9",
        "bjump 3B19 target: token/menu emit wrapper before row placement or menu state",
    ),
    (
        0x6B66,
        "26017afefb202f7bcb442807fec821b26b2827feca21a96b2820fecb21ad6b2819fed621bf6b2812fed821cb6b280bfed721d76b2804efca45c911f297d5cd2b19e1c9",
        "bjump 3B1F target: FB string selector or _KeyToString fallback",
    ),
    (
        0x5DD8,
        "017f40f33e07cdc30cd31079c53c325184cdbf20cdc30cd3103e20cdc30cd310060ccdc30cdb11cb7c2005cd90181809cdc30cdb11772310f7c13a518410cd3e",
        "bjump 3B67 / bcall _SaveDisp target: LCD byte capture plumbing",
    ),
]

STRUCTURAL_PREDICATE_FLOW_ANCHORS = [
    (
        0x48B6,
        "473ADE85FE1478C9",
        "predicate A: preserve A and compare 85DE with class 14",
    ),
    (
        0x48BE,
        "473ADE85FE41283EFE2A183A",
        "predicate B: class 41 or 2A, otherwise continue into the structural chain",
    ),
    (
        0x48CE,
        "FE211832473ADE85FE42282AFE442826FE372822FE36281EFE35281AFE342816FE432812FE38280EFE39280AFE332806FE322802FE3178C9",
        "predicate C: classes 42/44/37/36/35/34/43/38/39/33/32/31",
    ),
    (
        0x4990,
        "CDB6482803CDD248CA114A",
        "recursive entry context: class-14 predicate, then sibling predicate, before render-loop continuation",
    ),
    (
        0x4A02,
        "CD404CFDCB0CE6CDE94CCDB648280237C9",
        "render wrapper context: setup, raised-row helper, then class-14 predicate before returning",
    ),
    (
        0x52C1,
        "FE5A200ECD2D5DCA114ACDB648CA114A",
        "layout action-5A/close guard context before the active-cell path",
    ),
    (
        0x52E5,
        "CDB648CA6654F579FE822007F1322C9DC3A849F1",
        "active-cell prefix gate uses the class-14 predicate before checking C=82 recursion",
    ),
    (
        0x5961,
        "B72804232310FC7ECDB648200C2A11935F160019E7",
        "selected-cell scanner uses the predicate before chasing C=82 indirection",
    ),
    (
        0x4FFA,
        "3A4B9847CDC2482805CDCE4820052E00C3564A",
        "action-1 row navigation context: mid-chain predicates only select a row reset path",
    ),
]

STRUCTURAL_PREDICATE_TARGETS = [0x48B6, 0x48C2, 0x48CE]

STRUCTURAL_PREDICATE_EXPECTED_CALLERS = {
    0x48B6: {0x4990, 0x4A0C, 0x52CB, 0x52E5, 0x5969},
    0x48C2: {0x4FFE},
    0x48CE: {0x5003},
}

STRUCTURAL_PREDICATE_WINDOWS = [
    (0x4980, 0x49B8, "recursive entry/context gate"),
    (0x49F0, 0x4A20, "render wrapper / action-1 row gate"),
    (0x52B8, 0x530A, "layout close/action-5 active-cell gate"),
    (0x5955, 0x5988, "selected-cell scanner / 82 indirection gate"),
]

STRUCTURAL_PREDICATE_STATE_WORDS = [
    (0x85DE, "layout class/mode"),
    (0x85DF, "layout row/subrow"),
    (0x85E0, "argument/column index"),
    (0x85E1, "row/dimension count"),
    (0x85E2, "argument/cell count"),
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor base/dims"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x9D27, "saved measured fraction pair"),
    (0x844B, "display row"),
    (0x844C, "display column"),
]

STRUCTURAL_PREDICATE_DRAW_PATTERNS = [
    ("CALL 3555 _DarkLine", "cd5535"),
    ("CALL 3B37 display-byte mapper", "cd373b"),
    ("CALL 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL 3CDB VPutMap", "cddb3c"),
    ("CALL 4833 graph-window setup", "cd3348"),
    ("CALL 6AF5 descriptor/fraction box", "cdf56a"),
    ("CALL 6ABF fraction row/rule", "cdbf6a"),
    ("RST28 _ClearRect", "ef5c4d"),
    ("RST28 _InvertRect", "ef5f4d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
]

PAGE39_BJUMP_CALLER_PATTERNS = [
    (0x3B01, "CD013B", "page-39 structural predicate entry"),
    (0x3B0D, "CD0D3B", "page-39 menu/marker emit entry"),
    (0x3B13, "CD133B", "page-39 layout/action dispatcher entry"),
    (0x3B19, "CD193B", "page-39 token/menu emit entry"),
    (0x3B1F, "CD1F3B", "page-39 string/cell loader entry"),
    (0x3B67, "CD673B", "page-39 SaveDisp entry"),
]

PAGE39_BJUMP_CALLER_ANCHORS = [
    (
        0x01,
        0x780D,
        "fdcb1df6fdcb1dfecd013b9732a597",
        "page-1 setup bridge: set template box flags, call 3B01 state helper, then clear 97A5",
    ),
    (
        0x01,
        0x5EDA,
        "cd6765cd77202821217e5afdcb4976fdcb49f62805fdcb2866c8cd673b",
        "page-1 LCD-save guard: display/mode checks before calling 3B67 _SaveDisp",
    ),
    (
        0x01,
        0x7918,
        "32468478b7cd0d3bc9",
        "page-1 bridge: save normalized prefix byte in 8446, then call 3B0D",
    ),
    (
        0x01,
        0x79B1,
        "fe092004cd133bc9",
        "page-1 bridge: action 09 calls 3B13, the page-39 layout/action dispatcher",
    ),
    (
        0x01,
        0x79B9,
        "fecc20043eb41808fe9a3834feb43030d69a8721eb7b5f160019",
        "page-1 bridge: token range 9A..B3 / CC selects table 7BEB before local display setup",
    ),
    (
        0x01,
        0x79F9,
        "cd193bc9",
        "page-1 bridge: unmatched token/menu case calls 3B19 and returns",
    ),
    (
        0x01,
        0x7A31,
        "56235ed5cd1f3bcd525ccdc561d1ef7054c9",
        "page-1 bridge: load a two-byte cell, call 3B1F string loader, then run page-1 string measurement/output",
    ),
    (
        0x36,
        0x5050,
        "fe22200f21ec86cd673b21ec86010003c31f52",
        "page-36 LCD capture command: action 22 calls 3B67 _SaveDisp into 86EC, then copies 0x300 bytes",
    ),
]

PAGE39_BJUMP_CALLER_WINDOWS = [
    (0x01, 0x775C, 0x7C9A, "page-1 display bridge for 3B01/3B0D/3B13/3B19/3B1F"),
    (0x01, 0x5EDA, 0x5F3C, "page-1 LCD-save guard around 3B67"),
    (0x36, 0x5050, 0x5068, "page-36 LCD capture command around 3B67"),
]

PAGE39_BJUMP_CALLER_STATE_WORDS = [
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor pixel base"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x9D27, "saved measured fraction pair"),
    (0x86D7, "graph pen coordinate pair"),
    (0x86D8, "graph pen y"),
]

PAGE39_BJUMP_CALLER_PATTERNS_LOCAL = [
    ("CALL 3B01 page-39 state helper", "cd013b"),
    ("CALL 3B0D page-39 marker/menu emit", "cd0d3b"),
    ("CALL 3B13 page-39 layout dispatcher", "cd133b"),
    ("CALL 3B19 page-39 token/menu emit", "cd193b"),
    ("CALL 3B1F page-39 string/cell loader", "cd1f3b"),
    ("CALL 3B67 page-39 SaveDisp", "cd673b"),
    ("CALL 3CDB page-1 _VPutMap graph/small-font output", "cddb3c"),
    ("CALL 3B37 page-7 display-byte mapper", "cd373b"),
    ("CALL 3B3D page-7 large-font blitter", "cd3d3b"),
    ("CALL RAM 3555 _DarkLine", "cd5535"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _InvertRect", "ef5f4d"),
    ("RST28 _FillRect", "ef624d"),
    ("RST28 _FillRectPattern", "ef894d"),
    ("RST28 _DisplayImage", "ef9b4d"),
]

PAGE1_DISPLAY_BRIDGE_RANGE = (0x775C, 0x7C9A)

PAGE1_DISPLAY_BRIDGE_ANCHORS = [
    (
        0x7764,
        "fe3e280acdbf3acaa978cdc53ac9",
        "page-1 bridge entry gate: byte 3E takes setup, otherwise predicate/call helper path returns or enters 78A9",
    ),
    (
        0x7780,
        "3a9a85fe4c2808fe4d2804fe41200478c32a78",
        "context gate: 859A values 4C/4D/41 route directly to 782A, otherwise continue",
    ),
    (
        0x782C,
        "210000fdcb16ae22df85cd52783e0111000032a597ed534b84",
        "bridge setup: clear 85DF, initialize display row/column state, set 97A5 and 844B",
    ),
    (
        0x7873,
        "2ada853e01fdcb365ec4f53a2020fdcb3476281afdcb3e5e2805cd3300180f",
        "saved-cell fetch helper: read pointer 85DA, optionally route through page-39 cell service, return current D/E cell",
    ),
    (
        0x78A9,
        "47fdcb366628213a9a85fe402006fdcb495e2014cd4d7c3009",
        "bridge dispatch head: gate draw-mode/context, then normalize action-specific cases",
    ),
    (
        0x7A4A,
        "210100224b842ada85e53a198af5cdfd793a4b84fe07280bcd4a5fcdd77a38ee",
        "row loop: set 844B=1, emit current saved-cell pointer, advance rows until row 7 or end",
    ),
    (
        0x7AD7,
        "cd067bd0fdcb365e281efdcb296628183e0ccdf53a2011fdcb369ecda87afdcb36de",
        "forward saved-pointer step: walk 85DA by two-byte cells with draw-mode guard",
    ),
    (
        0x7B06,
        "2ada8511837f3e06fdcb365ec4f53a2026fdcb34762820fdcb3e5e2817",
        "reverse saved-pointer step: compare 85DA against table end before stepping backward",
    ),
    (
        0x7BAE,
        "e52aa6972d2600224b84e11803cd166297324c843e051806",
        "cursor-row setup: derive 844B from 97A6, then clear 844C before display cleanup",
    ),
    (
        0x7BC6,
        "97324c843e20cd985a37c9",
        "blank output path: clear 844C, emit space through page-1 _PutMap, return carry set",
    ),
    (
        0x7BEB,
        "a57cc17cc97cfb7c237d3d7d5f7d837d897da97da97da97dcd7de17dfb7d",
        "token-range table used by the 79C9 index path for 9A..B3 / CC cases",
    ),
]

PAGE1_DISPLAY_BRIDGE_STATE_WORDS = [
    (0x844B, "text row/column pair used as bridge row cursor"),
    (0x844C, "text column used by bridge output/erase helpers"),
    (0x8446, "prefix low byte saved before calling page-39 3B0D"),
    (0x85DA, "saved pointer into bridge/table cell stream"),
    (0x85DE, "page-39 class/state byte only tested at entry"),
    (0x85DF, "class row/subrow pair cleared during bridge setup"),
    (0x85E8, "template kind/state byte"),
    (0x85E9, "descriptor pixel base"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction/template columns"),
    (0x85EF, "measured fraction/template rows"),
    (0x86D7, "graph pen coordinate pair"),
    (0x86D8, "graph pen coordinate high byte"),
    (0x97A5, "display/context scratch row state"),
    (0x9D27, "saved measured fraction pair"),
]

PAGE1_DISPLAY_BRIDGE_SERVICE_PATTERNS = [
    ("CALL 3B01", "cd013b", "page-39 state helper"),
    ("CALL 3B0D", "cd0d3b", "page-39 marker/menu emit"),
    ("CALL 3B13", "cd133b", "page-39 layout/action dispatcher"),
    ("CALL 3B19", "cd193b", "page-39 token/menu emit"),
    ("CALL 3B1F", "cd1f3b", "page-39 string/cell loader"),
    ("CALL 5B4C", "cd4c5b", "page-1 _PutC text output"),
    ("CALL 5A98", "cd985a", "page-1 _PutMap text glyph output"),
    ("CALL 5C39", "cd395c", "page-1 _PutS string output"),
    ("CALL 5C52", "cd525c", "page-1 _PutPSB proportional string output"),
    ("CALL 61C5", "cdc561", "page-1 _EraseEOL"),
    ("CALL 61F4", "cdf461", "page-1 erase-to-end-of-screen"),
    ("CALL 6216", "cd1662", "page-1 _homeup"),
    ("CALL 3CDB", "cddb3c", "page-1 _VPutMap graph/small-font output"),
    ("CALL 3B37", "cd373b", "page-7 display-byte mapper"),
    ("CALL 3B3D", "cd3d3b", "page-7 large-font blitter"),
    ("RST28 _DrawRectBorder", "ef7d4d", "rectangle draw primitive"),
    ("RST28 _DrawRectBorderClear", "ef8c4d", "rectangle clear primitive"),
    ("RST28 _EraseRectBorder", "ef864d", "rectangle erase primitive"),
    ("RST28 _InvertRect", "ef5f4d", "rectangle invert primitive"),
    ("CALL RAM 3555 _DarkLine", "cd5535", "line primitive"),
]

PAGE1_ACTION_TABLE_ANCHORS = [
    (
        0x79B9,
        "fecc20043eb41808fe9a3834feb43030d69a8721eb7b5f160019",
        "page-1 bridge action range: CC is normalized to B4; 9A..B3/B4 index pointer table 7BEB",
    ),
    (
        0x7BEB,
        "a57cc17cc97cfb7c237d3d7d5f7d837d897da97da97da97dcd7de17dfb7d",
        "page-1 action pointer table for 9A..B3 plus CC-as-B4",
    ),
    (
        0x7CA5,
        "fe09fe10fc31ffed00c5fc9afc9cfc9efc9dfe40fbd6ff72ff71ffae",
        "first packed display-cell list referenced by the action table",
    ),
    (
        0x7D3D,
        "fee0fbcdff3dff53ff5200f200f100c8ff5fff5efdd0fe1ffc8f",
        "action 9F packed list includes display-name cell 00C8, not parser token BB24",
    ),
    (
        0x7DE1,
        "fee8fe23fbca00c7fbccfc6dff4ffedcfc8cfc8bfe13fe22fc66",
        "action A7 packed list includes display-name cell 00C7",
    ),
]

PAGE1_ACTION_TABLE_BASE = 0x7BEB
PAGE1_ACTION_TABLE_COUNT = 27
PAGE1_ACTION_TABLE_LAST_END = 0x7F39
PAGE1_ACTION_TABLE_INTERESTING_CELLS = [
    ((0xBB, 0x24), "BB24 parser token"),
    ((0xBB, 0x25), "BB25 parser token"),
    ((0x00, 0xC8), "00C8 fnInt display-name cell"),
    ((0x00, 0xC7), "00C7 nDeriv display-name cell"),
    ((0xFC, 0x3F), "FC3F Lintegral direct cell"),
    ((0x08, 0x42), "0842 Lintegral direct cell"),
    ((0x00, 0x10), "0010 Lroot literal cell"),
    ((0xFB, 0xC8), "FB C8 square-up marker"),
    ((0xFB, 0xC7), "FB C7 square-down marker"),
]

OVERFLOW_FLOW_ANCHORS = [
    (
        0x39,
        0x4F08,
        "3a4c84fe0fd5dcb73cd1cd444fc8cd624fc9",
        "emit-glyph overflow check: if 844C >= 0F, call bjump 3CB7 before marker handling",
    ),
    (
        0x39,
        0x6712,
        "3e01324c843e3acddb3fc93ae585fe2fc8fe1ec8fe1cc9",
        "overflow marker: set 844C=1, emit ':' through 3FDB, then gate display modes via 85E5",
    ),
    (
        0x01,
        0x61C5,
        "f5fdcb2a4e2805f1cd853bc9c5d5e53a4c84f5d6103011ed44473e20052805cd4c5b10fbcd985afbf1324c84c3475b",
        "bjump 3CB7 target: _EraseEOL fills remaining columns with spaces and restores 844C",
    ),
    (
        0x01,
        0x61F4,
        "f5e52a4b84e57d21a69796280bcdc5613c2805cd4a5f18f5e1224b84cdba5ee1",
        "bjump 3CBD target: erase-to-end-of-screen loops through _EraseEOL and _NewLine",
    ),
]

OVERFLOW_FLOW_XREF_TARGETS = [0x3CB7, 0x3CBD, 0x4F44, 0x4F62, 0x6712]

MATHPRINT_MODE_FLOW_ANCHORS = [
    (
        0x01,
        0x5A07,
        "d2094d4154485052494e54d307434c4153534943",
        "mode strings: D2/09 'MATHPRINT', then D3/07 'CLASSIC' (data, not code)",
    ),
    (
        0x02,
        0x7A90,
        "a27ab97ac47ac97ace7add7ae17ae57aea7a",
        "mode-option handler table: entries include 7AA2, 7AB9, 7AC4, 7AC9",
    ),
    (
        0x02,
        0x7AA2,
        "fdcb446ec0fd7e44ee20fd7744cdd93eef7f51cd0d38c9",
        "MATHPRINT option: if bit 5 is already set return, else toggle IY+44 bit 5 and refresh mode UI",
    ),
    (
        0x02,
        0x7AB9,
        "fdcb0dcefdcb446ec818e3",
        "CLASSIC option: set a display/edit flag, if bit 5 is set jump back to the same toggle path",
    ),
    (
        0x02,
        0x7AC4,
        "fdcb4886c9fdcb48c6c9",
        "fraction display options: RES/SET bit 0 of IY+48",
    ),
    (
        0x35,
        0x7337,
        "fdcb44fefdcb44eefdcb4886fdcb488efdcb4896",
        "reset/default path: set IY+44 bits 7 and 5, clear IY+48 bits 0/1/2",
    ),
    (
        0x37,
        0x6E1C,
        "fdcb44eeef3148ef2551ef2b51cd2d2defcc52",
        "startup/app init path: set IY+44 bit 5 before display/menu initialization",
    ),
]

MATHPRINT_MODE_PATTERNS = [
    ("BIT 5,(IY+44)", "fdcb446e"),
    ("SET 5,(IY+44)", "fdcb44ee"),
    ("RES 5,(IY+44)", "fdcb44ae"),
    ("LD/XOR/LD IY+44 bit 5 toggle", "fd7e44ee20fd7744"),
    ("RES 0,(IY+48)", "fdcb4886"),
    ("SET 0,(IY+48)", "fdcb48c6"),
]

DRAW_PRIMITIVE_BCALLS = [
    (0x4EE6, 0x450D, "_PutPSB", "generic cell/string display after 6B66 buffer selection"),
    (0x67B6, 0x4D5C, "_ClearRect", "template chrome clears the full template/menu rectangle"),
    (0x6826, 0x4D5F, "_InvertRect", "template chrome inverts the active tab rectangle"),
    (0x6AE9, 0x4D7D, "_DrawRectBorder", "fraction-bar/focused rectangle draw in set mode"),
    (0x6AEE, 0x4D86, "_EraseRectBorder", "fraction-bar/focused rectangle draw in erase mode"),
    (0x6AF8, 0x4D8C, "_DrawRectBorderClear", "descriptor/fraction box border draw"),
    (0x6B17, 0x4D5F, "_InvertRect", "focused fraction endpoint/cell rectangle"),
    (0x6B9C, 0x45CA, "_KeyToString", "menu/key string conversion helper, not a glyph stretcher"),
]

DRAW_PRIMITIVE_GHIDRA_RST28_SITES = [
    (0x4AC9, 0x52FF, "_grc_4611", "eqdisp_dispatch_token", "disabled-feature/message helper"),
    (0x4D61, 0x48D9, "_unknown_48D9", "_DispMenuTitle", "menu-title display helper"),
    (0x4EE6, 0x450D, "_PutPSB", "eqdisp_emit_glyph", "generic string/cell display"),
    (0x4EEF, 0x51E5, "_scr_4619", "eqdisp_emit_glyph", "display/screen helper after cell fallback"),
    (0x4FAE, 0x51CA, "_DispPagedStr", "eqdisp_layout_main", "paged-string display"),
    (0x53A7, 0x4A68, "_arc_59f1", "eqdisp_layout_multiarg", "archive/app state helper"),
    (0x554F, 0x51FA, "_grc_60cb", "mnu_show_and_getkey", "menu helper"),
    (0x556C, 0x5203, "_sta_5d3c", "mnu_show_and_getkey", "state/menu helper"),
    (0x5580, 0x5200, "_grc_5f42", "mnu_show_and_getkey", "menu helper"),
    (0x55BC, 0x5200, "_grc_5f42", "mnu_show_and_getkey", "menu helper"),
    (0x56D0, 0x4D6B, "_dsp_65ea", "mnu_show_and_getkey", "display/menu helper"),
    (0x5860, 0x51D6, "_grc_5d44", "eqdisp_restore_disp_state", "graph/display state helper"),
    (0x59B1, 0x5326, "_app_5de7", "eqdisp_emit_jp_d", "app helper"),
    (0x59BE, 0x5326, "_app_5de7", "eqdisp_emit_var_jp_c", "app helper"),
    (0x66A4, 0x51F1, "_scr_4056", "eqdisp_classify_paren", "screen/state helper"),
    (0x66DB, 0x49FC, "_SetNorm_Vals", "_ForceFullScreen", "display/window reset"),
    (0x67B6, 0x4D5C, "_ClearRect", "eqdisp_set_flag2_jp", "template chrome clear"),
    (0x6826, 0x4D5F, "_InvertRect", "gr_draw_at_row6", "template chrome invert"),
    (0x6AE9, 0x4D7D, "_DrawRectBorder", "eqdisp_draw_fraction_bar", "fraction/descriptor rectangle"),
    (0x6AEE, 0x4D86, "_EraseRectBorder", "eqdisp_draw_fraction_bar", "fraction/descriptor rectangle"),
    (0x6AF8, 0x4D8C, "_DrawRectBorderClear", "eqdisp_draw_box_jp", "fraction/descriptor rectangle"),
    (0x6B17, 0x4D5F, "_InvertRect", "eqdisp_draw_indent_jp", "focused fraction cell"),
    (0x6B9C, 0x45CA, "_KeyToString", "eqdisp_load_glyph18b2", "key string conversion"),
    (0x6D2E, 0x5458, "_edt_6bd1", "eqdisp_get_ctx_kind", "editor/context helper"),
    (0x6D5E, 0x5461, "_edt_69f8", "eqdisp_set_tok49_jp", "editor/token helper"),
]

DRAW_PRIMITIVE_RAW_RST28_CANDIDATES = [
    (
        0x4F04,
        0x51F4,
        "_dsp_60d1",
        "post-overflow display helper: bcall table resolves 51F4 to page 35:60D1",
    ),
    (
        0x5D90,
        0x4870,
        "_RestoreDisp",
        "display-buffer restore wrapper at 5D86; see --restore-display-flow",
    ),
]

DRAW_PRIMITIVE_51F4_ANCHORS = [
    (
        0x39,
        0x4EFC,
        "7bfe552007cdb73ceff451c9",
        "eqdisp_emit_glyph tail: if E=55, call 3CB7 overflow cleanup, then bcall 51F4, then return",
    ),
    (
        0x3B,
        0x51F4,
        "d16075",
        "bcall table entry 51F4 -> addr 60D1, page byte 75 masked to page 35",
    ),
    (
        0x35,
        0x60D1,
        "3afc92f57a32fc92cd075de5dde1215a643e1dcde921dd7e10e60ffe0128082156643e1ecde9213aa697f53e0732a697cd8864f132a697",
        "target prologue: save 92FC/97A6, load IX-backed record, emit fixed indexed strings through j_cross_if_nc",
    ),
    (
        0x35,
        0x6108,
        "cd693ccdb73c3a4b8487878732d8863e0c32d786dd7e00e60f21ea63cdb461cd",
        "target display setup: page-1 display helper, erase-EOL, derive graph pen y from 844B, set fixed x=0C",
    ),
    (
        0x35,
        0x611C,
        "dd7e00e60f21ea63cdb461cda5613e1a32d7863e00cdca603e3132d786cd075d381afe0520",
        "target body: choose fixed string pointers and fixed pen x positions 1A/31/48 around IX record state",
    ),
    (
        0x35,
        0x6189,
        "f132fc92c9",
        "target tail: restore saved 92FC and return",
    ),
]

DRAW_PRIMITIVE_51F4_STATE_WORDS = [
    (0x85EE, "85EE measured fraction columns"),
    (0x85EF, "85EF measured fraction rows"),
    (0x9D27, "9D27 saved measured fraction pair"),
    (0x86D7, "86D7 graph pen x"),
    (0x86D8, "86D8 graph pen y"),
    (0x844B, "844B text row"),
    (0x844C, "844C text column"),
    (0x92FC, "92FC page-35 display/menu scratch"),
    (0x97A6, "97A6 string/output limit"),
]

DRAW_PRIMITIVE_51F4_DISPLAY_PATTERNS = [
    ("CALL bjump 3C69 page-1 display helper", "cd693c"),
    ("CALL bjump 3CB7 _EraseEOL", "cdb73c"),
    ("CALL j_cross_if_nc", "cde921"),
]

DRAW_PRIMITIVE_DARKLINE_ANCHORS = [
    (
        0x00,
        0x3555,
        "cd092b254004",
        "RAM trampoline 3555: cross_page_jump inline target 04:4025 (_DarkLine)",
    ),
    (
        0x04,
        0x4025,
        "26011800",
        "_DarkLine entry: set H=1, then tail-jump into _ILine",
    ),
    (
        0x39,
        0x4F62,
        "3a4b84878787060b165eed44c63bc5d5cd0f22d1c14f5fcd60203af289f5fdcb02cecd5535f132f2892007cd5d21c8c31422210a22c31722",
        "post-marker row retouch: derive y from 844B, normalize split/window state, call _DarkLine, then restore graph window bytes",
    ),
    (
        0x39,
        0x67CE,
        "11fe85d5cd9c1aaf12e3cdf93ce1c1e5501e02cd55350c04593e108057cd553514420d1e02cd553504",
        "template tab loop: draw label text, then draw tab separator lines through _DarkLine",
    ),
    (
        0x39,
        0x6802,
        "3aee85b7010529110537cc5535",
        "empty-template cue: if 85EE is zero, conditionally draw a fixed line through _DarkLine",
    ),
]

DRAW_PRIMITIVE_DARKLINE_EXPECTED_CALLERS = {
    0x4F84: "post-marker split/window retouch after 4F44 accepts a marker",
    0x67E1: "template chrome tab separator line A",
    0x67EB: "template chrome tab separator line B",
    0x67F3: "template chrome tab separator line C",
    0x680C: "empty-template cue / saved-geometry fallback line",
}

MARKER_RETOUCH_FLOW_ANCHORS = [
    (
        0x4F08,
        "3a4c84fe0fd5dcb73cd1cd444fc8cd624fc9",
        "decoded-cell tail: overflow cleanup, FB C8/C7 marker gate, then optional row retouch",
    ),
    (
        0x4F62,
        "3a4b84878787060b165e",
        "record-cell retouch setup: y = 8 * 844B, B=0B, D=5E before shared 4F6C line helper",
    ),
    (
        0x6A5E,
        "3ad8863d061d1646cd6c4f",
        "descriptor-cell retouch setup: y = 86D8 - 1, B=1D, D=46 before shared 4F6C line helper",
    ),
    (
        0x4F6C,
        "ed44c63bc5d5cd0f22d1c14f5fcd60203af289f5fdcb02cecd5535",
        "shared retouch helper: transform y, normalize split/window flags, call _DarkLine",
    ),
    (
        0x00,
        0x3555,
        "cd092b254004",
        "RAM trampoline 3555: cross_page_jump inline target 04:4025 (_DarkLine)",
    ),
    (
        0x04,
        0x4025,
        "26011800",
        "_DarkLine entry: fixed-line primitive, not a bitmap blitter",
    ),
]

MARKER_RETOUCH_XREF_TARGETS = [0x4F44, 0x4F62, 0x4F6C, 0x3555]

MARKER_RETOUCH_STATE_WORDS = [
    (0x844B, "display row"),
    (0x844C, "display column/overflow"),
    (0x85DE, "layout class/mode"),
    (0x85DF, "layout row/subrow"),
    (0x85E8, "template kind/state"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph text coordinate pair"),
    (0x9D27, "saved measured fraction pair"),
]

DRAW_PRIMITIVE_DARKLINE_STATE_WORDS = [
    (0x85EE, "85EE measured fraction columns"),
    (0x85EF, "85EF measured fraction rows"),
    (0x9D27, "9D27 saved measured fraction pair"),
    (0x844B, "844B display row"),
    (0x89F2, "89F2 graph/display state byte"),
    (0x8DA2, "8DA2 graph window struct"),
]

DRAW_PRIMITIVE_ABSENT_BCALLS = [
    (0x4D62, "_FillRect"),
    (0x4D89, "_FillRectPattern"),
    (0x4D9B, "_DisplayImage"),
]

DRAW_PRIMITIVE_CALL_TARGETS = [0x3555, 0x3B2B, 0x3B37, 0x3B3D, 0x3CDB, 0x4833, 0x4822, 0x6AF5, 0x6ABF, 0x6B1C]

GRAPH_TABLE_HELPER_ANCHORS = [
    (
        0x66DC,
        "FC49FDCB1486FDCB148EC3F500",
        "gr_draw_tbl_glyph: short helper around _SetTblGraphDraw; no page-39 callers",
    ),
    (
        0x4833,
        "F5E5C5D521A28D11219D3A048A1213FDCB148ECD9A1ACD0F22D1C1E1F1C9",
        "gr_set_window_draw: save graph-window state into 9D21/9D22 and normalize flags",
    ),
    (
        0x4822,
        "F5E5C5D521219D7E32048A23CD17221819",
        "gr_save_window_flags: restore saved graph-window state from 9D21/9D22",
    ),
    (
        0x6AE4,
        "CD33483805EF7D4D1803EF864DCD2248C9",
        "fraction rectangle wrapper: calls 4833, draws/erases border, then restores through 4822",
    ),
    (
        0x6AF5,
        "CD3348EF8C4D18F4",
        "descriptor/fraction box wrapper: calls 4833, DrawRectBorderClear, then jumps to the 6AF1 restore tail",
    ),
]

GRAPH_TABLE_HELPER_XREF_TARGETS = [0x66DC, 0x4833, 0x4822, 0x6AE4, 0x6AF5]

LCD_CAPTURE_FLOW_ANCHORS = [
    (
        0x5DD1,
        "cd436cc0217298",
        "context gate: call 6C43, return unless carry/zero state allows falling into SaveDisp with HL=9872",
    ),
    (
        0x5DD8,
        "017f40f33e07cdc30cd310",
        "_SaveDisp body: BC=407F, DI, select LCD command 7 through port 10",
    ),
    (
        0x5DE3,
        "79c53c325184cdbf20cdc30cd310",
        "_SaveDisp column loop: advance LCD row state 8451, issue command through port 10",
    ),
    (
        0x5DF1,
        "3e20cdc30cd310060ccdc30cdb11cb7c2005cd90181809",
        "_SaveDisp read setup: select LCD command 20, read 12 bytes/column from port 11 or copy through 1890",
    ),
    (
        0x5E08,
        "cdc30cdb11772310f7c13a518410cd3e05cdc30cd310c9",
        "_SaveDisp RAM-buffer loop: store port-11 bytes at HL, finish with LCD command 5 and return",
    ),
]

LCD_CAPTURE_FLOW_XREF_TARGETS = [0x5DD1, 0x5DD8, 0x6C43]

RESTORE_DISPLAY_FLOW_ANCHORS = [
    (
        0x5D86,
        "0640fd7e14f5fdcb148eef7048f1fd7714c9",
        "RestoreDisp wrapper: save (IY+14), clear bit 1, bcall _RestoreDisp, restore (IY+14), return",
    ),
    (
        0x4AC0,
        "06f5cd355dcdd15df1efff52cdfd6bc0217298c3865d",
        "dispatch/context path: after LCD capture and disabled-feature check, jump to the restore wrapper",
    ),
    (
        0x5798,
        "cd293d217298cd865d1803cd233d",
        "menu/context path: call page-3D helper, load appBackUpScreen, call restore wrapper, otherwise call sibling helper",
    ),
    (
        0x586D,
        "cd436c217298cc865d210000224b84efd951",
        "display-state path: context helper 6C43, conditional restore from appBackUpScreen, then reset text row",
    ),
    (
        0x5D98,
        "f5c5d5e5dde521ec86cd865ddde1e1d1c1f1c9",
        "save-register wrapper: load 86EC backup buffer, call restore wrapper, restore registers",
    ),
    (
        0x6C19,
        "3a9a85fe492009cd293d217298c3865dcd973bc9",
        "context kind helper: for state 49, call page-3D helper, load appBackUpScreen, then jump restore wrapper",
    ),
]

RESTORE_DISPLAY_FLOW_XREF_TARGETS = [0x5D86]

RESTORE_DISPLAY_STATE_WORDS = [
    (0x85EE, "85EE measured fraction columns"),
    (0x85EF, "85EF measured fraction rows"),
    (0x9D27, "9D27 saved measured fraction pair"),
    (0x9872, "9872 appBackUpScreen"),
    (0x86EC, "86EC display backup buffer"),
    (0x844B, "844B text row"),
    (0x859A, "859A context kind/state"),
]

RESTORE_DISPLAY_WINDOWS = [
    (0x4AC0, 0x4AE0, "dispatch/context restore tail"),
    (0x5798, 0x57B0, "menu/context restore path"),
    (0x586D, 0x5888, "display-state restore path"),
    (0x5D86, 0x5DB5, "RestoreDisp wrapper cluster"),
    (0x6C18, 0x6C31, "context-kind helper"),
]

DRAW_MODE_CALLBACK_FLOW_ANCHORS = [
    (
        0x00,
        0x2CBB,
        "cd092ba87c7b",
        "fixed-bank draw-mode callback stub: cross_page_jump to page 3B:7CA8",
    ),
    (
        0x39,
        0x4AF3,
        "2808473e04cdbb2cc078fdcb16ae22df85",
        "classify/setup draw-pass hook: call 2CBB when (IY+36) bit 6 is set",
    ),
    (
        0x39,
        0x4DA7,
        "3e02fdcb3676c4bb2c20047ecd2b3b",
        "row-title draw-pass hook: call 2CBB instead of indexed-string output when draw-pass bit is set",
    ),
    (
        0x39,
        0x4ED1,
        "3e01fdcb3676c4bb2c200d7afefd20021600cd666bef0d45",
        "cell-emitter draw-pass hook: call 2CBB before generic string/glyph output",
    ),
    (
        0x39,
        0x5466,
        "fdcb36762808473e03cdbb2cc078cddb6d21de8528033649c93600",
        "menu/getkey draw-pass hook: call 2CBB with A=03 before menu state handling",
    ),
    (
        0x3B,
        0x7ABF,
        "c5d55e2356237efeff280e32779beb0600cd69212322759b78d1c1fe83c9",
        "page-3B shared checker: read saved triple, call pointer/symbol helper 2169, compare A with 83",
    ),
    (
        0x3B,
        0x7CA8,
        "f5e521c09bcdbf7ae128a8f1bffdcb36b6c9",
        "page-3B draw-pass bit-6 checker for slot 9BC0; clears (IY+36) bit 6 after check",
    ),
    (
        0x3B,
        0x7DB0,
        "22c09b32c29bfdcb36f6c9",
        "page-3B draw-pass bit-6 setter: store HL/A in 9BC0/9BC2 and set (IY+36) bit 6",
    ),
]

DRAW_MODE_CALLBACK_XREF_TARGETS = [
    (0x39, 0x2CBB),
    (0x3B, 0x7ABF),
    (0x3B, 0x7CA8),
    (0x3B, 0x7DB0),
]

DRAW_MODE_CALLBACK_WINDOWS = [
    (0x39, 0x4AE8, 0x4B10, "page-39 classify/setup draw-pass hook"),
    (0x39, 0x4D98, 0x4DC0, "page-39 row-title draw-pass hook"),
    (0x39, 0x4EC8, 0x4EEC, "page-39 cell-emitter draw-pass hook"),
    (0x39, 0x5458, 0x5480, "page-39 menu/getkey draw-pass hook"),
    (0x3B, 0x7ABF, 0x7AD8, "page-3B shared saved-triple checker"),
    (0x3B, 0x7CA8, 0x7CBC, "page-3B draw-pass bit-6 checker"),
    (0x3B, 0x7DB0, 0x7DBC, "page-3B draw-pass bit-6 setter"),
]

DRAW_MODE_CALLBACK_STATE_WORDS = [
    (0x85DE, "layout class/mode"),
    (0x85E8, "template kind/state"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph pen coordinate pair"),
    (0x86D8, "graph pen coordinate high byte"),
    (0x9BC0, "draw-mode saved HL slot"),
    (0x9BC2, "draw-mode saved A slot"),
    (0x9D27, "saved measured fraction pair"),
]

GLYPH_EMISSION_FLOW_ANCHORS = [
    (
        0x39,
        0x4E8E,
        "7afe1f202cdde5e1e7cd071be5dde1cd9017da0827218384cd092daf",
        "record/descriptor cell emitter: D=1F special, D=82 indexed string, otherwise generic token/glyph path",
    ),
    (
        0x39,
        0x4ECB,
        "d5cd7566d1d53e01fdcb3676c4bb2c200d7afefd20021600cd666bef",
        "generic cell path: classify parens, optionally map/copy cell string, then delegate through bjump layer",
    ),
    (
        0x39,
        0x4F1A,
        "7afefc200b7bfe41301ed63cd8c605c9fefe7b2008fe82300fd67dd8c9fe4220077afe0a3002b7c937c9",
        "token-glyph mapper: only FC3C..40, FE7D..81, and xx42 subscript-style cells map directly to glyph numbers",
    ),
    (
        0x39,
        0x6B62,
        "2600180226017afefb202f7bcb442807fec821b26b2827feca21a96b2820fecb21ad6b2819fed621bf6b2812fed821cb6b280bfed721d76b2804efca45c911f297d5cd2b19e1c903",
        "FB string loader: only FBCA/FBCB/FBD6/FBD8/FBD7 copy menu/answer strings before measurement/emission",
    ),
    (
        0x07,
        0x44DE,
        "fefe283cfefc2830fefb281efe0520051e3f1600c9d65a2100405f1600195ec9252820fefc7b281318033a4684",
        "page-7 display-byte classifier behind bjump 3B37; handles FE/FC/FB prefixes before large-glyph output",
    ),
    (
        0x07,
        0x4588,
        "fdcb356e2808473e01cde73678c8fdcb354e2808473e76cd1f3e78c811ff45eb19cdeb45115a84cd941a215a84c9",
        "large-font blitter: adjusts 45FF + code*8 to code*7 stride, then copies an 8-byte render record into 845A",
    ),
]

GLYPH_EMISSION_FLOW_XREF_TARGETS = [0x4E8E, 0x4F1A, 0x6B62, 0x6B66]

CELL_EMISSION_ALGORITHM_ANCHORS = [
    (
        0x4E8E,
        "7afe1f202cdde5e1e7cd071be5dde1cd9017da0827218384cd092daf329184218384cd853e3a4c84b7c2084f214b8435c9",
        "D=1F branch: IX-backed OP/string special form, then overflow row cleanup",
    ),
    (
        0x4EBF,
        "fe8220087bd63ecd2b3b183dd5cd7566d1d53e01fdcb3676c4bb2c200d7afefd20021600cd666b",
        "D=82 indexed-string branch, else generic delimiter/string/glyph path",
    ),
    (
        0x4EE3,
        "cd666bef0d45d1cd1a4f3804efe551c97afeff2810fefc280c7bfe552007cdb73c",
        "generic tail: optional string copy/_PutPSB, direct 4F1A glyph, then overflow cleanup",
    ),
    (
        0x4F08,
        "3a4c84fe0fd5dcb73cd1cd444fc8cd624fc9",
        "overflow/square-marker tail: erase-to-EOL guard, marker gate, row retouch helper",
    ),
    (
        0x4F44,
        "21c8fbcdbb2120063e07cd9138c021c7fbcdbb212802afc93e06cd9138c9",
        "FB C8/C7 square-marker gate: query selected marker and menu flag 07/06",
    ),
    (
        0x4F62,
        "3a4b84878787060b165eed44c63bc5d5cd0f22d1c14f5fcd60203af289f5",
        "row retouch helper: derives y from 844B, probes row state, then redraws marker context",
    ),
]

CELL_EMISSION_ALGORITHM_XREF_TARGETS = [
    (0x4E8E, "cell emitter"),
    (0x6675, "delimiter/fixed-pair classifier"),
    (0x4F1A, "direct large-font mapper"),
    (0x6B66, "generic string selector"),
    (0x4F08, "overflow/square-marker tail"),
    (0x4F44, "square-marker gate"),
    (0x4F62, "row retouch helper"),
]

SUFFIX_1F_FLOW_ANCHORS = [
    (
        0x4E8E,
        "7afe1f202cdde5e1e7cd071be5dde1cd9017da0827218384cd092daf329184218384cd853e3a4c84b7c2084f214b8435c9fe",
        "high-byte D=1F special path: IX-backed OP/string form; distinct from low-byte E=1F template cells",
    ),
    (
        0x4ECB,
        "d5cd7566d1d53e01fdcb3676c4bb2c200d7afefd20021600cd666bef0d45d1cd1a4f3804",
        "generic cell path: classify delimiter, optionally call 6B66 then _PutPSB, then try direct glyph mapper",
    ),
    (
        0x4F1A,
        "7afefc200b7bfe41301ed63cd8c605c9fefe7b2008fe82300fd67dd8c9fe4220077afe0a3002b7c937c9",
        "direct large-glyph mapper: only FC3C..40, FE7D..81, and xx42 cells map to glyph codes",
    ),
    (
        0x6B66,
        "26017afefb202f7bcb442807fec821b26b2827feca21a96b2820fecb21ad6b2819fed621bf6b2812fed821cb6b280bfed721d76b2804efca45c9",
        "generic cell string path: non-FB cells fall through to _KeyToString; selected FB cells use counted ROM strings",
    ),
    (
        0x6529,
        "0101001f12",
        "class 14 record: lone decoded D=1F cell 1F12, the actual high-byte special-form case",
    ),
    (
        0x64CF,
        "010d27001f011f021f031f041f051f061f071f081f091f0b1f0c1f0d1f",
        "class 21/3D record body: low-byte E=1F key/template cells",
    ),
    (
        0x654D,
        "010c6200100011061f031f081f071f041f011f021f051f091f0c1f",
        "class 2A root/power row: Lroot/Linverse followed by low-byte E=1F cells",
    ),
    (
        0x6433,
        "021201484600100011061f031f0012081f071f041f011f021f051f091f0b1f0c1f0d1f001b001c00130014",
        "class 31 stacked root/power row: row action 48 with low-byte E=1F cells and degree row",
    ),
]

KEY_STRING_1F_FLOW_ANCHORS = [
    (
        0x39,
        0x4ECB,
        "d5cd7566d1d53e01fdcb3676c4bb2c200d7afefd20021600cd666bef0d45d1cd1a4f3804",
        "page-39 generic cell path: call 6B66 and then _PutPSB before direct glyph fallback",
    ),
    (
        0x39,
        0x6B66,
        "26017afefb202f7bcb442807fec821b26b2827feca21a96b2820fecb21ad6b2819fed621bf6b2812fed821cb6b280bfed721d76b2804efca45c911f297d5cd",
        "page-39 generic string selector: non-special cells fall through to inline bcall 45CA (_KeyToString)",
    ),
    (
        0x01,
        0x6D41,
        "fe1f283bfe40384bfe59ca666dfe4020227afe107b201c214d6ffdcb354e3e08c41f3e18517afe0038043e6118133e40324484fe552819fe4c20093e5f18023e50821811fe562804fe422005c609c60d82d61bd610fe6538023e136f26002911",
        "page-1 _KeyToString: E=1F maps through A=0x50+D, then table lookup at 6E05+2*A",
    ),
    (
        0x01,
        0x6DB2,
        "5e2356ebbf2bcd1d2223c9",
        "page-1 _KeyToString table tail: load string pointer from table and copy the counted string",
    ),
]

KEY_STRING_1F_SAMPLE_CELLS = [
    (0x00, 0x1F),
    (0x06, 0x1F),
    (0x08, 0x1F),
    (0x0C, 0x1F),
    (0xFE, 0x1F),
    (0xFC, 0x1F),
]

KEY_STRING_STRUCTURAL_FLOW_ANCHORS = [
    (
        0x39,
        0x4ECB,
        "d5cd7566d1d53e01fdcb3676c4bb2c200d7afefd20021600cd666bef0d45d1cd1a4f3804",
        "page-39 generic cell path: delimiter/string attempt precedes the direct 4F1A glyph fallback",
    ),
    (
        0x39,
        0x6B66,
        "26017afefb202f7bcb442807fec821b26b2827feca21a96b2820fecb21ad6b2819fed621bf6b2812fed821cb6b280bfed721d76b2804efca45c911f297d5cd",
        "page-39 string selector: FB strings are local; ordinary cells inline-bcall _KeyToString",
    ),
    (
        0x01,
        0x6D10,
        "7afeff2811fefb2804fefc20072602cd313b1817fefe7b280dfe5a3814cdbd6dc8cd373b18052601cd313bcd0267c3b76d",
        "page-1 _KeyToString entry and prefix handling",
    ),
    (
        0x01,
        0x6D94,
        "d610fe6538023e136f26002911",
        "ordinary low-byte path: subtract 0x10, clamp high indexes, then address table 6E05+2*A",
    ),
    (
        0x01,
        0x6E05,
        "cf6ed56ee76ef66eff6e076f0c6f156f1c6f266f2b6f397140715d714d6f7371757173717371",
        "_KeyToString pointer table: index 00 starts at 6ECF; index 01 points before the next counted string",
    ),
    (
        0x07,
        0x466F,
        "07040404140c04",
        "page-7 fixed Lroot glyph bytes at 45FF + 0x10*7",
    ),
]

KEY_STRING_STRUCTURAL_SAMPLE_CELLS = [
    (0x00, 0x10, "root/power record cell, but _KeyToString index 00"),
    (0x00, 0x11, "root/power inverse cell contrast"),
    (0x00, 0x12, "stacked root/power row contrast"),
    (0x00, 0x14, "degree row contrast"),
    (0x06, 0x1F, "low-byte 1F cell still uses 50+D indexing"),
]

LROOT_FINAL_EMITTER_BOUNDARY_ANCHORS = [
    (
        0x39,
        0x4ED1,
        "3e01fdcb3676c4bb2c200d7afefd20021600cd666bef0d45d1cd1a4f3804",
        "final cell emitter draw-pass hook, string fallback, and direct glyph fallback",
    ),
    (
        0x39,
        0x4F1A,
        "7afefc200b7bfe41301ed63cd8c605c9fefe7b2008fe82300fd67dd8c9fe4220077afe0a3002b7c937c9",
        "direct glyph mapper: FC3C..40, FE7D..81, and xx42 only",
    ),
    (
        0x39,
        0x4D92,
        "cd274c462310fd230e003adf85b92004fdcb05dee53e02fdcb3676c4bb2c20047ecd2b3b",
        "row-action/title loop emits action bytes through 3B2B, separate from payload cells",
    ),
    (
        0x39,
        0x4DCA,
        "cd274c3adf85b7477e4f2806e5238610fce1cb279186235f160019c9",
        "row-cell pointer skips row_action bytes before payload cells",
    ),
    (
        0x39,
        0x654D,
        "010c6200100011061f031f081f071f041f011f021f051f091f0c1f",
        "class 2A root/power record: row action 62, payload starts with 0010",
    ),
    (
        0x39,
        0x6433,
        "021201484600100011061f031f0012081f071f041f011f021f051f091f0b1f0c1f0d1f001b001c00130014",
        "class 31 stacked root/power record: row action 48, payload starts with 0010",
    ),
    (
        0x00,
        0x2CBB,
        "cd092ba87c7b",
        "fixed-bank draw-mode callback stub: cross-page jump to page 3B:7CA8",
    ),
    (
        0x3B,
        0x7CA8,
        "f5e521c09bcdbf7ae128a8f1bffdcb36b6c9",
        "page-3B draw-mode saved-HL/A checker; clears draw-pass bit, no glyph output",
    ),
    (
        0x01,
        0x6D94,
        "d610fe6538023e136f26002911",
        "_KeyToString ordinary low-byte path: 0010 indexes table entry 00",
    ),
    (
        0x07,
        0x466F,
        "07040404140c04",
        "page-7 fixed Lroot glyph bytes at 45FF + 0x10*7",
    ),
]

TEMPLATE_TRACEPOINT_FLOW_ANCHORS = [
    (
        0x39,
        0x4F9A,
        "fdcb36664728233a9a85fe402006",
        "page-39 layout dispatcher entry: capture incoming action A and class/state 85DE",
    ),
    (
        0x39,
        0x4FD9,
        "c3ae68",
        "only static page-39 jump from class-48 actions into geometry dispatcher 68AE",
    ),
    (
        0x39,
        0x68AE,
        "21e8850e10fe4928100cfe48280b0cfe2ecad0680cfe5a200f79c37367cd336837c979",
        "geometry-mode action mapper: actions 49/48/2E/5A select kinds 10/11/12/13",
    ),
    (
        0x39,
        0x67A0,
        "cd3348cdac67cd2248c3c869",
        "geometry redraw wrapper: graph-window setup, template chrome, restore, then selector 69C8",
    ),
    (
        0x39,
        0x69C8,
        "21000022df8521e8857ee60f116f682823118068fe02381cca8a6a",
        "geometry selector: descriptor family or kind-2 fraction UI",
    ),
    (
        0x39,
        0x6A27,
        "cd3d6822d7863ae885cb4f20173ae085c631cddb3c3e3acddb3c3e20",
        "descriptor cell loop: map descriptor cell to pixels and emit small labels/cell strings",
    ),
    (
        0x39,
        0x4DE6,
        "3a4a98324b84cd0a4e56235e23e5c5cd8e4e",
        "record-row cell stream: each decoded D:E cell enters 4E8E",
    ),
    (
        0x39,
        0x4E8E,
        "7afe1f",
        "decoded-cell emitter entry tail used by records and saved-operand cells",
    ),
    (
        0x39,
        0x4EEA,
        "cd1a4f",
        "direct fixed-glyph mapper call after delimiter/string handling",
    ),
    (
        0x39,
        0x6ABF,
        "f5ed4bdf85cb482808212a2b11343318132615cb4028022620793c",
        "fraction/rule rectangle helper: endpoint math and graph-window draw/erase",
    ),
    (
        0x39,
        0x6B1C,
        "2e07473e1b8510fd6fc6045f7cc60657c9",
        "rule endpoint math: x=0x1B+7*n, right=x+4, y=H+6",
    ),
    (
        0x39,
        0x6AF5,
        "cd3348ef8c4d18f4",
        "descriptor/fraction box draw wrapper through _DrawRectBorderClear",
    ),
    (
        0x07,
        0x4588,
        "fdcb356e2808473e01cde73678c8fdcb354e2808473e76cd1f3e78c8",
        "page-7 large-font blitter entry: capture A/glyph code and pen state",
    ),
    (
        0x01,
        0x6293,
        "fdcbff86c547ed57eaa062ed57f578f3e5",
        "page-1 _VPutMap target reached by page-39 bjump 3CDB for small text and geometry labels",
    ),
]

TEMPLATE_TRACEPOINTS = [
    ("39:4F9A", "layout action dispatch", "A, 85DE, 85E0, 844B/844C"),
    ("39:4FD9", "geometry action branch", "A, 85E8, 85EE/85EF, 9D27"),
    ("39:68AE", "geometry action mapper", "A, 85E8, 85DE, 85EE/85EF"),
    ("39:67A0", "geometry redraw wrapper", "85E8, 85DF, 85EE/85EF, 86D7/86D8"),
    ("39:69C8", "descriptor/fraction selector", "85E8 kind, selected descriptor pointer"),
    ("39:6A27", "descriptor cell loop", "85DF, 85E0, 85E9, 85EB, 85EC, 86D7/86D8, D:E cell"),
    ("39:4DE6", "handler row cell stream", "85DE, 85DF, 85E0, 85E2, 844B/844C, D:E cell"),
    ("39:4E8E", "decoded-cell emitter", "D:E, 844B/844C, 86D7/86D8"),
    ("39:4EEA", "direct glyph fallback", "D:E, returned A glyph code, carry flag"),
    ("07:4588", "large-font blitter", "A glyph code, 844B/844C or pen x/y, output rows"),
    ("01:6293", "_VPutMap target", "A/code or HL glyph pointer, 86D7/86D8, plotted pixels"),
    ("39:6ABF", "rule/rectangle draw", "carry, 85DF, H/L/D/E endpoints, bcall id"),
    ("39:6B1C", "rule endpoint math", "input B/C/H/L, output D/E/H/L"),
    ("39:6AF5", "box draw wrapper", "HL/DE rectangle corners, bcall id 4D8C"),
]

RECTANGLE_RULE_EVENT_FLOW_ANCHORS = [
    (
        0x39,
        0x6987,
        "cb482025fe01201679fe0528f13c4fc537cdbf6ae122df85b7cdbf6a18e0",
        "kind-2 column move: compute new C, erase old rectangle with carry set, store 85DF, redraw with carry clear",
    ),
    (
        0x39,
        0x69B0,
        "fe032008783dfa85694718dafe04208278fe0228c03c18f1",
        "kind-2 row move: actions 3/4 adjust B, then reuse the erase/store/redraw event pair",
    ),
    (
        0x39,
        0x6ABF,
        "f5ed4bdf85cb482808212a2b11343318132615cb4028022620793ccd1c6b2d141414141cf1cd33483805ef7d4d1803ef864dcd2248c9",
        "rectangle event helper: 85DF selects full/numerator/denominator geometry, 6B1C computes endpoints, carry selects draw vs erase",
    ),
    (
        0x39,
        0x6B1C,
        "2e07473e1b8510fd6fc6045f7cc60657c9",
        "endpoint helper: L=0x1B+7*n, E=L+4, H=H+6, D=0",
    ),
    (
        0x39,
        0x6A8A,
        "3aee85b7c8211112114c35cdf56a1617215b6bcd2d6b162221546b",
        "kind-2 fraction UI setup: fixed box HL=1211/DE=354C through 6AF5, then ROW/COL labels",
    ),
    (
        0x39,
        0x6A00,
        "cde26bd5141c1ced53e985cde26be3cdf56ae17e32eb8523cde26b",
        "descriptor setup: descriptor +2 word is passed to 6AF5 as the descriptor box",
    ),
    (
        0x39,
        0x6AF5,
        "cd3348ef8c4d18f4",
        "box wrapper: graph-window setup, _DrawRectBorderClear, then restore tail",
    ),
]

RECTANGLE_RULE_EXPECTED_CALLERS = {
    0x6ABF: {
        0x6998: "erase old kind-2 fraction row/column rectangle before updating 85DF",
        0x69A0: "draw new kind-2 fraction row/column rectangle after storing 85DF",
    },
    0x6B1C: {
        0x6ADA: "endpoint math inside 6ABF for row/column rectangle extent",
        0x6B14: "endpoint math inside 6AFD focused-cell inversion extent",
    },
    0x6AF5: {
        0x6A0F: "descriptor box draw after descriptor origin word is loaded",
        0x6A95: "fixed kind-2 fraction box draw with HL=1211, DE=354C",
    },
}

RECTANGLE_RULE_ENDPOINT_SAMPLES = [
    (0, 0x1B, 0x1F, "zero-count baseline extent"),
    (1, 0x22, 0x26, "one measured cell extent"),
    (2, 0x29, 0x2D, "two measured cells extent"),
    (5, 0x3E, 0x42, "maximum kind-2 column selector extent"),
]

LARGE_FONT_FLOW_ANCHORS = [
    (
        0x44DE,
        "fefe283cfefc2830fefb281efe0520051e3f1600c9d65a2100405f1600195ec9252820fefc7b281318033a4684",
        "page-7 display-byte classifier: maps ordinary/FE/FC/FB display bytes to large-font codes",
    ),
    (
        0x4588,
        "fdcb356e2808473e01cde73678c8fdcb354e2808473e76cd1f3e78c811ff45eb19cdeb45115a84cd941a215a84c9",
        "large-font blitter: alternate-font guards, base 45FF, adjust stride through 45EB, copy to 845A",
    ),
    (
        0x45A4,
        "11ff45eb19cdeb45115a84cd941a215a84c9",
        "main glyph-copy tail: HL=45FF+code*8; 45EB subtracts code to get 45FF+code*7; _Mov8B copies record",
    ),
    (
        0x45EB,
        "cb3acb1bcb3acb1bcb3acb1bb7ed52c9",
        "large-font stride adjuster: divide DE=code*8 by 8 to recover code, then SBC HL,DE -> code*7",
    ),
    (
        0x45FB,
        "06077ecb2712231310f8c9",
        "alternate shifted copy helper: fixed 7-byte loop, no height-dependent stretch",
    ),
    (
        0x45FF,
        "2712231310f8c90000160909121200",
        "large-font table base sample: fixed data at 45FF, consumed by 7-byte stride/8-byte copy machinery",
    ),
]

DISPLAY_BYTE_MAP_FLOW_ANCHORS = [
    (
        0x44DE,
        "fefe283cfefc2830fefb281efe0520051e3f1600c9d65a2100405f1600195ec9252820fefc7b281318033a4684",
        "page-7 display-byte classifier: FE/FC/FB prefixes and ordinary >=5A table lookup",
    ),
    (
        0x4521,
        "fe69300521994018ced669",
        "FE low-byte split: lows <69 use one-byte table 4099; lows >=69 use pair table 4102",
    ),
    (
        0x452F,
        "6f260029195e53235ec9",
        "shared pair-table lookup: table + 2*A returns D=first byte, E=second byte",
    ),
]

DISPLAY_BYTE_MAP_TABLES = [
    (0x4000, "ordinary A>=5A one-byte display map"),
    (0x4099, "FE low-byte <69 one-byte display map"),
    (0x4102, "FE low-byte >=69 two-byte display map"),
    (0x422C, "FC two-byte display map"),
    (0x4426, "FB two-byte display map"),
]

DISPLAY_BYTE_MAP_SAMPLES = [
    (0xFB, 0xC8, "sqUp/template marker"),
    (0xFB, 0xC7, "sqDown/template marker"),
    (0xFB, 0xCA, "n/d menu string"),
    (0xFB, 0xCB, "Un/d menu string"),
    (0xFE, 0x09, "FE prefix row-1 class-08 cell"),
    (0xFE, 0xA7, "delimiter table-B sample"),
    (0xFC, 0x00, "delimiter table-A sample"),
    (0xFC, 0x22, "delimiter table-B sample"),
    (0xFC, 0x50, "delimiter table-C sample"),
    (0xFC, 0x8C, "63C3 two-byte form-table sample"),
    (0x00, 0xC8, "fnInt display/name cell"),
    (0x00, 0xC7, "nDeriv display/name cell"),
    (0x08, 0x42, "direct Lintegral glyph cell"),
    (0x00, 0x10, "direct Lroot/root-record cell"),
]

OFFPAGE_RENDER_FLOW_ANCHORS = [
    (
        0x01,
        0x5A98,
        "f3f5c5d5e5dde5fdcb0296fdcb0d4e2804cd2a6277b72804fef838023ed06f2600292929cd3d3b",
        "_PutMap path: clamp display code, compute code*8, then bjump through 3B3D",
    ),
    (
        0x01,
        0x5AE8,
        "0608af052805dd7e00dd2304cb27",
        "_PutMap blit loop prologue: fixed B=8 output rows from the loaded glyph record",
    ),
    (
        0x01,
        0x6267,
        "6f2600292929fdcb32562804cd8b3bc9fdcb32762812cd3d3b116184216084010700edb8eb3605c9",
        "_LoadPattern: compute code*8 and choose fixed pattern/glyph copy helpers 3B8B/3B3D/3B61",
    ),
    (
        0x06,
        0x7F66,
        "6f2600292929cd3d3bc9",
        "page-6 helper: compute code*8, call 3B3D, and return",
    ),
    (
        0x07,
        0x4588,
        "fdcb356e2808473e01cde73678c8fdcb354e2808473e76cd1f3e78c811ff45eb19cdeb45115a84cd941a215a84c9",
        "large-font blitter: fixed 7-byte-stride / 8-byte-record copy into 845A",
    ),
    (
        0x07,
        0x45EB,
        "cb3acb1bcb3acb1bcb3acb1bb7ed52c9",
        "stride adjuster: divide code*8 by 8, subtract code, and address 45FF+code*7",
    ),
    (
        0x35,
        0x734B,
        "21020222279dfdcb1a86c9",
        "reset/default path seeds 9D27=0202; initialization, not a measured-template consumer",
    ),
    (
        0x37,
        0x6D2D,
        "21020222279d3eff32b0973e00d327",
        "startup/init path seeds 9D27=0202; initialization, not a measured-template consumer",
    ),
]

OFFPAGE_RENDER_PATTERNS = [
    ("RST28 _FillRect", "ef624d"),
    ("RST28 _FillRectPattern", "ef894d"),
    ("RST28 _DisplayImage", "ef9b4d"),
    ("CALL bjump 3B3D", "cd3d3b"),
    ("word 85EE", "ee85"),
    ("word 9D27", "279d"),
]

GLYPH_SERVICE_CLOSED_ANCHORS = OFFPAGE_RENDER_FLOW_ANCHORS[:6]

GLYPH_SERVICE_CLOSED_CALLS = [
    (0x01, 0x5ABC, "_PutMap tail", "fixed B=8 glyph-record output after code*8 setup"),
    (0x01, 0x627D, "_LoadPattern path", "fixed pattern/glyph copy helper after code*8 setup"),
    (0x06, 0x7F6C, "page-6 helper", "fixed code*8 -> 3B3D glyph-service call"),
]

LARGE_GLYPH_CALLER_WINDOWS = [
    (0x01, 0x5A80, 0x5B05, "_PutMap caller window around 3B3D"),
    (0x01, 0x6258, 0x6290, "_LoadPattern caller window around 3B3D"),
    (0x06, 0x7F58, 0x7F78, "page-6 code*8 helper window around 3B3D"),
    (0x07, 0x4588, 0x45B6, "page-7 put_glyph_large body"),
]

LARGE_GLYPH_CALLER_STATE_WORDS = [
    (0x844B, "display row"),
    (0x844C, "display column/overflow"),
    (0x85DE, "layout class/mode"),
    (0x85E8, "template kind/state"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph pen coordinate pair"),
    (0x86D8, "graph pen y"),
    (0x9D27, "saved measured fraction pair"),
]

LARGE_GLYPH_CALLER_DRAW_PATTERNS = [
    ("CALL bjump 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL bjump 3B37 display-byte classifier", "cd373b"),
    ("CALL bjump 3CDB VPutMap", "cddb3c"),
    ("CALL RAM 3555 _DarkLine", "cd5535"),
    ("RST28 _FillRect", "ef624d"),
    ("RST28 _FillRectPattern", "ef894d"),
    ("RST28 _DisplayImage", "ef9b4d"),
]

INDEXED_STRING_CALLER_ANCHORS = [
    (
        0x01,
        0x7183,
        "5f160021a1711919cd3300c5fdcb354e28073e07cd1f3e2803cd735c",
        "page-1 put_indexed_string: index pointer table 71A1 and print the selected string",
    ),
    (
        0x39,
        0x4D08,
        "cd2b3b",
        "page-39 raised-row/indexed-title string output caller",
    ),
    (
        0x39,
        0x4DB3,
        "cd2b3b",
        "page-39 row-action/title loop output caller",
    ),
    (
        0x39,
        0x4EC6,
        "cd2b3b",
        "page-39 D=82 decoded-cell indexed-string output caller",
    ),
]

INDEXED_STRING_EXPECTED_CALLERS = [
    (0x39, 0x4D08, "raised-row/indexed-title helper"),
    (0x39, 0x4DB3, "row-action/menu-title loop"),
    (0x39, 0x4EC6, "D=82 decoded-cell indexed-string branch"),
]

INDEXED_STRING_CALLER_STATE_WORDS = [
    (0x844B, "display row"),
    (0x844C, "display column/overflow"),
    (0x85DE, "layout class/mode"),
    (0x85DF, "layout row/subrow"),
    (0x85E0, "argument/column index"),
    (0x85E1, "row/dimension count"),
    (0x85E2, "argument/cell count"),
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor base/dims"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph pen coordinate pair"),
    (0x86D8, "graph pen y"),
    (0x9D27, "saved measured fraction pair"),
]

INDEXED_STRING_MEASURED_WORDS = {0x85E8, 0x85E9, 0x85EB, 0x85EC, 0x85EE, 0x85EF, 0x9D27}

INDEXED_STRING_CALLER_DRAW_PATTERNS = [
    ("CALL bjump 3B2B indexed-string printer", "cd2b3b"),
    ("CALL bjump 3B37 display-byte classifier", "cd373b"),
    ("CALL bjump 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL bjump 3CDB VPutMap", "cddb3c"),
    ("CALL RAM 3555 _DarkLine", "cd5535"),
    ("RST28 _PutPSB", "ef5245"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _FillRect", "ef624d"),
    ("RST28 _FillRectPattern", "ef894d"),
    ("RST28 _DisplayImage", "ef9b4d"),
]

GENERIC_STRING_CALLER_ANCHORS = [
    (
        0x39,
        0x4ECB,
        "d5cd7566d1d53e01fdcb3676c4bb2c200d7afefd20021600cd666bef0d45d1cd1a4f3804",
        "page-39 generic cell path: delimiter/string attempt, _PutPSB, then direct glyph fallback",
    ),
    (
        0x39,
        0x4EE3,
        "cd666bef0d45",
        "page-39 generic string selector call followed by inline _PutPSB",
    ),
    (
        0x39,
        0x6B62,
        "2600180226017afefb202f7bcb442807fec821b26b2827feca21a96b2820fecb21ad6b2819fed621bf6b2812fed821cb6b280bfed721d76b2804efca45c911f297d5cd2b19e1c903",
        "page-39 FB string selector plus _KeyToString fallback",
    ),
    (
        0x01,
        0x6D10,
        "7afeff2811fefb2804fefc20072602cd313b1817fefe7b280dfe5a3814cdbd6dc8cd373b18052601cd313bcd0267c3b76d",
        "page-1 _KeyToString entry and prefix handling",
    ),
    (
        0x01,
        0x6DB2,
        "5e2356ebbf2bcd1d2223c9",
        "page-1 _KeyToString table tail copies the selected counted string",
    ),
]

GENERIC_STRING_PAGE39_EXPECTED = [
    (0x4EE3, "CALL 6B66 generic string selector from decoded-cell tail"),
    (0x4EE6, "RST28 _PutPSB after generic string selector"),
    (0x6A52, "CALL 6B62 descriptor FB string selector"),
    (0x6B9C, "RST28 _KeyToString inside 6B66 fallback"),
]

GENERIC_STRING_STATE_WORDS = [
    (0x844B, "display row"),
    (0x844C, "display column/overflow"),
    (0x85DE, "layout class/mode"),
    (0x85DF, "layout row/subrow"),
    (0x85E0, "argument/column index"),
    (0x85E1, "row/dimension count"),
    (0x85E2, "argument/cell count"),
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor base/dims"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph pen coordinate pair"),
    (0x86D8, "graph pen y"),
    (0x9D27, "saved measured fraction pair"),
]

GENERIC_STRING_MEASURED_WORDS = {0x85E8, 0x85E9, 0x85EB, 0x85EC, 0x85EE, 0x85EF, 0x9D27}

GENERIC_STRING_PATTERNS = [
    ("CALL 6B66 generic string selector", "cd666b"),
    ("CALL 6B62 descriptor string selector", "cd626b"),
    ("RST28 _PutPSB", "ef0d45"),
    ("RST28 _KeyToString", "efca45"),
    ("CALL bjump 3B2B indexed-string printer", "cd2b3b"),
    ("CALL bjump 3B37 display-byte classifier", "cd373b"),
    ("CALL bjump 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL bjump 3CDB VPutMap", "cddb3c"),
    ("CALL RAM 3555 _DarkLine", "cd5535"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _FillRect", "ef624d"),
    ("RST28 _FillRectPattern", "ef894d"),
    ("RST28 _DisplayImage", "ef9b4d"),
]

DISPLAY_BYTE_CALLER_ANCHORS = [
    (0x07, addr, hex_bytes, note)
    for addr, hex_bytes, note in DISPLAY_BYTE_MAP_FLOW_ANCHORS
] + [
    (
        0x39,
        0x6692,
        "cd373b",
        "page-39 delimiter classifier caller: matched fixed delimiter pairs route through display-byte mapper",
    ),
]

DISPLAY_BYTE_EXPECTED_CALLERS = [
    (0x01, 0x6D31, "page-1 key/string display helper"),
    (0x03, 0x4684, "page-3 editor/display helper"),
    (0x04, 0x477B, "page-4 graph/UI display helper"),
    (0x05, 0x420D, "page-5 table/list display helper"),
    (0x06, 0x4592, "page-6 cursor/UI display helper"),
    (0x06, 0x47E9, "page-6 token/display helper"),
    (0x06, 0x4901, "page-6 token/display helper"),
    (0x34, 0x4634, "page-34 parser/object display helper"),
    (0x37, 0x618F, "page-37 app/UI display helper"),
    (0x37, 0x6535, "page-37 app/UI display helper"),
    (0x39, 0x6692, "page-39 fixed delimiter-pair classifier"),
]

DISPLAY_BYTE_CALLER_STATE_WORDS = [
    (0x844B, "display row"),
    (0x844C, "display column/overflow"),
    (0x85DE, "layout class/mode"),
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor base/dims"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph pen coordinate pair"),
    (0x86D8, "graph pen y"),
    (0x9D27, "saved measured fraction pair"),
]

DISPLAY_BYTE_MEASURED_WORDS = {0x85E8, 0x85E9, 0x85EB, 0x85EC, 0x85EE, 0x85EF, 0x9D27}

DISPLAY_BYTE_CALLER_DRAW_PATTERNS = [
    ("CALL bjump 3B37 display-byte classifier", "cd373b"),
    ("CALL bjump 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL bjump 3CDB VPutMap", "cddb3c"),
    ("CALL RAM 3555 _DarkLine", "cd5535"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _FillRect", "ef624d"),
    ("RST28 _FillRectPattern", "ef894d"),
    ("RST28 _DisplayImage", "ef9b4d"),
]

VPUTMAP_SERVICE_ANCHORS = [
    (
        0x01,
        0x6293,
        "fdcbff86c547ed57eaa062ed57f578f3e5",
        "_VPutMap prologue: clear draw flag, read I/R, then enter LCD/graph-buffer pixel output",
    ),
    (
        0x39,
        0x6A39,
        "cddb3c3e3acddb3c3e20cddb3c3e20cddb3c",
        "descriptor-cell loop VPutMap burst: fixed small labels/spaces after descriptor cell mapping",
    ),
    (
        0x39,
        0x6AB0,
        "cddb3c3e4bcddb3ccd0e6bcd",
        "kind-2 fraction UI: print OK label, then enter row/focus helpers",
    ),
    (
        0x39,
        0x6B3C,
        "cddb3c3e20cddb3c3e20cddb3c78cddb3c0478fe37c818e606434f4c",
        "ROW/COL label printer: fixed digit/space VPutMap calls around counted labels",
    ),
]

VPUTMAP_EXPECTED_PAGE39_CALLERS = [
    0x6A39, 0x6A3E, 0x6A43, 0x6A48, 0x6AB0, 0x6AB5,
    0x6B3C, 0x6B41, 0x6B46, 0x6B4A, 0x6BF4,
]

VPUTMAP_CALLER_STATE_WORDS = [
    (0x844B, "display row"),
    (0x844C, "display column/overflow"),
    (0x85DE, "layout class/mode"),
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor base/dims"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph pen coordinate pair"),
    (0x86D8, "graph pen y"),
    (0x9D27, "saved measured fraction pair"),
]

VPUTMAP_MEASURED_WORDS = {0x85E9, 0x85EB, 0x85EC, 0x85EE, 0x85EF, 0x9D27}

VPUTMAP_CALLER_DRAW_PATTERNS = [
    ("CALL bjump 3CDB VPutMap", "cddb3c"),
    ("CALL bjump 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL RAM 3555 _DarkLine", "cd5535"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _FillRect", "ef624d"),
    ("RST28 _FillRectPattern", "ef894d"),
    ("RST28 _DisplayImage", "ef9b4d"),
]

GLYPH_SERVICE_ABSENT_PATTERNS = [
    ("ROM-wide inline _FillRect", "ef624d"),
    ("ROM-wide inline _FillRectPattern", "ef894d"),
    ("ROM-wide inline _DisplayImage", "ef9b4d"),
]

OFFPAGE_STATE_INTERSECTION_ANCHORS = [
    (
        0x06,
        0x4B24,
        "7e0e10fe4928100cfe48280b0cfe2eca3b4b0cfe5a200921e885713e3d21447c",
        "page-6 key/action helper: maps 49/48/2E/5A to 85E8 kind values and returns action 3D",
    ),
    (
        0x06,
        0x4B44,
        "3ade85fe007e20343a9a85fe542802fe537e2808fe0620043e051820",
        "page-6 continuation: tests 85DE zero and app/context bytes before returning to local key handling",
    ),
    (
        0x06,
        0x7CD0,
        "3e24cd8d302816fdcb2a4e280d2ad786e5cddb3ce122d7861803cdf73b",
        "page-6 cursor/display helper: may preserve 86D7 around VPutMap; no MathPrint measured state",
    ),
    (
        0x06,
        0x7CF3,
        "f53ade85fe492005f1ef6454c9dd2aa3973a9a85fe55281a",
        "page-6 cursor/menu helper: 85DE=49 takes display helper bcall, otherwise dispatches on app context",
    ),
    (
        0x07,
        0x5EEA,
        "fdcb0ce6c9fdcb0ca6af32de85324b98fdcb255e2807",
        "page-7 editor/parser cleanup: toggles IY+0C bit 4, clears 85DE and 984B",
    ),
    (
        0x07,
        0x6F90,
        "21e2403e6ffdcb354ec41f3efdcb14fefdcb05ce3e20cddb3c",
        "page-7 display helper: emits a space through 3CDB with no nearby MathPrint state refs",
    ),
    (
        0x37,
        0x529D,
        "3a9a85fe45c0cd9a5dc83ade85b7c0cdd36cc0fdcb3f76c8",
        "page-37 UI helper: requires app context 45 and 85DE zero before drawing message/UI state",
    ),
    (
        0x37,
        0x52D9,
        "ed53d786fdcb05defdcb05cecdc13221a484cdf93ccdc132cdc132cd0f53",
        "page-37 UI helper: stores a fixed DE coordinate to 86D7, then uses generic display helpers",
    ),
    (
        0x37,
        0x6D2D,
        "21020222279d3eff32b0973e00d327",
        "page-37 startup/init path seeds 9D27=0202; not a measured-template consumer",
    ),
    (
        0x37,
        0x6F9E,
        "ef8c4d3e29cdaa4d21ea6f3e431103021803110502",
        "page-37 message/defaults UI: DrawRectBorderClear followed by fixed message pointers",
    ),
]

OFFPAGE_STATE_INTERSECTION_WINDOWS = [
    (0x06, 0x4B10, 0x4C5E, "page-6 key/action helper"),
    (0x06, 0x7CB0, 0x7E40, "page-6 cursor/display helper"),
    (0x07, 0x5ED0, 0x6010, "page-7 editor/parser cleanup"),
    (0x07, 0x6F80, 0x6FBA, "page-7 display helper"),
    (0x37, 0x529D, 0x5310, "page-37 UI helper"),
    (0x37, 0x6D2D, 0x6E40, "page-37 startup/defaults path"),
    (0x37, 0x6F88, 0x6FD0, "page-37 message/defaults UI"),
]

OFFPAGE_STATE_INTERSECTION_WORDS = [
    (0x85DE, "layout class/mode"),
    (0x85DF, "layout row/subrow"),
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor base/dims"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph pen coordinate pair"),
    (0x86D8, "graph pen coordinate high byte"),
    (0x9D27, "saved measured fraction pair"),
]

OFFPAGE_STATE_INTERSECTION_PATTERNS = [
    ("CALL 3B37 display-byte mapper", "cd373b"),
    ("CALL 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL 3CDB VPutMap", "cddb3c"),
    ("RST28 _ClearRect", "ef5c4d"),
    ("RST28 _InvertRect", "ef5f4d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
    ("CALL RAM 3555 _DarkLine", "cd5535"),
]

OFFPAGE_DRAW_STATE_WORDS = [
    (0x85DE, "layout class/mode"),
    (0x85DF, "layout row/subrow"),
    (0x85E0, "argument/column index"),
    (0x85E1, "row/dimension count"),
    (0x85E2, "argument/cell count"),
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor base/dims"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x9D27, "saved measured fraction pair"),
]

OFFPAGE_DRAW_SERVICE_PATTERNS = [
    ("CALL RAM 3555 _DarkLine", "cd5535"),
    ("CALL Z RAM 3555 _DarkLine", "cc5535"),
    ("CALL bjump 3B37 display-byte classifier", "cd373b"),
    ("CALL bjump 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL bjump 3CDB VPutMap", "cddb3c"),
    ("RST28 _PutPSB", "ef0d45"),
    ("RST28 _ClearRect", "ef5c4d"),
    ("RST28 _InvertRect", "ef5f4d"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _FillRect", "ef624d"),
    ("RST28 _FillRectPattern", "ef894d"),
    ("RST28 _DisplayImage", "ef9b4d"),
    ("RST28 _RestoreDisp", "ef7048"),
    ("RST28 _UCLineS", "ef9547"),
    ("RST28 _CLine", "ef9847"),
    ("RST28 _CLineS", "ef9b47"),
    ("RST28 _DarkLine", "efdd47"),
    ("RST28 _ILine", "efe047"),
    ("RST28 _IPoint", "efe347"),
    ("RST28 _CPointS", "eff547"),
    ("RST28 _CPoint", "efc84d"),
    ("RST28 _LineCmd", "efac48"),
    ("RST28 _UnLineCmd", "efaf48"),
    ("RST28 _PointCmd", "efb248"),
    ("RST28 _PixelTest", "efb548"),
    ("RST28 _DrawCmd", "efc148"),
    ("RST28 _SetTblGraphDraw", "ef004c"),
    ("RST28 _PointOn", "ef394c"),
    ("RST28 _DrawCirc2", "ef664c"),
    ("RST28 _VertSplitDraw", "efdc48"),
    ("RST28 _Regraph", "ef8e48"),
    ("RST28 _DrawZeroOP1", "ef7348"),
    ("RST28 _grf_7066", "efc547"),
    ("RST28 _GraphTblNext", "efc847"),
    ("RST28 _GraphTblFind", "efcb47"),
    ("RST28 _GraphParseTok", "ef0a51"),
    ("RST28 _grf_435f", "ef4051"),
    ("RST28 _grf_5e06", "ef7654"),
]

OFFPAGE_COMMAND_DRAW_CONTEXT_WINDOWS = [
    (0x00, 0x4A90, 0x4DD0, "page-0 _grf_5e06 caller / state helper"),
    (0x02, 0x5630, 0x5668, "page-2 PixelTest prompt/command handler"),
    (0x02, 0x6400, 0x6420, "page-2 graph/parser helper"),
    (0x33, 0x5DF0, 0x5E24, "page-33 _grf_5e06 state helper"),
    (0x33, 0x71A8, 0x7368, "page-33 graph storage/style helpers"),
    (0x33, 0x74D0, 0x7500, "page-33 DrawCirc2 graph helper"),
    (0x38, 0x4980, 0x4F50, "page-38 Regraph/VertSplitDraw command handlers"),
    (0x3A, 0x6F60, 0x7AC0, "page-3A graph table navigation helpers"),
]

DIRECT_PIXEL_SURFACE_PATTERNS = [
    ("word plotSScreen 9340", "4093"),
    ("word appBackUpScreen 9872", "7298"),
    ("word display backup 86EC", "ec86"),
    ("OUT (10),A LCD command", "d310"),
    ("OUT (11),A LCD data", "d311"),
    ("IN A,(11) LCD data", "db11"),
]

DIRECT_PIXEL_SURFACE_WINDOWS = [
    (0x33, 0x4F00, 0x4F70, "page-33 85EE token/value helper"),
    (0x33, 0x5120, 0x5148, "page-33 display-backup pointer helper"),
    (0x35, 0x58E0, 0x5920, "page-35 direct LCD helper"),
    (0x35, 0x7338, 0x7360, "page-35 9D27 default seed"),
    (0x37, 0x6D2D, 0x6E40, "page-37 9D27 startup/default seed"),
    (0x37, 0x73A0, 0x73F0, "page-37 direct LCD helper"),
    (0x39, 0x4AC0, 0x4AE0, "page-39 dispatch/context restore tail"),
    (0x39, 0x5798, 0x5888, "page-39 restore-display callers"),
    (0x39, 0x5D86, 0x5E20, "page-39 RestoreDisp/SaveDisp direct LCD cluster"),
    (0x39, 0x6750, 0x6B30, "page-39 measured template/fraction geometry"),
]

PEN_SURFACE_STATE_WORDS = [
    (0x86D7, "graph pen coordinate pair"),
    (0x86D8, "graph pen coordinate high byte"),
]

PEN_SURFACE_MEASURED_WORDS = [
    (0x85DE, "layout class/mode"),
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor base/dims"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x9D27, "saved measured fraction pair"),
]

PEN_SURFACE_ANCHORS = [
    (
        0x06,
        0x7CD0,
        "3e24cd8d302816fdcb2a4e280d2ad786e5cddb3ce122d7861803cdf73b",
        "page-6 cursor/display helper: preserves 86D7 around one VPutMap call, no measured template state",
    ),
    (
        0x35,
        0x6887,
        "3ad7863d47570e3f1e39cd5535e1f1c9",
        "page-35 display/window helper: fixed 86D7-derived coordinate before _DarkLine",
    ),
    (
        0x37,
        0x52D9,
        "ed53d786fdcb05defdcb05cecdc13221a484cdf93ccdc132cdc132cd0f53",
        "page-37 UI helper: stores a fixed DE coordinate to 86D7, then calls generic display helpers",
    ),
    (
        0x39,
        0x67CE,
        "11fe85d5cd9c1aaf12e3cdf93ce1c1e5501e02cd55350c04593e108057cd553514420d1e02cd553504",
        "page-39 template chrome: fixed tab separator lines through _DarkLine",
    ),
    (
        0x39,
        0x6A27,
        "cd3d6822d7863ae885cb4f20173ae085c631cddb3c3e3acddb3c3e20cddb3c3e20cddb3ce156235e23e5d5cd626b",
        "page-39 descriptor cell loop: maps descriptor cell to 86D7 before fixed VPutMap/string emission",
    ),
]

PEN_SURFACE_WINDOWS = [
    (0x06, 0x7CB0, 0x7E40, "page-6 cursor/display helper"),
    (0x35, 0x6874, 0x6898, "page-35 fixed _DarkLine helper"),
    (0x37, 0x529D, 0x5310, "page-37 UI helper"),
    (0x39, 0x4F62, 0x4F99, "page-39 post-marker retouch"),
    (0x39, 0x67AC, 0x6829, "page-39 template chrome"),
    (0x39, 0x6A27, 0x6A5D, "page-39 descriptor cell loop"),
    (0x39, 0x6A8A, 0x6B20, "page-39 kind-2 fraction UI"),
]

OFFPAGE_DARKLINE_CONTEXT_ANCHORS = [
    (
        0x00,
        0x3555,
        "cd092b254004",
        "RAM trampoline 3555: cross_page_jump inline target 04:4025 (_DarkLine)",
    ),
    (
        0x04,
        0x4025,
        "26011800",
        "_DarkLine entry: set H=1, then tail-jump into _ILine",
    ),
    (
        0x05,
        0x53FD,
        "06004f5f165ecd5535c9",
        "page-5 graph/axis helper: fixed B=0, D=5E, call _DarkLine, return",
    ),
    (
        0x05,
        0x540E,
        "0e0947573e3fcd07545fcd5535c9",
        "page-5 graph/axis helper: derive endpoint through 5407, then call _DarkLine",
    ),
    (
        0x05,
        0x75A5,
        "062f1e080e0050cd55351604fdcb02ce",
        "page-5 graph draw helper: fixed line segment through _DarkLine",
    ),
    (
        0x35,
        0x6887,
        "3ad7863d47570e3f1e39cd5535e1f1c9",
        "page-35 display/window helper: fixed y/x values around 86D7, then _DarkLine",
    ),
    (
        0x39,
        0x4F62,
        "3a4b84878787060b165eed44c63bc5d5cd0f22d1c14f5fcd60203af289f5fdcb02cecd5535",
        "page-39 post-marker retouch: row-derived line after split/window normalization",
    ),
    (
        0x39,
        0x67CE,
        "11fe85d5cd9c1aaf12e3cdf93ce1c1e5501e02cd55350c04593e108057cd553514420d1e02cd553504",
        "page-39 template chrome: tab separator lines through _DarkLine",
    ),
    (
        0x39,
        0x6802,
        "3aee85b7010529110537cc5535",
        "page-39 empty-template cue: 85EE zero/nonzero guard before fixed _DarkLine call",
    ),
]

OFFPAGE_DARKLINE_STATE_WORDS = [
    (0x85DE, "85DE layout class/mode"),
    (0x85E8, "85E8 template kind/state"),
    (0x85EE, "85EE measured fraction columns"),
    (0x85EF, "85EF measured fraction rows"),
    (0x9D27, "9D27 saved measured fraction pair"),
    (0x86D7, "86D7 graph pen x"),
    (0x86D8, "86D8 graph pen y"),
    (0x844B, "844B display row"),
]

OFFPAGE_85EE_CANDIDATE_ANCHORS = [
    (
        0x33,
        0x4F42,
        "fe2b20272aee85cdf61e7cb520012323e52b2911160019e3eb210000011400190b78b120fa424bd119ebc9",
        "page-33 85EE candidate: token/value case 2B loads HL=(85EE), does arithmetic/list offset work, no inline draw primitive",
    ),
    (
        0x34,
        0x4880,
        "200dd521120019ed5bee85722373d1211400190e000c1600cdd54c2013",
        "page-34 85EE candidate A: LD DE,(85EE), store the pair into an object/record field at HL+12",
    ),
    (
        0x34,
        0x4DC8,
        "4456235e23ed53ee85e5ebcdf61ee53e2bcd7354da474e",
        "page-34 85EE candidate B: copy stream word into 85EE, then call evaluator/parser helpers",
    ),
    (
        0x34,
        0x5130,
        "025d28ec21010122ee85e5cd7354dab755010101c5d5cdf554",
        "page-34 85EE candidate C: seed 85EE=0101 before parser/evaluator calls",
    ),
]

OFFPAGE_85EE_CONTEXT_ANCHORS = [
    (
        0x33,
        0x4F23,
        "e5110200197efe2b200e11100019cd3300cdf61eeb13e1c9cd424f5059e1c9",
        "page-33 prologue: inspect record byte +2 for 2B, otherwise call the 4F42 case helper and return BC/DE-style offsets",
    ),
    (
        0x34,
        0x4D65,
        "fdcb208efdcb2dc6fdcb2dd6cd834fcd2248cdfd352af696b7ed5bf496ed5222c48dcd6d402005cdf84f1804afcd0755f5fdcb2d86fdcb2d96cdac49f1c937c9cdc121d25a4eb720067ee61fc35a4efe0c2009cded36da604ec37f4efe0d28f3fe02204456235e23ed53ee85e5ebcdf61ee53e2b",
        "page-34 parser/object switch: save workspace bounds, test OP1 real/type cases, then case 02 copies a stream word into 85EE",
    ),
    (
        0x34,
        0x512F,
        "cd025d28ec21010122ee85e5cd7354dab755010101c5d5cdf5543006d1c39e5038367bb2285d212b00cdbb212831210700ed52204e",
        "page-34 seed path: after a parser/object test, seed 85EE=0101 and enter parser/evaluator loop helpers",
    ),
    (
        0x35,
        0x734B,
        "21020222279dfdcb1a86c9",
        "off-page 9D27 seed: default 0202 measurement during reset/default-state cleanup",
    ),
    (
        0x37,
        0x6D2D,
        "21020222279d3e",
        "off-page 9D27 seed: startup/init writes default 0202 before hardware/display initialization",
    ),
    (
        0x34,
        0x4B18,
        "5e235623c9",
        "page-34 word reader used by object-record walkers: read DE=(HL), advance HL, return",
    ),
    (
        0x34,
        0x5473,
        "f5cda058cd444af1cd62483022f5cdac49cd",
        "page-34 parser wrapper: save A, call local parser/workspace helpers, then restore A and update state",
    ),
]

OFFPAGE_85EE_CANDIDATE_XREF_TARGETS = [
    (0x33, 0x4F25, [], [], "page-33 helper prologue before the 85EE case"),
    (0x33, 0x4F42, [(0x4F3B, "CALL")], [0x4F3C], "page-33 85EE case helper"),
    (0x34, 0x4880, [], [], "page-34 85EE object/record field copy block"),
    (0x34, 0x4DC8, [], [], "page-34 stream-word to 85EE block"),
    (0x34, 0x5130, [], [], "page-34 85EE=0101 seed block"),
]

OFFPAGE_85EE_HELPER_ANCHORS = [
    (
        0x00,
        0x1EF6,
        "442600545cebb7ed5a10fcc9",
        "_HTimesL helper body used by page-33 4F42 to scale the 85EE-derived count",
    ),
    (
        0x00,
        0x21BB,
        "e5b7ed52e1c9",
        "_CpHLDE helper body used by page-34 comparison/object-walk helpers",
    ),
    (
        0x33,
        0x4F3B,
        "cd424f5059e1c9",
        "only direct page-local call into 4F42, then restore/return through caller bookkeeping",
    ),
    (
        0x34,
        0x4DCA,
        "235e23ed53ee85e5ebcdf61ee53e2bcd7354da474e",
        "page-34 local case body: advance stream, copy word to 85EE, call parser/evaluator helpers",
    ),
]

LCD_TALLP_FLOW_ANCHORS = [
    (
        0x04,
        0x42EC,
        "f5e52aa38d2578bc300c79fe403007b72804e1f1b7c9e1f137c9",
        "page-4 _IBounds: compares incoming coordinates against (8DA3) LCD height/bounds state",
    ),
    (
        0x04,
        0x401D,
        "a38d5ff11d500e0126011800f53e01fdcb357ec449352803f1c9",
        "page-4 bounds/setup path: writes or tests generic LCD/graph geometry state, not MathPrint layout",
    ),
    (
        0x05,
        0x756E,
        "a38dc50e3f065fed43a38d21d37546234e78b12819cdd478",
        "page-5 graph helper: compares against lcdTallP around graph-point/line handling",
    ),
    (
        0x06,
        0x4FFC,
        "a38dd60c6f2600cdbb213001ebe1d5e5cd4e542808016000",
        "page-6 UI/helper path: subtracts lcdTallP in app/display positioning code",
    ),
    (
        0x33,
        0x584E,
        "a38dcd7f5cf1c9cd295cc11806cd813c3d20fa78c190cd0c5c",
        "page-33 parser/evaluator-side helper: lcdTallP byte appears without local MathPrint draw state",
    ),
    (
        0x35,
        0x709A,
        "a38dbed0fdcb24662804fe071802fe063fd07821a58dbed0",
        "page-35 display helper: lcdTallP compare in generic UI/display code",
    ),
    (
        0x37,
        0x4ED1,
        "a38dc50e3f065fed43a38d210f4f470e071e04c57e1680cb273005d5cd6735d1",
        "page-37 UI helper: lcdTallP compare before page-1 display service calls",
    ),
    (
        0x38,
        0x51FD,
        "a38d3d91daf4264fc5cd0933c1afef0d51d2f426ed43188d",
        "page-38 graph/coordinate helper: lcdTallP arithmetic around graph state",
    ),
]

LCD_TALLP_WORD = 0x8DA3

LCD_TALLP_MATHPRINT_WORDS = [
    (0x85DE, "layout class/mode"),
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor base/dims"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph pen coordinate pair"),
    (0x9D27, "saved measured fraction pair"),
]

LCD_TALLP_DRAW_PATTERNS = [
    ("CALL 3555 _DarkLine", "cd5535"),
    ("CALL 3B37 display-byte mapper", "cd373b"),
    ("CALL 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL 3CDB VPutMap", "cddb3c"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _FillRect", "ef624d"),
    ("RST28 _FillRectPattern", "ef894d"),
]

PAGE39_TALL_SURFACE_STATE_WORDS = [
    (0x85DE, "layout class/mode"),
    (0x85DF, "layout row/subrow"),
    (0x85E0, "argument/column index"),
    (0x85E1, "row/dimension count"),
    (0x85E2, "argument/cell count"),
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor base/dims"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph pen coordinate pair"),
    (0x9D27, "saved measured fraction pair"),
]

PAGE39_TALL_SURFACE_PATTERNS = [
    ("CALL 3555 _DarkLine", "cd5535"),
    ("CALL 3A53 parser scanner service", "cd533a"),
    ("CALL 306F parser scanner service", "cd6f30"),
    ("CALL 3B37 display-byte mapper", "cd373b"),
    ("CALL 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL 3CDB VPutMap", "cddb3c"),
    ("CALL 4833 graph-window setup", "cd3348"),
    ("CALL 4822 graph-window restore", "cd2248"),
    ("CALL 67A0 geometry draw wrapper", "cda067"),
    ("CALL 683D cell-to-pixel mapper", "cd3d68"),
    ("CALL 6ABF fraction row/rule", "cdbf6a"),
    ("CALL 6AF5 descriptor/fraction box", "cdf56a"),
    ("CALL 6B1C fraction endpoint math", "cd1c6b"),
    ("CALL 6B62 descriptor string loader", "cd626b"),
    ("CALL 6BE7 descriptor width helper", "cde76b"),
    ("RST28 _PutPSB", "efe551"),
    ("RST28 _ClearRect", "ef5c4d"),
    ("RST28 _InvertRect", "ef5f4d"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _FillRect", "ef624d"),
    ("RST28 _FillRectPattern", "ef894d"),
    ("RST28 _KeyToString", "efca45"),
]

PAGE39_TALL_SURFACE_BUCKETS = [
    (0x4850, 0x49A8, "entry predicates/context gates"),
    (0x49A8, 0x4A74, "render entry/draw-pass gates"),
    (0x4A74, 0x4C3F, "token dispatch/class setup"),
    (0x4C40, 0x4D20, "setup/subexpression/raised-row placement"),
    (0x4D21, 0x4F99, "record row/cell emission, glyph mapping, marker retouch"),
    (0x4F9A, 0x5466, "layout action and generic multi-argument window"),
    (0x5466, 0x57AC, "menu/key dispatch and app escape path"),
    (0x57AC, 0x5D2E, "display-state save/restore, saved-OP/list-token paths"),
    (0x5DD1, 0x5E40, "LCD save and two-byte form-table lookup"),
    (0x659D, 0x6621, "display flag helper"),
    (0x6667, 0x66C8, "delimiter pair classifier"),
    (0x66BD, 0x6712, "token peek/fullscreen/glyph helper"),
    (0x6712, 0x679F, "overflow, template-state handoff, measured-pair reload"),
    (0x67A0, 0x685D, "template chrome and cell-to-pixel/current-cell mapper"),
    (0x68AE, 0x69C8, "geometry action dispatcher and kind-2 measured fraction edits"),
    (0x69C8, 0x6BFE, "descriptor/fraction selector, box/rule/string helpers"),
    (0x6C43, 0x6E00, "menu/app-context restore helpers"),
    (0x7280, 0x72A0, "post-eqdisp table/data false-positive"),
]

STATE_WORD_REF_PREFIX_OPS = {
    # Common Z80 little-endian word operands used by this codebase for RAM refs:
    # LD rr,nn / LD HL,(nn) / LD (nn),HL / LD A,(nn) / LD (nn),A,
    # plus ED-prefixed LD rr,(nn) and LD (nn),rr where the byte before nn is
    # the second opcode byte.
    0x01, 0x11, 0x21, 0x31,
    0x2A, 0x22, 0x3A, 0x32,
    0x4B, 0x43, 0x5B, 0x53, 0x6B, 0x63, 0x7B, 0x73,
}

DELIMITER_FLOW_ANCHORS = [
    (
        0x62CB,
        "fc00fc01fc02fc1ffc20fc21fc25fc26fc27fc28",
        "paren/delimiter pair table A: ten fixed two-byte display cells",
    ),
    (
        0x62E2,
        "fea7fea8fea9fc22fc23fc24fc29fc2afc2bfc2c",
        "paren/delimiter pair table B: ten fixed two-byte display cells",
    ),
    (
        0x62F9,
        "fc50fc51fc52fc53fc54fc55fc56fc57fc58fc59",
        "paren/delimiter pair table C: ten fixed two-byte display cells",
    ),
    (
        0x6667,
        "060a7e23ba20037ebbc82310f5c9",
        "fixed pair-table scanner: B=0A entries, compare D/E, return Z on match",
    ),
    (
        0x6675,
        "21e262cd6766281021cb62cd6766280821f962cd676620137b3246847acd373b",
        "delimiter classifier: try three pair tables, then route matched pair through bjump 3B37",
    ),
    (
        0x66A0,
        "cd1a4fd8eff151d7d81806",
        "fallback for non-pair cells: map through 4F1A and emit ordinary large-font glyph",
    ),
    (
        0x66BD,
        "cdbe482804cdca48c03ade85b82001af324b9878c9",
        "peek/match context helper: updates 984B from current 85DE/B context, not draw geometry",
    ),
]

DELIMITER_FLOW_XREF_TARGETS = [0x6667, 0x6675, 0x3B37, 0x4F1A, 0x66BD]

DELIMITER_DISPLAY_MAP_TABLES = [
    (0x62CB, "A", 0x61, "fixed FC delimiter family A -> 6100..6109"),
    (0x62E2, "B", 0x60, "fixed FE/FC delimiter family B -> 6000..6009"),
    (0x62F9, "C", 0xAA, "fixed FC delimiter family C -> AA00..AA09"),
]

DELIMITER_RECORD_FAMILY_CLASSES = [
    (
        0x17,
        0x62C8,
        0x31,
        0x62CB,
        "A",
        0x61,
        "010a31fc00fc01fc02fc1ffc20fc21fc25fc26fc27fc28",
        "delimiter family A handler record",
    ),
    (
        0x18,
        0x62DF,
        0x3F,
        0x62E2,
        "B",
        0x60,
        "010a3ffea7fea8fea9fc22fc23fc24fc29fc2afc2bfc2c",
        "delimiter family B handler record",
    ),
    (
        0x19,
        0x62F6,
        0x52,
        0x62F9,
        "C",
        0xAA,
        "010a52fc50fc51fc52fc53fc54fc55fc56fc57fc58fc59",
        "delimiter family C handler record",
    ),
]

MENU_CELL_FLOW_ANCHORS = [
    (
        0x39,
        0x52DA,
        "fe05c2f8533ae085cd5559cdb648ca6654",
        "internal action 05: load the current argument/menu cell through 5955, then test menu-token context",
    ),
    (
        0x39,
        0x52E5,
        "cdb648ca6654f579fe822007f1322c9dc3a849f1",
        "loaded-cell prefix gate: C=82 stores A in 9D2C and jumps to 49A8 recursive token display",
    ),
    (
        0x39,
        0x52F9,
        "fdcb28662072fdcb4556206ccde36d206757fdcb44562808",
        "post-cell edit/menu guards before fraction/superscript table checks and token emission",
    ),
    (
        0x39,
        0x5373,
        "cd1f5e2809cd265e200e3e9218023e8e905f3246843e56",
        "two-byte token form selector: 6203/63E3 hits rewrite through 8446 and D=56",
    ),
    (
        0x39,
        0x53AD,
        "fefb202b3a4684fec72810fec8201e3e07cd91387828163e08180a3e06cd913878280a3e07efff523e09c39a4f",
        "FB C7/C8 square-marker branch: call RAM stub 3891 with actions 7/8 or 6/7, then restart layout action 09",
    ),
    (
        0x39,
        0x53DA,
        "3efbcddb6dc2b96ccd6654feff20023efecd475d2006fe40c8fe5ac9b7c9",
        "ordinary menu cell path: restore FB prefix, query menu, normalize FF->FE, and return selection state",
    ),
    (
        0x39,
        0x5466,
        "fdcb36762808473e03cdbb2cc078cddb6d21de8528033649c93600",
        "menu display/getkey entry: draw-pass bjump, then either force 85DE=49 or clear 85DE before menu handling",
    ),
    (
        0x39,
        0x6CB9,
        "fe402809cd546d4778fe40200dcd966dcdd56d3e96cd665437c9",
        "post-menu state path: save selected A in B, optionally restore menu/app state, then dispatch or normalize",
    ),
    (
        0x00,
        0x3891,
        "cd092bba7c7d",
        "RAM/page-0 cross-page stub used by FB C7/C8 branch: CALL 2B09; target 7CBA page 7D (masked page 3D)",
    ),
    (
        0x3D,
        0x7CBA,
        "e5c5bfc3aa7bfe0138772846fe05286afe062815fe07280c",
        "square-marker stub target lands in page-3D flash/object dispatcher, selected by action byte A",
    ),
    (
        0x3D,
        0x7CC6,
        "fe05286afe062815fe07280cfe03282c30230101011809780104081803010204",
        "page-3D action decode: action 7 uses BC=0804, action 6 uses BC=0402, then both share 7DC4",
    ),
    (
        0x3D,
        0x7DC4,
        "e5c5cdd945c147a1e1c9",
        "shared page-3D helper: read flash/object bit mask through 45D9, then AND with C",
    ),
]

MENU_CELL_FLOW_XREF_TARGETS = [0x49A8, 0x4F9A, 0x53AD, 0x5421, 0x5466, 0x6CB9]

ACTIVE_CELL_RECURSE_FLOW_ANCHORS = [
    (
        0x52DA,
        "fe05c2f8533ae085cd5559cdb648ca6654",
        "internal action 05: load the selected row/argument cell through 5955, then enter the active-cell gate",
    ),
    (
        0x52E5,
        "cdb648ca6654f579fe822007f1322c9dc3a849f1",
        "active-cell gate: after 54B6/5466, only C=82 stores A to 9D2C and jumps to 49A8",
    ),
    (
        0x49A8,
        "cd6a67cdbd66cdca04cd744a184c",
        "eqdisp_begin recursive token-display entry reached by the C=82 active-cell branch",
    ),
    (
        0x5955,
        "21e285bed0f5cdca4d",
        "selected-cell loader: bounds-check A against 85E2, compute row-cell base via 4DCA",
    ),
    (
        0x595F,
        "7823b72804232310fc7ecdb648200c2a11935f160019e7",
        "selected-cell scanner: skips 2*A bytes and returns the selected D/E cell prefix in C",
    ),
    (
        0x5373,
        "cd1f5e2809cd265e200e3e9218023e8e905f3246843e56",
        "non-82 active-cell continuation: two-byte form tables can rewrite to D=56, not recurse",
    ),
    (
        0x53AD,
        "fefb202b3a4684fec72810fec8201e3e07cd91387828163e08180a3e06cd913878280a3e07efff523e09c39a4f",
        "FB C7/C8 marker continuation: square-marker handling restarts action 09 instead of recursing",
    ),
]

ACTIVE_CELL_RECURSE_XREF_TARGETS = [0x49A8, 0x52DA, 0x52E5, 0x5373, 0x53AD, 0x5955, 0x595F]

ACTIVE_CELL_RECURSE_CHECK_CELLS = [
    (0x00, 0xC8, "fnInt display/name cell"),
    (0xFB, 0xC8, "square-up/template marker"),
    (0xFB, 0xC7, "square-down/template marker"),
    (0x08, 0x42, "fixed Lintegral structural glyph cell"),
    (0xFC, 0x3F, "fixed Lintegral FC-table glyph cell"),
    (0x00, 0x10, "Lroot root/power display cell"),
]

TWO_BYTE_FORM_FLOW_ANCHORS = [
    (
        0x5373,
        "cd1f5e2809cd265e200e3e9218023e8e905f3246843e56",
        "menu/template-cell branch: 6203 hit selects A=8E, 63E3 hit selects A=92, then rewrites D=56",
    ),
    (
        0x5E1F,
        "210362060e180c",
        "eqdisp_lookup_tbl_6203: HL=6203, B=0E, then shared two-byte lookup",
    ),
    (
        0x5E26,
        "21e36306041805",
        "eqdisp_lookup_tbl_63e3: HL=63E3, B=04, then shared two-byte lookup",
    ),
    (
        0x5E2D,
        "21c3630610",
        "third local selector: HL=63C3, B=10, then shared two-byte lookup",
    ),
    (
        0x5E32,
        "ed5b4684577abe2320047bbe7ac82310f4f6017ac9",
        "eqdisp_table_lookup2: compare A plus saved low byte at 8446 against {hi,lo} entries",
    ),
]

TWO_BYTE_FORM_TABLES = [
    (0x6203, 0x0E, "fraction/default rewrite table used by 39:5E1F"),
    (0x63E3, 0x04, "superscript rewrite table used by 39:5E26"),
    (0x63C3, 0x10, "third local two-byte lookup table selected at 39:5E2D"),
]

TWO_BYTE_FORM_CHECK_CELLS = [
    (0xBB, 0x24, "raw fnInt( token"),
    (0xBB, 0x25, "raw nDeriv( token"),
    (0x00, 0xC8, "fnInt template/menu display cell"),
    (0xFB, 0xC8, "fnInt square marker/control cell"),
    (0xFB, 0xC7, "nDeriv/logbase square marker/control cell"),
    (0x08, 0x42, "Lintegral structural glyph candidate"),
    (0x00, 0x10, "Lroot structural glyph candidate"),
    (0x00, 0xC6, "sigma structural glyph candidate"),
]

TWO_BYTE_FORM_XREF_TARGETS = [0x5373, 0x5E1F, 0x5E26, 0x5E2D, 0x5E32, 0x6203, 0x63C3, 0x63E3]

SQUARE_MARKER_FLOW_ANCHORS = [
    (
        0x39,
        0x53AD,
        "fefb202b3a4684fec72810fec8201e3e07cd91387828163e08180a3e06cd913878280a3e07efff523e09c39a4f",
        "page-39 FB C8/C7 branch: test action 7/6 via 3891; on success call bcall 52FF with A=8/7 and restart action 09",
    ),
    (
        0x00,
        0x3891,
        "cd092bba7c7d",
        "page-0 bjump stub: cross_page_jump to page 3D:7CBA",
    ),
    (
        0x3D,
        0x7CBA,
        "e5c5bfc3aa7bfe0138772846fe05286afe062815fe07280c",
        "page-3D wrapper: save HL/BC and enter flash_obj_dispatch action table",
    ),
    (
        0x3D,
        0x7CC6,
        "fe05286afe062815fe07280cfe03282c30230101011809780104081803010204",
        "page-3D action decode: action 7 -> BC=0804, action 6 -> BC=0402, action 2 -> BC=0101",
    ),
    (
        0x3D,
        0x7D5A,
        "d5f5d6084fcd767d79cd697df1d1c9",
        "bit-position helper: subtract 8 from A, preserve OP1 type while locating the byte, mask low three bits",
    ),
    (
        0x3D,
        0x7D76,
        "3a7884f5cd2752f1327884c9",
        "read helper: call page-local byte reader while preserving OP1 type at 8478",
    ),
    (
        0x3D,
        0x7DB2,
        "c5e5cd5a7dcd5d784fcdbc45a1e1c1c9",
        "flash/object bit test: derive mask, read byte, return A & mask",
    ),
    (
        0x3D,
        0x7DC4,
        "e5c5cdd945c147a1e1c9",
        "shared bit-mask helper used by actions 6/7: read byte via 45D9 and AND with C",
    ),
    (
        0x37,
        0x4611,
        "fe07281bfe08281efe062828fe05281dfe04205341c5cd9138f1b9c8d8184c21094c0ea11813",
        "bcall 52FF target: A=7/8/6/5 select page-37 disabled-feature messages before shared update",
    ),
]

CLASS49_FLOW_ANCHORS = [
    (
        0x4FC4,
        "3ade85fe49cac16cfe4878200bfe092807fe40281ec3ae68",
        "layout dispatcher gate: class 49 jumps to 6CC1; class 48 routes non-09/40 actions to geometry 68AE",
    ),
    (
        0x6CB9,
        "fe402809cd546d4778fe40200dcd966dcdd56d3e96cd665437c9",
        "post-menu state path: action 40 can force class 49 through 6D54, then enter shared class-49 dispatch",
    ),
    (
        0x6CC1,
        "78fe40200dcd966dcdd56d3e96cd665437c9fe0c28fafe5a2006fdcb0946280bfe403807fe5a3003c32154",
        "class-49 dispatcher: action 40 restores menu/app state, action 0C returns carry, alphabetic/menu range enters 5421",
    ),
    (
        0x6CEC,
        "feff20043efe183afefe2836fefc2832fefb200b3a4684b73efb20263a4484feef20043ea61816",
        "class-49 token normalizer: remap FF/FE/FC/FB and selected extended bytes before editor bcall 5458",
    ),
    (
        0x6D32,
        "f52a4b8422de8d11e58d21a597cd9e1a3a028a32e88d21000822a597fdcb0d8ef1c9",
        "class-49 state save: preserve display/app state before temporary menu/editor buffer rendering",
    ),
    (
        0x6D54,
        "f521de853649fdcb0d8eef6154fdcb0dce210100224b84211885066f7e23cddb3f10f97ecdf73b2ade8d224b84",
        "force class 49 and editor mode: write 85DE=49, call editor bcall 5461, print buffer bytes from 8518",
    ),
    (
        0x6D96,
        "f521a75e110885018000cd681821e08d11a597cd9e1a3ae48d324e8421dd8dcb562804fdcb44d6",
        "menu/app-state restore: copy page-39 defaults into 8508 and restore display/edit flags",
    ),
    (
        0x6DDB,
        "e521db9ccb7ee1c9",
        "menu/app flag test: check bit 7 of 9CDB and return with flags",
    ),
]

CLASS49_FLOW_XREF_TARGETS = [0x6CC1, 0x6D32, 0x6D54, 0x6D96, 0x6DD5, 0x6DDB, 0x5421, 0x5466]

CLASS49_FLOW_ENTRY_TARGETS = [0x6CB9, 0x6CC1]

CLASS49_FLOW_SERVICE_SITES = [
    (
        0x6D2E,
        "ef5854",
        "RST28 editor/context helper 5458 after class-49 token normalization",
    ),
    (
        0x6D5E,
        "ef6154",
        "RST28 editor service 5461 after forcing 85DE=49",
    ),
    (
        0x6CCE,
        "cd6654",
        "CALL 5466 menu show/get-key helper in action-40 restore path",
    ),
]

CLASS49_FLOW_MEASURED_STATE_WORDS = [
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor pixel base / saved-OP list index"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x9D27, "saved measured fraction pair"),
    (0x86D7, "graph pen coordinate pair"),
]

ROOT_FLOW_ANCHORS = [
    (
        0x5E97,
        "46654d65a05f065f665ff45ff26130603364",
        "handler table span: class 29 -> 6546, class 2A -> 654D, class 31 -> 6433",
    ),
    (
        0x6546,
        "02010062630059",
        "class 29 record: action 62 row with 0059, plus zero-arg action 63 row",
    ),
    (
        0x654D,
        "010c6200100011061f031f081f071f041f011f021f051f091f0c1f",
        "class 2A root/power row: action 62, Lroot/Linverse and 1F-suffixed display cells",
    ),
    (
        0x6433,
        "021201484600100011061f031f0012081f071f041f011f021f051f091f0b1f0c1f0d1f001b001c00130014",
        "class 31 stacked root/power row: action 48 row plus degree-row action 46",
    ),
]

ROOT_FLOW_XREF_TARGETS = [0x6546, 0x654D, 0x6433]

STRUCTURAL_GLYPH_CENSUS_CELLS = [
    (0xFC, 0x3F, "direct Lintegral FC-table large-font cell"),
    (0x08, 0x42, "direct Lintegral large-font cell"),
    (0x00, 0x10, "direct Lroot display cell"),
    (0x00, 0xC6, "Sigma display token / glyph candidate"),
    (0x00, 0xC8, "fnInt display-name cell"),
    (0xFB, 0xC8, "square-up template marker"),
    (0xFB, 0xC7, "square-down template marker"),
]

STRUCTURAL_SYMBOL_FLOW_ANCHORS = [
    (
        0x39,
        0x60F9,
        "030a100a39352cfe7dfe7efe7ffe80fe81fc3cfc3dfc3efc3ffc40fe3afe3bfe3cff3dfe3efe3ffe40fc44fc45fc46fc",
        "class 0D record: row 0 has FC3F=Lintegral and row 2 has xx42 cells through 0842=Lintegral",
    ),
    (
        0x39,
        0x4ECC,
        "cd7566d1d53e01fdcb3676c4bb2c200d7afefd20021600cd666bef0d45d1cd1a4f3804efe551c97a",
        "generic record-cell emitter tail: delimiter classifier, string path, then direct 4F1A glyph fallback",
    ),
    (
        0x39,
        0x6675,
        "21e262cd6766281021cb62cd6766280821f962cd676620137b3246847acd373bcdaf1b2179847223731807cd1a4fd8eff151d7d8",
        "delimiter classifier: three fixed pair tables, matched cells via 3B37, unmatched cells via 4F1A/RST28",
    ),
    (
        0x39,
        0x4F1A,
        "7afefc200b7bfe41301ed63cd8c605c9fefe7b2008fe82300fd67dd8c9fe4220077afe0a3002b7c937c9",
        "direct glyph mapper: only FC3C..40, FE7D..81, and xx42 cells map to fixed large-font codes",
    ),
    (
        0x39,
        0x654D,
        "010c6200100011061f031f081f071f041f011f021f051f091f0c1f",
        "class 2A root/power row: 0010=Lroot plus low-byte E=1F token-string cells",
    ),
    (
        0x39,
        0x6433,
        "021201484600100011061f031f0012081f071f041f011f021f051f091f0b1f0c1f0d1f001b001c00130014",
        "class 31 stacked root/power row: 0010=Lroot plus degree row; row action 48 is record metadata",
    ),
    (
        0x39,
        0x6B66,
        "26017afefb202f7bcb442807fec821b26b2827feca21a96b2820fecb21ad6b2819fed621bf6b2812fed821cb6b280bfed721d76b2804efca45c911f297d5cd2b",
        "generic string selector: selected FB strings or inline _KeyToString for ordinary cells",
    ),
    (
        0x01,
        0x6D10,
        "7afeff2811fefb2804fefc20072602cd313b1817fefe7b280dfe5a3814cdbd6dc8cd373b18052601cd313bcd0267c3b76dfe1f283bfe40384bfe59ca666dfe4020227afe107b201c",
        "page-1 _KeyToString entry: ordinary token/string conversion path used by non-direct cells",
    ),
]

STRUCTURAL_SYMBOL_FLOW_CELLS = [
    (0xFC, 0x3F, "Lintegral direct FC-table structural glyph"),
    (0x08, 0x42, "Lintegral direct xx42 structural glyph"),
    (0x00, 0x10, "Lroot root/power record cell"),
    (0x00, 0xC8, "fnInt display-name cell"),
    (0xFB, 0xC8, "square-up marker/control cell"),
]

STRUCTURAL_SYMBOL_PROVENANCE_CLASSES = (0x08, 0x0D, 0x30)

STRUCTURAL_PIECE_CANDIDATES = [
    (0x08, "Lintegral", "integral symbol candidate"),
    (0x10, "Lroot", "radical symbol candidate"),
    (0xC6, "Sigma", "summation symbol candidate"),
    (0xF5, "MathPrint underscore", "MathPrint 2.53MP underscore candidate"),
    (0xF6, "fraction slash", "MathPrint 2.53MP fraction-slash candidate"),
    (0xF7, "placeholder box", "MathPrint 2.53MP placeholder candidate"),
]

STRUCTURAL_MODELED_BITMAP_PATTERNS = [
    ("fixed Lintegral glyph bytes", "02050404041408"),
    ("fixed Lroot glyph bytes", "07040404140c04"),
    ("fixed Sigma glyph bytes", "1f08040204081f"),
]

STRUCTURAL_STRETCH_PATTERN_HEIGHTS = range(8, 41)

PAGE3F_GLYPH_DUPLICATE_ANCHORS = [
    (
        0x07,
        0x4637,
        "02050404041408",
        "canonical page-7 fixed Lintegral glyph rows at 45FF + 0x08*7",
    ),
    (
        0x3F,
        0x46B7,
        "060205040404140806",
        "page-3F width-prefixed duplicate: width 06, then the same fixed Lintegral rows, followed by next width byte",
    ),
    (
        0x3F,
        0x4690,
        "000011110a0a04060000111515150a060004061f06040006040a110a0a0a0e06",
        "surrounding page-3F glyph-like data records near the duplicate, not executable code bytes",
    ),
]

PAGE3F_GLYPH_DUPLICATE_REF_TARGETS = [
    (0x46B7, "page-3F width-prefixed Lintegral duplicate record"),
    (0x46B8, "page-3F Lintegral duplicate row bytes"),
]

PAGE3F_GLYPH_DUPLICATE_STATE_WORDS = [
    (0x85DE, "layout class/mode"),
    (0x85E8, "template kind/state"),
    (0x85E9, "descriptor base/dims"),
    (0x85EB, "descriptor row height"),
    (0x85EC, "descriptor cell pointer"),
    (0x85EE, "measured fraction columns"),
    (0x85EF, "measured fraction rows"),
    (0x86D7, "graph pen coordinate pair"),
    (0x9D27, "saved measured fraction pair"),
]

PAGE3F_GLYPH_DUPLICATE_DRAW_PATTERNS = [
    ("CALL 3B37 display-byte mapper", "cd373b"),
    ("CALL 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL 3CDB VPutMap", "cddb3c"),
    ("CALL RAM 3555 _DarkLine", "cd5535"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
    ("RST28 _InvertRect", "ef5f4d"),
]

STRUCTURAL_LITERAL_CODE_ANCHORS = [
    (
        0x6D32,
        "f52a4b8422de8d11e58d21a597cd9e1a3a028a32e88d21000822a597fdcb0d8ef1c9",
        "raw 0008 at 6D49 is HL=0008 stored to 97A5 inside class-49 state save, not a glyph cell",
    ),
]

STRUCTURAL_IMMEDIATE_CODES = [
    (0x08, "Lintegral"),
    (0x10, "Lroot"),
    (0xC6, "Sigma"),
    (0xF5, "MathPrint underscore"),
    (0xF6, "fraction slash"),
    (0xF7, "placeholder box"),
]

STRUCTURAL_IMMEDIATE_OPS = {
    0x3E: "LD A,n",
    0x1E: "LD E,n",
    0x16: "LD D,n",
    0x2E: "LD L,n",
    0x06: "LD B,n",
    0x0E: "LD C,n",
}

STRUCTURAL_IMMEDIATE_DRAW_PATTERNS = [
    ("CALL 3B37 display-byte mapper", "cd373b"),
    ("CALL 3B3D large-glyph blitter", "cd3d3b"),
    ("CALL 3CDB VPutMap", "cddb3c"),
    ("CALL RAM 3555 _DarkLine", "cd5535"),
    ("RST28 _PutPSB", "efca45"),
    ("RST28 _DrawRectBorder", "ef7d4d"),
    ("RST28 _EraseRectBorder", "ef864d"),
    ("RST28 _DrawRectBorderClear", "ef8c4d"),
    ("RST28 _InvertRect", "ef5f4d"),
]

STRUCTURAL_IMMEDIATE_EXPECTED_HITS = {
    (0x01, 0x5AE8, "LD B,n", 0x08): "page-1 fixed glyph-copy count near _PutMap/_LoadPattern, not a structural symbol code",
    (0x01, 0x6D5F, "LD A,n", 0x08): "page-1 _KeyToString branch constant near display-byte mapping, not Lintegral output",
    (0x03, 0x68E0, "LD A,n", 0x08): "page-3 UI/display state byte before VPutMap, no MathPrint measured-state input",
    (0x05, 0x54F0, "LD A,n", 0x10): "page-5 graph/UI coordinate constant near VPutMap, not Lroot",
    (0x05, 0x75A7, "LD E,n", 0x08): "page-5 fixed graph line endpoint before _DarkLine, not Lintegral",
    (0x37, 0x4C9A, "LD A,n", 0x10): "page-37 UI/message helper constant near VPutMap, not Lroot",
    (0x39, 0x67E7, "LD A,n", 0x10): "page-39 template-chrome line x-delta constant, not Lroot glyph selection",
    (0x39, 0x6C32, "LD L,n", 0xF5): "unaligned raw 2E F5 bytes inside a CALL operand/PUSH AF cluster near VPutMap",
    (0x3B, 0x5F20, "LD C,n", 0xC6): "page-3B display helper coordinate/count constant near VPutMap, not Sigma",
}

STRUCTURAL_IMMEDIATE_CONTEXT_ANCHORS = [
    (
        0x01,
        0x5ADC,
        "cd895acdc92078cdc30cd3100608af052805dd7e00dd2304cb27fdcb055e2835ee3ef53a",
        "page-1 5AE8 context: B=08 is an eight-byte copy/count constant around fixed glyph service plumbing",
    ),
    (
        0x01,
        0x6D50,
        "20227afe107b201c214d6ffdcb354e3e08c41f3e18517afe0038043e611813",
        "page-1 6D5F context: A=08 is in _KeyToString/display-byte branch logic, not an emitted Lintegral code",
    ),
    (
        0x03,
        0x68D8,
        "46cd0369fdcb32fe3e0832729b237ecddb3c380210f7fdcb32befdcb3296fdcb",
        "page-3 68E0 context: A=08 stores to 9B72 before a generic VPutMap path",
    ),
    (
        0x05,
        0x54E8,
        "cdb73cb7c92115403e10fdcb354ec41f3ecd853e18ed3a9a85fe4a200d",
        "page-5 54F0 context: A=10 is graph/UI arithmetic near VPutMap, not a root glyph selector",
    ),
    (
        0x05,
        0x75A0,
        "107ab7280c062f1e080e0050cd55351604fdcb02ce6206000e09162f59",
        "page-5 75A7 context: E=08 is a fixed _DarkLine endpoint in graph drawing",
    ),
    (
        0x37,
        0x4C94,
        "9ec93e5f18023e10f5e5cd504ce1f19038031fb7c9afc9fdcb05ce",
        "page-37 4C9A context: A=10 is a UI/message helper constant, not root glyph output",
    ),
    (
        0x39,
        0x67DC,
        "c1e5501e02cd55350c04593e108057cd553514420d1e02cd553504e1ed5bd786f15ff13d20c23aee85",
        "page-39 67E7 context: A=10 is added into D for template chrome line coordinates before _DarkLine",
    ),
    (
        0x39,
        0x6C28,
        "5dcd973bc93e46c9cd472ef53a9a85fe402804f1c31131f1c3d32c",
        "page-39 6C32 context: raw 2E F5 is unaligned inside CALL 2E47 / PUSH AF bytes",
    ),
    (
        0x3B,
        0x5F18,
        "329a81cd8f5ffdcb0ec6b7c17832fd89e122d786c9f5c5d5e53a79813c473ad786f5903019ed4447fe04",
        "page-3B 5F20 context: C=C6 is in fixed display helper arithmetic before VPutMap",
    ),
]

STRUCTURAL_RECORD_PLACEMENT_ANCHORS = [
    (
        0x39,
        0x60F9,
        "030a100a39352cfe7dfe7efe7ffe80fe81fc3cfc3dfc3efc3ffc40fe3afe3bfe3cff3dfe3efe3ffe40fc44fc45fc46fc92fc93fe2dfe2efe2ffe300042014202420342044205420642074208420942",
        "class 0D fixed record: NAMES/MATH/EDIT rows, with FC3F and 0842 both mapping to Lintegral",
    ),
    (
        0x39,
        0x4DE6,
        "3a4a98324b84cd0a4e56235e23e5c5cd8e4ec1e10c3ae285b9c8d83a4b84fe07c83c",
        "record-row cell stream: restore row baseline 984A, emit gutter, then each two-byte cell through 4E8E",
    ),
    (
        0x39,
        0x4DFA,
        "0c3ae285b9c8d83a4b84fe07c83c18df97324c84",
        "row-cell loop tail: increment slot, stop at 85E2 or row 7, otherwise increment display row 844B",
    ),
    (
        0x39,
        0x4F1A,
        "7afefc200b7bfe41301ed63cd8c605c9fefe7b2008fe82300fd67dd8c9fe4220077afe0a30",
        "direct glyph mapper: FC3C..40 and xx42 cells become fixed large-font glyph codes",
    ),
    (
        0x07,
        0x4637,
        "02050404041408",
        "page-7 fixed Lintegral glyph bytes at 45FF + 0x08*7",
    ),
    (
        0x07,
        0x466F,
        "07040404140c04",
        "page-7 fixed Lroot glyph bytes at 45FF + 0x10*7",
    ),
]

STRUCTURAL_RECORD_PLACEMENT_ACTIONS = (0x39, 0x35, 0x2C)


def romoff(page, addr):
    return page * 0x4000 + (addr - 0x4000)


def word(rom, page, addr):
    o = romoff(page, addr)
    return rom[o] | (rom[o + 1] << 8)


def token_name(d, e):
    names = {
        (0x00, 0xC7): "nDeriv(",
        (0x00, 0xC8): "fnInt(",
        (0xFB, 0xC7): "sqDown/template marker",
        (0xFB, 0xC8): "sqUp/template marker",
        (0xFB, 0xCA): "n/d menu string",
        (0xFB, 0xCB): "Un/d menu string",
        (0xFB, 0xD6): "AUTO Answer string",
        (0xFB, 0xD7): "DEC Answer string",
        (0xFB, 0xD8): "FRAC Answer string",
    }
    return names.get((d, e), "")


def page_indexed_string(rom, index):
    ptr = word(rom, 0x01, PAGE1_INDEXED_STRING_TABLE + 2 * index)
    o = romoff(0x01, ptr)
    n = rom[o]
    raw = rom[o + 1:o + 1 + n]
    text = "".join(chr(b) if 32 <= b < 127 else f"\\x{b:02X}" for b in raw)
    return ptr, text


def fmt_cell(d, e):
    label = token_name(d, e)
    return f"{d:02X}{e:02X}" + (f"={label}" if label else "")


def parse_handler_record(rom, cls):
    table = romoff(PAGE, HANDLER_TABLE)
    ptr = rom[table + 2 * cls] | (rom[table + 2 * cls + 1] << 8)
    if not 0x4000 <= ptr < 0x8000:
        return ptr, None

    o = romoff(PAGE, ptr)
    rows = rom[o]
    if rows == 0 or rows > 16:
        return ptr, None

    counts = list(rom[o + 1:o + 1 + rows])
    actions = list(rom[o + 1 + rows:o + 1 + 2 * rows])
    tbase = o + 1 + 2 * rows
    parsed = []
    pos = 0
    for row, (count, action) in enumerate(zip(counts, actions)):
        cells = []
        for i in range(count):
            d = rom[tbase + 2 * (pos + i)]
            e = rom[tbase + 2 * (pos + i) + 1]
            cells.append((d, e))
        parsed.append({"row": row, "count": count, "action": action, "cells": cells})
        pos += count
    return ptr, {"rows": rows, "items": parsed}


def dump_handler_records(rom, only_class=None):
    for cls in range(HANDLER_COUNT):
        if only_class is not None and cls != only_class:
            continue
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            if 0x4000 <= ptr < 0x8000:
                print(f"class {cls:02X}: ptr {ptr:04X} (not a decoded record)")
            else:
                print(f"class {cls:02X}: ptr {ptr:04X} (outside page)")
            continue

        print(f"class {cls:02X}: ptr {ptr:04X} rows={record['rows']}")
        for item in record["items"]:
            cells = [fmt_cell(d, e) for d, e in item["cells"]]
            print(
                f"  row {item['row']}: count={item['count']:02X} "
                f"action={item['action']:02X} {' '.join(cells)}"
            )


def parse_descriptors(rom):
    descriptors = []
    for addr in DESCRIPTORS:
        p = addr
        base = word(rom, PAGE, p)
        p += 2
        box = word(rom, PAGE, p)
        p += 2
        row_height = rom[romoff(PAGE, p)]
        p += 1
        dims = word(rom, PAGE, p)
        p += 2
        cols = dims >> 8
        rows = dims & 0xFF
        cells_ptr = word(rom, PAGE, p)
        cells = []
        for i in range(cols * rows):
            d = rom[romoff(PAGE, cells_ptr + 2 * i)]
            e = rom[romoff(PAGE, cells_ptr + 2 * i + 1)]
            cells.append((d, e))
        descriptors.append(
            {
                "addr": addr,
                "base": base,
                "box": box,
                "row_height": row_height,
                "cols": cols,
                "rows": rows,
                "cells_ptr": cells_ptr,
                "cells": cells,
            }
        )
    return descriptors


def dump_descriptors(rom):
    for desc in parse_descriptors(rom):
        cells = [fmt_cell(d, e) for d, e in desc["cells"]]
        print(
            f"desc {desc['addr']:04X}: base={desc['base']:04X} "
            f"box={desc['box']:04X} row_h={desc['row_height']:02X} "
            f"cols={desc['cols']} rows={desc['rows']} "
            f"cells={desc['cells_ptr']:04X}"
        )
        print("  " + " ".join(cells))


def kind_path(kind):
    nibble = kind & 0x0F
    if nibble == 0:
        return "descriptor 686F"
    if nibble == 1:
        return "descriptor 6880"
    if nibble == 2:
        return "fraction special path 6A8A"
    # Mirrors the 69C8 descriptor cascade: the exact branch is encoded by the
    # ROM helpers at 025E/0254, but these are the possible descriptor families.
    return "descriptor family 689C/68A5/6893"


def action_kind(action):
    return TEMPLATE_ACTIONS.get(action)


def parse_cell(s):
    text = s.replace(":", "").replace(",", "").strip()
    if len(text) != 4:
        raise argparse.ArgumentTypeError("cell must be two bytes, e.g. 00C8 or FB:C8")
    try:
        value = int(text, 16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cell must be hexadecimal") from exc
    return value >> 8, value & 0xFF


def find_cell(rom, target):
    td, te = target
    found = False
    print(f"searching page-39 decoded records/descriptors for {fmt_cell(td, te)}")
    for cls in range(HANDLER_COUNT):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            continue
        for item in record["items"]:
            for idx, (d, e) in enumerate(item["cells"]):
                if (d, e) == target:
                    found = True
                    print(
                        f"  class {cls:02X} ptr {ptr:04X} "
                        f"row {item['row']} cell {idx}"
                    )

    for desc in parse_descriptors(rom):
        for idx, (d, e) in enumerate(desc["cells"]):
            if (d, e) == target:
                found = True
                print(
                    f"  desc {desc['addr']:04X} cells {desc['cells_ptr']:04X} "
                    f"cell {idx}"
                )

    if not found:
        print("  no decoded record/descriptor hits")


def find_action(rom, target):
    found = False
    print(f"searching page-39 decoded records for row action {target:02X}")
    for cls in range(HANDLER_COUNT):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            continue
        for item in record["items"]:
            if item["action"] != target:
                continue
            found = True
            kind = action_kind(target)
            suffix = f" -> kind {kind:02X} ({kind_path(kind)})" if kind else ""
            cells = " ".join(fmt_cell(d, e) for d, e in item["cells"])
            print(
                f"  class {cls:02X} ptr {ptr:04X} row {item['row']} "
                f"count={item['count']:02X}{suffix} {cells}"
            )
    if not found:
        print("  no decoded record hits")


def dump_template_actions(rom):
    for action, kind in TEMPLATE_ACTIONS.items():
        print(f"action {action:02X} -> kind {kind:02X} ({kind_path(kind)})")
        any_hit = False
        for cls in range(HANDLER_COUNT):
            ptr, record = parse_handler_record(rom, cls)
            if record is None:
                continue
            for item in record["items"]:
                if item["action"] != action:
                    continue
                any_hit = True
                cells = " ".join(fmt_cell(d, e) for d, e in item["cells"])
                print(
                    f"  class {cls:02X} ptr {ptr:04X} row {item['row']} "
                    f"count={item['count']:02X} {cells}"
                )
        if not any_hit:
            print("  no decoded record hits")


def token_class(raw):
    """Model eqdisp_dispatch_token's coarse class for single-byte tokens only.

    Two-byte TI tokens such as BB 24 (tFnInt) are normalized before this page-39
    class byte is used, so this helper is intentionally limited to the simple
    `A - 0x2A` path visible at 39:4A74.
    """
    if raw == 0x3D:
        return "special 39:672E"
    cls = raw - 0x2A
    if not 0 <= cls <= 0xFF:
        return "outside coarse single-byte range"
    return f"class {cls:02X}"


def dispatch_context_class(raw, iy2=0xFF, iy9=0x00):
    if raw == 0x3D:
        return None, "special 672E handoff"
    cls = (raw - 0x2A) & 0xFF
    notes = [f"A-2A -> {cls:02X}"]
    if cls == 0x11 and (iy2 & 0x10) == 0:
        cls = (raw - 1) & 0xFF
        notes.append("IY+2 bit4 reset: class=raw-1")
        if (iy2 & 0x40) == 0:
            cls = (cls + 1) & 0xFF
            notes.append("IY+2 bit6 reset: increment")
            if (iy2 & 0x20) == 0:
                cls = (cls + 1) & 0xFF
                notes.append("IY+2 bit5 reset: increment")
    if (iy9 & 0x01) != 0 and cls in (0x03, 0x04, 0x05, 0x06, 0x07, 0x08):
        cls = (cls + 0x28) & 0xFF
        notes.append("IY+9 bit0 set: classes 03..08 add 28")
    return cls, "; ".join(notes)


def dump_dispatch_context_flow(rom):
    print("dispatch context class-flow ROM anchors")
    for addr, hex_bytes, note in DISPATCH_CONTEXT_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontext-sensitive class samples")
    for raw, iy2, iy9, note in DISPATCH_CONTEXT_SAMPLES:
        cls, rule = dispatch_context_class(raw, iy2, iy9)
        print(f"  raw {raw:02X}, IY+2={iy2:02X}, IY+9={iy9:02X}: {note}")
        if cls is None:
            print(f"    result: {rule}")
            continue
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            print(f"    result: class {cls:02X}; handler ptr {ptr:04X}; record: none")
            continue
        row_summary = ", ".join(
            f"row {item['row']} count={item['count']:02X} action={item['action']:02X}"
            for item in record["items"]
        )
        print(f"    result: class {cls:02X}; {rule}")
        print(f"    handler: 5E45+2*{cls:02X} -> {ptr:04X}; {row_summary}")

    print("\ninterpretation")
    print("  4A74 is the page-39 token/action-to-layout-class algorithm before handler-table lookup")
    print("  raw 3D never becomes an 85DE class; it jumps to the measured-template handoff at 672E")
    print("  raw 3B is the exponent-context special case controlled by IY+2 bits 4/6/5")
    print("  active fraction/argument context maps ordinary classes 03..08 to stacked classes 2B..30")
    print("  this recovers the pre-template class selection step; it is upstream of final tall-symbol pixel placement")


def explain_token(raw):
    print(f"raw byte {raw:02X} -> {token_class(raw)}")
    print("notes:")
    print("  - page-39 handler records use normalized class bytes in 0x85DE")
    print("  - display cells like 00C8 are menu/name cells, not raw TI tokens")
    print("  - tFnInt is the two-byte parser token BB 24; it is not a 00C8 cell")


def control_refs(rom, target):
    start = romoff(PAGE, 0x4000)
    end = romoff(PAGE, 0x8000)
    lo = target & 0xFF
    hi = target >> 8

    direct = []
    for o in range(start, end - 2):
        if rom[o] in CONTROL_FLOW_OPS and rom[o + 1] == lo and rom[o + 2] == hi:
            direct.append((0x4000 + o - start, CONTROL_FLOW_OPS[rom[o]]))
    words = []
    for o in range(start, end - 1):
        if rom[o] == lo and rom[o + 1] == hi:
            words.append(0x4000 + o - start)
    return direct, words


def control_refs_on_page(rom, page, target):
    start = romoff(page, 0x4000)
    end = romoff(page, 0x8000)
    lo = target & 0xFF
    hi = target >> 8

    direct = []
    for o in range(start, end - 2):
        if rom[o] in CONTROL_FLOW_OPS and rom[o + 1] == lo and rom[o + 2] == hi:
            direct.append((0x4000 + o - start, CONTROL_FLOW_OPS[rom[o]]))
    words = []
    for o in range(start, end - 1):
        if rom[o] == lo and rom[o + 1] == hi:
            words.append(0x4000 + o - start)
    return direct, words


def page_word_refs(rom, page, target):
    start = romoff(page, 0x4000)
    end = romoff(page, 0x8000)
    lo = target & 0xFF
    hi = target >> 8
    refs = []
    for o in range(start, end - 1):
        if rom[o] == lo and rom[o + 1] == hi:
            refs.append(0x4000 + o - start)
    return refs


def rom_pattern_hits(rom, pattern):
    hits = []
    end = len(rom) - len(pattern) + 1
    for o in range(end):
        if rom[o : o + len(pattern)] == pattern:
            hits.append((o // 0x4000, 0x4000 + (o % 0x4000)))
    return hits


def page_count_summary(hits):
    counts = {}
    for page, _addr in hits:
        counts[page] = counts.get(page, 0) + 1
    return " ".join(f"{page:02X}({count})" for page, count in sorted(counts.items())) or "none"


def page_word_ref_map(rom, words):
    out = {}
    for target, label in words:
        for page in range(len(rom) // 0x4000):
            refs = state_word_refs_on_page(rom, page, target)
            if not refs:
                continue
            out.setdefault(page, []).append((label, target, refs))
    return out


def state_word_refs_on_page(rom, page, target):
    refs = []
    for addr in page_word_refs(rom, page, target):
        off = romoff(page, addr)
        prev = rom[off - 1] if off > 0 else 0
        if prev not in STATE_WORD_REF_PREFIX_OPS:
            continue
        refs.append(addr)
    return refs


def page_pattern_ref_map(rom, patterns):
    out = {}
    for label, hex_bytes in patterns:
        for page, addr in rom_pattern_hits(rom, bytes.fromhex(hex_bytes)):
            out.setdefault(page, []).append((label, addr))
    return out


def page_pattern_hits_in_range(rom, page, lo_addr, hi_addr, patterns):
    hits = []
    lo = max(0x4000, lo_addr)
    hi = min(0x8000, hi_addr)
    for label, hex_bytes in patterns:
        pattern = bytes.fromhex(hex_bytes)
        start = romoff(page, lo)
        end = romoff(page, hi)
        o = start
        while True:
            found = rom.find(pattern, o, end)
            if found < 0:
                break
            hits.append((label, 0x4000 + (found % 0x4000)))
            o = found + 1
    return sorted(hits, key=lambda item: item[1])


def xrefs(rom, target):
    """Find simple page-local references to a page-0x39 address/word."""
    print(f"xrefs to {target:04X} on page {PAGE:02X}")
    direct, words = control_refs(rom, target)
    if direct:
        print("  direct control-flow:")
        for addr, op in direct:
            print(f"    {addr:04X}: {op}")
    else:
        print("  direct control-flow: none")

    if words:
        print("  immediate/raw word refs:")
        print("    " + " ".join(f"{addr:04X}" for addr in words))
    else:
        print("  immediate/raw word refs: none")


def rom_bytes(rom, addr, size):
    o = romoff(PAGE, addr)
    return rom[o:o + size]


def rom_bytes_at(rom, page, addr, size):
    o = romoff(page, addr)
    return rom[o:o + size]


def rom_bytes_banked(rom, page, addr, size):
    o = page * 0x4000 + (addr & 0x3FFF)
    return rom[o:o + size]


def dump_operand_flow(rom):
    print("operand/template-emission ROM anchors")
    for addr, hex_bytes, note in OPERAND_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in OPERAND_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ndisplay/cursor bjumps under the multi-argument walker")
    for page, addr, hex_bytes, note in OPERAND_DISPLAY_BJUMP_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 display/cursor bjump xrefs")
    for target in OPERAND_DISPLAY_BJUMP_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  5167 uses 3C81/3C93 for cursor/scroll recovery while walking argument slots")
    print("  those fixed-bank targets land in page-1 display-row helpers, not in page-39 template construction")
    print("  4E0A/6712 ultimately emit ordinary characters through _PutC at page 01:5B4C")

    print("\nfnInt/nDeriv record rows")
    for cls in (0x08, 0x30):
        ptr, record = parse_handler_record(rom, cls)
        print(f"  class {cls:02X} ptr {ptr:04X} rows={record['rows']}")
        for item in record["items"]:
            cells = " ".join(fmt_cell(d, e) for d, e in item["cells"])
            print(
                f"    row {item['row']} count={item['count']:02X} "
                f"action={item['action']:02X} {cells}"
            )


def arg_row_step(cls, slot):
    if cls == 0x06 and slot <= 2:
        return 2
    return 1


def dump_multiarg_placement_flow(rom):
    print("multi-argument placement ROM anchors")
    for addr, hex_bytes, note in MULTIARG_PLACEMENT_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in MULTIARG_PLACEMENT_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nrow-step examples from 5949")
    for cls in (0x06, 0x08, 0x30):
        steps = " ".join(f"slot{slot}:{arg_row_step(cls, slot)}" for slot in range(5))
        ptr, record = parse_handler_record(rom, cls)
        label = f"class {cls:02X} ptr {ptr:04X}"
        if record is not None:
            label += f" rows={record['rows']}"
        print(f"  {label}: {steps}")

    print("\ninterpretation")
    print("  raw Ghidra names 5167 as eqdisp_layout_multiarg and 4C5A/4CA4 as subexpression emit helpers")
    print("  5949 is the row-step classifier: class 06 slots 0..2 consume two display rows; all other tested slots consume one")
    print("  forward placement emits the previous slot index, advances 844B by that one/two-row step, emits the current slot index, then emits saved-E7")
    print("  reverse placement mirrors that by emitting the next slot index, subtracting the one/two-row step from 844B, then emitting saved-E7 as a variable")
    print("  action 08 advances the visible argument window; action 07 backs/remaps it through the 50CF/5101 clamp")
    print("  action 03 jumps to the last visible argument for eight-or-more-argument forms and emits it on row 7")
    print("  action 04 repeatedly calls 5167 until the current slot reaches the final argument")
    print("  saved-OP direct slot actions write 85E0 and render operands until the visible row index 844B reaches that slot")
    print("  this identifies 5167 as the shared row compositor; fnInt field identity is covered by --fnint-argument-order-flow")


def dump_saved_op_flow(rom):
    print("saved-OP/list-token ROM anchors")
    for addr, hex_bytes, note in SAVED_OP_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in SAVED_OP_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")


def dump_record_flow(rom):
    print("handler-record emission ROM anchors")
    for addr, hex_bytes, note in RECORD_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in RECORD_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nfnInt/nDeriv row actions")
    for action in FNINT_ROW_ACTIONS:
        print(f"  action {action:02X}")
        for cls in range(HANDLER_COUNT):
            ptr, record = parse_handler_record(rom, cls)
            if record is None:
                continue
            for item in record["items"]:
                if item["action"] != action:
                    continue
                cells = " ".join(fmt_cell(d, e) for d, e in item["cells"])
                print(
                    f"    class {cls:02X} ptr {ptr:04X} row {item['row']} "
                    f"count={item['count']:02X} {cells}"
                )


def record_row_cell_base(ptr, record, row):
    return ptr + 1 + 2 * record["rows"] + 2 * sum(
        item["count"] for item in record["items"][:row]
    )


def record_stream_label(cls, row, slot):
    if slot < 9:
        return slot + 0x31
    if slot == 9:
        return 0x30
    if cls in (0x03, 0x29, 0x02):
        return 0x20
    if cls == 0x10 and row == 0:
        return 0x20
    if cls == 0x2B and row == 2:
        return 0x20
    if slot == 0x24:
        return 0x5B
    if slot >= 0x24:
        return 0x20
    return slot + 0x37


def record_stream_separator(slot, baseline_row, current_row, arg_count):
    if current_row == baseline_row:
        return 0x3A if slot == 0 else 0x1E
    if current_row == 7:
        last = arg_count - 1
        if slot == last or slot > last:
            return 0x3A
        return 0x1F
    return 0x3A


def printable_code(code):
    if 0x20 <= code < 0x7F:
        return f"{code:02X} '{chr(code)}'"
    return f"{code:02X}"


def dump_record_cell_stream_flow(rom):
    print("record-cell stream/gutter ROM anchors")
    for addr, hex_bytes, note in RECORD_CELL_STREAM_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow xrefs")
    for target in RECORD_CELL_STREAM_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nrow cell bases")
    for cls in (0x08, 0x0D, 0x2A, 0x31):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            continue
        print(f"  class {cls:02X} ptr {ptr:04X}")
        for item in record["items"]:
            base = record_row_cell_base(ptr, record, item["row"])
            end = base + 2 * item["count"]
            print(
                f"    row {item['row']} action={item['action']:02X} "
                f"count={item['count']:02X} cells {base:04X}..{end:04X}"
            )

    print("\n4E0A gutter examples")
    examples = [
        (0x08, 0, 0, 1, 1, 0x0C, "first fnInt/nDeriv MATH-row slot"),
        (0x08, 0, 8, 1, 1, 0x0C, "fnInt display cell slot"),
        (0x08, 0, 9, 1, 1, 0x0C, "square-up marker slot"),
        (0x0D, 0, 8, 1, 1, 0x0A, "direct Lintegral row-0 glyph slot"),
        (0x0D, 2, 8, 1, 3, 0x0A, "direct Lintegral row-2 glyph slot on later row"),
        (0x31, 0, 0, 1, 1, 0x12, "stacked root/power Lroot slot"),
        (0x08, 0, 10, 1, 7, 0x0C, "row-7 continuation separator before final slot"),
        (0x08, 0, 11, 1, 7, 0x0C, "row-7 final-slot separator"),
    ]
    for cls, row, slot, baseline, current, arg_count, note in examples:
        label = record_stream_label(cls, row, slot)
        sep = record_stream_separator(slot, baseline, current, arg_count)
        print(
            f"  class {cls:02X} row {row} slot {slot:02X}: "
            f"label {printable_code(label)}, sep {printable_code(sep)}  {note}"
        )

    print("\ninterpretation")
    print("  4DCA implements the handler-record formula: cells start after row_count, arg_count[], and row_action[]")
    print("  4DE6 emits each visible slot as: gutter label/separator via 4E0A, then the two-byte D:E cell via 4E8E")
    print("  4E0A is fixed UI gutter/separator logic driven by class, row, slot, baseline row, and argument count")
    print("  it does not inspect glyph bitmap data, measured radicand height, or template descriptor dimensions")
    print("  the pre-cell record stream is therefore closed through row labels, slot gutters, and fixed display cells")


def dump_argument_gutter_caller_flow(rom):
    print("argument-gutter caller closure ROM anchors")
    for addr, hex_bytes, note in ARG_GUTTER_CALLER_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\n4E0A direct caller closure")
    direct, words = control_refs(rom, 0x4E0A)
    direct_map = {addr: op for addr, op in direct}
    for addr, note in sorted(ARG_GUTTER_CALLER_EXPECTED.items()):
        op = direct_map.get(addr)
        status = op if op is not None else "MISSING"
        print(f"  39:{addr:04X}: {status}  {note}")
    unexpected = sorted(set(direct_map) - set(ARG_GUTTER_CALLER_EXPECTED))
    print("  unexpected direct 4E0A callers: " + (" ".join(f"{addr:04X}" for addr in unexpected) or "none"))
    raw_unexpected = sorted(set(words) - {addr + 1 for addr in ARG_GUTTER_CALLER_EXPECTED})
    print("  unexpected raw 4E0A word refs: " + (" ".join(f"{addr:04X}" for addr in raw_unexpected) or "none"))

    print("\n4E14 highlighted-entry caller closure")
    direct, words = control_refs(rom, 0x4E14)
    direct_map = {addr: op for addr, op in direct}
    for addr, note in sorted(ARG_GUTTER_MID_ENTRY_EXPECTED.items()):
        op = direct_map.get(addr)
        status = op if op is not None else "MISSING"
        print(f"  39:{addr:04X}: {status}  {note}")
    unexpected = sorted(set(direct_map) - set(ARG_GUTTER_MID_ENTRY_EXPECTED))
    print("  unexpected direct 4E14 callers: " + (" ".join(f"{addr:04X}" for addr in unexpected) or "none"))
    raw_unexpected = sorted(set(words) - {addr + 1 for addr in ARG_GUTTER_MID_ENTRY_EXPECTED})
    print("  unexpected raw 4E14 word refs: " + (" ".join(f"{addr:04X}" for addr in raw_unexpected) or "none"))

    print("\nclassified caller paths")
    print("  4DEC is the record-cell stream already closed by --record-cell-stream-flow")
    print("  51A6/51CE/51DD are forward multi-argument slot gutters around saved normal operands")
    print("  5261/528B/529C are reverse multi-argument slot gutters around saved variable operands")
    print("  5236 is the action-03 row-7 highlighted current-slot gutter path")
    print("  5B46 is the saved-operand tail gutter before optional OP restore and string/control emission")
    print("  6712 overflow markers are separate ':' output through 3FDB and do not call 4E0A")

    print("\ninterpretation")
    print("  every page-39 caller of the 4E0A gutter routine is now classified")
    print("  all callers emit slot labels/separators around fixed record cells or generic operand recursion")
    print("  none is a measured tall-symbol builder, glyph bitmap loop, or descriptor-height consumer")
    print("  this closes the 4E0A argument-gutter boundary; remaining tall placement must be earlier than operand recursion or dynamic")


def dump_row_action_flow(rom):
    print("row-action versus internal-action ROM anchors")
    for addr, hex_bytes, note in ROW_ACTION_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in ROW_ACTION_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ndecoded records whose row_action byte is also a geometry action byte")
    for action, kind in TEMPLATE_ACTIONS.items():
        print(f"  row_action {action:02X}; geometry kind {kind:02X} only after 85DE=48")
        found = False
        for cls in range(HANDLER_COUNT):
            ptr, record = parse_handler_record(rom, cls)
            if record is None:
                continue
            for item in record["items"]:
                if item["action"] != action:
                    continue
                found = True
                cells = " ".join(fmt_cell(d, e) for d, e in item["cells"])
                print(
                    f"    class {cls:02X} ptr {ptr:04X} row {item['row']} "
                    f"count={item['count']:02X} {cells}"
                )
        if not found:
            print("    none")

    print("\ninterpretation")
    print("  4D92 reads row_action bytes from handler records and sends them to bjump 3B2B as row labels")
    print("  4DCA skips the row_count, arg_count, and row_action arrays before locating display-cell payloads")
    print("  4DE6 emits only the display-cell payloads through 4E8E")
    print("  4F9A saves the incoming action byte in B; it does not read row_action from the current record")
    print("  68AE maps 49/48/2E/5A to geometry kinds only after 6761 has forced 85DE to 48")


def dump_setup_flow(rom):
    print("template/setup-state ROM anchors")
    for addr, hex_bytes, note in SETUP_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in SETUP_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")


def dump_row_placement_flow(rom):
    print("row-placement/render-loop ROM anchors")
    for addr, hex_bytes, note in ROW_PLACEMENT_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in ROW_PLACEMENT_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nraised-row decoded classes")
    for cls in ROW_PLACEMENT_CLASSES:
        ptr, record = parse_handler_record(rom, cls)
        print(f"  class {cls:02X} ptr {ptr:04X} rows={record['rows']}")
        for item in record["items"]:
            cells = " ".join(fmt_cell(d, e) for d, e in item["cells"])
            print(
                f"    row {item['row']} count={item['count']:02X} "
                f"action={item['action']:02X} {cells}"
            )

    print("\ninterpretation")
    print("  4CE9 is the only page-39 helper that forces raised display rows for classes 24..28 and 39")
    print("  classes 24..27 render on row 4, class 28 renders on row 3, and class 39 renders on row 4")
    print("  the helper emits indexed strings through 3B2B; it does not walk descriptors, measure operands, or draw tall symbols")
    print("  4A02 calls this helper after 4C40 and before the 4A18/4A28 render/action loop")


def dump_layout_flow(rom):
    print("layout-action dispatch ROM anchors")
    for addr, hex_bytes, note in LAYOUT_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in LAYOUT_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")


def dump_emit_boundary_flow(rom):
    print("expression-emitter boundary ROM anchors")
    for addr, hex_bytes, note in EMIT_BOUNDARY_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in EMIT_BOUNDARY_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  4C40/4CB7 is record-cell emission; 4CDF/4CE4 enters saved-OP or named-argument emission")
    print("  59D0/59E0/59F9 are operand parser-token emitters, not tall-symbol draw routines")
    print("  6ABF/6B1C are directly referenced only by the kind-2 fraction path")


def dump_operand_service_flow(rom):
    print("operand parser-service boundary ROM anchors")
    for page, addr, hex_bytes, note in OPERAND_SERVICE_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-7 scanner/caller context")
    for addr, hex_bytes, note in OPERAND_SERVICE_SCANNER_CONTEXT_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, 0x07, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  07:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-local control-flow xrefs")
    for page, target in OPERAND_SERVICE_XREF_TARGETS:
        direct, words = control_refs_on_page(rom, page, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {page:02X}:{target:04X}: direct {refs}; raw {raw}")

    print("\nfixed-bank service identities from raw Ghidra HTTP")
    print("  ram:3A53 is a cross_page_jump to page_07:50B5")
    print("  ram:306F is a cross_page_jump to page_07:50B8")
    print("  ram:3F27 and ram:3C69 use the same cross-page stub form")

    print("\ninterpretation")
    print("  page-39 59E0/59F9 do not draw; they cross into page-7 parser/expression scanning services")
    print("  page-7 50B5/50B8 walks expression pointers such as 982E/9830 and scratch values 8480/8496")
    print("  the same page-7 scanner has evaluator/parser callers at 5544, 6361, 70D6, and 7207")
    print("  this is the parser-token traversal boundary below operand recursion, not a local tall-symbol emitter")
    print("  the visible tall-template builder still has to be tied to the class/geometry state above this boundary")


def dump_geometry_flow(rom):
    print("geometry/descriptor ROM anchors")
    for addr, hex_bytes, note in GEOMETRY_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in GEOMETRY_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ndecoded descriptors")
    for desc in parse_descriptors(rom):
        cells = " ".join(fmt_cell(d, e) for d, e in desc["cells"])
        print(
            f"  desc {desc['addr']:04X}: base={desc['base']:04X} "
            f"box={desc['box']:04X} row_h={desc['row_height']:02X} "
            f"cols={desc['cols']} rows={desc['rows']} cells={desc['cells_ptr']:04X} "
            f"{cells}"
        )


def descriptor_cell_positions(desc):
    base_y = desc["base"] >> 8
    base_x = desc["base"] & 0xFF
    positions = []
    for row in range(desc["rows"]):
        y = base_y + row * (desc["row_height"] + 2)
        for col in range(desc["cols"]):
            idx = row * desc["cols"] + col
            x = base_x + 7 * col
            positions.append((idx, row, col, x, y, desc["cells"][idx]))
    return positions


def dump_template_descriptor_algorithm_flow(rom):
    print("template descriptor emission algorithm")
    for addr, hex_bytes, note in TEMPLATE_DESCRIPTOR_ALGORITHM_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    descriptors = {desc["addr"]: desc for desc in parse_descriptors(rom)}

    print("\naction to template kind and selector destination")
    for action, kind in sorted(TEMPLATE_ACTIONS.items()):
        label = TEMPLATE_DESCRIPTOR_KIND_LABELS.get(kind, "")
        print(f"  action {action:02X} -> kind {kind:02X} {label}: {kind_path(kind)}")

    print("\ndescriptor ABI")
    print("  +0 word: pixel base, high byte y and low byte x")
    print("  +2 word: rectangle/box size word passed through 6AF5")
    print("  +4 byte: row height")
    print("  +5 word: high byte columns, low byte rows")
    print("  +7 word: pointer to packed two-byte display cells")

    print("\ndecoded descriptor cell placement")
    for desc in parse_descriptors(rom):
        print(
            f"  desc {desc['addr']:04X}: base_y={desc['base'] >> 8:02X} "
            f"base_x={desc['base'] & 0xFF:02X} box={desc['box']:04X} "
            f"row_h={desc['row_height']:02X} cols={desc['cols']} rows={desc['rows']} "
            f"cells={desc['cells_ptr']:04X}"
        )
        for idx, row, col, x, y, cell in descriptor_cell_positions(desc):
            d, e = cell
            print(f"    cell {idx:02d} row {row} col {col}: x={x:02X} y={y:02X} {fmt_cell(d, e)}")

    print("\ndescriptor-backed template menu cells")
    for action, kind in sorted(TEMPLATE_ACTIONS.items()):
        if kind == 0x10:
            desc = descriptors[0x686F]
        elif kind == 0x11:
            desc = descriptors[0x6880]
        elif kind == 0x12:
            print("  action 2E kind 12: jumps to 6A8A measured fraction editor path, not a descriptor cell loop")
            continue
        else:
            print("  action 5A kind 13: selector cascade chooses one of 689C/68A5/6893 descriptor families")
            continue
        cells = " ".join(fmt_cell(d, e) for d, e in desc["cells"])
        print(f"  action {action:02X} kind {kind:02X} uses descriptor {desc['addr']:04X}: {cells}")

    print("\nalgorithm summary")
    print("  68AE maps geometry actions to a kind byte through 6773/6761 and forces 85DE=48")
    print("  69C8 clears 85DF/85E0, selects a descriptor or kind-2 fraction path, and stores normalized kind state")
    print("  6A00 reads the descriptor ABI into 85E9/85EB/85E1/85EC and draws the descriptor box")
    print("  683D maps each descriptor row/column to pixels using x=base_x+7*col and y=base_y+sum(row_h+2)")
    print("  6A27..6A6E walks packed two-byte display cells, measuring strings through 6B62/6BE7 and marker gates through 4F44")
    print("  this recovers the descriptor-backed template menu emitter; it still does not name a measured tall radical/integral stretch caller")


def descriptor_position_for(desc, row, col):
    idx = row * desc["cols"] + col
    base_y = desc["base"] >> 8
    base_x = desc["base"] & 0xFF
    return idx, base_x + 7 * col, base_y + row * (desc["row_height"] + 2), desc["cells"][idx]


def delimiter_family_locations(rom, cell):
    locations = []
    for table_addr, table_name, _expected_high, _note in DELIMITER_DISPLAY_MAP_TABLES:
        raw = rom_bytes(rom, table_addr, 20)
        for idx in range(10):
            if (raw[2 * idx], raw[2 * idx + 1]) == cell:
                locations.append(f"table {table_name} 39:{table_addr + 2 * idx:04X} index {idx}")
    return locations


def dump_template_pixel_sample_flow(rom):
    print("template pixel-coordinate sample verifier")
    for addr, hex_bytes, note in (
        TEMPLATE_DESCRIPTOR_ALGORITHM_ANCHORS[3],
        TEMPLATE_DESCRIPTOR_ALGORITHM_ANCHORS[4],
        TEMPLATE_DESCRIPTOR_ALGORITHM_ANCHORS[5],
        TEMPLATE_DESCRIPTOR_ALGORITHM_ANCHORS[6],
    ):
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")
    for page, addr, hex_bytes, note in (
        RECTANGLE_RULE_EVENT_FLOW_ANCHORS[2],
        RECTANGLE_RULE_EVENT_FLOW_ANCHORS[3],
        RECTANGLE_RULE_EVENT_FLOW_ANCHORS[6],
    ):
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ndescriptor ABI checks")
    descriptors = {desc["addr"]: desc for desc in parse_descriptors(rom)}
    unexpected = []
    for addr, expected in sorted(TEMPLATE_PIXEL_DESCRIPTOR_EXPECTED.items()):
        desc = descriptors.get(addr)
        if desc is None:
            unexpected.append((addr, "missing descriptor"))
            print(f"  desc {addr:04X}: MISSING")
            continue
        fields = ("base", "box", "row_height", "cols", "rows", "cells_ptr")
        mismatches = [field for field in fields if desc[field] != expected[field]]
        status = "ok" if not mismatches else "MISMATCH"
        if mismatches:
            unexpected.append((addr, ",".join(mismatches)))
        print(
            f"  desc {addr:04X}: {status} base={desc['base']:04X} box={desc['box']:04X} "
            f"row_h={desc['row_height']:02X} cols={desc['cols']} rows={desc['rows']} cells={desc['cells_ptr']:04X}"
        )

    print("\n683D coordinate samples")
    for addr, row, col, expected_x, expected_y, expected_cell, note in TEMPLATE_PIXEL_DESCRIPTOR_SAMPLES:
        desc = descriptors[addr]
        idx, x, y, cell = descriptor_position_for(desc, row, col)
        status = "ok" if (x, y, cell) == (expected_x, expected_y, expected_cell) else "MISMATCH"
        if status != "ok":
            unexpected.append((addr, f"sample row {row} col {col}"))
        print(
            f"  desc {addr:04X} cell {idx:02d} row={row} col={col}: {status} "
            f"x={x:02X} y={y:02X} {fmt_cell(*cell)}  {note}"
        )

    print("\n6B1C rule endpoint samples")
    for count, left, right, note in RECTANGLE_RULE_ENDPOINT_SAMPLES:
        computed_left = 0x1B + 7 * count
        computed_right = computed_left + 4
        status = "ok" if (computed_left, computed_right) == (left, right) else "MISMATCH"
        if status != "ok":
            unexpected.append((0x6B1C, f"endpoint {count}"))
        print(f"  n={count}: {status} left={computed_left:02X} right={computed_right:02X}  {note}")

    print("\nclosure")
    if unexpected:
        for addr, label in unexpected:
            print(f"  {addr:04X}: {label}")
    else:
        print("  descriptor ABI fields, sample cell coordinates, and kind-2 rule endpoints match the recovered formulas")

    print("\ninterpretation")
    print("  descriptor-backed template cells use x=base_x+7*col and y=base_y+row*(row_height+2)")
    print("  descriptor boxes are drawn only through 6AF5, and kind-2 rule endpoints use x=0x1B+7*n through 6B1C")
    print("  this makes the descriptor/fraction template pixel algorithm concrete; it still does not prove the non-descriptor tall-symbol pixels")


def dump_geometry_selector_closed_flow(rom):
    start, end = GEOMETRY_SELECTOR_CLOSED_RANGE
    print(f"69C8 geometry selector closed-world audit ({start:04X}..{end:04X})")
    for addr, hex_bytes, note in GEOMETRY_SELECTOR_CLOSED_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nselector destinations")
    print("  kind nibble 0 -> descriptor 686F")
    print("  kind nibble 1 -> descriptor 6880")
    print("  kind nibble 2 -> kind-2 fraction path 6A8A")
    print("  kind nibble >=3 -> descriptor cascade 689C / 68A5 / 6893")

    print("\nrange-local direct control-flow references")
    for target in GEOMETRY_SELECTOR_CALL_TARGETS:
        direct, words = control_refs(rom, target)
        direct = [(addr, op) for addr, op in direct if start <= addr <= end]
        words = [addr for addr in words if start <= addr <= end]
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    bcall_names = {
        addr: (target, name, parent, note)
        for addr, target, name, parent, note in DRAW_PRIMITIVE_GHIDRA_RST28_SITES
    }
    print("\ninline RST28 bcalls in selector/helper range")
    aligned = [
        (addr, target, name, parent, note)
        for addr, (target, name, parent, note) in sorted(bcall_names.items())
        if start <= addr <= end
    ]
    if aligned:
        for addr, target, name, parent, note in aligned:
            actual = rom_bytes(rom, addr, 3)
            status = "ok" if actual == bytes((0xEF, target & 0xFF, target >> 8)) else "MISMATCH"
            print(f"  {addr:04X}: {status} {target:04X} {name} ({parent}) - {note}")
    else:
        print("  none")

    print("\nrange-local state word references")
    for word, note in GEOMETRY_SELECTOR_STATE_WORDS:
        refs = [addr for addr in page_word_refs(rom, PAGE, word) if start <= addr <= end]
        where = " ".join(f"{addr:04X}" for addr in refs) or "none"
        print(f"  {word:04X}: {where}  {note}")

    print("\ninterpretation")
    print("  69C8 is a closed selector: fixed descriptors, kind-2 fraction UI, or descriptor-family cascade")
    print("  inline bcalls in this range are descriptor/fraction boxes, focused-cell inversion, and key/string conversion")
    print("  9D27 is not referenced inside the selector; only 85EE/85EF drive the kind-2 fraction UI")
    print("  no decoded path in 69C8..6BFE contains a top/middle/bottom symbol table or variable-height glyph loop")


def dump_cell_pixel_mapper_flow(rom):
    print("cell-to-pixel mapper / draw-indented caller closure")
    for addr, hex_bytes, note in CELL_PIXEL_MAPPER_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow caller closure")
    for target, expected_callers in CELL_PIXEL_MAPPER_EXPECTED_CALLERS.items():
        direct, words = control_refs(rom, target)
        direct_map = {addr: op for addr, op in direct}
        print(f"  {target:04X}")
        for addr, note in sorted(expected_callers.items()):
            op = direct_map.get(addr)
            status = "ok" if op is not None else "MISSING"
            print(f"    {addr:04X}: {status} {op or '-'}  {note}")
        unexpected = sorted(set(direct_map) - set(expected_callers))
        raw_expected = {addr + 1 for addr in expected_callers}
        raw_unexpected = sorted(set(words) - raw_expected)
        print(
            "    unexpected direct: "
            + (" ".join(f"{addr:04X}:{direct_map[addr]}" for addr in unexpected) or "none")
        )
        print("    unexpected raw words: " + (" ".join(f"{addr:04X}" for addr in raw_unexpected) or "none"))

    print("\nlocal state-word and draw/display scans")
    for lo, hi, label in CELL_PIXEL_MAPPER_WINDOWS:
        print(f"  {label} {lo:04X}..{hi:04X}")
        for target, state_label in CELL_PIXEL_MAPPER_STATE_WORDS:
            refs = [
                addr for addr in state_word_refs_on_page(rom, PAGE, target)
                if lo <= addr < hi
            ]
            print(f"    {target:04X} {state_label}: " + (" ".join(f"{addr:04X}" for addr in refs) or "none"))
        hits = page_pattern_hits_in_range(rom, PAGE, lo, hi, CELL_PIXEL_MAPPER_DRAW_PATTERNS)
        if hits:
            for pattern_label, addr in hits:
                print(f"    pattern {addr:04X}: {pattern_label}")
        else:
            print("    pattern: none")

    print("\ninterpretation")
    print("  683D is a coordinate mapper: it derives x/y from 85E9, 85DF, and row heights at 85EB")
    print("  the only callers are the 6833 current-cell cue wrapper and the 6A27 descriptor-cell loop")
    print("  682A reaches 67A0/69C8 geometry redraw before mapping the current cell; it is not a glyph stretcher")
    print("  68AE calls 6833 only for focus/cell-cue placement before the kind-2 measured fraction edit branch")
    print("  this closes 682A/6833/683D as coordinate/highlight plumbing, not the tall radical/integral emitter")


def dump_descriptor_marker_flow(rom):
    print("descriptor square-marker ROM anchors")
    for addr, hex_bytes, note in DESCRIPTOR_MARKER_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ndescriptor and record hits")
    for d, e, note in DESCRIPTOR_MARKER_CELLS:
        desc_hits = []
        for desc in parse_descriptors(rom):
            for idx, cell in enumerate(desc["cells"]):
                if cell == (d, e):
                    desc_hits.append(f"desc {desc['addr']:04X} cell {idx}")

        record_hits = []
        for cls in range(HANDLER_COUNT):
            ptr, record = parse_handler_record(rom, cls)
            if record is None:
                continue
            for item in record["items"]:
                for idx, cell in enumerate(item["cells"]):
                    if cell == (d, e):
                        record_hits.append(f"class {cls:02X} row {item['row']} cell {idx}")

        print(f"  {fmt_cell(d, e)} {note}:")
        print("    descriptors: " + (", ".join(desc_hits) or "none"))
        print("    records: " + (", ".join(record_hits) or "none"))

    print("\npage-39 control-flow/raw xrefs")
    for target in DESCRIPTOR_MARKER_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nraw Ghidra identities")
    print("  39:4F44 is named eqdisp_cmp_cursor_bounds, but its byte body compares DE to FB C8 / FB C7")
    print("  39:4F6C is named eqdisp_setnorm_split2 and normalizes display/split state after a marker hit")
    print("  39:6A4B is inside the 69C8 descriptor walker and calls 4F44 after 6B62/6BE7 string measurement")

    print("\ninterpretation")
    print("  descriptor 6880 includes FE09, FB C8, 00C7, 00C8, FB C7 in that order")
    print("  FB C8 and FB C7 are actively special-cased in the descriptor walker through page-3D actions 7 and 6")
    print("  00C8 and 00C7 are ordinary display/name cells in the same descriptor and do not enter the marker gate")
    print("  this corrects the 4F44 role: it is square-marker handling, not a hidden tall-symbol draw routine")


def dump_marker_retouch_flow(rom):
    print("marker retouch / _DarkLine ROM anchors")
    for item in MARKER_RETOUCH_FLOW_ANCHORS:
        if len(item) == 3:
            addr, hex_bytes, note = item
            page = PAGE
        else:
            page, addr, hex_bytes, note = item
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow/raw xrefs")
    for target in MARKER_RETOUCH_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nlocal retouch-window state refs")
    for lo, hi, label in (
        (0x4F08, 0x4F99, "decoded-cell marker/retouch tail"),
        (0x6A4B, 0x6A6A, "descriptor-cell marker/retouch tail"),
    ):
        print(f"  {label} {lo:04X}..{hi:04X}")
        for target, state_label in MARKER_RETOUCH_STATE_WORDS:
            refs = [
                addr for addr in state_word_refs_on_page(rom, PAGE, target)
                if lo <= addr < hi
            ]
            print(f"    {target:04X} {state_label}: " + (" ".join(f"{addr:04X}" for addr in refs) or "none"))

    print("\nraw Ghidra identities")
    print("  raw HTTP identifies 39:4F6C as eqdisp_setnorm_split2, ending in CALL 3555")
    print("  raw HTTP identifies 00:3555 as a trampoline to page 04:4025, the _DarkLine entry")
    print("  raw HTTP identifies 39:4F44 as a marker gate that compares DE against FB C8 / FB C7")

    print("\ninterpretation")
    print("  4F62 is reached only from the decoded-cell tail after the FB C8/C7 marker gate")
    print("  6A66 is reached only from the descriptor-cell loop after 4F44 reports a marker hit")
    print("  both setup paths pass fixed endpoints into 4F6C; neither reads 85EE/85EF/9D27 or a repeat count")
    print("  CALL 3555 is therefore marker/split retouch on this path, not the measured tall integral/radical pixel builder")


def counted_ascii_at(rom, page, addr):
    size = rom_bytes_at(rom, page, addr, 1)[0]
    data = rom_bytes_at(rom, page, addr + 1, size)
    return data.decode("ascii")


def nul_message_at(rom, page, addr, limit=48):
    data = rom_bytes_at(rom, page, addr, limit)
    out = []
    for byte in data:
        if byte == 0:
            break
        if byte == 0x06:
            out.append(" ")
        elif 0x20 <= byte < 0x7F:
            out.append(chr(byte))
        else:
            out.append(f"<{byte:02X}>")
    return "".join(out)


def dump_fraction_template_flow(rom):
    print("kind-2 fraction template ROM anchors")
    for addr, hex_bytes, note in FRACTION_TEMPLATE_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nlabel strings")
    for addr in (0x6B54, 0x6B5B):
        print(f"  {addr:04X}: {counted_ascii_at(rom, PAGE, addr)!r}")

    print("\ncontrol-flow xrefs")
    for target in FRACTION_TEMPLATE_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ncoordinate conventions")
    print("  6A8A draws the fixed fraction template box via 6AF5 with HL=1211, DE=354C")
    print("  6B2D prints ROW/COL counted strings at y=17/22, x=13, followed by selector labels 1..6")
    print("  6AFD inverts the focused numerator/denominator extent using 85EE or 85EF and _InvertRect")
    print("  6ABF draws/erases row rectangles with _DrawRectBorder/_EraseRectBorder; carry selects the bcall")
    print("  this is the recovered kind-2 fraction template UI algorithm, not the tall radical/integral stretch caller")


def dump_template_chrome_flow(rom):
    print("template chrome/rectangle emission ROM anchors")
    for addr, hex_bytes, note in TEMPLATE_CHROME_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ninline rectangle bcalls")
    for addr, bcall_id, name, note in TEMPLATE_CHROME_BCALLS:
        actual = rom_bytes(rom, addr, 3)
        expected = bytes((0xEF, bcall_id & 0xFF, bcall_id >> 8))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {name} ({bcall_id:04X}) - {note}")

    print("\ncontrol-flow xrefs")
    for target in TEMPLATE_CHROME_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  67AC emits the four-tab template chrome using literal ROM labels FRAC/FUNC/MTRX/YVAR")
    print("  tab separators use CALL 3555 -> _DarkLine, and the 6802 85EE test only gates the fixed empty-template cue")
    print("  680F highlights the active tab from low nibble of 85E8 using 19-pixel x steps")
    print("  683D is the shared cell-to-pixel mapper; it uses 7-pixel columns and row_height+2 vertical steps")
    print("  this is confirmed template UI/chrome rectangle/line emission, not a hidden tall integral or radical stretch table")


def dump_template_state_flow(rom):
    print("template-state/geometry-mode ROM anchors")
    for addr, hex_bytes, note in TEMPLATE_STATE_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in TEMPLATE_STATE_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ngeometry-mode action bytes")
    for action, kind in TEMPLATE_ACTIONS.items():
        print(f"  action {action:02X} -> kind {kind:02X} ({kind_path(kind)})")


def dump_template_draw_bridge_flow(rom):
    print("template draw bridge ROM anchors")
    for addr, hex_bytes, note in TEMPLATE_DRAW_BRIDGE_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nraw-reference data anchors")
    for addr, hex_bytes, note in TEMPLATE_DRAW_BRIDGE_RAW_REF_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\n4C40 caller/gate anchors")
    for addr, hex_bytes, note in TEMPLATE_DRAW_BRIDGE_CALLER_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    unclassified = []
    for target in TEMPLATE_DRAW_BRIDGE_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")
        direct_operands = {addr + 1 for addr, _op in direct}
        data_refs = sorted(set(words) - direct_operands)
        expected = TEMPLATE_DRAW_BRIDGE_RAW_REF_EXPECTED.get(target, {})
        missing = sorted(set(expected) - set(data_refs))
        unexpected = sorted(set(data_refs) - set(expected))
        if data_refs:
            details = " ".join(
                f"{addr:04X}:{expected.get(addr, 'UNCLASSIFIED')}" for addr in data_refs
            )
            print(f"    non-control raw refs: {details}")
        if missing:
            print("    missing expected raw data refs: " + " ".join(f"{addr:04X}" for addr in missing))
        if unexpected:
            unclassified.extend((target, addr) for addr in unexpected)

    direct_4c40 = {addr for addr, _op in control_refs(rom, 0x4C40)[0]}
    expected_4c40 = set(TEMPLATE_DRAW_BRIDGE_4C40_CALLERS)
    missing_4c40 = sorted(expected_4c40 - direct_4c40)
    unexpected_4c40 = sorted(direct_4c40 - expected_4c40)
    print("\n4C40 direct caller classification")
    for addr in sorted(direct_4c40):
        label = TEMPLATE_DRAW_BRIDGE_4C40_CALLERS.get(addr, "UNCLASSIFIED")
        print(f"  {addr:04X}: {label}")
    print("  missing expected 4C40 callers: " + (" ".join(f"{addr:04X}" for addr in missing_4c40) or "none"))
    print("  unexpected 4C40 callers: " + (" ".join(f"{addr:04X}" for addr in unexpected_4c40) or "none"))

    print("\nraw-reference closure")
    if unclassified:
        for target, addr in unclassified:
            print(f"  UNCLASSIFIED {addr:04X} raw word matching {target:04X}")
    else:
        print("  all non-control raw refs to bridge targets are classified data")

    print("\nbridge interpretation")
    print("  49A8 is the recursive template-cell path reached from action-05 cells with C=82")
    print("  4A02 calls 4C40 before ordinary row placement; 4C40 has only 4A02 and 5077 as direct callers")
    print("  5077 is the generic action-01/02 row-navigation redraw tail; class-48 actions 01/02 are gated to 68AE first")
    print("  the extra raw 4A02 word at 650E is class-27 count/action record data, not an indirect draw caller")
    print("  4C40 jumps to 682A only when 85DE is the forced template state 48")
    print("  682A is the only page-39 direct caller of 67A0, and 67A0 always jumps to 69C8 after template chrome")
    print("  this proves the draw bridge into descriptor/fraction geometry; it still delegates final cell/rule work to 69C8")


def dump_template_emission_closure_flow(rom):
    print("template-emission closure ROM anchors")
    for addr, hex_bytes, note in TEMPLATE_EMISSION_CLOSURE_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow closure")
    for target, label in TEMPLATE_EMISSION_CLOSURE_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X} {label}: direct {refs}; raw {raw}")

    print("\ndraw primitive closure")
    for addr, bcall_id, name, note in DRAW_PRIMITIVE_BCALLS:
        print(f"  39:{addr:04X}: {name} ({bcall_id:04X}) - {note}")
    for bcall_id, name in DRAW_PRIMITIVE_ABSENT_BCALLS:
        pattern = bytes((0xEF, bcall_id & 0xFF, bcall_id >> 8))
        hits = rom_pattern_hits(rom, pattern)
        where = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
        print(f"  absent {name} ({bcall_id:04X}): {where}")

    print("\nclosure interpretation")
    print("  class 48 template actions enter geometry only at 4FD9 -> 68AE; 68AE has no other page-39 direct caller")
    print("  decoded cells enter glyph/string emission only through 4DF5 or the saved-operand tail at 5B63")
    print("  page 39 never directly calls the large-font blitter 3B3D; fixed glyphs route through 3B37/page-7")
    print("  VPutMap calls are confined to descriptor/string output in 69C8..6BFE, not template-action dispatch")
    print("  rectangle/image drawing is confined to template chrome and descriptor/fraction boxes; fill-rect/image bcalls are absent")
    print("  this closes the static template-emission exits; any remaining tall-symbol placement must be outside these direct draw exits or require a dynamic pen trace")


def dump_geometry_action_flow(rom):
    print("geometry-mode action dispatch ROM anchors")
    for addr, hex_bytes, note in GEOMETRY_ACTION_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in GEOMETRY_ACTION_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nraw Ghidra names")
    print("  39:68AE eqdisp_layout_token_geom")
    print("  39:6833 eqdisp_draw_indented")
    print("  39:6773 eqdisp_menu_tok_jp")
    print("  39:595F eqdisp_scan_arg_tok")
    print("  39:53AD eqdisp_menu_or_emit")

    print("\naction interpretation")
    print("  while 85DE=48, actions 49/48/2E/5A select template kinds 10/11/12/13 and redraw through 6773")
    print("  for non-fraction kinds, actions 3/4 move rows, action 5 dispatches the current descriptor cell, and 8F..97 select visible slots")
    print("  for kind 12, action 5 updates the measured 85EE/85EF fraction counts, copies them to 9D27, and redraws via 6AFD")
    print("  kind-12 actions 1/2 adjust the selected column and 3/4 adjust the selected row by drawing/erasing through 6ABF")
    print("  this recovers the editable template-geometry action algorithm; it is still UI/template geometry, not a glyph-stretch table")


def dump_geometry_handoff_flow(rom):
    print("template geometry handoff ROM anchors")
    for addr, hex_bytes, note in GEOMETRY_HANDOFF_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in GEOMETRY_HANDOFF_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nmeasurement-word references")
    for word, name in ((0x9D27, "9D27"), (0x85EE, "85EE"), (0x85EF, "85EF")):
        lo = word & 0xFF
        hi = word >> 8
        refs = []
        start = romoff(PAGE, 0x4000)
        end = romoff(PAGE, 0x8000)
        for o in range(start, end - 1):
            if rom[o] == lo and rom[o + 1] == hi:
                refs.append(0x4000 + o - start)
        print(f"  {name}: " + (" ".join(f"{addr:04X}" for addr in refs) or "none"))

    print("\ninterpretation")
    print("  incoming byte 3D is the only page-39 direct control-flow entry to the 672E handoff")
    print("  9D27 is written from 85EE in the kind-2 fraction path and read back only by the 6753/6758 handoff")
    print("  this proves a measured-geometry handoff; row composition is handled by 5167, while this path covers the template-state bridge")


def dump_template_handoff_guard_flow(rom):
    print("template handoff guard ROM anchors")
    for page, addr, hex_bytes, note in TEMPLATE_HANDOFF_GUARD_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow/raw xrefs")
    for target in TEMPLATE_HANDOFF_GUARD_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nraw Ghidra identities")
    print("  ram:2077 is BIT 5,(IY+44); this is the MathPrintActive predicate")
    print("  ram:36FF is a bjump to page_04:7FBA; Ghidra has not split page_04:7FBA into a function")
    print("  39:66BD is eqdisp_peek_match_tok; 39:6DDB is _mnu_6ddb; 39:6773 is an inline wrapper")
    print("  39:67A0 is eqdisp_draw_window and jumps to 69C8 after drawing template chrome")

    print("\n672E branch interpretation")
    print("  if MathPrintActive is clear, 672E takes the HL=0000 path and then forces 85DE=48")
    print("  if the page-4 guard returns NZ, 859A must be 40 before 672E can continue toward the restore tests")
    print("  6DDB returning NZ, IY+45 bit 5 clear, or IY+44 bit 1 clear all force the HL=0000 path")
    print("  only the surviving path reloads HL=(9D27), stores it to 85EE/85EF, then forces 85DE=48")
    print("  6773 is the menu action wrapper that sets box flags, sets 85E8/85DE through 6761, and re-enters drawing")
    print("  this is a guarded state handoff into geometry mode; it still contains no measured tall-symbol piece builder")


def dump_measured_state_flow(rom):
    print("page-39 measured-state consumer audit")
    for addr, hex_bytes, note in MEASURED_STATE_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 measured-state word references")
    for target, name in MEASURED_STATE_WORDS:
        refs = page_word_refs(rom, PAGE, target)
        where = " ".join(f"{addr:04X}" for addr in refs) or "none"
        print(f"  {target:04X}: {where}  {name}")

    print("\ncontrol-flow xrefs")
    for target in MEASURED_STATE_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  85E9/85EB/85EC are produced and consumed by the descriptor geometry path at 6A00 and 683D")
    print("  the extra 85E9 read at 5BD7 is classified by --class10-dynamic-selector-flow as a saved-OP/menu selector")
    print("  it generates FE77..FE7C for 85E9 < 6 and has no measured-height draw primitive")
    print("  85EE/85EF/9D27 stay scoped to the measured fraction/template handoff already pinned by --geometry-handoff-flow")
    print("  86D7/86D8 are graph pen coordinates used by descriptor/chrome/string output, not a height builder by themselves")
    print("  this rules out the remaining obvious page-39 measured-state outlier as the tall-symbol emitter")


def dump_class10_saved_tail_flow(rom):
    print("class-10 saved-operand tail ROM anchors")
    for addr, hex_bytes, note in CLASS10_SAVED_TAIL_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow xrefs")
    for target in CLASS10_SAVED_TAIL_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nclass-10 branch local state/draw scan")
    window_lo, window_hi = 0x5B46, 0x5B8C
    for target, name in ((0x85E8, "85E8"), (0x85E9, "85E9"), (0x85EE, "85EE"), (0x85EF, "85EF"), (0x9D27, "9D27")):
        refs = [
            addr for addr in state_word_refs_on_page(rom, PAGE, target)
            if window_lo <= addr < window_hi
        ]
        print(f"  {name}: " + (" ".join(f"{addr:04X}" for addr in refs) or "none"))
    draw_hits = page_pattern_hits_in_range(
        rom,
        PAGE,
        window_lo,
        window_hi,
        OFFPAGE_DRAW_SERVICE_PATTERNS + [("RST28 bcall 51F7", "eff751")],
    )
    if draw_hits:
        for label, addr in draw_hits:
            print(f"  draw/display pattern: {label} at 39:{addr:04X}")
    else:
        print("  draw/display pattern: none")

    print("\nROM-wide single-bcall check")
    for label, hex_bytes in (("RST28 bcall 51F7", "eff751"), ("CALL _ChkFindSym 00:0E60", "cd600e")):
        hits = find_pattern_locations(rom, bytes.fromhex(hex_bytes))
        where = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
        print(f"  {label}: {where}")

    print("\nbcall 51F7 target chain")
    for page, addr, hex_bytes, note in CLASS10_BCALL_51F7_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        if page == 0 and addr < 0x4000:
            actual = rom[addr:addr + len(expected)]
            loc = f"ram:{addr:04X}"
        else:
            actual = rom_bytes_at(rom, page, addr, len(expected))
            loc = f"{page:02X}:{addr:04X}"
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {loc}: {status} {actual.hex().upper()}  {note}")
    bcall_addr, raw_page = word(rom, 0x3B, 0x51F7), rom[romoff(0x3B, 0x51F9)]
    print(f"  resolved: 51F7 -> {raw_page & 0x3F:02X}:{bcall_addr:04X} (raw page byte {raw_page:02X})")

    print("\nraw Ghidra identities")
    print("  ram:0E60 is _ChkFindSym")
    print("  ram:1785 is ret_noop_1785")
    print("  page_39:66AB, page_39:65A2, page_39:65AE are not split as functions in this database")
    print("  bcall 51F7 is absent from the local symbol lists, but the raw table resolves it to page_35:6485")
    print("  page_01:5C39 is _PutS; ram:221D is copy18_to_9d76/keyForStr")

    print("\ninterpretation")
    print("  5B46 emits the fixed slot gutter, then class 10 enters the 5B66 special path")
    print("  66AB only checks for an OP1 symbol and emits a '*' marker through 3FDB when present")
    print("  5B66 reads 85E8 and at most the adjacent 85E9 byte as menu/list state bounds")
    print("  bcall 51F7 selects a ROM string, copies it to keyForStr, and prints it through _PutS")
    print("  this branch does not read 85EE/85EF/9D27 and does not loop over glyph rows or descriptor heights")
    print("  the single 51F7 bcall is guarded by 85E8/85E9 tests and is followed by erase-to-EOL, not a stretcher loop")


def dump_class10_dynamic_selector_flow(rom):
    print("class-10 dynamic selector ROM anchors")
    for page, addr, hex_bytes, note in CLASS10_DYNAMIC_SELECTOR_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\n85E9-indexed generated FE cells")
    unexpected = []
    for selector in range(6):
        d, e = 0xFE, 0x77 + selector
        mapped = page7_display_byte_map(rom, d, e)
        direct = map_token_glyph_cell(d, e)
        rec_hits = "; ".join(cell_record_locations(rom, (d, e))) or "none"
        desc_hits = "; ".join(cell_descriptor_locations(rom, (d, e))) or "none"
        if mapped is None:
            unexpected.append((selector, d, e, None))
            print(f"  85E9={selector}: MISMATCH {fmt_cell(d, e)} -> INVALID")
            continue
        md, me, source = mapped
        status = "ok" if (md, me) == (0x5D, selector) else "MISMATCH"
        if status != "ok":
            unexpected.append((selector, d, e, (md, me)))
        direct_text = f"L{direct:02X}" if direct is not None else "no"
        print(
            f"  85E9={selector}: {status} {fmt_cell(d, e)} -> {fmt_cell(md, me)} via {source}; "
            f"4F1A direct glyph={direct_text}; records={rec_hits}; descriptors={desc_hits}"
        )

    print("\nclass-10 selector local state/draw scan")
    window_lo, window_hi = 0x5BA1, 0x5C30
    for target, name in CLASS10_DYNAMIC_SELECTOR_STATE_WORDS:
        refs = [
            addr for addr in state_word_refs_on_page(rom, PAGE, target)
            if window_lo <= addr < window_hi
        ]
        print(f"  {target:04X} {name}: " + (" ".join(f"{addr:04X}" for addr in refs) or "none"))
    hits = page_pattern_hits_in_range(
        rom,
        PAGE,
        window_lo,
        window_hi,
        OFFPAGE_DRAW_SERVICE_PATTERNS
        + [
            ("CALL class-49 force/editor path", "cd546d"),
            ("CALL menu/app flag test", "cddb6d"),
            ("JP class-49 post-menu path", "c3b96c"),
        ],
    )
    for label, addr in hits:
        print(f"  {addr:04X}: {label}")
    if not hits:
        print("  draw/display/menu patterns: none")

    print("\ncontrol-flow closure")
    for target in (0x5BA1, 0x5BD0, 0x5BED, 0x6CB9, 0x6D54, 0x6DDB, 0x545B):
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nclosure")
    if unexpected:
        for selector, d, e, mapped in unexpected:
            if mapped is None:
                print(f"  selector {selector}: {fmt_cell(d, e)} did not map through page 7")
            else:
                md, me = mapped
                print(f"  selector {selector}: {fmt_cell(d, e)} mapped unexpectedly to {fmt_cell(md, me)}")
    else:
        print("  selectors 0..5 all generate FE77..FE7C and page 7 maps them to 5D00..5D05")

    print("\ninterpretation")
    print("  the 5BD7 85E9 read is an actual ROM-backed selector: E=85E9+77 with D=FE for six cases")
    print("  those generated FE cells are remapped by the page-7 display-byte table, not by the direct 4F1A glyph path")
    print("  the branch has no 85EE/85EF/9D27 measured-height input and no local graph/rectangle/fill primitive")
    print("  the 85E9 >= 6 arm falls into class-29/menu state handling and the class-49 editor boundary")
    print("  this classifies the saved-operand dynamic selector; final row placement is covered by 5167/5B10/5B1D")


def dump_entry_dispatch_flow(rom):
    print("page-39 entry dispatch ROM anchors")
    for addr, hex_bytes, note in ENTRY_DISPATCH_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in ENTRY_DISPATCH_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  byte 3D is tested as an incoming token/action byte at 496C and 4A74")
    print("  the ordinary class path starts only after 4A79 subtracts 2A from the incoming byte")
    print("  therefore the 672E handoff is ROM-backed, but should not be described as a normalized class")


def dump_fnint_token_flow(rom):
    print("fnInt/nDeriv token/display bridge ROM anchors")
    for page, addr, hex_bytes, note in FNINT_TOKEN_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nidentity split")
    print("  parser token: BB24 = tFnInt, BB25 = tNDeriv")
    print("  display cells: 00C8 = fnInt(, 00C7 = nDeriv(")
    print("  unresolved here: which recursive operand slot is displayed as each visible field")


def dump_extended_token_table_flow(rom):
    print("page-7 extended-token table/scanner ROM anchors")
    for page, addr, hex_bytes, note in EXTENDED_TOKEN_TABLE_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nROM-wide parser-token occurrences")
    for label, hex_bytes in (("BB24 tFnInt", "bb24"), ("BB25 tNDeriv", "bb25")):
        hits = rom_pattern_hits(rom, bytes.fromhex(hex_bytes))
        rendered = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
        print(f"  {label}: {rendered}")

    print("\npage-7 word/control references")
    for page, target in EXTENDED_TOKEN_TABLE_XREF_TARGETS:
        direct, words = control_refs_on_page(rom, page, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {page:02X}:{target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  BB24/BB25 occur only in page-7 extended-token table data")
    print("  the table-entry addresses 42EE/42F6/428A have no page-local word refs")
    print("  page-39 reaches page-7 50B5/50B8 through operand parser services, not through display code")
    print("  50B5/50B8 scan expression pointers and token kinds; they are not tall-symbol emitters")


def dump_fnint_template_flow(rom):
    print("fnInt/nDeriv template-row and evaluator ROM anchors")
    for page, addr, hex_bytes, note in FNINT_TEMPLATE_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-1 row-action labels")
    for action in FNINT_ROW_ACTIONS:
        ptr, text = page_indexed_string(rom, action)
        expected = PAGE1_INDEXED_STRING_LABELS.get(action)
        suffix = f" expected={expected}" if expected is not None else ""
        print(f"  action {action:02X}: ptr={ptr:04X} text={text!r}{suffix}")

    print("\nfnInt/nDeriv row/slot positions")
    for cls in FNINT_CLASS_ROWS:
        ptr, record = parse_handler_record(rom, cls)
        print(f"  class {cls:02X} ptr {ptr:04X}")
        for item in record["items"]:
            ptr1, label = page_indexed_string(rom, item["action"])
            cells = " ".join(
                f"{slot}:{fmt_cell(d, e)}" for slot, (d, e) in enumerate(item["cells"])
            )
            print(
                f"    row {item['row']} action={item['action']:02X} "
                f"label={label!r} cells {cells}"
            )

    print("\ninterpretation")
    print("  fnInt( is row 0 slot 8 under the MATH row-action label; nDeriv( is row 0 slot 7")
    print("  slots 9 and 10 are the adjacent square-up/down template markers, not integral glyph pieces")
    print("  page-2 evaluator bytes prove a numeric-calculus parser/evaluator bridge for BB24/BB25")
    print("  this labels operator/menu identity; visible integrand/variable/lower/upper field placement is handled by 5167")


def dump_fnint_eval_flow(rom):
    print("fnInt parser/evaluator FPS-flow ROM anchors")
    for page, addr, hex_bytes, note in FNINT_EVAL_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        if page == 0x00 and addr < 0x4000:
            actual = rom_bytes_banked(rom, page, addr, len(expected))
        else:
            actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nraw Ghidra helper names used by these anchors")
    print("  00:163F _CpyTo2FPS3 -> OP2 from parsed FPS slot 3")
    print("  00:169C _CpyTo1FPS2 -> OP1 from parsed FPS slot 2")
    print("  00:168D _CpyTo1FPS1 -> OP1 from parsed FPS slot 1")
    print("  33:4D00 fnint_body starts by subtracting FPS2/FPS3 and applying _TimesPt5")
    print("  02:6AF6 push_half_const seeds the default tolerance/exponent path before page-33 execution")

    print("\ninterpretation")
    print("  the numeric engine consumes parsed FPS slots 2 and 3 as the interval endpoints and immediately forms a half-width")
    print("  the public token syntax names those endpoints as lower/upper bounds in fnInt(expr,var,a,b[,tol])")
    print("  this backs the endpoint/tolerance side of field naming, but page 39 still provides only generic operand-slot rendering")
    print("  display-side tall integral placement is separate from this numeric evaluator flow and is handled by 5167")


def dump_fnint_argument_order_flow(rom):
    print("fnInt parser-argument order ROM anchors")
    for page, addr, hex_bytes, note in FNINT_ARGUMENT_ORDER_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nraw Ghidra identities used by this boundary")
    print("  39:5167 is eqdisp_layout_multiarg")
    print("  39:5B10 is eqdisp_emit_op_save_e7; 39:5B1D is the saved-E7 variable wrapper")
    print("  39:59E0 is eqdisp_emit_op_d2; 39:59F9 is eqdisp_emit_op_var_c")
    print("  33:4D00 is fnint_body")

    print("\nordered parser-argument slots")
    for slot, label, note in FNINT_ARGUMENT_SLOTS:
        print(f"  slot {slot}: {label} - {note}")

    print("\nslot-walk interpretation")
    print("  page 39 keeps the current parser-argument index in 85E0 and the count in 85E2")
    print("  5167 advances or backs 85E0 by one slot at a time; 5949 only changes the display row-step size")
    print("  the in-row forward path calls 5B10 after incrementing 85E0; the reverse path calls 5B1D after decrementing")
    print("  5B10/5B1D restore saved OP state, then call 59E0/59F9 parser scanners rather than selecting a new field order")
    print("  the evaluator proves slots 2 and 3 are the integration endpoints; no page-39 permutation of fnInt fields is visible")
    print("  vertical placement is handled by the multi-argument row compositor at 5167; this flow pins parser-argument identity order")


def dump_fnint_row_window_flow(rom):
    print("fnInt visible row-window ROM anchors")
    for addr, hex_bytes, note in FNINT_ROW_WINDOW_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nraw Ghidra identities used by this boundary")
    print("  39:50CF is eqdisp_clamp_argcount")
    print("  39:5101 is eqdisp_set_row_from_arg")
    print("  39:513E is eqdisp_layout_arg")
    print("  39:4C5A is eqdisp_emit_subexpr; 39:4CA4 is eqdisp_emit_subexpr2")
    print("  39:5949 is eqdisp_arg_kind")

    print("\nfnInt class row-window examples")
    for cls in FNINT_CLASS_ROWS:
        ptr, record = parse_handler_record(rom, cls)
        print(f"  class {cls:02X} ptr {ptr:04X} rows={record['rows']}")
        for slot, label, _note in FNINT_ARGUMENT_SLOTS:
            step = arg_row_step(cls, slot)
            visible_row = min(slot + 1, 7)
            print(f"    slot {slot}: row_step={step} direct_visible_row={visible_row} {label}")

    print("\nwindow interpretation")
    print("  50CF bounds 85E0 by the current row argument count 85E2 and computes a six-row overflow window")
    print("  5101 maps the selected slot to visible row min(85E0 + 1, 7)")
    print("  513E restores 844B from 984A after laying out the requested argument")
    print("  5949 leaves classes 08/30 on the one-row path for all tested fnInt argument slots")
    print("  4C5A/4CA4 emit the row cell at base + 2*visible_slot and restore the baseline row")
    print("  this recovers the generic visible operand row-window around fnInt; fixed glyph/rule paths provide the final pixels")


def slot_actions_for_cell(slot, mappings):
    actions = []
    for start, end, base, label in mappings:
        action = (base + slot) & 0xFF
        if start <= action <= end:
            actions.append((action, label))
    return actions


def dump_fnint_slot_flow(rom):
    print("fnInt/nDeriv action-byte to row-slot ROM anchors")
    for addr, hex_bytes, note in FNINT_SLOT_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nnormal action-byte slot ranges")
    for start, end, base, label in FNINT_DIRECT_SLOT_ACTIONS:
        slot0 = (start - base) & 0xFF
        slot1 = (end - base) & 0xFF
        if start == end:
            print(f"  action {start:02X}: slot {slot0:02X} ({label})")
        else:
            print(f"  actions {start:02X}..{end:02X}: slots {slot0:02X}..{slot1:02X} ({label})")

    print("\nsaved-OP slot-subtraction ranges")
    for start, end, base, label in FNINT_SAVED_SLOT_ACTIONS:
        slot0 = (start - base) & 0xFF
        slot1 = (end - base) & 0xFF
        if start == end:
            print(f"  action {start:02X}: slot {slot0:02X} ({label})")
        else:
            print(f"  actions {start:02X}..{end:02X}: slots {slot0:02X}..{slot1:02X} ({label})")
    print("  saved-OP actions 9A..B3/CC branch to the named/list path at 5C65, not direct 5955 slot loading")

    print("\nclass 08/30 row-0 operator slot selection")
    for cls in FNINT_CLASS_ROWS:
        ptr, record = parse_handler_record(rom, cls)
        item = record["items"][0]
        ptr1, label = page_indexed_string(rom, item["action"])
        print(f"  class {cls:02X} ptr {ptr:04X} row 0 action={item['action']:02X} label={label!r}")
        for slot, (d, e) in enumerate(item["cells"]):
            direct = ", ".join(
                f"{action:02X}" for action, _ in slot_actions_for_cell(slot, FNINT_DIRECT_SLOT_ACTIONS)
            ) or "-"
            saved = ", ".join(
                f"{action:02X}" for action, _ in slot_actions_for_cell(slot, FNINT_SAVED_SLOT_ACTIONS)
            ) or "-"
            print(f"    slot {slot:02X}: direct={direct:>2} saved={saved:>2} cell={fmt_cell(d, e)}")

    print("\ninterpretation")
    print("  5955/595F prove action-derived slot indexes select cells from the current handler row")
    print("  on the MATH row, action 96 selects slot 7 (00C7 nDeriv) and action 97 selects slot 8 (00C8 fnInt)")
    print("  action 8E selects slot 9 (FB C8 square-up); normal action 9A selects slot 10 (FB C7 square-down)")
    print("  this proves operator/menu-cell selection, but not the later parser-argument placement for integrand/dx/bounds")


def dump_bjump_flow(rom):
    print("display bjump ROM anchors")
    for page, addr, hex_bytes, note in BJUMP_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 bjump-table call sites")
    for vector in BJUMP_FLOW_VECTORS:
        direct, words = control_refs(rom, vector)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {vector:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  3B2B is indexed-string output, not a raw glyph blitter")
    print("  3B3D/page 07:4588 is the large-font glyph blitter")
    print("  3CDB/page 01:6293 is _VPutMap graph/small-font pixel output")


def dump_page39_external_entry_flow(rom):
    print("page-39 external bjump entry surface")
    for vector, target, label in PAGE39_EXTERNAL_ENTRY_VECTORS:
        print(f"  {vector:04X} -> 39:{target:04X}  {label}")

    print("\npage-39 external entry ROM anchors")
    for addr, hex_bytes, note in PAGE39_EXTERNAL_ENTRY_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-local xrefs to entry-adjacent helpers")
    for target in (0x48A6, 0x48AC, 0x48B6, 0x48C2, 0x48CE, 0x4F9A, 0x53AD, 0x5421, 0x6B66, 0x5DD8):
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  the public page-39 bjump surface is small: state/predicate helpers, layout action dispatch, menu/cell emit, string loading, and SaveDisp")
    print("  3B13 -> 4F9A is the only external entry into the large layout/action dispatcher already audited by --layout-flow")
    print("  3B0D/3B19/3B1F are menu/template-cell and string-loader paths, not independent tall-symbol builders")
    print("  3B01 exposes structural class predicates but no record walk or draw primitive")
    print("  no additional public page-39 bjump target remains as a hidden BB24 definite-integral pixel-placement routine")


def dump_structural_predicate_flow(rom):
    print("structural-class predicate ROM anchors")
    for addr, hex_bytes, note in STRUCTURAL_PREDICATE_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 predicate caller closure")
    for target in STRUCTURAL_PREDICATE_TARGETS:
        direct, words = control_refs(rom, target)
        direct_addrs = {addr for addr, _ in direct}
        expected = STRUCTURAL_PREDICATE_EXPECTED_CALLERS[target]
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        status = "ok" if direct_addrs == expected else "MISMATCH"
        print(f"  {target:04X}: {status} direct {refs}; raw {raw}")

    print("\npredicate-tested handler records")
    for cls in (0x14, 0x41, 0x2A, 0x21, 0x42, 0x44, 0x37, 0x36, 0x35, 0x34, 0x43, 0x38, 0x39, 0x33, 0x32, 0x31):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            print(f"  class {cls:02X}: ptr {ptr:04X} non-record")
            continue
        actions = " ".join(f"{item['action']:02X}" for item in record["items"])
        counts = " ".join(f"{item['count']:02X}" for item in record["items"])
        print(f"  class {cls:02X}: ptr {ptr:04X} rows={record['rows']} counts={counts} actions={actions}")

    print("\nwindow-local measured/template state refs")
    for lo, hi, label in STRUCTURAL_PREDICATE_WINDOWS:
        print(f"  {lo:04X}..{hi:04X} {label}")
        for target, state_label in STRUCTURAL_PREDICATE_STATE_WORDS:
            refs = [
                addr for addr in state_word_refs_on_page(rom, PAGE, target)
                if lo <= addr < hi
            ]
            print(f"    {state_label}: " + (" ".join(f"{addr:04X}" for addr in refs) or "none"))

    print("\nwindow-local draw/service patterns")
    for lo, hi, label in STRUCTURAL_PREDICATE_WINDOWS:
        print(f"  {lo:04X}..{hi:04X} {label}")
        for name, hex_bytes in STRUCTURAL_PREDICATE_DRAW_PATTERNS:
            pattern = bytes.fromhex(hex_bytes)
            hits = []
            for addr in range(lo, hi - len(pattern) + 1):
                if rom_bytes(rom, addr, len(pattern)) == pattern:
                    hits.append(addr)
            print(f"    {name}: " + (" ".join(f"{addr:04X}" for addr in hits) or "none"))

    print("\nraw Ghidra note")
    print("  Ghidra splits 48B6 as ret_a_thunk2, but the surrounding bytes are a shared class-predicate chain")

    print("\ninterpretation")
    print("  the predicate family only compares 85DE against structural/root/power classes while preserving A")
    print("  its callers are render-loop, active-cell, row-navigation, and selected-cell scanner gates")
    print("  local windows have no 85EE/85EF/9D27 measured-state use and no draw/rectangle/glyph service call")
    print("  this closes the structural predicate chain as a classifier/control gate, not the tall-symbol placement routine")


def dump_page39_bjump_caller_flow(rom):
    print("ROM-wide callers of public page-39 bjump entries")
    for vector, hex_bytes, label in PAGE39_BJUMP_CALLER_PATTERNS:
        hits = rom_pattern_hits(rom, bytes.fromhex(hex_bytes))
        where = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
        print(f"  CALL {vector:04X}: {where}  {label}")

    print("\npage-1 bridge ROM anchors")
    for page, addr, hex_bytes, note in PAGE39_BJUMP_CALLER_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nbridge local xrefs")
    for page, target in (
        (0x01, 0x780D),
        (0x01, 0x5EDA),
        (0x01, 0x7918),
        (0x01, 0x79B1),
        (0x01, 0x79F9),
        (0x01, 0x7A31),
        (0x01, 0x7A4A),
        (0x01, 0x7A50),
        (0x36, 0x5050),
    ):
        direct, words = control_refs_on_page(rom, page, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {page:02X}:{target:04X}: direct {refs}; raw {raw}")

    print("\ncaller-window measured state and draw-service scan")
    for page, lo, hi, label in PAGE39_BJUMP_CALLER_WINDOWS:
        print(f"  {page:02X}:{lo:04X}..{hi:04X} {label}")
        for target, state_label in PAGE39_BJUMP_CALLER_STATE_WORDS:
            refs = [
                ref for ref in state_word_refs_on_page(rom, page, target)
                if lo <= ref < hi
            ]
            print(f"    {target:04X} {state_label}: " + (" ".join(f"{page:02X}:{ref:04X}" for ref in refs) or "none"))
        hits = page_pattern_hits_in_range(rom, page, lo, hi, PAGE39_BJUMP_CALLER_PATTERNS_LOCAL)
        if hits:
            for pattern_label, hit in hits:
                print(f"    pattern {page:02X}:{hit:04X}: {pattern_label}")
        else:
            print("    pattern: none")

    print("\ninterpretation")
    print("  all ROM-wide callers of 3B01/3B0D/3B13/3B19/3B1F are in the page-1 display bridge")
    print("  3B67 is only called by LCD-save/capture plumbing on pages 1 and 36")
    print("  caller windows have no 85E8/85E9/85EB/85EC/85EE/85EF/9D27 measured-template refs and no rectangle/line/large-glyph draw service")
    print("  page 1 orchestrates prefix normalization, action-09 redispatch, token/menu cases, and string measurement/output")
    print("  the bridge delegates layout actions back to the audited page-39 entries; it is not another tall-symbol piece table or renderer")


def dump_page1_display_bridge_flow(rom):
    start, end = PAGE1_DISPLAY_BRIDGE_RANGE
    print(f"page-1 display bridge audit ({start:04X}..{end:04X})")
    for addr, hex_bytes, note in PAGE1_DISPLAY_BRIDGE_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, 0x01, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  01:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nrange-local state word references")
    for word_value, note in PAGE1_DISPLAY_BRIDGE_STATE_WORDS:
        refs = [
            addr
            for addr in page_word_refs(rom, 0x01, word_value)
            if start <= addr < end
        ]
        where = " ".join(f"01:{addr:04X}" for addr in refs) or "none"
        print(f"  {word_value:04X}: {where}  {note}")

    print("\nrange-local service/draw pattern scan")
    for label, hex_bytes, note in PAGE1_DISPLAY_BRIDGE_SERVICE_PATTERNS:
        pattern = bytes.fromhex(hex_bytes)
        hits = []
        for addr in range(start, end - len(pattern) + 1):
            actual = rom_bytes_at(rom, 0x01, addr, len(pattern))
            if actual == pattern:
                hits.append(addr)
        where = " ".join(f"01:{addr:04X}" for addr in hits) or "none"
        print(f"  {label}: {where}  {note}")

    print("\ninline RST28 callsites in bridge range")
    seen = False
    for addr in range(start, end - 2):
        actual = rom_bytes_at(rom, 0x01, addr, 3)
        if actual[0] != 0xEF:
            continue
        seen = True
        target = actual[1] | (actual[2] << 8)
        print(f"  01:{addr:04X}: {target:04X}")
    if not seen:
        print("  none")

    print("\nraw Ghidra helper identities")
    print("  01:5A98 is _PutMap; the bridge reaches it only at the blank/space path 7BC6")
    print("  01:5B4C is _PutC; 01:5C39 is _PutS; 01:5C52 is _PutPSB")
    print("  01:61C5 is _EraseEOL and 01:61F4 is erase-to-end-of-screen")
    print("  Ghidra has no split functions for the 775C..7C9A bridge itself, so byte anchors carry this audit")

    print("\ninterpretation")
    print("  this bridge touches text row/column state, the saved cell pointer 85DA, and page-39 class state at entry")
    print("  it has no refs to 85E8/85E9/85EB/85EC/85EE/85EF/86D7/86D8/9D27 measured/template geometry words")
    print("  its local display services are text output and erase helpers; rectangle, line, VPutMap graph, and large-glyph bjump patterns are absent")
    print("  therefore page 1 is an off-page display bridge into page 39, not the missing measured tall-symbol placement routine")


def page1_action_table_action(index):
    return 0xCC if index == 26 else 0x9A + index


def page1_action_table_entries(rom):
    entries = []
    for index in range(PAGE1_ACTION_TABLE_COUNT):
        action = page1_action_table_action(index)
        ptr = word(rom, 0x01, PAGE1_ACTION_TABLE_BASE + 2 * index)
        entries.append((action, ptr))

    unique_ptrs = sorted({ptr for _action, ptr in entries} | {PAGE1_ACTION_TABLE_LAST_END})
    out = []
    for action, ptr in entries:
        end = next((candidate for candidate in unique_ptrs if candidate > ptr), ptr)
        cells = []
        for addr in range(ptr, end, 2):
            if addr + 1 >= end:
                break
            cells.append((addr, rom[romoff(0x01, addr)], rom[romoff(0x01, addr + 1)]))
        out.append((action, ptr, end, cells))
    return out


def dump_page1_action_table_flow(rom):
    print("page-1 action-table / display-cell remap audit")
    for addr, hex_bytes, note in PAGE1_ACTION_TABLE_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, 0x01, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  01:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\naction pointer entries")
    for action, ptr, end, cells in page1_action_table_entries(rom):
        shared = ""
        if not cells:
            shared = " empty/shared-tail"
        print(f"  action {action:02X}: ptr={ptr:04X} end={end:04X} cells={len(cells):02d}{shared}")

    print("\ninteresting cells inside action-table lists")
    hits_by_label = {label: [] for _cell, label in PAGE1_ACTION_TABLE_INTERESTING_CELLS}
    interesting = {cell: label for cell, label in PAGE1_ACTION_TABLE_INTERESTING_CELLS}
    for action, _ptr, _end, cells in page1_action_table_entries(rom):
        for addr, d, e in cells:
            label = interesting.get((d, e))
            if label is None:
                continue
            hits_by_label[label].append((action, addr, d, e))
    for _cell, label in PAGE1_ACTION_TABLE_INTERESTING_CELLS:
        hits = hits_by_label[label]
        if hits:
            where = " ".join(f"action {action:02X}@01:{addr:04X}:{fmt_cell(d, e)}" for action, addr, d, e in hits)
        else:
            where = "none"
        print(f"  {label}: {where}")

    print("\ninterpretation")
    print("  79B9 maps only incoming actions 9A..B3 and CC through this page-1 pointer table")
    print("  the table contains fnInt/nDeriv display-name cells 00C8/00C7, plus square-marker cells in later entries")
    print("  it contains no BB24/BB25 parser tokens, no Lintegral direct cells FC3F/0842, and no Lroot literal cell 0010")
    print("  therefore the page-1 action table is a display-cell remap list, not the hidden tall-integral/radical pixel builder")


def dump_overflow_flow(rom):
    print("overflow/erase display ROM anchors")
    for page, addr, hex_bytes, note in OVERFLOW_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow xrefs")
    for target in OVERFLOW_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  3CB7 targets page 01:61C5 (_EraseEOL), not page 3A")
    print("  page-39 overflow handling erases/fills display columns and restores 844C")
    print("  this is a display cleanup/scroll boundary, not a separate MathPrint template-emission page")


def find_pattern_locations(rom, pattern):
    hits = []
    start = 0
    while True:
        off = rom.find(pattern, start)
        if off < 0:
            return hits
        page = off // 0x4000
        within = off % 0x4000
        addr = within + 0x4000
        hits.append((page, addr))
        start = off + 1


def dump_mathprint_mode_flow(rom):
    print("MathPrint/Classic mode ROM anchors")
    for page, addr, hex_bytes, note in MATHPRINT_MODE_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nROM-wide flag-operation hits")
    for label, hex_bytes in MATHPRINT_MODE_PATTERNS:
        pattern = bytes.fromhex(hex_bytes)
        hits = find_pattern_locations(rom, pattern)
        where = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
        print(f"  {label}: {where}")

    print("\ninterpretation")
    print("  01:5A09 lies inside the MATHPRINT string; it is mode-menu data, not executable mode logic")
    print("  02:7AA2/7AB9 are the selectable MATHPRINT/CLASSIC handlers for the mode option table")
    print("  IY+44 bit 5 is the persistent MathPrintActive bit: selecting MATHPRINT sets it, CLASSIC clears it")
    print("  IY+48 bit 0 is the n/d-vs-Un/d fraction-display option, not the MathPrint/Classic selector")


def page_rst28_sites(rom, bcall_id):
    lo = bcall_id & 0xFF
    hi = bcall_id >> 8
    start = romoff(PAGE, 0x4000)
    end = romoff(PAGE, 0x8000)
    sites = []
    for o in range(start, end - 2):
        if rom[o] == 0xEF and rom[o + 1] == lo and rom[o + 2] == hi:
            sites.append(0x4000 + o - start)
    return sites


def dump_draw_primitive_flow(rom):
    print("page-39 draw primitive census")
    for addr, bcall_id, name, note in DRAW_PRIMITIVE_BCALLS:
        actual = rom_bytes(rom, addr, 3)
        expected = bytes((0xEF, bcall_id & 0xFF, bcall_id >> 8))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {name} ({bcall_id:04X}) - {note}")

    print("\nraw-Ghidra page-39 executable RST28 census")
    for addr, bcall_id, name, function, note in DRAW_PRIMITIVE_GHIDRA_RST28_SITES:
        actual = rom_bytes(rom, addr, 3)
        expected = bytes((0xEF, bcall_id & 0xFF, bcall_id >> 8))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {name} ({bcall_id:04X}) in {function} - {note}")

    print("\nraw RST28 byte candidates not lifted as Ghidra RST28 lines")
    for addr, bcall_id, name, note in DRAW_PRIMITIVE_RAW_RST28_CANDIDATES:
        actual = rom_bytes(rom, addr, 3)
        expected = bytes((0xEF, bcall_id & 0xFF, bcall_id >> 8))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {name} ({bcall_id:04X}) - {note}")

    print("\npost-overflow bcall 51F4 target chain")
    for page, addr, hex_bytes, note in DRAW_PRIMITIVE_51F4_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")
    bcall_addr, raw_page = word(rom, 0x3B, 0x51F4), rom[romoff(0x3B, 0x51F6)]
    print(f"  resolved: 51F4 -> {raw_page & 0x3F:02X}:{bcall_addr:04X} (raw page byte {raw_page:02X})")

    print("\npost-overflow 51F4 target local state/display scan")
    window_lo, window_hi = 0x60D1, 0x618E
    for target, label in DRAW_PRIMITIVE_51F4_STATE_WORDS:
        refs = [
            addr for addr in state_word_refs_on_page(rom, 0x35, target)
            if window_lo <= addr < window_hi
        ]
        print(f"  {label}: " + (" ".join(f"{addr:04X}" for addr in refs) or "none"))
    patterns = DRAW_PRIMITIVE_51F4_DISPLAY_PATTERNS + OFFPAGE_DRAW_SERVICE_PATTERNS
    hits = page_pattern_hits_in_range(rom, 0x35, window_lo, window_hi, patterns)
    if hits:
        for label, addr in hits:
            print(f"  display pattern: {label} at 35:{addr:04X}")
    else:
        print("  display pattern: none")

    print("\nRAM-trampoline line primitive target chain")
    for page, addr, hex_bytes, note in DRAW_PRIMITIVE_DARKLINE_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 CALL 3555 (_DarkLine) caller closure")
    direct, words = control_refs(rom, 0x3555)
    direct_map = {addr: op for addr, op in direct}
    for addr, note in sorted(DRAW_PRIMITIVE_DARKLINE_EXPECTED_CALLERS.items()):
        op = direct_map.get(addr)
        status = "ok" if op == "CALL" or op == "CALL Z" else "MISSING"
        print(f"  {addr:04X}: {status} {op or '-'}  {note}")
    unexpected = sorted(set(direct_map) - set(DRAW_PRIMITIVE_DARKLINE_EXPECTED_CALLERS))
    if unexpected:
        print("  unexpected direct callers: " + " ".join(f"{addr:04X}:{direct_map[addr]}" for addr in unexpected))
    else:
        print("  unexpected direct callers: none")

    print("\n_DarkLine caller measured-state scan")
    for lo, hi, label in ((0x4F62, 0x4F99, "post-marker retouch"), (0x67AC, 0x6829, "template chrome")):
        print(f"  {label} {lo:04X}..{hi:04X}")
        for target, state_label in DRAW_PRIMITIVE_DARKLINE_STATE_WORDS:
            refs = [
                addr for addr in state_word_refs_on_page(rom, PAGE, target)
                if lo <= addr < hi
            ]
            print(f"    {state_label}: " + (" ".join(f"{addr:04X}" for addr in refs) or "none"))

    print("\nabsent inline rectangle/fill/image bcalls")
    for bcall_id, name in DRAW_PRIMITIVE_ABSENT_BCALLS:
        sites = page_rst28_sites(rom, bcall_id)
        print(f"  {name} ({bcall_id:04X}): " + (" ".join(f"{s:04X}" for s in sites) or "none"))

    print("\npage-39 display/draw service call targets")
    for target in DRAW_PRIMITIVE_CALL_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  raw Ghidra HTTP reports the executable RST28 set above, with duplicate parent functions collapsed by address")
    print("  the extra raw-byte hit at 4F04 is real bcall 51F4, but it resolves to page 35 display/menu helper code")
    print("  51F4 uses fixed pen coordinates and page-1 display helpers, and has no 85EE/85EF/9D27 measured-state input")
    print("  the extra raw-byte hit at 5D90 is _RestoreDisp inside display-buffer restore wrapper 5D86; see --restore-display-flow")
    print("  CALL 3555 is a real _DarkLine primitive, but all page-39 callers are template chrome or post-marker split/window retouch")
    print("  the only measured-state touch in those callers is the 6803 85EE zero/nonzero empty-template cue guard")
    print("  page 39 does not directly call the large-glyph bjump 3B3D; glyph output reaches page 7 through 3B37")
    print("  rectangle/image drawing in page 39 is limited to template chrome and fraction/descriptor boxes")
    print("  no page-39 rectangle/fill/image/DarkLine primitive remains as a hidden tall radical/integral stretcher")


def dump_graph_table_helper_flow(rom):
    print("graph-table helper / graph-window wrapper ROM anchors")
    for addr, hex_bytes, note in GRAPH_TABLE_HELPER_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow xrefs")
    for target in GRAPH_TABLE_HELPER_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nraw Ghidra identities")
    print("  39:66DC is gr_draw_tbl_glyph")
    print("  39:4833 is gr_set_window_draw")
    print("  39:4822 is gr_save_window_flags")

    print("\ninterpretation")
    print("  gr_draw_tbl_glyph has no page-39 direct or raw xrefs, so it is not the tall-symbol procedural emitter")
    print("  graph-window setup 4833 is called only by 67A0, 6AE4, and 6AF5")
    print("  graph-window restore 4822 is called only by 67A6 and 6AF1")
    print("  those callers are already classified as template chrome and descriptor/fraction rectangle wrappers")


def dump_lcd_capture_flow(rom):
    print("page-39 LCD capture/save ROM anchors")
    for addr, hex_bytes, note in LCD_CAPTURE_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow xrefs")
    for target in LCD_CAPTURE_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  raw Ghidra names 39:5DD8 as bcall _SaveDisp and 39:5DD1 as lcd_screen_shift_capture")
    print("  the direct LCD I/O writes port 10 commands and reads port 11 bytes into the 9872 appBackUpScreen buffer")
    print("  callers reach this path only as display capture/save plumbing around the render loop")
    print("  this path has no token/class dispatch, measured height state, glyph table, or rectangle primitive for tall templates")


def dump_restore_display_flow(rom):
    print("page-39 RestoreDisp wrapper ROM anchors")
    for addr, hex_bytes, note in RESTORE_DISPLAY_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow xrefs")
    for target in RESTORE_DISPLAY_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nROM-wide inline _RestoreDisp bcall hits")
    hits = rom_pattern_hits(rom, bytes.fromhex("ef7048"))
    print("  " + (" ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"))

    print("\nwindow-local state refs")
    for start, end, label in RESTORE_DISPLAY_WINDOWS:
        print(f"  {label} {start:04X}..{end:04X}")
        for target, name in RESTORE_DISPLAY_STATE_WORDS:
            refs = [
                addr for addr in page_word_refs(rom, PAGE, target)
                if start <= addr < end
            ]
            where = " ".join(f"{addr:04X}" for addr in refs) or "none"
            print(f"    {name}: {where}")

    print("\nraw Ghidra identities")
    print("  raw HTTP does not split 39:5D86 as a function, but xrefs prove it is reachable code")
    print("  39:5DD8 remains the direct _SaveDisp LCD capture body covered by --lcd-capture-flow")

    print("\ninterpretation")
    print("  5D86 only restores a saved LCD buffer after clearing/restoring (IY+14) bit 1")
    print("  its callers are dispatch/menu/context display cleanup paths using 9872 or 86EC buffers")
    print("  local windows contain no 85EE/85EF/9D27 measured-template state")
    print("  this closes page-39 _RestoreDisp as display-buffer plumbing, not a tall-template emitter")


def dump_draw_mode_callback_flow(rom):
    print("draw-mode callback ROM anchors")
    for page, addr, hex_bytes, note in DRAW_MODE_CALLBACK_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        shown_addr = addr if addr >= 0x4000 else addr
        print(f"  {page:02X}:{shown_addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-local control-flow xrefs")
    for page, target in DRAW_MODE_CALLBACK_XREF_TARGETS:
        direct, words = control_refs_on_page(rom, page, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {page:02X}:{target:04X}: direct {refs}; raw {raw}")

    print("\nlocal state and draw-service scan")
    for page, lo, hi, label in DRAW_MODE_CALLBACK_WINDOWS:
        print(f"  {label} {page:02X}:{lo:04X}..{hi:04X}")
        any_state = False
        for target, state_label in DRAW_MODE_CALLBACK_STATE_WORDS:
            refs = [
                addr for addr in state_word_refs_on_page(rom, page, target)
                if lo <= addr < hi
            ]
            if refs:
                any_state = True
                print(f"    {target:04X} {state_label}: " + " ".join(f"{addr:04X}" for addr in refs))
        if not any_state:
            print("    measured/pen/callback state refs: none")
        hits = page_pattern_hits_in_range(
            rom,
            page,
            lo,
            hi,
            OFFPAGE_DRAW_SERVICE_PATTERNS,
        )
        if hits:
            for service_label, addr in hits:
                print(f"    {service_label}: {addr:04X}")
        else:
            print("    draw/display services: none")

    print("\ninterpretation")
    print("  ram/page-0 2CBB is a cross-page callback to page 3B:7CA8")
    print("  page-39 uses 2CBB only at draw-pass gates guarded by (IY+36) bit 6")
    print("  page 3B stores/checks HL/A triples in 9Bxx state slots and clears the matching draw-pass bit")
    print("  local callback windows have no 85EE/85EF/9D27 measured geometry and no draw/display services")
    print("  this callback is state/pointer validation, not a glyph, rectangle, or measured tall-template emitter")


def map_token_glyph_cell(d, e):
    if d == 0xFC and e < 0x41:
        if e < 0x3C:
            return None
        return e - 0x37
    if d == 0xFE and e < 0x82:
        if e < 0x7D:
            return None
        return e - 0x7D
    if e == 0x42 and d < 0x0A:
        return d
    return None


def dump_glyph_emission_flow(rom):
    print("glyph/cell emission ROM anchors")
    for page, addr, hex_bytes, note in GLYPH_EMISSION_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow xrefs")
    for target in GLYPH_EMISSION_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nsample decoded-cell mapper results")
    for d, e in ((0x00, 0xC8), (0x00, 0xC7), (0xFB, 0xC8), (0xFB, 0xCA),
                 (0xFE, 0x7D), (0xFE, 0x81), (0xFC, 0x3C), (0xFC, 0x40),
                 (0xFC, 0x3F), (0x00, 0x42), (0x08, 0x42)):
        mapped = map_token_glyph_cell(d, e)
        if mapped is None:
            print(f"  {fmt_cell(d, e)}: not directly mapped by 4F1A")
        else:
            print(f"  {fmt_cell(d, e)}: 4F1A maps to large-font code {mapped:02X}")

    print("\ndecoded records with direct 4F1A large-font cells")
    found = False
    for cls in range(HANDLER_COUNT):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            continue
        for item in record["items"]:
            hits = []
            for idx, (d, e) in enumerate(item["cells"]):
                mapped = map_token_glyph_cell(d, e)
                if mapped is not None:
                    hits.append((idx, d, e, mapped))
            if not hits:
                continue
            found = True
            cells = " ".join(
                f"cell {idx} {fmt_cell(d, e)}->L{mapped:02X}"
                for idx, d, e, mapped in hits
            )
            print(f"  class {cls:02X} ptr {ptr:04X} row {item['row']}: {cells}")
    if not found:
        print("  none")

    print("\ninterpretation")
    print("  00C8/00C7 are display-name cells, not direct 4F1A glyph mappings")
    print("  FC3F and 0842 are direct Lintegral glyph cells in class 0D, separate from the fnInt display-name cell")
    print("  FBCA/FBCB/FBD6/FBD8/FBD7 are the only FB cells copied as page-39 menu/answer strings by 6B62")
    print("  page-7 4588 is fixed 7-byte-stride / 8-byte-record glyph copy machinery, not a tall-symbol stretch routine")


def dump_cell_emission_algorithm_flow(rom):
    print("cell-emission algorithm ROM anchors")
    for addr, hex_bytes, note in CELL_EMISSION_ALGORITHM_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow closure")
    for target, label in CELL_EMISSION_ALGORITHM_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X} {label}: direct {refs}; raw {raw}")

    print("\n4E8E branch algorithm")
    print("  if D == 1F: use the IX-backed OP/string special form, emit it, then run the overflow row cleanup")
    print("  else if D == 82: convert E-3E to an indexed string through bjump 3B2B")
    print("  else: classify delimiter-pair cells through 6675")
    print("  after delimiter classification, bit 6 of (IY+36) may call the page-3B draw-state callback 2CBB")
    print("  then non-direct cells may call 6B66 and _PutPSB; direct fixed glyph cells call 4F1A and RST28 _PutMap-style output")
    print("  the tail handles line overflow through 3CB7, then checks FB C8/FB C7 marker gates at 4F44 and row retouch at 4F62")

    print("\ndirect-glyph classifier examples")
    for d, e in ((0xFC, 0x3F), (0x08, 0x42), (0x00, 0x10), (0x00, 0xC8), (0xFB, 0xC8)):
        mapped = map_token_glyph_cell(d, e)
        if mapped is None:
            print(f"  {fmt_cell(d, e)}: string/control path, not direct 4F1A glyph")
        else:
            print(f"  {fmt_cell(d, e)}: direct fixed large-font glyph L{mapped:02X}")

    print("\ninterpretation")
    print("  cell emission is a fixed branch algorithm over the two-byte display cell D:E")
    print("  its only direct fixed-glyph path is the 4F1A classifier: FC3C..40, FE7D..81, and xx42")
    print("  Lroot 0010 and fnInt 00C8 do not enter the direct glyph path; they use string/control handling")
    print("  the overflow and square-marker tail has no measured-height input, repeat count, or variable line/fill primitive")
    print("  this closes the decoded-cell emission algorithm; tall-symbol placement must be before the final cell stream or in a dynamic pen trace")


def dump_suffix_1f_flow(rom):
    print("1F-suffix/template-cell ROM anchors")
    for addr, hex_bytes, note in SUFFIX_1F_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ndecoded cells with high byte D=1F")
    found = False
    for cls in range(HANDLER_COUNT):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            continue
        for item in record["items"]:
            hits = [(idx, d, e) for idx, (d, e) in enumerate(item["cells"]) if d == 0x1F]
            if not hits:
                continue
            found = True
            cells = " ".join(f"{idx}:{fmt_cell(d, e)}" for idx, d, e in hits)
            print(f"  class {cls:02X} ptr {ptr:04X} row {item['row']} action={item['action']:02X} {cells}")
    if not found:
        print("  none")

    print("\ndecoded cells with low byte E=1F")
    for cls in range(HANDLER_COUNT):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            continue
        for item in record["items"]:
            hits = [(idx, d, e) for idx, (d, e) in enumerate(item["cells"]) if e == 0x1F]
            if not hits:
                continue
            cells = " ".join(f"{idx}:{fmt_cell(d, e)}" for idx, d, e in hits)
            print(f"  class {cls:02X} ptr {ptr:04X} row {item['row']} action={item['action']:02X} {cells}")

    print("\n1F-suffix mapper results")
    for d, e in ((0x1F, 0x12), (0x00, 0x1F), (0x06, 0x1F), (0x0C, 0x1F),
                 (0xFE, 0x1F), (0xFC, 0x1F)):
        mapped = map_token_glyph_cell(d, e)
        if mapped is None:
            print(f"  {fmt_cell(d, e)}: not directly mapped by 4F1A")
        else:
            print(f"  {fmt_cell(d, e)}: 4F1A maps to large-font code {mapped:02X}")

    print("\ninterpretation")
    print("  D=1F and E=1F are separate cases; only D=1F takes the IX/RST20 special path at 4E8E")
    print("  root/power and fnInt-related 1F cells are low-byte E=1F cells, so they use generic token-string output")
    print("  low-byte E=1F cells are not direct 4F1A large-glyph mappings and do not enter the D=1F special path")
    print("  this explains the template-family cell emission path, but still does not name the measured tall-symbol caller")


def dump_key_string_1f_flow(rom):
    print("low-byte 1F key-string ROM anchors")
    for page, addr, hex_bytes, note in KEY_STRING_1F_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nroot/power low-byte 1F table-index samples")
    for d, e in KEY_STRING_1F_SAMPLE_CELLS:
        if e == 0x1F:
            idx = (0x50 + d) & 0xFF
            table = 0x6E05 + 2 * idx
            ptr = word(rom, 0x01, table)
            print(f"  {fmt_cell(d, e)}: _KeyToString index {idx:02X}, table {table:04X} -> ptr {ptr:04X}")
        else:
            print(f"  {fmt_cell(d, e)}: not a low-byte 1F sample")

    print("\npage-39 xrefs")
    for target in (0x6B66, 0x4E8E, 0x4F1A):
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  low-byte E=1F root/power cells are converted by _KeyToString at page 01:6D10")
    print("  _KeyToString computes table index 50+D for E=1F, then copies a token string")
    print("  this path produces display strings through _PutPSB; it has no dimension input or draw primitive for tall stretching")


def key_to_string_index(d, e):
    if d in (0xFF, 0xFE, 0xFC, 0xFB):
        return None, "prefix dispatch"
    if e >= 0x5A:
        return None, "control dispatch"
    if e == 0x1F:
        return (0x50 + d) & 0xFF, "E=1F special: 50+D"
    if e >= 0x40:
        if e == 0x59:
            return (0x61 + d) & 0xFF, "E=59 special: 61+D"
        if e == 0x40 and d == 0x10:
            return None, "special literal at 6F4D"
        if e == 0x4C:
            return (0x5F + d) & 0xFF, "E=4C special: 5F+D"
        if e in (0x56, 0x42):
            value = (e + 0x16 + d - 0x1B - 0x10) & 0xFF
            return value if value <= 0x64 else 0x13, "E=56/42 adjusted path"
        value = (e - 0x1B - 0x10) & 0xFF
        return value if value <= 0x64 else 0x13, "E>=40 adjusted path"
    value = (e - 0x10) & 0xFF
    return value if value <= 0x64 else 0x13, "ordinary E-10 path"


def printable_counted_string(rom, page, addr):
    for start in (addr, addr + 1):
        size = rom_bytes_at(rom, page, start, 1)[0]
        if size > 18:
            continue
        data = rom_bytes_at(rom, page, start + 1, size)
        if data.endswith(b"\xCE"):
            data = data[:-1]
        if all(0x20 <= byte < 0x7F for byte in data):
            return start, data.decode("ascii")
    return None, None


def dump_key_string_structural_flow(rom):
    print("structural-cell _KeyToString boundary ROM anchors")
    for page, addr, hex_bytes, note in KEY_STRING_STRUCTURAL_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\n_KeyToString structural-cell samples")
    for d, e, note in KEY_STRING_STRUCTURAL_SAMPLE_CELLS:
        idx, rule = key_to_string_index(d, e)
        print(f"  {fmt_cell(d, e)}: {note}")
        if idx is None:
            print(f"    index: none ({rule})")
            continue
        table = 0x6E05 + 2 * idx
        ptr = word(rom, 0x01, table)
        raw = rom_bytes_at(rom, 0x01, ptr, 12)
        text_start, text = printable_counted_string(rom, 0x01, ptr)
        print(f"    index: {idx:02X} by {rule}; table 01:{table:04X} -> ptr {ptr:04X}")
        print(f"    ptr bytes: {raw.hex().upper()}")
        if text is not None:
            print(f"    counted ASCII at {text_start:04X}: {text!r}")
        else:
            print("    counted ASCII: none at ptr/ptr+1")

    root_records = cell_record_locations(rom, (0x00, 0x10))
    print("\n0010 root/power provenance")
    print("  records: " + (", ".join(root_records) or "none"))
    print("  direct 4F1A glyph: " + ("yes" if map_token_glyph_cell(0x00, 0x10) is not None else "no"))
    print("  fixed page-7 Lroot bytes: " + rom_bytes_at(rom, 0x07, 0x466F, 7).hex().upper())

    print("\ninterpretation")
    print("  0010 is ROM-backed as a root/power handler-record cell and page-7 fixed Lroot glyph bytes")
    print("  but 0010 is not a direct 4F1A glyph cell; if treated as ordinary _KeyToString, it indexes the 'All+' string")
    print("  therefore the current tall-root renderer is glyph-data-backed, with row placement delegated to the 5167 compositor")


def dump_lroot_final_emitter_boundary_flow(rom):
    print("Lroot final-emitter boundary verifier")
    for page, addr, hex_bytes, note in LROOT_FINAL_EMITTER_BOUNDARY_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\n0010 provenance and final-emitter classification")
    records = cell_record_locations(rom, (0x00, 0x10))
    descriptors = cell_descriptor_locations(rom, (0x00, 0x10))
    mapped = map_token_glyph_cell(0x00, 0x10)
    idx, rule = key_to_string_index(0x00, 0x10)
    table = 0x6E05 + 2 * idx if idx is not None else None
    ptr = word(rom, 0x01, table) if table is not None else None
    text_start, text = printable_counted_string(rom, 0x01, ptr) if ptr is not None else (None, None)
    print("  decoded records: " + (", ".join(records) or "none"))
    print("  decoded descriptors: " + (", ".join(descriptors) or "none"))
    delimiter_hits = delimiter_family_locations(rom, (0x00, 0x10))
    print("  delimiter family membership: " + (", ".join(delimiter_hits) or "none"))
    print("  4F1A direct glyph: " + (f"L{mapped:02X}" if mapped is not None else "no"))
    if idx is None:
        print(f"  _KeyToString index: none ({rule})")
    else:
        print(f"  _KeyToString index: {idx:02X} by {rule}; table 01:{table:04X} -> ptr {ptr:04X}")
        print(f"  _KeyToString counted text: {text!r} at 01:{text_start:04X}")
    print("  page-7 Lroot glyph bytes: " + rom_bytes_at(rom, 0x07, 0x466F, 7).hex().upper())

    print("\nroot row-action separation")
    for cls in (0x29, 0x2A, 0x31):
        ptr, record = parse_handler_record(rom, cls)
        print(f"  class {cls:02X} ptr {ptr:04X}")
        for item in record["items"]:
            label_ptr, label = page_indexed_string(rom, item["action"])
            payload = " ".join(fmt_cell(d, e) for d, e in item["cells"][:4])
            print(
                f"    row {item['row']} action={item['action']:02X} "
                f"label={label!r} label_ptr={label_ptr:04X} payload {payload}"
            )

    print("\ndraw-mode callback closure for the final cell emitter")
    direct, words = control_refs(rom, 0x2CBB)
    print("  page-39 2CBB callers: " + (" ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"))
    print("  page-39 2CBB raw refs: " + (" ".join(f"{addr:04X}" for addr in words) or "none"))
    for lo, hi, label in (
        (0x4EC8, 0x4EEC, "cell-emitter callback window"),
        (0x7CA8, 0x7CBC, "page-3B callback checker"),
    ):
        page = PAGE if lo < 0x8000 and label.startswith("cell") else 0x3B
        print(f"  {label} {page:02X}:{lo:04X}..{hi:04X}")
        for target, state_label in ((0x85EE, "85EE"), (0x85EF, "85EF"), (0x9D27, "9D27"), (0x86D7, "86D7")):
            refs = [
                addr for addr in state_word_refs_on_page(rom, page, target)
                if lo <= addr < hi
            ]
            print(f"    {state_label}: " + (" ".join(f"{addr:04X}" for addr in refs) or "none"))
        hits = page_pattern_hits_in_range(
            rom,
            page,
            lo,
            hi,
            [
                ("CALL 3B37 display-byte mapper", "cd373b"),
                ("CALL 3B3D large-glyph blitter", "cd3d3b"),
                ("CALL 3CDB VPutMap", "cddb3c"),
                ("CALL 3555 _DarkLine", "cd5535"),
                ("RST28 _PutPSB", "ef0d45"),
                ("RST28 _KeyToString", "efca45"),
                ("RST28 _DrawRectBorder", "ef7d4d"),
                ("RST28 _DrawRectBorderClear", "ef8c4d"),
            ],
        )
        print("    draw/display patterns: " + (" ".join(f"{addr:04X}:{name}" for name, addr in hits) or "none"))

    print("\ninterpretation")
    print("  0010 is a ROM-backed root/power payload cell and the fixed Lroot glyph bytes exist on page 7")
    print("  but 0010 is not a descriptor cell, delimiter cell, or direct 4F1A large-glyph cell")
    print("  if it falls through the ordinary string path, _KeyToString selects 'All+', not Lroot")
    print("  row actions 62/48 are labels/control metadata and are skipped before 4E8E sees payload cells")
    print("  the 2CBB draw-mode callback around 4E8E is state validation with no measured geometry or glyph/rule output")
    print("  therefore final generic cell emission cannot be the Lroot/vinculum builder; the special root caller must be upstream or dynamic")


def dump_template_tracepoint_flow(rom):
    print("template-emission dynamic tracepoint ROM anchors")
    for page, addr, hex_bytes, note in TEMPLATE_TRACEPOINT_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nminimal breakpoint manifest")
    for addr, purpose, capture in TEMPLATE_TRACEPOINTS:
        print(f"  {addr}: {purpose}; capture {capture}")

    print("\ntrace proof target")
    print("  render fnInt(sqrt(X^2+1),X,1/2,3^2) and fnInt(sqrt((X^2+1)/X),X,1/2,3^2)")
    print("  record the ordered events at 4E8E/4EEA/07:4588 for glyph codes 08, 10, C6 and delimiter cells")
    print("  record 39:6ABF/6B1C/6AF5 rectangle endpoints for fraction bars, radical bars, boxes, and focus rectangles")
    print("  record 01:6293 VPutMap calls to separate small labels/limits from large structural glyphs")
    print("  the missing algorithm is proved only when these dynamic events explain final integral/root/delimiter pixels")
    print("  without an emulator trace, the current static evidence remains a closed-boundary proof rather than full recovery")


def dump_rectangle_rule_event_flow(rom):
    print("rectangle/rule event ROM anchors")
    for page, addr, hex_bytes, note in RECTANGLE_RULE_EVENT_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncaller closure")
    for target, expected in RECTANGLE_RULE_EXPECTED_CALLERS.items():
        direct, words = control_refs(rom, target)
        direct_map = {addr: op for addr, op in direct}
        print(f"  {target:04X}")
        for addr, note in sorted(expected.items()):
            op = direct_map.get(addr)
            status = op if op is not None else "MISSING"
            print(f"    {addr:04X}: {status}  {note}")
        unexpected = sorted(set(direct_map) - set(expected))
        raw_expected = {addr + 1 for addr in expected}
        raw_unexpected = sorted(set(words) - raw_expected)
        print("    unexpected direct callers: " + (" ".join(f"{addr:04X}" for addr in unexpected) or "none"))
        print("    unexpected raw word refs: " + (" ".join(f"{addr:04X}" for addr in raw_unexpected) or "none"))

    print("\n6B1C endpoint samples")
    for count, left, right, note in RECTANGLE_RULE_ENDPOINT_SAMPLES:
        computed_left = 0x1B + 7 * count
        computed_right = computed_left + 4
        status = "ok" if (computed_left, computed_right) == (left, right) else "MISMATCH"
        print(f"  n={count}: {status} L={computed_left:02X} E={computed_right:02X}  {note}")

    print("\nkind-2 rectangle event sequence")
    print("  action 1/2: adjust C column within 0..5, then use the shared erase/store/redraw pair")
    print("  action 3/4: adjust B row within 0..2, then use the shared erase/store/redraw pair")
    print("  first 6ABF call is preceded by SCF, so it erases the old rectangle through _EraseRectBorder")
    print("  second 6ABF call is preceded by OR A after storing 85DF, so it draws the new rectangle through _DrawRectBorder")
    print("  6AF5 callers are descriptor/fraction box draws only; no radical/integral caller reaches this box wrapper")

    print("\ninterpretation")
    print("  every static 6ABF/6B1C event is kind-2 fraction-template UI geometry or focus inversion")
    print("  if a later dynamic trace shows radical/integral bars, they must appear as different draw events or off-page calls")
    print("  this gives the dynamic trace a concrete filter: discard the closed fraction UI rectangle pair before looking for tall-symbol bars")


def dump_large_font_flow(rom):
    print("page-7 large-font display ROM anchors")
    for addr, hex_bytes, note in LARGE_FONT_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, 0x07, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  07:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ninterpretation")
    print("  _PutMap starts from code*8, but 07:45EB subtracts code to address the 7-byte-stride table")
    print("  07:4588 then copies a fixed 8-byte render record into 845A through _Mov8B")
    print("  07:45FB is a fixed 7-iteration shifted-copy helper, not a variable-height symbol stretcher")
    print("  no page-7 large-font path here measures radicand height or builds tall integral/radical pieces")


def page7_display_byte_map(rom, d, e):
    if d == 0xFE:
        if e < 0x69:
            return (0x00, rom_bytes_at(rom, 0x07, 0x4099 + e, 1)[0], "FE one-byte table 4099")
        idx = e - 0x69
        raw = rom_bytes_at(rom, 0x07, 0x4102 + 2 * idx, 2)
        return (raw[0], raw[1], "FE pair table 4102")
    if d == 0xFC:
        raw = rom_bytes_at(rom, 0x07, 0x422C + 2 * e, 2)
        return (raw[0], raw[1], "FC pair table 422C")
    if d == 0xFB:
        idx = e - 0x7F if e >= 0x8C else e
        raw = rom_bytes_at(rom, 0x07, 0x4426 + 2 * idx, 2)
        return (raw[0], raw[1], "FB pair table 4426")
    if d == 0x05:
        return (0x00, 0x3F, "special A=05")
    if d >= 0x5A:
        raw = rom_bytes_at(rom, 0x07, 0x4000 + d - 0x5A, 1)
        return (0x00, raw[0], "ordinary one-byte table 4000")
    return None


def dump_display_byte_map_flow(rom):
    print("page-7 display-byte classifier ROM anchors")
    for addr, hex_bytes, note in DISPLAY_BYTE_MAP_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, 0x07, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  07:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nclassifier tables")
    for addr, note in DISPLAY_BYTE_MAP_TABLES:
        raw = rom_bytes_at(rom, 0x07, addr, 16)
        print(f"  07:{addr:04X}: {raw.hex().upper()}  {note}")

    print("\nsample cell mappings")
    for d, e, note in DISPLAY_BYTE_MAP_SAMPLES:
        mapped = page7_display_byte_map(rom, d, e)
        if mapped is None:
            print(f"  {fmt_cell(d, e)}: not a valid direct input to 07:44DE  {note}")
            continue
        md, me, source = mapped
        print(f"  {fmt_cell(d, e)} -> {fmt_cell(md, me)} via {source}  {note}")

    print("\ninterpretation")
    print("  07:44DE is a prefix/display-byte remapper, not a variable-height glyph builder")
    print("  FE/FC/FB cells use fixed ROM lookup tables; ordinary inputs are only valid for A>=5A")
    print("  fnInt display cells 00C8/00C7 and 0842/0010 structural cells do not enter this table path")
    print("  this keeps the off-page display-byte boundary separate from the missing measured tall-symbol caller")


def dump_offpage_render_flow(rom):
    print("off-page render-service ROM anchors")
    for page, addr, hex_bytes, note in OFFPAGE_RENDER_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nROM-wide pattern hits")
    for label, hex_bytes in OFFPAGE_RENDER_PATTERNS:
        hits = find_pattern_locations(rom, bytes.fromhex(hex_bytes))
        where = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
        print(f"  {label}: {where}")

    print("\noff-page measured-state references")
    for target, label in ((0x85EE, "85EE"), (0x9D27, "9D27")):
        hits = []
        pattern = bytes((target & 0xFF, target >> 8))
        start = 0
        while True:
            off = rom.find(pattern, start)
            if off < 0:
                break
            page = off // 0x4000
            addr = (off % 0x4000) + 0x4000
            if page != PAGE:
                hits.append((page, addr, rom[off - 1] if off else 0))
            start = off + 1
        where = " ".join(f"{page:02X}:{addr:04X}/prev={prev:02X}" for page, addr, prev in hits) or "none"
        print(f"  {label}: {where}")

    print("\ninterpretation")
    print("  _PutMap/_LoadPattern/page-7 large-font paths use code*8 -> 45FF+code*7 and fixed 8-row records")
    print("  ROM-wide _FillRect/_FillRectPattern/_DisplayImage inline bcalls are absent, so no hidden fill/image-based stretcher exists")
    print("  off-page 9D27 writes at 35:734E and 37:6D30 seed the default 0202 measurement during reset/startup")
    print("  use --offpage-85ee-candidate-flow to classify the remaining page-33/page-34 85EE refs")


def dump_glyph_service_closed_flow(rom):
    print("generic glyph/display service closed-world audit")
    for page, addr, hex_bytes, note in GLYPH_SERVICE_CLOSED_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nROM-wide 3B3D large-glyph bjump callers")
    hits = find_pattern_locations(rom, bytes.fromhex("cd3d3b"))
    known = {(page, addr): (name, note) for page, addr, name, note in GLYPH_SERVICE_CLOSED_CALLS}
    for page, addr in hits:
        name, note = known.get((page, addr), ("unclassified", "unexpected caller"))
        print(f"  {page:02X}:{addr:04X}: {name} - {note}")
    missing = sorted(set(known) - set(hits))
    if missing:
        print("  missing expected callers: " + " ".join(f"{page:02X}:{addr:04X}" for page, addr in missing))

    print("\nROM-wide fill/image primitive absence")
    for label, hex_bytes in GLYPH_SERVICE_ABSENT_PATTERNS:
        hits = find_pattern_locations(rom, bytes.fromhex(hex_bytes))
        where = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
        print(f"  {label}: {where}")

    print("\noff-page measured-state word refs")
    for target, label in ((0x85EE, "85EE"), (0x85EF, "85EF"), (0x9D27, "9D27")):
        refs = []
        for page in range(len(rom) // 0x4000):
            for addr in page_word_refs(rom, page, target):
                if page == PAGE:
                    continue
                off = romoff(page, addr)
                prev = rom[off - 1] if off > 0 else 0
                refs.append((page, addr, prev))
        where = " ".join(f"{page:02X}:{addr:04X}/prev={prev:02X}" for page, addr, prev in refs) or "none"
        print(f"  {label}: {where}")

    print("\nraw Ghidra identities")
    print("  01:5A98 is _PutMap; 01:6267 is _LoadPattern; 07:4588 is put_glyph_large")
    print("  06:7F66 and off-page 85EE refs are not split as relevant Ghidra functions in this database")

    print("\ninterpretation")
    print("  every ROM-wide 3B3D caller feeds a fixed code*8 glyph/pattern service, not measured template geometry")
    print("  page 07:4588 adjusts code*8 to 45FF+code*7 and copies one fixed 8-byte render record to 845A")
    print("  ROM-wide inline _FillRect/_FillRectPattern/_DisplayImage bcalls are absent")
    print("  generic off-page glyph/display services do not read 9D27 and do not build variable-height symbol pieces")


def dump_large_glyph_caller_flow(rom):
    print("large-glyph bjump caller-window audit")
    for page, addr, name, note in GLYPH_SERVICE_CLOSED_CALLS:
        actual = rom_bytes_banked(rom, page, addr, 3)
        status = "ok" if actual == bytes.fromhex("cd3d3b") else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {name}: {note}")

    print("\nROM-wide CALL 3B3D caller set")
    hits = find_pattern_locations(rom, bytes.fromhex("cd3d3b"))
    known = {(page, addr) for page, addr, _name, _note in GLYPH_SERVICE_CLOSED_CALLS}
    where = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
    print(f"  callers: {where}")
    unexpected = sorted(set(hits) - known)
    print("  unexpected callers: " + (" ".join(f"{page:02X}:{addr:04X}" for page, addr in unexpected) or "none"))

    print("\ncaller local state/draw scans")
    for page, lo, hi, label in LARGE_GLYPH_CALLER_WINDOWS:
        print(f"  {page:02X}:{lo:04X}..{hi:04X} {label}")
        for target, state_label in LARGE_GLYPH_CALLER_STATE_WORDS:
            refs = [
                addr for addr in state_word_refs_on_page(rom, page, target)
                if lo <= addr < hi
            ]
            print(f"    {target:04X} {state_label}: " + (" ".join(f"{page:02X}:{addr:04X}" for addr in refs) or "none"))
        hits = page_pattern_hits_in_range(rom, page, lo, hi, LARGE_GLYPH_CALLER_DRAW_PATTERNS)
        if hits:
            for pattern_label, addr in hits:
                print(f"    pattern {page:02X}:{addr:04X}: {pattern_label}")
        else:
            print("    pattern: none")

    print("\nraw Ghidra identities")
    print("  raw HTTP identifies 01:5A98 as _PutMap and 01:6267 as _LoadPattern")
    print("  raw HTTP identifies 07:4588 as put_glyph_large")
    print("  page 06:7F66 is an unsplit helper whose bytes are fixed code*8 -> CALL 3B3D -> RET")

    print("\ninterpretation")
    print("  the complete ROM-wide 3B3D caller set is fixed and has no unexpected callers")
    print("  caller windows contain no 85EE/85EF/9D27 and no fill/image/line draw primitive")
    print("  page-7 put_glyph_large copies one fixed 8-byte render record; it is not a measured tall-symbol builder")


def dump_indexed_string_caller_flow(rom):
    print("indexed-string bjump caller/body audit")
    for page, addr, hex_bytes, note in INDEXED_STRING_CALLER_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nROM-wide CALL 3B2B caller set")
    callers = find_pattern_locations(rom, bytes.fromhex("cd2b3b"))
    expected = {(page, addr) for page, addr, _note in INDEXED_STRING_EXPECTED_CALLERS}
    actual = set(callers)
    for page, addr, note in INDEXED_STRING_EXPECTED_CALLERS:
        present = "ok" if (page, addr) in actual else "MISSING"
        print(f"  {page:02X}:{addr:04X}: {present}  {note}")
    unexpected = sorted(actual - expected)
    missing = sorted(expected - actual)
    print("  unexpected callers: " + (" ".join(f"{page:02X}:{addr:04X}" for page, addr in unexpected) or "none"))
    print("  missing callers: " + (" ".join(f"{page:02X}:{addr:04X}" for page, addr in missing) or "none"))

    print("\ncaller windows with measured/template state within +/-0x60")
    any_state = False
    for page, addr in callers:
        lo = max(0x4000, addr - 0x60)
        hi = min(0x8000, addr + 0x63)
        refs_by_word = []
        for target, label in INDEXED_STRING_CALLER_STATE_WORDS:
            refs = [
                ref for ref in state_word_refs_on_page(rom, page, target)
                if lo <= ref < hi
            ]
            if refs and target in INDEXED_STRING_MEASURED_WORDS:
                refs_by_word.append((target, label, refs))
        if not refs_by_word:
            continue
        any_state = True
        print(f"  {page:02X}:{addr:04X} window {lo:04X}..{hi:04X}")
        for target, label, refs in refs_by_word:
            print(f"    {target:04X} {label}: " + " ".join(f"{page:02X}:{ref:04X}" for ref in refs))
        hits = page_pattern_hits_in_range(rom, page, lo, hi, INDEXED_STRING_CALLER_DRAW_PATTERNS)
        for pattern_label, hit in hits:
            print(f"    pattern {page:02X}:{hit:04X}: {pattern_label}")
    if not any_state:
        print("  none")

    print("\nall caller local state/draw scans")
    for page, addr, note in INDEXED_STRING_EXPECTED_CALLERS:
        lo = max(0x4000, addr - 0x60)
        hi = min(0x8000, addr + 0x63)
        print(f"  {page:02X}:{addr:04X} window {lo:04X}..{hi:04X} {note}")
        for target, label in INDEXED_STRING_CALLER_STATE_WORDS:
            refs = [
                ref for ref in state_word_refs_on_page(rom, page, target)
                if lo <= ref < hi
            ]
            print(f"    {target:04X} {label}: " + (" ".join(f"{page:02X}:{ref:04X}" for ref in refs) or "none"))
        hits = page_pattern_hits_in_range(rom, page, lo, hi, INDEXED_STRING_CALLER_DRAW_PATTERNS)
        if hits:
            for pattern_label, hit in hits:
                print(f"    pattern {page:02X}:{hit:04X}: {pattern_label}")
        else:
            print("    pattern: none")

    print("\nput_indexed_string body state refs")
    page, lo, hi = 0x01, 0x7183, 0x71A1
    for target, label in INDEXED_STRING_CALLER_STATE_WORDS:
        refs = [
            ref for ref in state_word_refs_on_page(rom, page, target)
            if lo <= ref < hi
        ]
        print(f"  {target:04X} {label}: " + (" ".join(f"01:{ref:04X}" for ref in refs) or "none"))

    print("\nraw Ghidra identity")
    print("  raw HTTP identifies 01:7183 as put_indexed_string; decompilation indexes table 71A1 and prints the selected string")

    print("\ninterpretation")
    print("  every ROM-wide 3B2B caller is accounted for and all callers are on page 39")
    print("  caller windows contain row/menu-title state but no measured 85E8/85E9/85EB/85EC/85EE/85EF/9D27 template-state cluster")
    print("  page-1 put_indexed_string has no measured template refs and only resolves/prints fixed indexed strings")
    print("  this closes 3B2B/page-1 indexed-string output as row-label/string emission, not final tall integral/radical construction")


def dump_generic_string_caller_flow(rom):
    print("generic string/_PutPSB caller/body audit")
    for page, addr, hex_bytes, note in GENERIC_STRING_CALLER_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 direct string-output closure")
    targets = [
        (0x6B66, "generic string selector"),
        (0x6B62, "descriptor FB string selector"),
    ]
    for target, label in targets:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X} {label}: direct {refs}; raw {raw}")

    page39_putpsb = page_rst28_sites(rom, 0x450D)
    page39_key = page_rst28_sites(rom, 0x45CA)
    print("  RST28 _PutPSB page-39 sites: " + (" ".join(f"{addr:04X}" for addr in page39_putpsb) or "none"))
    print("  RST28 _KeyToString page-39 sites: " + (" ".join(f"{addr:04X}" for addr in page39_key) or "none"))

    expected_sites = {addr: label for addr, label in GENERIC_STRING_PAGE39_EXPECTED}
    actual_sites = {addr for addr, _op in control_refs(rom, 0x6B66)[0]}
    actual_sites |= {addr for addr, _op in control_refs(rom, 0x6B62)[0]}
    actual_sites |= set(page39_putpsb)
    actual_sites |= set(page39_key)
    missing = sorted(set(expected_sites) - actual_sites)
    unexpected = sorted(actual_sites - set(expected_sites))
    print("  expected sites: " + " ".join(f"{addr:04X}:{label}" for addr, label in sorted(expected_sites.items())))
    print("  missing expected sites: " + (" ".join(f"{addr:04X}" for addr in missing) or "none"))
    print("  unexpected page-39 sites: " + (" ".join(f"{addr:04X}" for addr in unexpected) or "none"))

    print("\nlocal measured/template state windows")
    windows = [
        (0x39, 0x4ECB, 0x4F08, "decoded-cell generic string/_PutPSB tail"),
        (0x39, 0x6B62, 0x6BA8, "page-39 FB string selector and _KeyToString fallback"),
        (0x01, 0x6D10, 0x6DBC, "page-1 _KeyToString body"),
    ]
    for page, lo, hi, label in windows:
        print(f"  {page:02X}:{lo:04X}..{hi:04X} {label}")
        for target, state_label in GENERIC_STRING_STATE_WORDS:
            refs = [
                ref for ref in state_word_refs_on_page(rom, page, target)
                if lo <= ref < hi
            ]
            print(f"    {target:04X} {state_label}: " + (" ".join(f"{page:02X}:{ref:04X}" for ref in refs) or "none"))
        hits = page_pattern_hits_in_range(rom, page, lo, hi, GENERIC_STRING_PATTERNS)
        if hits:
            for pattern_label, hit in hits:
                print(f"    pattern {page:02X}:{hit:04X}: {pattern_label}")
        else:
            print("    pattern: none")

    print("\nselected string cells")
    for d, e, note in (
        (0xFB, 0xCA, "n/d menu string"),
        (0xFB, 0xCB, "Un/d menu string"),
        (0xFB, 0xD6, "AUTO answer-mode string"),
        (0xFB, 0xD8, "FRAC answer-mode string"),
        (0xFB, 0xD7, "DEC answer-mode string"),
        (0x00, 0xC8, "fnInt display-name cell"),
        (0x00, 0x10, "root/power Lroot record cell"),
        (0x06, 0x1F, "low-byte 1F root/power cell"),
    ):
        idx, rule = key_to_string_index(d, e)
        if d == 0xFB and e in (0xCA, 0xCB, 0xD6, 0xD8, 0xD7):
            print(f"  {fmt_cell(d, e)}: local page-39 FB string selector ({note})")
        elif idx is None:
            print(f"  {fmt_cell(d, e)}: no _KeyToString index ({rule})  {note}")
        else:
            print(f"  {fmt_cell(d, e)}: _KeyToString index {idx:02X} by {rule}  {note}")

    print("\nraw Ghidra identities")
    print("  raw HTTP identifies 39:6B66 as eqdisp_load_glyph18b2, the FB string selector/_KeyToString fallback")
    print("  raw HTTP identifies 01:6D10 as _KeyToString, whose decompilation maps cells to fixed counted strings")

    print("\ninterpretation")
    print("  page-39 generic string output is limited to 4EE3/4EE6 and descriptor FB string selection at 6A52")
    print("  local string/_PutPSB windows have no measured 85E8/85E9/85EB/85EC/85EE/85EF/9D27 template-state cluster")
    print("  _KeyToString maps cells to fixed counted strings; it has no height input, draw primitive, or glyph-piece loop")
    print("  this closes the generic string/_PutPSB branch as fixed string output, not final tall integral/radical construction")


def dump_display_byte_caller_flow(rom):
    print("display-byte mapper caller/body audit")
    for page, addr, hex_bytes, note in DISPLAY_BYTE_CALLER_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nROM-wide CALL 3B37 caller set")
    callers = find_pattern_locations(rom, bytes.fromhex("cd373b"))
    expected = {(page, addr) for page, addr, _note in DISPLAY_BYTE_EXPECTED_CALLERS}
    actual = set(callers)
    for page, addr, note in DISPLAY_BYTE_EXPECTED_CALLERS:
        present = "ok" if (page, addr) in actual else "MISSING"
        print(f"  {page:02X}:{addr:04X}: {present}  {note}")
    unexpected = sorted(actual - expected)
    missing = sorted(expected - actual)
    print("  unexpected callers: " + (" ".join(f"{page:02X}:{addr:04X}" for page, addr in unexpected) or "none"))
    print("  missing callers: " + (" ".join(f"{page:02X}:{addr:04X}" for page, addr in missing) or "none"))

    print("\ncaller windows with measured/template state within +/-0x60")
    any_state = False
    for page, addr in callers:
        lo = max(0x4000, addr - 0x60)
        hi = min(0x8000, addr + 0x63)
        refs_by_word = []
        for target, label in DISPLAY_BYTE_CALLER_STATE_WORDS:
            refs = [
                ref for ref in state_word_refs_on_page(rom, page, target)
                if lo <= ref < hi
            ]
            if refs and target in DISPLAY_BYTE_MEASURED_WORDS:
                refs_by_word.append((target, label, refs))
        if not refs_by_word:
            continue
        any_state = True
        print(f"  {page:02X}:{addr:04X} window {lo:04X}..{hi:04X}")
        for target, label, refs in refs_by_word:
            print(f"    {target:04X} {label}: " + " ".join(f"{page:02X}:{ref:04X}" for ref in refs))
        hits = page_pattern_hits_in_range(rom, page, lo, hi, DISPLAY_BYTE_CALLER_DRAW_PATTERNS)
        for pattern_label, hit in hits:
            print(f"    pattern {page:02X}:{hit:04X}: {pattern_label}")
    if not any_state:
        print("  none")

    print("\nall caller local state/draw scans")
    for page, addr, note in DISPLAY_BYTE_EXPECTED_CALLERS:
        lo = max(0x4000, addr - 0x60)
        hi = min(0x8000, addr + 0x63)
        print(f"  {page:02X}:{addr:04X} window {lo:04X}..{hi:04X} {note}")
        for target, label in DISPLAY_BYTE_CALLER_STATE_WORDS:
            refs = [
                ref for ref in state_word_refs_on_page(rom, page, target)
                if lo <= ref < hi
            ]
            print(f"    {target:04X} {label}: " + (" ".join(f"{page:02X}:{ref:04X}" for ref in refs) or "none"))
        hits = page_pattern_hits_in_range(rom, page, lo, hi, DISPLAY_BYTE_CALLER_DRAW_PATTERNS)
        if hits:
            for pattern_label, hit in hits:
                print(f"    pattern {page:02X}:{hit:04X}: {pattern_label}")
        else:
            print("    pattern: none")

    print("\npage-7 display-byte classifier body state refs")
    page, lo, hi = 0x07, 0x44DE, 0x453A
    for target, label in DISPLAY_BYTE_CALLER_STATE_WORDS:
        refs = [
            ref for ref in state_word_refs_on_page(rom, page, target)
            if lo <= ref < hi
        ]
        print(f"  {target:04X} {label}: " + (" ".join(f"07:{ref:04X}" for ref in refs) or "none"))

    print("\nraw Ghidra identity")
    print("  raw HTTP identifies 07:44DE as arc_chk_type, but bytes show the page-7 FE/FC/FB display-byte classifier")
    print("  raw Ghidra does not split the ROM-wide caller sites as functions, so this audit uses byte anchors and local-window scans")

    print("\ninterpretation")
    print("  every ROM-wide 3B37 caller is accounted for and no unexpected display-byte mapper caller remains")
    print("  caller windows contain no measured 85E8/85E9/85EB/85EC/85EE/85EF/9D27 template-state cluster")
    print("  page-7 44DE is a fixed display-byte remapper; it does not read measured template state or emit variable-height pieces")
    print("  this closes 3B37/page-7 display-byte mapping as fixed glyph remap, not final tall integral/radical construction")


def dump_vputmap_caller_flow(rom):
    print("VPutMap bjump caller/body audit")
    for page, addr, hex_bytes, note in VPUTMAP_SERVICE_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nROM-wide CALL 3CDB caller set")
    callers = find_pattern_locations(rom, bytes.fromhex("cddb3c"))
    for page in sorted({page for page, _addr in callers}):
        addrs = " ".join(f"{addr:04X}" for p, addr in callers if p == page)
        print(f"  page {page:02X}: {addrs}")

    print("\npage-39 VPutMap caller closure")
    page39_callers = sorted(addr for page, addr in callers if page == PAGE)
    expected = set(VPUTMAP_EXPECTED_PAGE39_CALLERS)
    print("  expected: " + " ".join(f"{addr:04X}" for addr in VPUTMAP_EXPECTED_PAGE39_CALLERS))
    print("  actual:   " + (" ".join(f"{addr:04X}" for addr in page39_callers) or "none"))
    unexpected = sorted(set(page39_callers) - expected)
    missing = sorted(expected - set(page39_callers))
    print("  unexpected: " + (" ".join(f"{addr:04X}" for addr in unexpected) or "none"))
    print("  missing: " + (" ".join(f"{addr:04X}" for addr in missing) or "none"))

    print("\nCALL 3CDB windows with template/measured state within +/-0x40")
    any_state = False
    for page, addr in callers:
        lo = max(0x4000, addr - 0x40)
        hi = min(0x8000, addr + 0x43)
        refs_by_word = []
        for target, label in VPUTMAP_CALLER_STATE_WORDS:
            refs = [
                ref for ref in state_word_refs_on_page(rom, page, target)
                if lo <= ref < hi
            ]
            if refs and target in VPUTMAP_MEASURED_WORDS:
                refs_by_word.append((target, label, refs))
        if not refs_by_word:
            continue
        any_state = True
        print(f"  {page:02X}:{addr:04X} window {lo:04X}..{hi:04X}")
        for target, label, refs in refs_by_word:
            print(f"    {target:04X} {label}: " + " ".join(f"{page:02X}:{ref:04X}" for ref in refs))
        hits = page_pattern_hits_in_range(rom, page, lo, hi, VPUTMAP_CALLER_DRAW_PATTERNS)
        for pattern_label, hit in hits:
            print(f"    pattern {page:02X}:{hit:04X}: {pattern_label}")
    if not any_state:
        print("  none")

    print("\n_VPutMap body state refs")
    page, lo, hi = 0x01, 0x6293, 0x6460
    for target, label in VPUTMAP_CALLER_STATE_WORDS:
        refs = [
            ref for ref in state_word_refs_on_page(rom, page, target)
            if lo <= ref < hi
        ]
        print(f"  {target:04X} {label}: " + (" ".join(f"01:{ref:04X}" for ref in refs) or "none"))

    print("\nraw Ghidra identity")
    print("  raw HTTP identifies 01:6293 as _VPutMap; decompilation shows it uses 86D7/86D8 as pen coordinates and _LoadPattern for glyph data")

    print("\ninterpretation")
    print("  page-39 calls to 3CDB are exactly the descriptor/fraction small-label sites in 69C8..6BFE")
    print("  caller windows with measured/template refs are those same descriptor/fraction UI windows, not independent off-page builders")
    print("  the _VPutMap body reads graph pen coordinates but no 85EE/85EF/9D27 measured template state")
    print("  this closes 3CDB/_VPutMap as small-label pixel output, not final tall integral/radical construction")


def dump_offpage_state_intersection_flow(rom):
    print("remaining off-page state/draw intersection audit")
    for page, addr, hex_bytes, note in OFFPAGE_STATE_INTERSECTION_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nwindow-local state references")
    for page, start, end, label in OFFPAGE_STATE_INTERSECTION_WINDOWS:
        print(f"  {page:02X}:{start:04X}..{end:04X} {label}")
        for word_value, note in OFFPAGE_STATE_INTERSECTION_WORDS:
            refs = [
                addr
                for addr in page_word_refs(rom, page, word_value)
                if start <= addr < end
            ]
            where = " ".join(f"{addr:04X}" for addr in refs) or "none"
            print(f"    {word_value:04X}: {where}  {note}")

    print("\nwindow-local draw/service patterns")
    for page, start, end, label in OFFPAGE_STATE_INTERSECTION_WINDOWS:
        print(f"  {page:02X}:{start:04X}..{end:04X} {label}")
        for name, hex_bytes in OFFPAGE_STATE_INTERSECTION_PATTERNS:
            pattern = bytes.fromhex(hex_bytes)
            hits = []
            for addr in range(start, end - len(pattern) + 1):
                actual = rom_bytes_at(rom, page, addr, len(pattern))
                if actual == pattern:
                    hits.append(addr)
            where = " ".join(f"{addr:04X}" for addr in hits) or "none"
            print(f"    {name}: {where}")

    print("\ninterpretation")
    print("  page 6 shares template action bytes and 85E8/85DE with page 39, but this is key/cursor/display-state handling")
    print("  page 6 cursor drawing may preserve 86D7 around 3CDB, but it has no 85EE/85EF/9D27 or descriptor geometry words")
    print("  page 7 clears 85DE/984B in an editor/parser cleanup path; its nearby draw helper has no MathPrint state refs")
    print("  page 37 tests 85DE only in an app/UI helper, while its 9D27 write is the startup/default 0202 seed")
    print("  these remaining off-page intersections are not measured tall-symbol placement routines")


def dump_offpage_draw_state_flow(rom):
    print("ROM-wide MathPrint-state / draw-service intersection audit")
    state_pages = page_word_ref_map(rom, OFFPAGE_DRAW_STATE_WORDS)
    service_pages = page_pattern_ref_map(rom, OFFPAGE_DRAW_SERVICE_PATTERNS)

    print("\nMathPrint-specific state word refs by page")
    for target, label in OFFPAGE_DRAW_STATE_WORDS:
        hits = []
        for page in range(len(rom) // 0x4000):
            refs = state_word_refs_on_page(rom, page, target)
            if refs:
                hits.extend((page, addr) for addr in refs)
        print(f"  {target:04X} {label}: {page_count_summary(hits)}")

    print("\ndraw/display service byte patterns by page")
    for label, hex_bytes in OFFPAGE_DRAW_SERVICE_PATTERNS:
        hits = rom_pattern_hits(rom, bytes.fromhex(hex_bytes))
        print(f"  {label}: {page_count_summary(hits)}")

    print("\npages containing both MathPrint state refs and draw/display service calls")
    both = sorted(set(state_pages) & set(service_pages))
    if not both:
        print("  none")
    for page in both:
        state = "; ".join(
            f"{target:04X} {label}:"
            + ",".join(f"{addr:04X}" for addr in refs[:8])
            + ("..." if len(refs) > 8 else "")
            for label, target, refs in state_pages[page]
        )
        services_by_label = {}
        for label, addr in service_pages[page]:
            services_by_label.setdefault(label, []).append(addr)
        services = "; ".join(
            f"{label}:"
            + ",".join(f"{addr:04X}" for addr in addrs[:8])
            + ("..." if len(addrs) > 8 else "")
            for label, addrs in services_by_label.items()
        )
        print(f"  page {page:02X}")
        print(f"    state: {state}")
        print(f"    draw:  {services}")

    print("\nhigh-risk intersections")
    for target, label in ((0x85EE, "85EE"), (0x85EF, "85EF"), (0x9D27, "9D27")):
        pages = set()
        for page in range(len(rom) // 0x4000):
            if state_word_refs_on_page(rom, page, target):
                pages.add(page)
        draw_pages = pages & set(service_pages)
        where = " ".join(f"{page:02X}" for page in sorted(draw_pages)) or "none"
        print(f"  {label} with any draw/display service on same page: {where}")

    print("\nhigh-risk refs with nearest same-page draw/display service")
    for target, label in ((0x85EE, "85EE"), (0x85EF, "85EF"), (0x9D27, "9D27")):
        for page in range(len(rom) // 0x4000):
            refs = state_word_refs_on_page(rom, page, target)
            if not refs or page not in service_pages:
                continue
            service_hits = service_pages[page]
            for ref in refs:
                nearest_label, nearest_addr = min(
                    service_hits,
                    key=lambda item: abs(item[1] - ref),
                )
                delta = nearest_addr - ref
                print(
                    f"  {label} {page:02X}:{ref:04X} -> "
                    f"{nearest_label} at {page:02X}:{nearest_addr:04X} "
                    f"(delta {delta:+d})"
                )

    print("\nROM-wide _DarkLine caller context")
    for page, addr, hex_bytes, note in OFFPAGE_DARKLINE_CONTEXT_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\n_DarkLine caller page-local state scan")
    for page, lo, hi, label in (
        (0x05, 0x53F0, 0x5420, "page-5 graph/axis helpers"),
        (0x05, 0x7588, 0x75C0, "page-5 graph draw helper"),
        (0x35, 0x6874, 0x6898, "page-35 display/window helper"),
        (0x39, 0x4F62, 0x4F99, "page-39 post-marker retouch"),
        (0x39, 0x67AC, 0x6829, "page-39 template chrome"),
    ):
        print(f"  {label} {page:02X}:{lo:04X}..{hi:04X}")
        for target, state_label in OFFPAGE_DARKLINE_STATE_WORDS:
            refs = [
                addr for addr in state_word_refs_on_page(rom, page, target)
                if lo <= addr < hi
            ]
            print(f"    {state_label}: " + (" ".join(f"{addr:04X}" for addr in refs) or "none"))

    print("\ncommand-level graph/display helper local state scan")
    for page, lo, hi, label in OFFPAGE_COMMAND_DRAW_CONTEXT_WINDOWS:
        print(f"  {label} {page:02X}:{lo:04X}..{hi:04X}")
        for target, state_label in OFFPAGE_DRAW_STATE_WORDS:
            refs = [
                addr for addr in state_word_refs_on_page(rom, page, target)
                if lo <= addr < hi
            ]
            if refs:
                print(f"    {state_label}: " + " ".join(f"{addr:04X}" for addr in refs))
        if not any(
            lo <= addr < hi
            for target, _state_label in OFFPAGE_DRAW_STATE_WORDS
            for addr in state_word_refs_on_page(rom, page, target)
        ):
            print("    MathPrint measured/template state refs: none")

    print("\ninterpretation")
    print("  state refs require a plausible Z80 word-operand prefix, filtering inline bcall/data byte coincidences")
    print("  this is still a page-granularity census, so intersections are candidates, not proof of dataflow")
    print("  page 39 is expected: it owns the MathPrint layout state and the descriptor/fraction draw-service calls")
    print("  command-level graph/display bcalls are included; they add only non-measured page-level coincidences")
    print("  their local windows have no 85EE/85EF/9D27 refs; the page-33 _grf_5e06 window only touches 85DE before graph helper dispatch")
    print("  pages with draw services but no 85DE..85F2/9D27 refs are generic display/glyph providers")
    print("  page 35 has both a 9D27 reset/default seed and a _DarkLine caller, but the local windows do not intersect")
    print("  page 33/page 34 85EE intersections are closed more deeply by --offpage-85ee-candidate-flow")
    print("  ROM-wide _DarkLine callers are graph/chrome/window helpers, not measured tall-symbol stretchers")


def dump_direct_pixel_surface_flow(rom):
    print("ROM-wide direct pixel-surface / LCD I/O audit")
    state_pages = page_word_ref_map(rom, OFFPAGE_DRAW_STATE_WORDS)
    surface_pages = page_pattern_ref_map(rom, DIRECT_PIXEL_SURFACE_PATTERNS)

    print("\ndirect pixel-surface byte/word patterns by page")
    for label, hex_bytes in DIRECT_PIXEL_SURFACE_PATTERNS:
        hits = rom_pattern_hits(rom, bytes.fromhex(hex_bytes))
        print(f"  {label}: {page_count_summary(hits)}")

    print("\npages containing both MathPrint state refs and direct pixel-surface refs")
    both = sorted(set(state_pages) & set(surface_pages))
    if not both:
        print("  none")
    for page in both:
        state = "; ".join(
            f"{target:04X} {label}:"
            + ",".join(f"{addr:04X}" for addr in refs[:8])
            + ("..." if len(refs) > 8 else "")
            for label, target, refs in state_pages[page]
        )
        surfaces_by_label = {}
        for label, addr in surface_pages[page]:
            surfaces_by_label.setdefault(label, []).append(addr)
        surfaces = "; ".join(
            f"{label}:"
            + ",".join(f"{addr:04X}" for addr in addrs[:8])
            + ("..." if len(addrs) > 8 else "")
            for label, addrs in surfaces_by_label.items()
        )
        print(f"  page {page:02X}")
        print(f"    state: {state}")
        print(f"    surface: {surfaces}")

    print("\nhigh-risk measured refs with nearest same-page direct surface")
    for target, label in ((0x85EE, "85EE"), (0x85EF, "85EF"), (0x9D27, "9D27")):
        for page in range(len(rom) // 0x4000):
            refs = state_word_refs_on_page(rom, page, target)
            if not refs or page not in surface_pages:
                continue
            surface_hits = surface_pages[page]
            for ref in refs:
                nearest_label, nearest_addr = min(
                    surface_hits,
                    key=lambda item: abs(item[1] - ref),
                )
                delta = nearest_addr - ref
                print(
                    f"  {label} {page:02X}:{ref:04X} -> "
                    f"{nearest_label} at {page:02X}:{nearest_addr:04X} "
                    f"(delta {delta:+d})"
                )

    print("\nlocal high-risk windows")
    for page, lo, hi, label in DIRECT_PIXEL_SURFACE_WINDOWS:
        print(f"  {label} {page:02X}:{lo:04X}..{hi:04X}")
        for target, state_label in OFFPAGE_DRAW_STATE_WORDS:
            refs = [
                addr for addr in state_word_refs_on_page(rom, page, target)
                if lo <= addr < hi
            ]
            if refs:
                print(f"    {state_label}: " + " ".join(f"{addr:04X}" for addr in refs))
        surface_hits = page_pattern_hits_in_range(
            rom,
            page,
            lo,
            hi,
            DIRECT_PIXEL_SURFACE_PATTERNS,
        )
        if surface_hits:
            for surface_label, addr in surface_hits:
                print(f"    {surface_label}: {addr:04X}")
        else:
            print("    direct pixel-surface refs: none")

    print("\ninterpretation")
    print("  page 39 has no direct plotSScreen word refs; its direct LCD I/O is the SaveDisp/RestoreDisp buffer path")
    print("  page-33 85EE and display-backup refs are local-window separated")
    print("  page-35 and page-37 direct LCD helpers are local-window separated from their 9D27 default seeds")
    print("  the page-39 measured geometry window has no direct LCD port I/O or plotSScreen/appBackUpScreen word refs")
    print("  no direct graph-buffer or LCD-port writer remains as the static tall-symbol pixel emitter")


def dump_pen_surface_flow(rom):
    print("ROM-wide pen-coordinate / draw-service audit")
    print("\nROM-backed pen-coordinate anchors")
    for page, addr, hex_bytes, note in PEN_SURFACE_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    pen_pages = page_word_ref_map(rom, PEN_SURFACE_STATE_WORDS)
    measured_pages = page_word_ref_map(rom, PEN_SURFACE_MEASURED_WORDS)
    draw_pages = page_pattern_ref_map(rom, OFFPAGE_DRAW_SERVICE_PATTERNS)

    print("\npen-coordinate word refs by page")
    for target, label in PEN_SURFACE_STATE_WORDS:
        hits = []
        for page in range(len(rom) // 0x4000):
            for addr in state_word_refs_on_page(rom, page, target):
                hits.append((page, addr))
        print(f"  {target:04X} {label}: {page_count_summary(hits)}")

    print("\npages with pen refs and draw/display services")
    for page in sorted(set(pen_pages) & set(draw_pages)):
        refs = "; ".join(
            f"{target:04X} {label}:"
            + ",".join(f"{addr:04X}" for addr in addrs[:8])
            + ("..." if len(addrs) > 8 else "")
            for label, target, addrs in pen_pages[page]
        )
        services_by_label = {}
        for label, addr in draw_pages[page]:
            services_by_label.setdefault(label, []).append(addr)
        services = "; ".join(
            f"{label}:"
            + ",".join(f"{addr:04X}" for addr in addrs[:8])
            + ("..." if len(addrs) > 8 else "")
            for label, addrs in services_by_label.items()
        )
        measured = "; ".join(
            f"{target:04X} {label}:"
            + ",".join(f"{addr:04X}" for addr in addrs[:8])
            + ("..." if len(addrs) > 8 else "")
            for label, target, addrs in measured_pages.get(page, [])
        ) or "none"
        print(f"  page {page:02X}")
        print(f"    pen: {refs}")
        print(f"    measured/template: {measured}")
        print(f"    draw: {services}")

    print("\nlocal pen/draw windows")
    for page, lo, hi, label in PEN_SURFACE_WINDOWS:
        print(f"  {label} {page:02X}:{lo:04X}..{hi:04X}")
        for target, state_label in PEN_SURFACE_MEASURED_WORDS + PEN_SURFACE_STATE_WORDS:
            refs = [
                addr for addr in state_word_refs_on_page(rom, page, target)
                if lo <= addr < hi
            ]
            if refs:
                print(f"    {target:04X} {state_label}: " + " ".join(f"{addr:04X}" for addr in refs))
        service_hits = page_pattern_hits_in_range(
            rom,
            page,
            lo,
            hi,
            OFFPAGE_DRAW_SERVICE_PATTERNS,
        )
        if service_hits:
            for service_label, addr in service_hits:
                print(f"    {service_label}: {addr:04X}")
        else:
            print("    draw/display services: none")

    print("\ninterpretation")
    print("  86D7/86D8 are staged pen coordinates, so pen+draw intersections are expected")
    print("  off-page pen+draw windows are cursor/UI helpers and have no 85EE/85EF/9D27 measured geometry")
    print("  page-39 pen+draw windows are template chrome or descriptor/fraction cell emission already closed by local verifiers")
    print("  the measured geometry window still lacks a pen-coordinate path that combines variable-height state with a new draw primitive")


def dump_offpage_85ee_candidate_flow(rom):
    print("off-page 85EE candidate ROM anchors")
    for page, addr, hex_bytes, note in OFFPAGE_85EE_CANDIDATE_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

        window_lo = addr - 0x100
        window_hi = addr + len(expected) + 0x100
        hits = page_pattern_hits_in_range(
            rom,
            page,
            window_lo,
            window_hi,
            OFFPAGE_DRAW_SERVICE_PATTERNS,
        )
        if hits:
            where = "; ".join(f"{label} at {page:02X}:{hit:04X}" for label, hit in hits)
        else:
            where = "none"
        print(f"    local +/-0x100 draw/display patterns: {where}")

    print("\nsurrounding parser/object context anchors")
    for page, addr, hex_bytes, note in OFFPAGE_85EE_CONTEXT_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-local control-flow references")
    for page, target, expected_direct, expected_raw, note in OFFPAGE_85EE_CANDIDATE_XREF_TARGETS:
        direct, words = control_refs_on_page(rom, page, target)
        status = "ok" if direct == expected_direct and words == expected_raw else "MISMATCH"
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {page:02X}:{target:04X}: {status} direct {refs}; raw {raw}  {note}")

    print("\ncandidate-window measured-state refs")
    for page, lo, hi in ((0x33, 0x4F00, 0x4F70), (0x34, 0x4800, 0x51C0)):
        print(f"  page {page:02X} {lo:04X}..{hi:04X}")
        for target, label in OFFPAGE_DRAW_STATE_WORDS:
            refs = [
                addr for addr in state_word_refs_on_page(rom, page, target)
                if lo <= addr < hi
            ]
            if refs:
                print(f"    {label} {target:04X}: " + " ".join(f"{addr:04X}" for addr in refs))

    print("\npage-wide high-risk draw proximity")
    state_pages = page_word_ref_map(rom, OFFPAGE_DRAW_STATE_WORDS)
    service_pages = page_pattern_ref_map(rom, OFFPAGE_DRAW_SERVICE_PATTERNS)
    for page in (0x33, 0x34):
        refs = []
        for label, target, addrs in state_pages.get(page, []):
            if target == 0x85EE:
                refs.extend(addrs)
        services = service_pages.get(page, [])
        print(f"  page {page:02X}")
        if not refs:
            print("    no filtered 85EE refs")
            continue
        for ref in refs:
            if not services:
                print(f"    85EE {ref:04X}: no draw/display service on page")
                continue
            nearest_label, nearest_addr = min(services, key=lambda item: abs(item[1] - ref))
            print(
                f"    85EE {ref:04X}: nearest {nearest_label} at "
                f"{nearest_addr:04X} (delta {nearest_addr - ref:+d})"
            )

    print("\nhelper identities and entry context anchors")
    for page, addr, hex_bytes, note in OFFPAGE_85EE_HELPER_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        loc = f"ram:{addr:04X}" if page == 0x00 and addr < 0x4000 else f"{page:02X}:{addr:04X}"
        print(f"  {loc}: {status} {actual.hex().upper()}  {note}")
    print("\nraw Ghidra identities")
    print("  ram:1EF6 is _HTimesL; raw HTTP body ram:1ef6..1f01")
    print("  ram:21BB is _CpHLDE; raw HTTP body ram:21bb..21c0")
    print("  page_33:4F42 and page_34:4880/4DC8/5130 are not split as functions in this Ghidra database")

    print("\ninterpretation")
    print("  the page-33/page-34 85EE refs are real-looking Z80 word operands, not inline bcall byte coincidences")
    print("  page-33 4F42 is a 2B token/value helper: it scales 85EE with _HTimesL and returns offsets, with no draw primitive")
    print("  page-34 4880 stores 85EE into an object/record field at offset +12; it does not read 85EF/9D27 or emit pixels")
    print("  page-34 4DC8 and 5130 manipulate 85EE inside parser/object case handling before evaluator/workspace helpers")
    print("  the only off-page 9D27 refs seed the default 0202 measurement during reset/startup")
    print("  these close the known page-33/page-34 off-page 85EE refs as parser/evaluator/object bookkeeping, not tall-symbol emitters")


def dump_lcd_tallp_flow(rom):
    print("lcdTallP / generic LCD-height false-lead audit")
    for page, addr, hex_bytes, note in LCD_TALLP_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nfiltered lcdTallP refs by page")
    pages = sorted({page for page, _addr, _hex_bytes, _note in LCD_TALLP_FLOW_ANCHORS} | {PAGE})
    for page in pages:
        refs = state_word_refs_on_page(rom, page, LCD_TALLP_WORD)
        print(f"  {page:02X}: " + (" ".join(f"{addr:04X}" for addr in refs) or "none"))

    print("\npage-local MathPrint-state and draw-service intersection")
    for page in pages:
        print(f"  page {page:02X}")
        for target, label in LCD_TALLP_MATHPRINT_WORDS:
            refs = state_word_refs_on_page(rom, page, target)
            print(f"    {target:04X} {label}: " + (" ".join(f"{addr:04X}" for addr in refs[:12]) or "none"))
        hits = page_pattern_hits_in_range(rom, page, 0x4000, 0x8000, LCD_TALLP_DRAW_PATTERNS)
        if hits:
            rendered = " ".join(f"{addr:04X}:{label}" for label, addr in hits[:16])
            if len(hits) > 16:
                rendered += f" ... +{len(hits) - 16}"
            print(f"    draw/display patterns: {rendered}")
        else:
            print("    draw/display patterns: none")

    print("\nraw-Ghidra identity")
    print("  page_04:42EC is _IBounds; raw HTTP decompilation compares input coordinates against (8DA3)")

    print("\ninterpretation")
    print("  lcdTallP (8DA3) is generic LCD/graph height or bounds state, used by graph/UI helpers")
    print("  page 39 has no filtered 8DA3 refs, so the MathPrint page does not consume lcdTallP directly")
    print("  pages with lcdTallP refs do not combine it with 85EE/85EF/9D27 and a local variable-height glyph loop")
    print("  the symbol name is therefore a false lead for MathPrint tall integral/radical construction")


def classify_page39_tall_surface_addr(addr):
    for lo, hi, label in PAGE39_TALL_SURFACE_BUCKETS:
        if lo <= addr < hi:
            return label
    return None


def dump_page39_tall_surface_flow(rom):
    print("page-39 tall-template candidate surface audit")
    print("classified buckets")
    for lo, hi, label in PAGE39_TALL_SURFACE_BUCKETS:
        print(f"  {lo:04X}..{hi:04X}: {label}")

    unclassified = []
    print("\nfiltered MathPrint state-word refs")
    for target, label in PAGE39_TALL_SURFACE_STATE_WORDS:
        refs = state_word_refs_on_page(rom, PAGE, target)
        if not refs:
            print(f"  {target:04X} {label}: none")
            continue
        parts = []
        for addr in refs:
            bucket = classify_page39_tall_surface_addr(addr)
            parts.append(f"{addr:04X}({bucket or 'UNCLASSIFIED'})")
            if bucket is None:
                unclassified.append((addr, f"state {target:04X} {label}"))
        print(f"  {target:04X} {label}: " + " ".join(parts))

    print("\ndraw/display/service pattern hits")
    pattern_hits = page_pattern_hits_in_range(
        rom,
        PAGE,
        0x4000,
        0x8000,
        PAGE39_TALL_SURFACE_PATTERNS,
    )
    for label, addr in pattern_hits:
        bucket = classify_page39_tall_surface_addr(addr)
        print(f"  {addr:04X}: {label}  {bucket or 'UNCLASSIFIED'}")
        if bucket is None:
            unclassified.append((addr, label))

    print("\nunclassified candidate hits")
    if unclassified:
        for addr, label in sorted(unclassified):
            print(f"  {addr:04X}: {label}")
    else:
        print("  none")

    print("\ninterpretation")
    if unclassified:
        print("  unclassified candidate hits remain above; classify them before claiming page-39 closure")
    else:
        print("  every filtered page-39 MathPrint state ref and draw/display service hit is inside an already-classified bucket")
        print("  the only measured 85EE/85EF/9D27 refs are in the template handoff, chrome guard, and kind-2 fraction geometry")
        print("  page-39 has no remaining unclassified static draw/state window for a hidden tall-symbol builder")
    print("  remaining proof must come from a dynamic pen/glyph trace or from an off-page caller not visible as page-39 state/draw refs")


def dump_delimiter_flow(rom):
    print("paren/delimiter classifier ROM anchors")
    for addr, hex_bytes, note in DELIMITER_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nfixed delimiter-pair tables")
    for addr, _, note in DELIMITER_FLOW_ANCHORS[:3]:
        raw = rom_bytes(rom, addr, 20)
        cells = " ".join(fmt_cell(raw[i], raw[i + 1]) for i in range(0, 20, 2))
        print(f"  39:{addr:04X}: {cells}  {note}")

    print("\npage-39 control-flow xrefs")
    for target in DELIMITER_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ninterpretation")
    print("  39:6675 classifies three fixed ten-entry delimiter-pair tables through 39:6667")
    print("  matched pairs store the low byte at 8446 and route the high byte through bjump 3B37")
    print("  unmatched cells fall back to 4F1A, the ordinary token-to-large-font mapper")
    print("  this path has no measured height, repeat count, rectangle/fill call, or stretched-delimiter builder")


def dump_delimiter_display_map_flow(rom):
    print("delimiter display-byte map ROM closure")
    for addr, hex_bytes, note in DELIMITER_FLOW_ANCHORS[:5]:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")
    for addr, hex_bytes, note in DISPLAY_BYTE_MAP_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_at(rom, 0x07, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  07:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ndelimiter pair tables through page-7 display-byte map")
    unexpected = []
    for table_addr, table_name, expected_high, note in DELIMITER_DISPLAY_MAP_TABLES:
        raw = rom_bytes(rom, table_addr, 20)
        print(f"  table {table_name} 39:{table_addr:04X}: {note}")
        for idx in range(10):
            d, e = raw[2 * idx], raw[2 * idx + 1]
            mapped = page7_display_byte_map(rom, d, e)
            if mapped is None:
                unexpected.append((table_name, idx, d, e, None))
                print(f"    {idx}: {fmt_cell(d, e)} -> INVALID")
                continue
            md, me, source = mapped
            status = "ok" if (md, me) == (expected_high, idx) else "MISMATCH"
            if status != "ok":
                unexpected.append((table_name, idx, d, e, (md, me)))
            print(f"    {idx}: {status} {fmt_cell(d, e)} -> {fmt_cell(md, me)} via {source}")

    print("\noutput-cell occurrences in page 39")
    for _table_addr, table_name, expected_high, _note in DELIMITER_DISPLAY_MAP_TABLES:
        refs = []
        decoded = []
        for idx in range(10):
            cell = (expected_high, idx)
            refs.extend((idx, addr) for addr in page39_raw_cell_hits(rom, cell))
            decoded.extend((idx, item) for item in cell_record_locations(rom, cell))
            decoded.extend((idx, item) for item in cell_descriptor_locations(rom, cell))
        where = " ".join(f"{idx}:{addr:04X}" for idx, addr in refs) or "none"
        decoded_where = "; ".join(f"{idx}:{item}" for idx, item in decoded) or "none"
        print(f"  family {table_name} {expected_high:02X}00..{expected_high:02X}09")
        print(f"    raw: {where}")
        print(f"    decoded records/descriptors: {decoded_where}")

    print("\nclosure")
    if unexpected:
        for table_name, idx, d, e, mapped in unexpected:
            if mapped is None:
                print(f"  {table_name}[{idx}] {fmt_cell(d, e)} did not map")
            else:
                md, me = mapped
                print(f"  {table_name}[{idx}] {fmt_cell(d, e)} mapped unexpectedly to {fmt_cell(md, me)}")
    else:
        print("  all 30 delimiter cells map to the expected fixed output families")

    print("\ninterpretation")
    print("  page-39 delimiter classification selects one of three fixed ten-entry encoded families")
    print("  page-7 display-byte tables map those cells to 6100..6109, 6000..6009, or AA00..AA09")
    print("  raw page-39 output-cell byte coincidences are not decoded records/descriptors")
    print("  delimiter variants are generated display-byte outputs, not page-39 record/descriptor recipes")
    print("  this closes the fixed delimiter-map surface; dynamic row-window movement belongs to the 5167 compositor")


def dump_delimiter_record_family_flow(rom):
    print("delimiter handler-record family ROM closure")
    unexpected = []
    for cls, ptr_expected, action_expected, table_addr, family, high_expected, hex_bytes, note in DELIMITER_RECORD_FAMILY_CLASSES:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, ptr_expected, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        if status != "ok":
            unexpected.append((family, "record bytes", ptr_expected))
        table_ptr = word(rom, PAGE, HANDLER_TABLE + 2 * cls)
        ptr_status = "ok" if table_ptr == ptr_expected else "MISMATCH"
        if ptr_status != "ok":
            unexpected.append((family, "handler pointer", HANDLER_TABLE + 2 * cls))
        print(f"  class {cls:02X} table {HANDLER_TABLE + 2 * cls:04X}: {ptr_status} -> {table_ptr:04X}  {note}")
        print(f"  39:{ptr_expected:04X}: {status} {actual.hex().upper()}")

        ptr, record = parse_handler_record(rom, cls)
        if ptr != ptr_expected or record is None or record["rows"] != 1:
            unexpected.append((family, "decoded record header", ptr_expected))
            print("    decoded: MISMATCH")
            continue
        item = record["items"][0]
        row_status = "ok" if item["count"] == 10 and item["action"] == action_expected else "MISMATCH"
        if row_status != "ok":
            unexpected.append((family, "decoded row", ptr_expected))
        print(f"    decoded: {row_status} rows=1 row=0 count={item['count']:02X} action={item['action']:02X}")

        table_raw = rom_bytes(rom, table_addr, 20)
        table_cells = [(table_raw[2 * idx], table_raw[2 * idx + 1]) for idx in range(10)]
        if item["cells"] != table_cells:
            unexpected.append((family, "record/table cell agreement", table_addr))
        for idx, (d, e) in enumerate(item["cells"]):
            mapped = page7_display_byte_map(rom, d, e)
            rec_hits = "; ".join(cell_record_locations(rom, (d, e))) or "none"
            desc_hits = "; ".join(cell_descriptor_locations(rom, (d, e))) or "none"
            if mapped is None:
                unexpected.append((family, f"cell {idx} map", table_addr + 2 * idx))
                print(f"      {idx}: MISMATCH {fmt_cell(d, e)} -> INVALID  records: {rec_hits}; descriptors: {desc_hits}")
                continue
            md, me, source = mapped
            cell_status = "ok" if (md, me) == (high_expected, idx) else "MISMATCH"
            if cell_status != "ok":
                unexpected.append((family, f"cell {idx} output", table_addr + 2 * idx))
            print(
                f"      {idx}: {cell_status} {fmt_cell(d, e)} -> {fmt_cell(md, me)} via {source}  "
                f"records: {rec_hits}; descriptors: {desc_hits}"
            )

    print("\nclosure")
    if unexpected:
        for family, label, addr in unexpected:
            print(f"  family {family}: {label} mismatch near 39:{addr:04X}")
    else:
        print("  class 17/18/19 handler-table pointers, record bytes, decoded rows, and display-byte outputs all agree")
        print("  each delimiter family is a ROM handler record containing exactly ten fixed cells")

    print("\ninterpretation")
    print("  delimiter families A/B/C are not renderer-invented cells: they are decoded class records at 39:62C8/62DF/62F6")
    print("  the row actions select fixed ten-cell families that page-7 maps to 6100..6109, 6000..6009, and AA00..AA09")
    print("  this proves the fixed delimiter family surface is ROM-backed; the remaining gap is the upstream dynamic variant selector")


def dump_menu_cell_flow(rom):
    print("menu/template-cell dispatch ROM anchors")
    for page, addr, hex_bytes, note in MENU_CELL_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow xrefs")
    for target in MENU_CELL_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nrelevant decoded cells")
    for target in ((0x00, 0xC8), (0xFB, 0xC8), (0xFB, 0xC7), (0x08, 0x42)):
        td, te = target
        hits = []
        for cls in range(HANDLER_COUNT):
            ptr, record = parse_handler_record(rom, cls)
            if record is None:
                continue
            for item in record["items"]:
                for idx, cell in enumerate(item["cells"]):
                    if cell == target:
                        hits.append(f"class {cls:02X} row {item['row']} cell {idx}")
        print(f"  {fmt_cell(td, te)}: " + (", ".join(hits) or "no decoded record hit"))

    print("\ninterpretation")
    print("  action 05 loads a decoded row/descriptor cell, then 52E5 either recurses on C=82 or enters menu/token handling")
    print("  FB C7/C8 are square-marker controls that call the 3891->page_3D:7CBA stub and restart action 09")
    print("  in this ROM view that stub dispatches action 6/7 through page_3D:7DC4 flash/object bit-mask checks")
    print("  00C8 remains a display/menu-name cell on this path; operand slots are selected later by 5955/5167-style walkers")


def record_cell_hits(rom, target):
    hits = []
    for cls in range(HANDLER_COUNT):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            continue
        for item in record["items"]:
            for idx, cell in enumerate(item["cells"]):
                if cell == target:
                    hits.append((cls, ptr, item["row"], item["action"], idx))
    return hits


def dump_active_cell_recurse_flow(rom):
    print("active-cell recursion boundary ROM anchors")
    for addr, hex_bytes, note in ACTIVE_CELL_RECURSE_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow xrefs")
    for target in ACTIVE_CELL_RECURSE_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ndecoded cells with prefix 82 (the only action-05 recursive-token prefix)")
    recursive_hits = []
    for cls in range(HANDLER_COUNT):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            continue
        for item in record["items"]:
            for idx, (d, e) in enumerate(item["cells"]):
                if d != 0x82:
                    continue
                recursive_hits.append((cls, ptr, item["row"], item["action"], idx, d, e))
    for cls, ptr, row, action, idx, d, e in recursive_hits:
        print(
            f"  class {cls:02X} ptr {ptr:04X} row {row} "
            f"action={action:02X} cell {idx}: {fmt_cell(d, e)}"
        )
    if not recursive_hits:
        print("  none")

    print("\ncandidate cell membership")
    recursive_cells = {(d, e) for _, _, _, _, _, d, e in recursive_hits}
    for target in ACTIVE_CELL_RECURSE_CHECK_CELLS:
        d, e, note = target
        hits = record_cell_hits(rom, (d, e))
        record_where = ", ".join(
            f"class {cls:02X} row {row} cell {idx}" for cls, _, row, _, idx in hits
        ) or "no decoded record hit"
        recursive = "yes" if (d, e) in recursive_cells else "no"
        print(f"  {fmt_cell(d, e)}: recursive-prefix={recursive}; records={record_where}  {note}")

    print("\nraw Ghidra identities")
    print("  39:49A8 is eqdisp_begin; 39:53AD is eqdisp_menu_or_emit; 39:68AE is eqdisp_layout_token_geom")
    print("  39:52E5 is an embedded block inside eqdisp_layout_main, not a split Ghidra function in this database")

    print("\ninterpretation")
    print("  action 05 can recurse into token display only when the loaded cell has high byte 82")
    print("  the ROM's decoded 82xx cells are confined to classes 0B, 0C, and 20")
    print("  fnInt 00C8, square markers FB C7/C8, Lintegral FC3F/0842, and Lroot 0010 are not on the recursive 82xx branch")
    print("  therefore the active-cell path does not transform fnInt/menu markers into the fixed structural-glyph records")


def decode_two_byte_table(rom, addr, count):
    raw = rom_bytes(rom, addr, count * 2)
    return [(raw[i], raw[i + 1]) for i in range(0, len(raw), 2)]


def dump_two_byte_form_flow(rom):
    print("two-byte token form selector ROM anchors")
    for addr, hex_bytes, note in TWO_BYTE_FORM_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ndecoded two-byte form tables")
    table_sets = {}
    for addr, count, note in TWO_BYTE_FORM_TABLES:
        entries = decode_two_byte_table(rom, addr, count)
        table_sets[addr] = set(entries)
        cells = " ".join(fmt_cell(d, e) for d, e in entries)
        print(f"  39:{addr:04X} count={count:02X}: {cells}  {note}")

    print("\ncandidate membership")
    for d, e, note in TWO_BYTE_FORM_CHECK_CELLS:
        hits = [f"{addr:04X}" for addr, _, _ in TWO_BYTE_FORM_TABLES if (d, e) in table_sets[addr]]
        print(f"  {fmt_cell(d, e)}: " + (", ".join(hits) if hits else "no table hit") + f"  {note}")

    print("\npage-39 control-flow/raw xrefs")
    for target in TWO_BYTE_FORM_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nraw Ghidra identities")
    print("  39:5E1F is named eqdisp_lookup_tbl_6203 and loads table 6203 with B=0E")
    print("  39:5E26 is named eqdisp_lookup_tbl_63e3 and loads table 63E3 with B=04")
    print("  39:5E32 is named eqdisp_table_lookup2 and compares A plus saved 8446 low byte")
    print("  39:5E2D is an inline sibling selector for table 63C3; Ghidra has not split it into a function")

    print("\ninterpretation")
    print("  5373 rewrites only cells present in 6203/63E3 into D=56 fraction/superscript form cells")
    print("  63C3 is a separate local lookup table and contains no fnInt or structural tall-glyph candidate")
    print("  BB24/BB25, 00C8, FB C7/C8, Lintegral, Lroot, and Sigma candidates are absent from all three tables")
    print("  these ROM tables are not the missing fnInt field mapper or tall-symbol stretch recipe")


def dump_square_marker_flow(rom):
    print("square-marker off-page control ROM anchors")
    for page, addr, hex_bytes, note in SQUARE_MARKER_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\n_grc_4611 (bcall 52FF) inline call sites")
    pattern = bytes.fromhex("efff52")
    hits = find_pattern_locations(rom, pattern)
    for page, addr in hits:
        print(f"  {page:02X}:{addr:04X}")

    print("\npage-37 disabled-feature messages selected by _grc_4611")
    for action, addr, selector in (
        (0x05, 0x4B07, 0x9A),
        (0x06, 0x4B23, 0x9C),
        (0x07, 0x4C09, 0xA1),
        (0x08, 0x4C24, 0xA2),
    ):
        print(f"  A={action:02X}: msg={addr:04X} selector={selector:02X} text={nul_message_at(rom, 0x37, addr)!r}")

    print("\nbranch interpretation")
    print("  FB C8 first tests page-3D action 7; if nonzero, bcall 52FF runs with A=8, then page 39 restarts action 09")
    print("  FB C7 first tests page-3D action 6; if nonzero, bcall 52FF runs with A=7, then page 39 restarts action 09")
    print("  page-3D action 7 uses mask 0804 and action 6 uses mask 0402 through the 7DC4 bit-mask helper")
    print("  bcall 52FF maps A=8 to the 'summation' disabled message and A=7 to the 'logBASE(' disabled message")
    print("  this is square-marker disabled-feature handling, not a measured tall-symbol emission routine")


def dump_class49_flow(rom):
    print("class-49 menu/editor state ROM anchors")
    for addr, hex_bytes, note in CLASS49_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\npage-39 control-flow xrefs")
    for target in CLASS49_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nclass-49 entry closure")
    for target in CLASS49_FLOW_ENTRY_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\nclass-49 local service sites")
    for addr, hex_bytes, note in CLASS49_FLOW_SERVICE_SITES:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nclass-49 local measured/template refs")
    lo, hi = 0x6CB9, 0x6DE3
    for target, label in CLASS49_FLOW_MEASURED_STATE_WORDS:
        refs = [
            ref for ref in state_word_refs_on_page(rom, 0x39, target)
            if lo <= ref < hi
        ]
        print(f"  {target:04X} {label}: " + (" ".join(f"39:{ref:04X}" for ref in refs) or "none"))

    print("\ndecoded row actions that enter class 49")
    found = False
    for cls in range(HANDLER_COUNT):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            continue
        for item in record["items"]:
            if item["action"] != 0x49:
                continue
            found = True
            cells = " ".join(fmt_cell(d, e) for d, e in item["cells"])
            print(
                f"  class {cls:02X} ptr {ptr:04X} row {item['row']} "
                f"count={item['count']:02X} action=49 {cells}"
            )
    if not found:
        print("  none")

    print("\ninterpretation")
    print("  85DE=49 is the dispatcher branch at 4FC7/6CC1, separate from the 85DE=48 geometry branch")
    print("  class 49 is forced by 6D54 and appears as a decoded row action only in class 06")
    print("  6CB9 is reached only from menu/saved-OP post-state paths, and 6CC1 only from the class-49 dispatcher gate")
    print("  the branch normalizes menu/editor tokens and calls editor/menu services 5458/5461/5466")
    print("  the local class-49 window has no 85E8/85E9/85EB/85EC/85EE/85EF/9D27 measured-template cluster")
    print("  it has no direct geometry descriptor walk, measured-height state, or fraction-rule/tall-symbol draw call")


def dump_root_flow(rom):
    print("root/power template ROM anchors")
    for addr, hex_bytes, note in ROOT_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ncontrol-flow xrefs")
    for target in ROOT_FLOW_XREF_TARGETS:
        direct, words = control_refs(rom, target)
        refs = " ".join(f"{addr:04X}:{op}" for addr, op in direct) or "none"
        raw = " ".join(f"{addr:04X}" for addr in words) or "none"
        print(f"  {target:04X}: direct {refs}; raw {raw}")

    print("\ndecoded root/power classes")
    for cls in (0x29, 0x2A, 0x31):
        ptr, record = parse_handler_record(rom, cls)
        print(f"  class {cls:02X} ptr {ptr:04X} rows={record['rows']}")
        for item in record["items"]:
            cells = " ".join(fmt_cell(d, e) for d, e in item["cells"])
            print(
                f"    row {item['row']} count={item['count']:02X} "
                f"action={item['action']:02X} {cells}"
            )

    print("\naction-byte interpretation")
    print("  action 62 is present in class 29/2A records but is not a geometry-mode action")
    print("  action 48 is a class-31 row byte and maps to geometry kind 11 only after 85DE='H'")


def dump_structural_glyph_census(rom):
    print("structural glyph/menu-cell census")
    for d, e, note in STRUCTURAL_GLYPH_CENSUS_CELLS:
        print(f"\n{fmt_cell(d, e)}: {note}")
        pattern = bytes((d, e))
        raw_hits = []
        start = romoff(PAGE, 0x4000)
        end = romoff(PAGE, 0x8000)
        for o in range(start, end - 1):
            if rom[o:o + 2] == pattern:
                raw_hits.append(0x4000 + o - start)
        print("  page-39 raw hits: " + (" ".join(f"{addr:04X}" for addr in raw_hits) or "none"))

        mapped = map_token_glyph_cell(d, e)
        if mapped is None:
            print("  4F1A direct mapping: no")
        else:
            print(f"  4F1A direct mapping: L{mapped:02X}")

        hits = []
        for cls in range(HANDLER_COUNT):
            ptr, record = parse_handler_record(rom, cls)
            if record is None:
                continue
            for item in record["items"]:
                for idx, cell in enumerate(item["cells"]):
                    if cell == (d, e):
                        hits.append(f"class {cls:02X} ptr {ptr:04X} row {item['row']} cell {idx}")

        desc_hits = []
        for desc in parse_descriptors(rom):
            for idx, cell in enumerate(desc["cells"]):
                if cell == (d, e):
                    desc_hits.append(f"desc {desc['addr']:04X} cells {desc['cells_ptr']:04X} cell {idx}")

        if hits:
            for hit in hits:
                print(f"  record: {hit}")
        else:
            print("  record: no decoded record hit")

        if desc_hits:
            for hit in desc_hits:
                print(f"  descriptor: {hit}")
        else:
            print("  descriptor: no decoded descriptor hit")

    print("\ninterpretation")
    print("  Lintegral direct cells include FC3F in class 0D row 0 and 0842 in class 0D row 2, separate from fnInt menu rows")
    print("  Lroot cells are direct display cells in the root/power records, not descriptor geometry entries")
    print("  Sigma is not present as a simple 00C6 decoded record/descriptor cell in this page-39 table")
    print("  fnInt and square-marker cells are menu/template controls and are not direct 4F1A structural glyph mappings")


def cell_record_locations(rom, target):
    hits = []
    for cls in range(HANDLER_COUNT):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            continue
        for item in record["items"]:
            for idx, cell in enumerate(item["cells"]):
                if cell == target:
                    hits.append(f"class {cls:02X} ptr {ptr:04X} row {item['row']} cell {idx}")
    return hits


def cell_descriptor_locations(rom, target):
    hits = []
    for desc in parse_descriptors(rom):
        for idx, cell in enumerate(desc["cells"]):
            if cell == target:
                hits.append(f"desc {desc['addr']:04X} cell {idx}")
    return hits


def delimiter_pair_table_hits(rom, target):
    hits = []
    for addr in (0x62CB, 0x62E2, 0x62F9):
        raw = rom_bytes(rom, addr, 20)
        entries = [(raw[i], raw[i + 1]) for i in range(0, len(raw), 2)]
        if target in entries:
            hits.append(f"{addr:04X}")
    return hits


def dump_structural_symbol_flow(rom):
    print("structural symbol emission ROM anchors")
    for page, addr, hex_bytes, note in STRUCTURAL_SYMBOL_FLOW_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\noperator/menu versus structural-glyph provenance")
    for cls in STRUCTURAL_SYMBOL_PROVENANCE_CLASSES:
        ptr, record = parse_handler_record(rom, cls)
        print(f"  class {cls:02X} ptr {ptr:04X}")
        for item in record["items"]:
            ptr1, label = page_indexed_string(rom, item["action"])
            interesting = []
            for idx, (d, e) in enumerate(item["cells"]):
                if (d, e) in ((0x00, 0xC8), (0xFB, 0xC8), (0xFB, 0xC7), (0xFC, 0x3F), (0x08, 0x42)):
                    interesting.append(f"slot {idx}:{fmt_cell(d, e)}")
            if not interesting:
                continue
            print(
                f"    row {item['row']} action={item['action']:02X} "
                f"label={label!r} " + ", ".join(interesting)
            )

    print("\ncell emission classification")
    for d, e, note in STRUCTURAL_SYMBOL_FLOW_CELLS:
        target = (d, e)
        mapped = map_token_glyph_cell(d, e)
        pairs = delimiter_pair_table_hits(rom, target)
        records = cell_record_locations(rom, target)
        descs = cell_descriptor_locations(rom, target)
        print(f"  {fmt_cell(d, e)}  {note}")
        print("    records: " + (", ".join(records) or "none"))
        print("    descriptors: " + (", ".join(descs) or "none"))
        print("    delimiter-pair tables: " + (", ".join(pairs) or "none"))
        if mapped is None:
            print("    4F1A direct glyph: no")
        else:
            print(f"    4F1A direct glyph: L{mapped:02X}")

    print("\nemission path interpretation")
    print("  fnInt's 00C8 cell is selected from class 08/30 row 0; it is not the class 0D Lintegral glyph cell")
    print("  class 0D supplies the fixed Lintegral cells FC3F and 0842 on separate structural-symbol rows")
    print("  FC3F and 0842 are emitted as fixed Lintegral glyphs: 4E8E -> 6675 fallback -> 4F1A -> RST28")
    print("  0010 is a root/power record cell, but not a 4F1A direct glyph; _KeyToString alone would resolve it as table string index 00")
    print("  00C8 and FB C8 remain display/menu-control cells and do not become structural glyph stretch recipes")
    print("  no path here consumes measured radicand/limit height, repeat counts, or rectangle/rule endpoints")


def direct_cells_for_glyph_code(code):
    cells = []
    for d in range(0x100):
        for e in range(0x100):
            if map_token_glyph_cell(d, e) == code:
                cells.append((d, e))
    return cells


def page39_raw_cell_hits(rom, cell):
    pattern = bytes(cell)
    hits = []
    start = romoff(PAGE, 0x4000)
    end = romoff(PAGE, 0x8000)
    for o in range(start, end - 1):
        if rom[o:o + 2] == pattern:
            hits.append(0x4000 + o - start)
    return hits


def modeled_integral_stretch_pattern(height):
    if height < 7:
        raise ValueError("integral stretch height must be at least 7")
    return bytes.fromhex("0205") + (b"\x04" * (height - 4)) + bytes.fromhex("1408")


def modeled_root_stretch_pattern(height):
    if height < 7:
        raise ValueError("root stretch height must be at least 7")
    return bytes.fromhex("07") + (b"\x04" * (height - 3)) + bytes.fromhex("140c04")


STRUCTURAL_STRETCH_PATTERN_FAMILIES = [
    ("renderer modeled tall integral", modeled_integral_stretch_pattern),
    ("renderer modeled tall root", modeled_root_stretch_pattern),
]


def structural_immediate_draw_hits(rom, radius=0x40):
    codes = {code: name for code, name in STRUCTURAL_IMMEDIATE_CODES}
    hits = []
    for page in range(len(rom) // 0x4000):
        services = page_pattern_hits_in_range(
            rom,
            page,
            0x4000,
            0x8000,
            STRUCTURAL_IMMEDIATE_DRAW_PATTERNS,
        )
        if not services:
            continue
        start = romoff(page, 0x4000)
        end = romoff(page, 0x8000)
        for off in range(start, end - 1):
            op = STRUCTURAL_IMMEDIATE_OPS.get(rom[off])
            code = rom[off + 1]
            if op is None or code not in codes:
                continue
            addr = 0x4000 + off - start
            nearby = [
                (label, svc_addr)
                for label, svc_addr in services
                if abs(svc_addr - addr) <= radius
            ]
            if nearby:
                hits.append((page, addr, op, code, nearby))
    return hits


def dump_structural_immediate_draw_flow(rom):
    print("structural glyph immediate/draw-service census")
    code_names = {code: name for code, name in STRUCTURAL_IMMEDIATE_CODES}
    actual = structural_immediate_draw_hits(rom)
    expected = set(STRUCTURAL_IMMEDIATE_EXPECTED_HITS)

    print("\nROM-wide structural-code immediates within +/-0x40 of draw/display services")
    for page, addr, op, code, nearby in actual:
        key = (page, addr, op, code)
        status = "ok" if key in expected else "UNEXPECTED"
        note = STRUCTURAL_IMMEDIATE_EXPECTED_HITS.get(key, "unclassified structural-code immediate near draw service")
        near = "; ".join(
            f"{label} at {page:02X}:{svc_addr:04X} (delta {svc_addr - addr:+d})"
            for label, svc_addr in nearby
        )
        print(f"  {page:02X}:{addr:04X}: {status} {op} {code:02X} {code_names[code]}  {note}")
        print(f"    nearby: {near}")

    actual_keys = {(page, addr, op, code) for page, addr, op, code, _nearby in actual}
    missing = sorted(expected - actual_keys)
    unexpected = sorted(actual_keys - expected)
    print("\nclosure")
    print("  missing expected hits: " + (" ".join(f"{p:02X}:{a:04X}" for p, a, _op, _code in missing) or "none"))
    print("  unexpected hits: " + (" ".join(f"{p:02X}:{a:04X}" for p, a, _op, _code in unexpected) or "none"))

    print("\ncontext anchors")
    for page, addr, hex_bytes, note in STRUCTURAL_IMMEDIATE_CONTEXT_ANCHORS:
        expected_bytes = bytes.fromhex(hex_bytes)
        actual_bytes = rom_bytes_banked(rom, page, addr, len(expected_bytes))
        status = "ok" if actual_bytes == expected_bytes else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual_bytes.hex().upper()}  {note}")

    print("\nlocal measured-state refs around hits")
    for page, addr, op, code, _nearby in actual:
        refs = []
        lo = max(0x4000, addr - 0x40)
        hi = min(0x8000, addr + 0x40)
        for target, label in OFFPAGE_DRAW_STATE_WORDS:
            addrs = [
                ref for ref in state_word_refs_on_page(rom, page, target)
                if lo <= ref < hi
            ]
            if addrs:
                refs.append(f"{label} {target:04X}:" + ",".join(f"{ref:04X}" for ref in addrs))
        where = "; ".join(refs) or "none"
        print(f"  {page:02X}:{addr:04X} {op} {code:02X}: {where}")

    print("\ninterpretation")
    print("  this byte-level scan covers procedural-looking structural code immediates near draw services")
    print("  all such hits are fixed counts, coordinates, UI/display constants, or one unaligned raw false positive")
    print("  the only page-39 measured-state-adjacent hit is the already-classified template-chrome line coordinate at 67E7")
    print("  no hidden procedural load of Lintegral/Lroot/Sigma/MathPrint-piece code remains near 3B37/3B3D/3CDB/_DarkLine/RST28")


def dump_structural_piece_census(rom):
    print("structural piece candidate census")
    for code, name, note in STRUCTURAL_PIECE_CANDIDATES:
        glyph_addr = 0x45FF + code * 7
        glyph = rom_bytes_banked(rom, 0x07, glyph_addr, 7)
        direct_cells = direct_cells_for_glyph_code(code)
        literal_cell = (0x00, code)
        candidate_cells = sorted(set(direct_cells + [literal_cell]))

        print(f"\nL{code:02X} {name}: {note}")
        print(f"  glyph bytes 07:{glyph_addr:04X}: {glyph.hex().upper()}")
        print("  4F1A direct cells: " + (" ".join(fmt_cell(d, e) for d, e in direct_cells) or "none"))
        print(f"  literal display cell checked: {fmt_cell(*literal_cell)}")

        any_hit = False
        for cell in candidate_cells:
            raw = page39_raw_cell_hits(rom, cell)
            records = cell_record_locations(rom, cell)
            descs = cell_descriptor_locations(rom, cell)
            if not raw and not records and not descs:
                continue
            any_hit = True
            print(f"  {fmt_cell(*cell)}")
            print("    page-39 raw hits: " + (" ".join(f"{addr:04X}" for addr in raw) or "none"))
            print("    records: " + (", ".join(records) or "none"))
            print("    descriptors: " + (", ".join(descs) or "none"))
        if not any_hit:
            print("  decoded page-39 hits: none")

    print("\nROM-wide fixed glyph bitmap byte patterns")
    for label, hex_bytes in STRUCTURAL_MODELED_BITMAP_PATTERNS:
        pattern = bytes.fromhex(hex_bytes)
        hits = rom_pattern_hits(rom, pattern)
        where = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
        print(f"  {label}: {where}")

    print(f"\nROM-wide modeled stretch bitmap families, heights {STRUCTURAL_STRETCH_PATTERN_HEIGHTS.start}..{STRUCTURAL_STRETCH_PATTERN_HEIGHTS.stop - 1}")
    for label, pattern_fn in STRUCTURAL_STRETCH_PATTERN_FAMILIES:
        family_hits = []
        for height in STRUCTURAL_STRETCH_PATTERN_HEIGHTS:
            hits = rom_pattern_hits(rom, pattern_fn(height))
            if hits:
                where = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits)
                family_hits.append(f"h={height}: {where}")
        print(f"  {label}: " + ("; ".join(family_hits) if family_hits else "none"))

    print("\npage-39 literal-code false-positive anchors")
    for addr, hex_bytes, note in STRUCTURAL_LITERAL_CODE_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes(rom, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  39:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\ninterpretation")
    print("  Lintegral has two direct page-39 record cells: FC3F and 0842, both in class 0D")
    print("  Lroot appears as literal 0010 in root/power records, but has no 4F1A direct-cell mapping")
    print("  Sigma C6 and MathPrint F5/F6/F7 piece candidates have no decoded page-39 record/descriptor hits")
    print("  the raw 0008 hit at 6D49 is an HL=0008 state-save literal, not a decoded glyph cell")
    print("  modeled tall integral/root stretch-family byte sequences for heights 8..40 are absent ROM-wide; fixed font glyphs are present")
    print("  this rules out decoded record/descriptor piece tables and modeled bitmap-table copies, but not a later pixel-placement routine")


def dump_page3f_glyph_duplicate_flow(rom):
    print("page-3F fixed-glyph duplicate audit")
    for page, addr, hex_bytes, note in PAGE3F_GLYPH_DUPLICATE_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nROM-wide fixed glyph bitmap byte patterns")
    for label, hex_bytes in STRUCTURAL_MODELED_BITMAP_PATTERNS:
        pattern = bytes.fromhex(hex_bytes)
        hits = rom_pattern_hits(rom, pattern)
        where = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
        print(f"  {label}: {where}")

    print("\nROM-wide raw word refs to page-3F duplicate addresses")
    for target, label in PAGE3F_GLYPH_DUPLICATE_REF_TARGETS:
        hits = []
        lo = target & 0xFF
        hi = target >> 8
        for page in range(len(rom) // 0x4000):
            start = romoff(page, 0x4000)
            end = romoff(page, 0x8000)
            for off in range(start, end - 1):
                if rom[off] == lo and rom[off + 1] == hi:
                    hits.append((page, 0x4000 + off - start))
        where = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
        print(f"  {target:04X} {label}: {where}")

    print("\npage-3F local MathPrint state refs around duplicate window")
    lo_addr, hi_addr = 0x4600, 0x4700
    for target, label in PAGE3F_GLYPH_DUPLICATE_STATE_WORDS:
        refs = [
            addr for addr in state_word_refs_on_page(rom, 0x3F, target)
            if lo_addr <= addr < hi_addr
        ]
        where = " ".join(f"3F:{addr:04X}" for addr in refs) or "none"
        print(f"  {target:04X} {label}: {where}")

    print("\npage-3F local draw/display patterns around duplicate window")
    hits = page_pattern_hits_in_range(
        rom,
        0x3F,
        lo_addr,
        hi_addr,
        PAGE3F_GLYPH_DUPLICATE_DRAW_PATTERNS,
    )
    if hits:
        for label, addr in hits:
            print(f"  3F:{addr:04X}: {label}")
    else:
        print("  none")

    print("\nraw Ghidra identity")
    print("  raw HTTP reports no function at page_3F:46B8; page 3F has no split function covering the duplicate")

    print("\ninterpretation")
    print("  page 3F contains a width-prefixed copy of the fixed Lintegral glyph rows, not a modeled tall-integral byte sequence")
    print("  the duplicate record address and row address have no ROM-wide raw word refs")
    print("  the local page-3F window has no MathPrint measured-state refs and no draw/display service calls")
    print("  this closes the page-3F duplicate as font/data, not the measured tall-symbol placement caller")


def dump_structural_record_placement_flow(rom):
    print("structural record placement ROM anchors")
    for page, addr, hex_bytes, note in STRUCTURAL_RECORD_PLACEMENT_ANCHORS:
        expected = bytes.fromhex(hex_bytes)
        actual = rom_bytes_banked(rom, page, addr, len(expected))
        status = "ok" if actual == expected else "MISMATCH"
        print(f"  {page:02X}:{addr:04X}: {status} {actual.hex().upper()}  {note}")

    print("\nclass 0D row labels and cells")
    ptr, record = parse_handler_record(rom, 0x0D)
    print(f"  raw byte 37 -> normalized class 0D, record {ptr:04X}")
    for item in record["items"]:
        ptr1, label = page_indexed_string(rom, item["action"])
        cells = " ".join(f"{idx}:{fmt_cell(d, e)}" for idx, (d, e) in enumerate(item["cells"]))
        print(
            f"    row {item['row']} action={item['action']:02X} "
            f"label={label!r} cells {cells}"
        )

    print("\nrow-action label check")
    for action in STRUCTURAL_RECORD_PLACEMENT_ACTIONS:
        ptr, label = page_indexed_string(rom, action)
        print(f"  action {action:02X}: ptr={ptr:04X} text={label!r}")

    print("\nstructural glyph provenance")
    for cell, name in (((0xFC, 0x3F), "row-0 Lintegral"), ((0x08, 0x42), "row-2 Lintegral"), ((0x00, 0x10), "root/power Lroot")):
        d, e = cell
        mapped = map_token_glyph_cell(d, e)
        records = cell_record_locations(rom, cell)
        print(f"  {fmt_cell(d, e)} {name}")
        print("    records: " + (", ".join(records) or "none"))
        print("    direct 4F1A glyph: " + (f"L{mapped:02X}" if mapped is not None else "no"))

    print("\nparser-token boundary")
    for label, hex_bytes in (("BB24 tFnInt", "bb24"), ("BB25 tNDeriv", "bb25")):
        hits = rom_pattern_hits(rom, bytes.fromhex(hex_bytes))
        rendered = " ".join(f"{page:02X}:{addr:04X}" for page, addr in hits) or "none"
        print(f"  {label}: {rendered}")

    print("\ninterpretation")
    print("  class 0D is a fixed three-row record selected by raw byte 37, with row labels NAMES/MATH/EDIT")
    print("  FC3F and 0842 are ROM-backed fixed Lintegral cells, emitted by ordinary row-cell placement through 4E8E/4F1A")
    print("  that record proves fixed structural glyph placement, not the inserted BB24 fnInt( display template")
    print("  BB24/BB25 remain page-7 parser-token table entries with no direct page-39 record-cell occurrence")
    print("  the definite-integral template uses the 5167 row compositor to map parsed fnInt operands around fixed structural cells")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=Path(__file__).with_name("rom.bin"))
    ap.add_argument("--class", dest="only_class", type=lambda s: int(s, 0))
    ap.add_argument("--descriptors", action="store_true")
    ap.add_argument("--find-cell", type=parse_cell, metavar="HHLL")
    ap.add_argument("--find-action", type=lambda s: int(s, 0), metavar="BYTE")
    ap.add_argument("--template-actions", action="store_true")
    ap.add_argument("--operand-flow", action="store_true")
    ap.add_argument("--multiarg-placement-flow", action="store_true")
    ap.add_argument("--saved-op-flow", action="store_true")
    ap.add_argument("--record-flow", action="store_true")
    ap.add_argument("--record-cell-stream-flow", action="store_true")
    ap.add_argument("--argument-gutter-caller-flow", action="store_true")
    ap.add_argument("--row-action-flow", action="store_true")
    ap.add_argument("--setup-flow", action="store_true")
    ap.add_argument("--row-placement-flow", action="store_true")
    ap.add_argument("--layout-flow", action="store_true")
    ap.add_argument("--emit-boundary-flow", action="store_true")
    ap.add_argument("--operand-service-flow", action="store_true")
    ap.add_argument("--geometry-flow", action="store_true")
    ap.add_argument("--template-descriptor-algorithm-flow", action="store_true")
    ap.add_argument("--geometry-selector-closed-flow", action="store_true")
    ap.add_argument("--cell-pixel-mapper-flow", action="store_true")
    ap.add_argument("--descriptor-marker-flow", action="store_true")
    ap.add_argument("--marker-retouch-flow", action="store_true")
    ap.add_argument("--fraction-template-flow", action="store_true")
    ap.add_argument("--template-chrome-flow", action="store_true")
    ap.add_argument("--template-state-flow", action="store_true")
    ap.add_argument("--template-draw-bridge-flow", action="store_true")
    ap.add_argument("--template-emission-closure-flow", action="store_true")
    ap.add_argument("--geometry-action-flow", action="store_true")
    ap.add_argument("--geometry-handoff-flow", action="store_true")
    ap.add_argument("--template-handoff-guard-flow", action="store_true")
    ap.add_argument("--measured-state-flow", action="store_true")
    ap.add_argument("--class10-saved-tail-flow", action="store_true")
    ap.add_argument("--class10-dynamic-selector-flow", action="store_true")
    ap.add_argument("--entry-dispatch-flow", action="store_true")
    ap.add_argument("--dispatch-context-flow", action="store_true")
    ap.add_argument("--fnint-token-flow", action="store_true")
    ap.add_argument("--extended-token-table-flow", action="store_true")
    ap.add_argument("--fnint-template-flow", action="store_true")
    ap.add_argument("--fnint-eval-flow", action="store_true")
    ap.add_argument("--fnint-argument-order-flow", action="store_true")
    ap.add_argument("--fnint-row-window-flow", action="store_true")
    ap.add_argument("--fnint-slot-flow", action="store_true")
    ap.add_argument("--bjump-flow", action="store_true")
    ap.add_argument("--page39-external-entry-flow", action="store_true")
    ap.add_argument("--structural-predicate-flow", action="store_true")
    ap.add_argument("--page39-bjump-caller-flow", action="store_true")
    ap.add_argument("--page1-display-bridge-flow", action="store_true")
    ap.add_argument("--page1-action-table-flow", action="store_true")
    ap.add_argument("--overflow-flow", action="store_true")
    ap.add_argument("--mathprint-mode-flow", action="store_true")
    ap.add_argument("--draw-primitive-flow", action="store_true")
    ap.add_argument("--graph-table-helper-flow", action="store_true")
    ap.add_argument("--lcd-capture-flow", action="store_true")
    ap.add_argument("--restore-display-flow", action="store_true")
    ap.add_argument("--draw-mode-callback-flow", action="store_true")
    ap.add_argument("--glyph-emission-flow", action="store_true")
    ap.add_argument("--cell-emission-algorithm-flow", action="store_true")
    ap.add_argument("--suffix-1f-flow", action="store_true")
    ap.add_argument("--key-string-1f-flow", action="store_true")
    ap.add_argument("--key-string-structural-flow", action="store_true")
    ap.add_argument("--lroot-final-emitter-boundary-flow", action="store_true")
    ap.add_argument("--template-tracepoint-flow", action="store_true")
    ap.add_argument("--template-pixel-sample-flow", action="store_true")
    ap.add_argument("--rectangle-rule-event-flow", action="store_true")
    ap.add_argument("--large-font-flow", action="store_true")
    ap.add_argument("--display-byte-map-flow", action="store_true")
    ap.add_argument("--offpage-render-flow", action="store_true")
    ap.add_argument("--glyph-service-closed-flow", action="store_true")
    ap.add_argument("--large-glyph-caller-flow", action="store_true")
    ap.add_argument("--indexed-string-caller-flow", action="store_true")
    ap.add_argument("--generic-string-caller-flow", action="store_true")
    ap.add_argument("--display-byte-caller-flow", action="store_true")
    ap.add_argument("--vputmap-caller-flow", action="store_true")
    ap.add_argument("--offpage-state-intersection-flow", action="store_true")
    ap.add_argument("--offpage-draw-state-flow", action="store_true")
    ap.add_argument("--direct-pixel-surface-flow", action="store_true")
    ap.add_argument("--pen-surface-flow", action="store_true")
    ap.add_argument("--offpage-85ee-candidate-flow", action="store_true")
    ap.add_argument("--lcd-tallp-flow", action="store_true")
    ap.add_argument("--page39-tall-surface-flow", action="store_true")
    ap.add_argument("--delimiter-flow", action="store_true")
    ap.add_argument("--delimiter-display-map-flow", action="store_true")
    ap.add_argument("--delimiter-record-family-flow", action="store_true")
    ap.add_argument("--menu-cell-flow", action="store_true")
    ap.add_argument("--active-cell-recurse-flow", action="store_true")
    ap.add_argument("--two-byte-form-flow", action="store_true")
    ap.add_argument("--square-marker-flow", action="store_true")
    ap.add_argument("--class49-flow", action="store_true")
    ap.add_argument("--root-flow", action="store_true")
    ap.add_argument("--structural-glyph-census", action="store_true")
    ap.add_argument("--structural-symbol-flow", action="store_true")
    ap.add_argument("--structural-piece-census", action="store_true")
    ap.add_argument("--structural-immediate-draw-flow", action="store_true")
    ap.add_argument("--page3f-glyph-duplicate-flow", action="store_true")
    ap.add_argument("--structural-record-placement-flow", action="store_true")
    ap.add_argument("--explain-token", type=lambda s: int(s, 0), metavar="BYTE")
    ap.add_argument("--xref", type=lambda s: int(s, 0), metavar="ADDR",
                    help="find simple page-39 direct calls/jumps and word refs")
    args = ap.parse_args()

    rom = Path(args.rom).read_bytes()
    if args.xref is not None:
        xrefs(rom, args.xref)
    elif args.find_cell is not None:
        find_cell(rom, args.find_cell)
    elif args.find_action is not None:
        find_action(rom, args.find_action)
    elif args.template_actions:
        dump_template_actions(rom)
    elif args.operand_flow:
        dump_operand_flow(rom)
    elif args.multiarg_placement_flow:
        dump_multiarg_placement_flow(rom)
    elif args.saved_op_flow:
        dump_saved_op_flow(rom)
    elif args.record_flow:
        dump_record_flow(rom)
    elif args.record_cell_stream_flow:
        dump_record_cell_stream_flow(rom)
    elif args.argument_gutter_caller_flow:
        dump_argument_gutter_caller_flow(rom)
    elif args.row_action_flow:
        dump_row_action_flow(rom)
    elif args.setup_flow:
        dump_setup_flow(rom)
    elif args.row_placement_flow:
        dump_row_placement_flow(rom)
    elif args.layout_flow:
        dump_layout_flow(rom)
    elif args.emit_boundary_flow:
        dump_emit_boundary_flow(rom)
    elif args.operand_service_flow:
        dump_operand_service_flow(rom)
    elif args.geometry_flow:
        dump_geometry_flow(rom)
    elif args.template_descriptor_algorithm_flow:
        dump_template_descriptor_algorithm_flow(rom)
    elif args.geometry_selector_closed_flow:
        dump_geometry_selector_closed_flow(rom)
    elif args.cell_pixel_mapper_flow:
        dump_cell_pixel_mapper_flow(rom)
    elif args.descriptor_marker_flow:
        dump_descriptor_marker_flow(rom)
    elif args.marker_retouch_flow:
        dump_marker_retouch_flow(rom)
    elif args.fraction_template_flow:
        dump_fraction_template_flow(rom)
    elif args.template_chrome_flow:
        dump_template_chrome_flow(rom)
    elif args.template_state_flow:
        dump_template_state_flow(rom)
    elif args.template_draw_bridge_flow:
        dump_template_draw_bridge_flow(rom)
    elif args.template_emission_closure_flow:
        dump_template_emission_closure_flow(rom)
    elif args.geometry_action_flow:
        dump_geometry_action_flow(rom)
    elif args.geometry_handoff_flow:
        dump_geometry_handoff_flow(rom)
    elif args.template_handoff_guard_flow:
        dump_template_handoff_guard_flow(rom)
    elif args.measured_state_flow:
        dump_measured_state_flow(rom)
    elif args.class10_saved_tail_flow:
        dump_class10_saved_tail_flow(rom)
    elif args.class10_dynamic_selector_flow:
        dump_class10_dynamic_selector_flow(rom)
    elif args.entry_dispatch_flow:
        dump_entry_dispatch_flow(rom)
    elif args.dispatch_context_flow:
        dump_dispatch_context_flow(rom)
    elif args.fnint_token_flow:
        dump_fnint_token_flow(rom)
    elif args.extended_token_table_flow:
        dump_extended_token_table_flow(rom)
    elif args.fnint_template_flow:
        dump_fnint_template_flow(rom)
    elif args.fnint_eval_flow:
        dump_fnint_eval_flow(rom)
    elif args.fnint_argument_order_flow:
        dump_fnint_argument_order_flow(rom)
    elif args.fnint_row_window_flow:
        dump_fnint_row_window_flow(rom)
    elif args.fnint_slot_flow:
        dump_fnint_slot_flow(rom)
    elif args.bjump_flow:
        dump_bjump_flow(rom)
    elif args.page39_external_entry_flow:
        dump_page39_external_entry_flow(rom)
    elif args.structural_predicate_flow:
        dump_structural_predicate_flow(rom)
    elif args.page39_bjump_caller_flow:
        dump_page39_bjump_caller_flow(rom)
    elif args.page1_display_bridge_flow:
        dump_page1_display_bridge_flow(rom)
    elif args.page1_action_table_flow:
        dump_page1_action_table_flow(rom)
    elif args.overflow_flow:
        dump_overflow_flow(rom)
    elif args.mathprint_mode_flow:
        dump_mathprint_mode_flow(rom)
    elif args.draw_primitive_flow:
        dump_draw_primitive_flow(rom)
    elif args.graph_table_helper_flow:
        dump_graph_table_helper_flow(rom)
    elif args.lcd_capture_flow:
        dump_lcd_capture_flow(rom)
    elif args.restore_display_flow:
        dump_restore_display_flow(rom)
    elif args.draw_mode_callback_flow:
        dump_draw_mode_callback_flow(rom)
    elif args.glyph_emission_flow:
        dump_glyph_emission_flow(rom)
    elif args.cell_emission_algorithm_flow:
        dump_cell_emission_algorithm_flow(rom)
    elif args.suffix_1f_flow:
        dump_suffix_1f_flow(rom)
    elif args.key_string_1f_flow:
        dump_key_string_1f_flow(rom)
    elif args.key_string_structural_flow:
        dump_key_string_structural_flow(rom)
    elif args.lroot_final_emitter_boundary_flow:
        dump_lroot_final_emitter_boundary_flow(rom)
    elif args.template_tracepoint_flow:
        dump_template_tracepoint_flow(rom)
    elif args.template_pixel_sample_flow:
        dump_template_pixel_sample_flow(rom)
    elif args.rectangle_rule_event_flow:
        dump_rectangle_rule_event_flow(rom)
    elif args.large_font_flow:
        dump_large_font_flow(rom)
    elif args.display_byte_map_flow:
        dump_display_byte_map_flow(rom)
    elif args.offpage_render_flow:
        dump_offpage_render_flow(rom)
    elif args.glyph_service_closed_flow:
        dump_glyph_service_closed_flow(rom)
    elif args.large_glyph_caller_flow:
        dump_large_glyph_caller_flow(rom)
    elif args.indexed_string_caller_flow:
        dump_indexed_string_caller_flow(rom)
    elif args.generic_string_caller_flow:
        dump_generic_string_caller_flow(rom)
    elif args.display_byte_caller_flow:
        dump_display_byte_caller_flow(rom)
    elif args.vputmap_caller_flow:
        dump_vputmap_caller_flow(rom)
    elif args.offpage_state_intersection_flow:
        dump_offpage_state_intersection_flow(rom)
    elif args.offpage_draw_state_flow:
        dump_offpage_draw_state_flow(rom)
    elif args.direct_pixel_surface_flow:
        dump_direct_pixel_surface_flow(rom)
    elif args.pen_surface_flow:
        dump_pen_surface_flow(rom)
    elif args.offpage_85ee_candidate_flow:
        dump_offpage_85ee_candidate_flow(rom)
    elif args.lcd_tallp_flow:
        dump_lcd_tallp_flow(rom)
    elif args.page39_tall_surface_flow:
        dump_page39_tall_surface_flow(rom)
    elif args.delimiter_flow:
        dump_delimiter_flow(rom)
    elif args.delimiter_display_map_flow:
        dump_delimiter_display_map_flow(rom)
    elif args.delimiter_record_family_flow:
        dump_delimiter_record_family_flow(rom)
    elif args.menu_cell_flow:
        dump_menu_cell_flow(rom)
    elif args.active_cell_recurse_flow:
        dump_active_cell_recurse_flow(rom)
    elif args.two_byte_form_flow:
        dump_two_byte_form_flow(rom)
    elif args.square_marker_flow:
        dump_square_marker_flow(rom)
    elif args.class49_flow:
        dump_class49_flow(rom)
    elif args.root_flow:
        dump_root_flow(rom)
    elif args.structural_glyph_census:
        dump_structural_glyph_census(rom)
    elif args.structural_symbol_flow:
        dump_structural_symbol_flow(rom)
    elif args.structural_piece_census:
        dump_structural_piece_census(rom)
    elif args.structural_immediate_draw_flow:
        dump_structural_immediate_draw_flow(rom)
    elif args.page3f_glyph_duplicate_flow:
        dump_page3f_glyph_duplicate_flow(rom)
    elif args.structural_record_placement_flow:
        dump_structural_record_placement_flow(rom)
    elif args.explain_token is not None:
        explain_token(args.explain_token)
    elif args.descriptors:
        dump_descriptors(rom)
    else:
        dump_handler_records(rom, args.only_class)


if __name__ == "__main__":
    main()
