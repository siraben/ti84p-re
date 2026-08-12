#!/usr/bin/env python3
"""Attribute MathPrint LCD mutations to dynamic ROM call frames.

The page-0x39 editor records describe template construction. The settled
expression redraw also traverses page 0x34 and delegates glyph and geometry
output to pages 0x01, 0x04, and 0x07. This tool aligns accepted, visible-changing
T6A04 writes with those dynamic calls so a renderer translation can preserve
both geometry and operation order.

TLMT stores the first opcode bytes as an integer, but it does not identify
calls. A stack-pointer decrement alone is insufficient because PUSH has the
same effect. Calls are therefore recognized only when a single-byte CALL/RST
opcode is followed by the expected stack change.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Iterable, Iterator

from hardware_trace import ResolvedInstruction, iter_resolved_instructions
from trace_lcd import LcdMutation, replay_mutations


CALL_OPCODES = frozenset({0xCD, 0xC4, 0xCC, 0xD4, 0xDC, 0xE4, 0xEC, 0xF4, 0xFC})
RST_OPCODES = frozenset({0xC7, 0xCF, 0xD7, 0xDF, 0xE7, 0xEF, 0xF7, 0xFF})
EMITTER_PAGES = frozenset({"page_01", "page_04", "page_07"})


@dataclass(frozen=True)
class Location:
    space: str
    address: int

    def text(self) -> str:
        return f"{self.space}:{self.address:04X}"


@dataclass(frozen=True)
class CallFrame:
    caller: Location
    callee: Location
    stack_pointer: int
    instruction_index: int


@dataclass(frozen=True)
class MutationAttribution:
    mutation: LcdMutation
    page34_frame: CallFrame | None
    emitter_frame: CallFrame | None


def is_taken_call(previous: ResolvedInstruction, current: ResolvedInstruction) -> bool:
    """Return whether the transition is a taken single-byte CALL or RST."""

    # A packed prefixed opcode such as CB C7 has low byte C7 but is not RST 00h.
    if not 0 <= previous.opcode <= 0xFF:
        return False
    if previous.opcode not in CALL_OPCODES | RST_OPCODES:
        return False
    return current.sp == ((previous.sp - 2) & 0xFFFF)


class DynamicCallStack:
    """Recover the active call frames from resolved instruction transitions."""

    def __init__(self) -> None:
        self.frames: list[CallFrame] = []

    def advance(
        self, previous: ResolvedInstruction | None, current: ResolvedInstruction
    ) -> tuple[CallFrame, ...]:
        # A return restores SP above the callee's entry value. This also removes
        # frames abandoned by a tail jump into a routine that later returns.
        while self.frames and current.sp > self.frames[-1].stack_pointer:
            self.frames.pop()
        if previous is not None and is_taken_call(previous, current):
            self.frames.append(
                CallFrame(
                    caller=Location(previous.space, previous.address),
                    callee=Location(current.space, current.address),
                    stack_pointer=current.sp,
                    instruction_index=current.instruction_index,
                )
            )
        return tuple(self.frames)


def nearest_frame(
    frames: tuple[CallFrame, ...], spaces: frozenset[str]
) -> CallFrame | None:
    for frame in reversed(frames):
        if frame.caller.space in spaces or frame.callee.space in spaces:
            return frame
    return None


def attribute_mutations(
    instructions: Iterable[ResolvedInstruction],
    mutations: Iterable[LcdMutation],
) -> Iterator[MutationAttribution]:
    """Yield each mutation with its nearest page-34 and emitter call frames."""

    by_index = {mutation.instruction_index: mutation for mutation in mutations}
    if not by_index:
        return
    last_index = max(by_index)
    stack = DynamicCallStack()
    previous = None
    for current in instructions:
        frames = stack.advance(previous, current)
        mutation = by_index.get(current.instruction_index)
        if mutation is not None:
            yield MutationAttribution(
                mutation=mutation,
                page34_frame=nearest_frame(frames, frozenset({"page_34"})),
                emitter_frame=nearest_frame(frames, EMITTER_PAGES),
            )
        if current.instruction_index >= last_index:
            break
        previous = current


def frame_key(frame: CallFrame | None) -> str:
    if frame is None:
        return "unattributed"
    return f"{frame.caller.text()} -> {frame.callee.text()}"


def build_report(
    trace: Path, from_index: int, *, sample_count: int = 4
) -> dict[str, object]:
    replay = replay_mutations(trace, from_index=from_index)
    stream = (
        event
        for event in iter_resolved_instructions(trace, initial_mapping="ti84p-reset")
        if event.instruction_index >= from_index
    )
    attributed = tuple(attribute_mutations(stream, replay.events))

    page34_counts: Counter[str] = Counter()
    emitter_counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in attributed:
        page34 = frame_key(item.page34_frame)
        emitter = frame_key(item.emitter_frame)
        page34_counts[page34] += 1
        emitter_counts[emitter] += 1
        if len(samples[page34]) < sample_count:
            mutation = item.mutation
            samples[page34].append(
                {
                    "instruction_index": mutation.instruction_index,
                    "lcd_pointer": [mutation.pointer_x, mutation.pointer_y],
                    "value": mutation.value,
                    "changed_pixels": len(mutation.changes),
                    "emitter_frame": emitter,
                }
            )

    def ranked(counts: Counter[str]) -> list[dict[str, object]]:
        return [
            {"frame": frame, "mutations": count, "samples": samples.get(frame, [])}
            for frame, count in counts.most_common()
        ]

    return {
        "trace": str(trace),
        "from_instruction": from_index,
        "visible_changing_writes": len(replay.events),
        "attributed_writes": len(attributed),
        "page34_frames": ranked(page34_counts),
        "emitter_frames": ranked(emitter_counts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--from-index", type=int, required=True)
    parser.add_argument("--sample-count", type=int, default=4)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.from_index < 0:
        parser.error("--from-index must be nonnegative")
    if args.sample_count < 0:
        parser.error("--sample-count must be nonnegative")

    report = build_report(args.trace, args.from_index, sample_count=args.sample_count)
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
        return

    print(
        f"{report['visible_changing_writes']} visible-changing LCD writes; "
        f"{report['attributed_writes']} attributed"
    )
    print("nearest page-34 call frame")
    for row in report["page34_frames"]:
        print(f"{row['mutations']:5}  {row['frame']}")
        for sample in row["samples"]:
            print(
                f"       instruction {sample['instruction_index']}, "
                f"LCD {sample['lcd_pointer'][0]},{sample['lcd_pointer'][1]}, "
                f"value 0x{sample['value']:02X}, "
                f"{sample['changed_pixels']} pixel(s), {sample['emitter_frame']}"
            )


if __name__ == "__main__":
    main()
