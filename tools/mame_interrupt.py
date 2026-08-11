"""Typed report and oracle for MAME's TI-84 Plus legacy interrupts."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from interrupt_controller import MAME_STANDARD_TIMER_RATES, MameLegacyInterruptState
from mame_runtime import MAME_VERSION, MameRuntimeError, parse_report_fields

MASK_VALUES = (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0xFF)


@dataclass(frozen=True)
class MameInterruptReport:
    """Complete native port, ON-edge, timer, and reset observations."""

    machine: str
    version: str
    reset_status02: int
    reset_status03: int
    reset_status04: int
    mask_values: tuple[int, ...]
    mask_status03: tuple[int, ...]
    mask_status04: tuple[int, ...]
    injected_seed07: int
    injected_keep_on: int
    injected_keep_timers: int
    injected_keep_all: int
    injected_clear: int
    injected_status02: int
    on_masked_press: int
    on_held_enable: int
    on_release: int
    on_enabled_press: int
    on_enabled_release: int
    on_after_ack: int
    timer1_status: int
    timer2_status: int
    timers_both_status: int
    timer_config00_status: int
    timer_config06_status: int
    soft_before: int
    soft_immediate03: int
    soft_immediate04: int
    soft_after_timers: int
    soft_after_on: int
    soft_pc: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _line(output: str, prefix: str) -> dict[str, str]:
    lines = [line for line in output.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        raise MameRuntimeError(f"MAME interrupt output omits {prefix.strip()} report")
    return parse_report_fields(lines[0])


def _hex(fields: dict[str, str], name: str) -> int:
    try:
        return int(fields[name], 16)
    except KeyError as error:
        raise MameRuntimeError(
            f"MAME interrupt report omits field {error.args[0]}"
        ) from error
    except ValueError as error:
        raise MameRuntimeError(f"invalid MAME interrupt field {name}") from error


def _block(value: str, size: int, name: str) -> tuple[int, ...]:
    if len(value) != size * 2:
        raise MameRuntimeError(
            f"MAME interrupt {name} must contain exactly {size} bytes"
        )
    try:
        return tuple(
            int(value[index : index + 2], 16) for index in range(0, len(value), 2)
        )
    except ValueError as error:
        raise MameRuntimeError(f"invalid MAME interrupt {name}") from error


def parse_mame_interrupt_report(output: str) -> MameInterruptReport:
    """Parse every native MAME legacy-interrupt report line."""

    identity = _line(output, "MAME_INTERRUPT identity ")
    reset = _line(output, "MAME_INTERRUPT reset ")
    masks = _line(output, "MAME_INTERRUPT masks ")
    injected = _line(output, "MAME_INTERRUPT injected ")
    on = _line(output, "MAME_INTERRUPT on ")
    timers = _line(output, "MAME_INTERRUPT timers ")
    soft = _line(output, "MAME_INTERRUPT soft_reset ")
    try:
        return MameInterruptReport(
            machine=identity["machine"],
            version=identity["version"],
            reset_status02=_hex(reset, "status02"),
            reset_status03=_hex(reset, "status03"),
            reset_status04=_hex(reset, "status04"),
            mask_values=_block(masks["values"], len(MASK_VALUES), "mask values"),
            mask_status03=_block(
                masks["status03"], len(MASK_VALUES), "port-0x03 status"
            ),
            mask_status04=_block(
                masks["status04"], len(MASK_VALUES), "port-0x04 status"
            ),
            injected_seed07=_hex(injected, "seed07"),
            injected_keep_on=_hex(injected, "keep_on"),
            injected_keep_timers=_hex(injected, "keep_timers"),
            injected_keep_all=_hex(injected, "keep_all"),
            injected_clear=_hex(injected, "clear"),
            injected_status02=_hex(injected, "status02"),
            on_masked_press=_hex(on, "masked_press"),
            on_held_enable=_hex(on, "held_enable"),
            on_release=_hex(on, "release"),
            on_enabled_press=_hex(on, "enabled_press"),
            on_enabled_release=_hex(on, "enabled_release"),
            on_after_ack=_hex(on, "after_ack"),
            timer1_status=_hex(timers, "timer1"),
            timer2_status=_hex(timers, "timer2"),
            timers_both_status=_hex(timers, "both"),
            timer_config00_status=_hex(timers, "config00"),
            timer_config06_status=_hex(timers, "config06"),
            soft_before=_hex(soft, "before"),
            soft_immediate03=_hex(soft, "immediate03"),
            soft_immediate04=_hex(soft, "immediate04"),
            soft_after_timers=_hex(soft, "after_timers"),
            soft_after_on=_hex(soft, "after_on"),
            soft_pc=_hex(soft, "pc"),
        )
    except KeyError as error:
        raise MameRuntimeError(
            f"MAME interrupt report omits field {error.args[0]}"
        ) from error


def expected_mame_interrupt_report() -> MameInterruptReport:
    """Derive the exact report from the reusable MAME state model."""

    reset = MameLegacyInterruptState()
    mask_reads = tuple(reset.write_port03(value).status for value in MASK_VALUES)

    seeded = reset.write_port02(0x07)
    keep_on = seeded.write_port03(0x01)
    keep_timers = seeded.write_port03(0x06)
    keep_all = seeded.write_port03(0xFF)
    cleared = seeded.write_port03(0x00)

    on = reset.write_port02(0).write_port03(0).sample_on(True)
    masked_press = on.status
    on = on.write_port03(0x01).sample_on(True)
    held_enable = on.status
    on = on.sample_on(False)
    released = on.status
    on = on.sample_on(True)
    enabled_press = on.status
    on = on.sample_on(False)
    enabled_release = on.status
    after_ack = on.write_port03(0xFE).status

    timer1 = reset.write_port02(0).write_port03(0x02).standard_timer_tick(1)
    timer2 = reset.write_port02(0).write_port03(0x04).standard_timer_tick(2)
    both = (
        reset.write_port02(0)
        .write_port03(0x06)
        .standard_timer_tick(1)
        .standard_timer_tick(2)
    )

    soft = reset.write_port02(0x07).write_port03(0x07).soft_reset()
    soft_cleared = soft.write_port02(0)
    soft_timers = soft_cleared.standard_timer_tick(1).standard_timer_tick(2)
    soft_on = soft_timers.sample_on(True)
    return MameInterruptReport(
        machine="ti84pv3",
        version=MAME_VERSION,
        reset_status02=0xC3,
        reset_status03=reset.status,
        reset_status04=reset.status,
        mask_values=MASK_VALUES,
        mask_status03=mask_reads,
        mask_status04=mask_reads,
        injected_seed07=seeded.status,
        injected_keep_on=keep_on.status,
        injected_keep_timers=keep_timers.status,
        injected_keep_all=keep_all.status,
        injected_clear=cleared.status,
        injected_status02=0xC3,
        on_masked_press=masked_press,
        on_held_enable=held_enable,
        on_release=released,
        on_enabled_press=enabled_press,
        on_enabled_release=enabled_release,
        on_after_ack=after_ack,
        timer1_status=timer1.status,
        timer2_status=timer2.status,
        timers_both_status=both.status,
        timer_config00_status=timer1.status,
        timer_config06_status=timer1.status,
        soft_before=soft.status,
        soft_immediate03=soft.status,
        soft_immediate04=soft.status,
        soft_after_timers=soft_timers.status,
        soft_after_on=soft_on.status,
        soft_pc=0,
    )


def validate_mame_interrupt_report(
    report: MameInterruptReport,
) -> dict[str, object]:
    """Require native observations implied by MAME 0.287's source."""

    expected = expected_mame_interrupt_report()
    if report != expected:
        raise MameRuntimeError(
            "MAME interrupt report disagrees with the 0.287 source model"
        )
    return {
        "source_model": {
            "port03_read": "shared legacy/completion status",
            "port04_read": "shared legacy/completion status",
            "port02_write": "direct overwrite of ON and timer pending bits",
            "port03_write_mask": "bits 0-2 only; clear pending on zero",
            "link_interrupt": False,
            "low_power_control": False,
            "on_edge": "press transition sampled by timer 1",
            "standard_timer_hz": list(MAME_STANDARD_TIMER_RATES),
            "port04_timer_rate_control": False,
            "soft_reset_retains_fields": True,
        },
        "native": report.to_dict(),
    }
