"""Reusable decoders and models for the TI-84 Plus retail boot sequence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from hardware_trace import ResolvedExecution, ResolvedInstruction, ResolvedIoEvent
from rom_image import RomImage, RomLocation

BOOT_PAGE = 0x3F
RESET_DELAY_START_SP = 0xFDFA
RESET_DELAY_OUTER_ITERATIONS = 0x10000 - RESET_DELAY_START_SP
RESET_DELAY_INNER_ITERATIONS = 0x100

# The wrapper body after the protected port-0x14 write at 3F:4163.  The same
# byte sequence occurs after all ten gate-enable writes on the retail page.
FLASH_GATE_SAFETY_BODY = bytes.fromhex(
    "C5E5ED73E8833AE983E6C0FEC02803C30000"
    "0108002AE8830938F4DB06E63FFE3F2808FE2C38E8FE3030E4"
    "DB07FE8120DE2100C00E007E472F777E2FB820D07779B72804"
    "E1C118072100800E0118E7F1"
)
FLASH_GATE_ENABLE_PREFIX = bytes.fromhex("F53E010000ED56F3D314F3")
FLASH_GATE_DISABLE_WRAPPER = bytes.fromhex(
    "F5AF0000ED56F3D314F3B7C20000F1"
)


@dataclass(frozen=True)
class ResetDelay:
    """Exact loop counts and timing for the delay at ``3F:412C``."""

    start_sp: int
    outer_iterations: int
    inner_iterations: int
    djnz_executions: int
    loop_instruction_count: int
    setup_instruction_count: int
    total_instruction_count: int
    standard_loop_tstates: int
    standard_total_tstates: int
    tilem_total_tstates: int
    tilem_difference_tstates: int

    def seconds(self, clock_hz: int = 6_000_000) -> float:
        if clock_hz <= 0:
            raise ValueError("clock rate must be positive")
        return self.standard_total_tstates / clock_hz


def reset_delay() -> ResetDelay:
    """Model the nested ``DJNZ``/stack-carry delay at ``3F:412C``.

    Standard Z80 timing assigns 15 T-states to ``ADD IX,SP``.  Pinned TilEm
    assigns 13, accounting for its two-T-state-per-outer-loop discrepancy.
    """

    outer = RESET_DELAY_OUTER_ITERATIONS
    inner = RESET_DELAY_INNER_ITERATIONS
    djnz_executions = outer * inner
    loop_instruction_count = djnz_executions + 4 * outer
    setup_instruction_count = 3
    djnz_tstates = outer * (255 * 13 + 8)
    common_outer_tstates = 14 + 10
    standard_loop_tstates = (
        djnz_tstates
        + outer * (common_outer_tstates + 15)
        + (outer - 1) * 12
        + 7
    )
    standard_total_tstates = 8 + 7 + 10 + standard_loop_tstates
    tilem_difference = outer * 2
    return ResetDelay(
        start_sp=RESET_DELAY_START_SP,
        outer_iterations=outer,
        inner_iterations=inner,
        djnz_executions=djnz_executions,
        loop_instruction_count=loop_instruction_count,
        setup_instruction_count=setup_instruction_count,
        total_instruction_count=loop_instruction_count + setup_instruction_count,
        standard_loop_tstates=standard_loop_tstates,
        standard_total_tstates=standard_total_tstates,
        tilem_total_tstates=standard_total_tstates - tilem_difference,
        tilem_difference_tstates=tilem_difference,
    )


@dataclass(frozen=True)
class ResetDelayTraceObservation:
    """Counts and clocks observed while executing the reset-delay region."""

    first_instruction_index: int
    last_instruction_index: int
    start_clock: int
    end_clock: int
    elapsed_tstates: int
    total_instruction_count: int
    djnz_executions: int
    outer_iterations: int


class _ResetDelayObserver:
    def __init__(self) -> None:
        self.previous: ResolvedInstruction | None = None
        self.first: ResolvedInstruction | None = None
        self.last: ResolvedInstruction | None = None
        self.start_clock: int | None = None
        self.total_instruction_count = 0
        self.djnz_executions = 0
        self.outer_iterations = 0
        self.finished = False

    def feed(self, event: ResolvedInstruction) -> None:
        if self.finished:
            return
        if self.first is None:
            if event.space == "page_3F" and event.address == 0x412C:
                if self.previous is None:
                    raise ValueError("reset-delay trace has no preceding clock record")
                self.first = event
                self.start_clock = self.previous.clock
            else:
                self.previous = event
                return
        elif event.space == "page_3F" and event.address == 0x413F:
            self.finished = True
            return

        self.last = event
        self.total_instruction_count += 1
        self.djnz_executions += event.address == 0x4133
        self.outer_iterations += event.address == 0x4135
        self.previous = event

    def report(self) -> ResetDelayTraceObservation:
        if self.first is None or self.start_clock is None:
            raise ValueError("trace does not execute the reset delay at 3F:412C")
        if (
            not self.finished
            or self.last is None
            or self.last.space != "page_3F"
            or self.last.address != 0x413D
        ):
            raise ValueError("trace does not reach the reset-delay exit at 3F:413D")
        return ResetDelayTraceObservation(
            first_instruction_index=self.first.instruction_index,
            last_instruction_index=self.last.instruction_index,
            start_clock=self.start_clock,
            end_clock=self.last.clock,
            elapsed_tstates=self.last.clock - self.start_clock,
            total_instruction_count=self.total_instruction_count,
            djnz_executions=self.djnz_executions,
            outer_iterations=self.outer_iterations,
        )


def observe_reset_delay_trace(
    events: Iterable[ResolvedInstruction],
) -> ResetDelayTraceObservation:
    """Measure ``3F:412C``–``3F:413D`` in a resolved full-reset trace."""

    observer = _ResetDelayObserver()
    for event in events:
        observer.feed(event)
        if observer.finished:
            break
    return observer.report()


def reset_delay_trace_mismatches(
    observation: ResetDelayTraceObservation,
) -> tuple[str, ...]:
    """Compare an emulator observation with the modeled counts and TilEm time."""

    expected = reset_delay()
    fields = (
        (
            "instruction count",
            expected.total_instruction_count,
            observation.total_instruction_count,
        ),
        ("DJNZ count", expected.djnz_executions, observation.djnz_executions),
        ("outer count", expected.outer_iterations, observation.outer_iterations),
        ("TilEm T-states", expected.tilem_total_tstates, observation.elapsed_tstates),
    )
    return tuple(
        f"reset delay {name}: expected {want}, observed {actual}"
        for name, want, actual in fields
        if want != actual
    )


@dataclass(frozen=True)
class ProtectedFlashGateWrite:
    """One protected port-``0x14`` write and its integrity wrapper."""

    location: RomLocation
    value: int
    action: str
    wrapper_start: RomLocation
    safety_checks: bool


def protected_flash_gate_writes(rom: RomImage) -> tuple[ProtectedFlashGateWrite, ...]:
    """Find exact protected Flash-gate wrappers on retail boot page ``0x3F``."""

    page = rom.page(BOOT_PAGE)
    writes: list[ProtectedFlashGateWrite] = []
    for offset in range(7, len(page) - 2):
        if page[offset : offset + 2] != bytes.fromhex("D314"):
            continue
        enable_start = offset - 8
        disable_start = offset - 7
        enable = FLASH_GATE_ENABLE_PREFIX
        disable = FLASH_GATE_DISABLE_WRAPPER
        if page[enable_start : enable_start + len(enable)] == enable:
            start = enable_start
            safety_start = start + len(enable)
            safety_end = safety_start + len(FLASH_GATE_SAFETY_BODY)
            if page[safety_start:safety_end] != FLASH_GATE_SAFETY_BODY:
                raise ValueError(
                    f"unrecognized Flash-gate safety body at "
                    f"{BOOT_PAGE:02X}:{start + 0x4000:04X}"
                )
            writes.append(
                ProtectedFlashGateWrite(
                    RomLocation(BOOT_PAGE, offset + 0x4000),
                    1,
                    "enable",
                    RomLocation(BOOT_PAGE, start + 0x4000),
                    True,
                )
            )
        elif page[disable_start : disable_start + len(disable)] == disable:
            start = disable_start
            writes.append(
                ProtectedFlashGateWrite(
                    RomLocation(BOOT_PAGE, offset + 0x4000),
                    0,
                    "disable",
                    RomLocation(BOOT_PAGE, start + 0x4000),
                    False,
                )
            )
        else:
            raise ValueError(
                f"unrecognized protected port-0x14 write at "
                f"{BOOT_PAGE:02X}:{offset + 0x4000:04X}"
            )
    return tuple(writes)


@dataclass(frozen=True)
class BootPortWrite:
    """One ordered output in the reset-to-key-scan hardware sequence."""

    location: RomLocation
    port: int
    value: int
    value_source: RomLocation
    group: str
    protected: bool = False


def _write(
    address: int,
    port: int,
    value: int,
    source: int,
    group: str,
    *,
    protected: bool = False,
) -> BootPortWrite:
    return BootPortWrite(
        RomLocation(BOOT_PAGE, address),
        port,
        value,
        RomLocation(BOOT_PAGE, source),
        group,
        protected,
    )


BOOT_PORT_WRITES = (
    _write(0x4002, 0x04, 0x07, 0x4000, "reset mapping"),
    _write(0x4006, 0x06, 0x7F, 0x4004, "reset mapping"),
    _write(0x400A, 0x0E, 0x03, 0x4008, "reset mapping"),
    _write(0x4144, 0x0F, 0x03, 0x4142, "mapping transition"),
    _write(0x4148, 0x07, 0x7F, 0x4146, "mapping transition"),
    _write(0x414C, 0x04, 0x06, 0x414A, "mapping transition"),
    _write(0x4159, 0x07, 0x81, 0x4157, "mapping transition"),
    _write(0x4163, 0x14, 0x01, 0x415C, "Flash gate", protected=True),
    _write(0x41B8, 0x2D, 0x02, 0x41B6, "link assist"),
    _write(0x627A, 0x00, 0x00, 0x6278, "link reset"),
    _write(0x627E, 0x09, 0x97, 0x627C, "link assist"),
    _write(0x6282, 0x0A, 0xB4, 0x6280, "link assist"),
    _write(0x6284, 0x0B, 0xB4, 0x6280, "link assist"),
    _write(0x6286, 0x0C, 0xB4, 0x6280, "link assist"),
    _write(0x628A, 0x08, 0x80, 0x6288, "link assist"),
    _write(0x628E, 0x08, 0x00, 0x628C, "link assist"),
    _write(0x41BF, 0x29, 0x17, 0x41BD, "bus timing"),
    _write(0x41C3, 0x2A, 0x27, 0x41C1, "bus timing"),
    _write(0x41C7, 0x2B, 0x2F, 0x41C5, "bus timing"),
    _write(0x41CB, 0x2C, 0x3B, 0x41C9, "bus timing"),
    _write(0x41CF, 0x2E, 0x45, 0x41CD, "bus timing"),
    _write(0x41D3, 0x2F, 0x4B, 0x41D1, "bus timing"),
    _write(0x41DC, 0x21, 0x00, 0x41D5, "ASIC control", protected=True),
    _write(0x41E6, 0x22, 0x08, 0x41DF, "execution protection", protected=True),
    _write(0x41F0, 0x23, 0x29, 0x41E9, "execution protection", protected=True),
    _write(0x41FA, 0x25, 0x10, 0x41F3, "execution protection", protected=True),
    _write(0x4204, 0x26, 0x20, 0x41FD, "execution protection", protected=True),
    _write(0x4208, 0x0E, 0x00, 0x4207, "runtime mapping"),
    _write(0x420A, 0x0F, 0x00, 0x4207, "runtime mapping"),
    _write(0x420C, 0x05, 0x00, 0x4207, "runtime mapping"),
    _write(0x4210, 0x06, 0x3F, 0x420E, "runtime mapping"),
    _write(0x4214, 0x39, 0xF0, 0x4212, "GPIO"),
    _write(0x4218, 0x4A, 0x20, 0x4216, "USB control"),
    _write(0x4221, 0x14, 0x00, 0x421B, "Flash gate", protected=True),
    _write(0x422B, 0x07, 0x80, 0x4229, "runtime mapping"),
)


def validate_boot_port_writes(rom: RomImage) -> tuple[str, ...]:
    """Check the manifest's immediate OUT opcodes and value sources in a ROM."""

    errors: list[str] = []
    for write in BOOT_PORT_WRITES:
        output = rom.bytes_at(write.location.page, write.location.address, 2)
        if output != bytes((0xD3, write.port)):
            errors.append(
                f"{write.location}: expected OUT opcode D3{write.port:02X}, "
                f"found {output.hex().upper()}"
            )
        source = rom.bytes_at(write.value_source.page, write.value_source.address, 1)
        if source == b"\xAF":
            actual = 0
        elif source == b"\x3E":
            actual = rom.bytes_at(
                write.value_source.page, write.value_source.address + 1, 1
            )[0]
        else:
            errors.append(
                f"{write.value_source}: expected XOR A or LD A,n value source"
            )
            continue
        if actual != write.value:
            errors.append(
                f"{write.value_source}: expected value 0x{write.value:02X}, "
                f"found 0x{actual:02X}"
            )
    return tuple(errors)


def boot_trace_mismatches(events: Iterable[ResolvedIoEvent]) -> tuple[str, ...]:
    """Compare an executed resolved I/O stream with the ordered boot manifest."""

    expected_by_location = {
        (str(write.location), write.port): write for write in BOOT_PORT_WRITES
    }
    observed: list[tuple[str, int, int | None]] = []
    for event in events:
        key = (f"{event.space.removeprefix('page_')}:{event.address:04X}", event.port)
        if event.direction == "OUT" and key in expected_by_location:
            observed.append((key[0], event.port, event.value))
    return _boot_write_mismatches(observed)


def _boot_write_mismatches(
    observed: list[tuple[str, int, int | None]],
) -> tuple[str, ...]:
    expected = [
        (str(write.location), write.port, write.value) for write in BOOT_PORT_WRITES
    ]
    errors: list[str] = []
    for index, (want, got) in enumerate(zip(expected, observed, strict=False)):
        if want != got:
            errors.append(f"write {index}: expected {want}, observed {got}")
    if len(observed) != len(expected):
        errors.append(
            f"expected {len(expected)} manifest writes, observed {len(observed)}"
        )
    return tuple(errors)


@dataclass(frozen=True)
class BootTraceAnalysis:
    """Constant-memory validation of one resolved full-reset trace."""

    reset_delay: ResetDelayTraceObservation
    processed_instructions: int
    observed_boot_writes: int
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def analyze_boot_trace(
    executions: Iterable[ResolvedExecution],
) -> BootTraceAnalysis:
    """Validate boot timing and ordered I/O in one constant-memory pass."""

    expected_by_location = {
        (str(write.location), write.port): write for write in BOOT_PORT_WRITES
    }
    observed: list[tuple[str, int, int | None]] = []
    delay_observer = _ResetDelayObserver()
    final_key = (str(BOOT_PORT_WRITES[-1].location), BOOT_PORT_WRITES[-1].port)
    processed_instructions = 0
    for execution in executions:
        processed_instructions += 1
        delay_observer.feed(execution.instruction)
        event = execution.io_event
        if event is None or event.direction != "OUT":
            continue
        key = (f"{event.space.removeprefix('page_')}:{event.address:04X}", event.port)
        if key in expected_by_location:
            observed.append((key[0], event.port, event.value))
            if key == final_key and delay_observer.finished:
                break
    delay = delay_observer.report()
    errors = (
        *_boot_write_mismatches(observed),
        *reset_delay_trace_mismatches(delay),
    )
    return BootTraceAnalysis(delay, processed_instructions, len(observed), errors)


def ram_test_pattern(length: int) -> bytes:
    """Return the repeating ``0x00``–``0xFA`` pattern used by ``3F:461A``."""

    if not 0 <= length <= 0x10000:
        raise ValueError("RAM-test length must be between zero and 0x10000")
    pattern = bytes(range(0xFB))
    repeats, remainder = divmod(length, len(pattern))
    return pattern * repeats + pattern[:remainder]


def first_ram_test_mismatch(data: bytes) -> int | None:
    """Return the first offset that fails the ``3F:461A`` pattern check."""

    expected = ram_test_pattern(len(data))
    return next(
        (index for index, (actual, wanted) in enumerate(zip(data, expected)) if actual != wanted),
        None,
    )


def dataclass_dict(value: object) -> dict[str, object]:
    """Serialize these reports while rendering ROM locations as strings."""

    payload = asdict(value)
    for key, item in tuple(payload.items()):
        if isinstance(item, dict) and set(item) == {"page", "address"}:
            payload[key] = f"{item['page']:02X}:{item['address']:04X}"
    return payload
