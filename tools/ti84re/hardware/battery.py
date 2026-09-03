"""ROM battery-level decision logic and emulator comparator models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from itertools import pairwise

SELECTORS = (0x06, 0x46, 0x86, 0xC6)
ROM_TEST_ORDER = (0x06, 0xC6, 0x86, 0x46)
TILEM_THRESHOLDS_TENTHS = {
    0x06: 33,
    0x46: 39,
    0x86: 36,
    0xC6: 43,
}


@dataclass(frozen=True)
class BatteryRegion:
    """One voltage interval with stable comparator and bcall results."""

    lower_tenths: int | None
    upper_tenths: int | None
    samples: tuple[bool, ...]
    level: int

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["lower_volts"] = _volts(self.lower_tenths)
        result["upper_volts"] = _volts(self.upper_tenths)
        result["samples"] = {
            f"0x{selector:02X}": passed
            for selector, passed in zip(SELECTORS, self.samples, strict=True)
        }
        del result["lower_tenths"]
        del result["upper_tenths"]
        return result


def _volts(tenths: int | None) -> str | None:
    return None if tenths is None else f"{tenths / 10:.1f}"


def parse_voltage_tenths(text: str) -> int:
    """Parse a voltage that can be represented in TilEm's 0.1 V units."""

    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"invalid voltage {text!r}") from error
    tenths = value * 10
    if tenths != tenths.to_integral_value():
        raise ValueError("voltage must be a multiple of 0.1 V")
    result = int(tenths)
    if not 0 <= result <= 255:
        raise ValueError("voltage must fit TilEm's unsigned 0.1 V field")
    return result


def battery_level(samples: Mapping[int, bool]) -> int:
    """Return `_Chk_Batt_Level`'s result for four comparator observations."""

    if set(samples) != set(SELECTORS):
        missing = set(SELECTORS) - set(samples)
        extra = set(samples) - set(SELECTORS)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(f"0x{x:02X}" for x in sorted(missing)))
        if extra:
            detail.append("extra " + ", ".join(f"0x{x:02X}" for x in sorted(extra)))
        raise ValueError("battery samples must cover exactly four selectors: " + "; ".join(detail))
    if not samples[0x06]:
        return 0
    if samples[0xC6]:
        return 4
    if samples[0x86]:
        return 3
    if samples[0x46]:
        return 2
    return 1


def comparator_samples(
    voltage_tenths: int,
    thresholds: Mapping[int, int] = TILEM_THRESHOLDS_TENTHS,
) -> dict[int, bool]:
    """Evaluate the four selector comparators for one modeled voltage."""

    if set(thresholds) != set(SELECTORS):
        raise ValueError("threshold model must cover exactly the four selectors")
    return {
        selector: voltage_tenths >= thresholds[selector]
        for selector in SELECTORS
    }


def modeled_battery_level(
    voltage_tenths: int,
    thresholds: Mapping[int, int] = TILEM_THRESHOLDS_TENTHS,
) -> int:
    """Apply the ROM decision tree to one comparator threshold model."""

    return battery_level(comparator_samples(voltage_tenths, thresholds))


def threshold_regions(
    thresholds: Mapping[int, int] = TILEM_THRESHOLDS_TENTHS,
) -> tuple[BatteryRegion, ...]:
    """Return every voltage region separated by a modeled threshold."""

    if set(thresholds) != set(SELECTORS):
        raise ValueError("threshold model must cover exactly the four selectors")
    boundaries = sorted(set(thresholds.values()))
    regions = []
    intervals = [(None, boundaries[0])]
    intervals.extend(pairwise(boundaries))
    intervals.append((boundaries[-1], None))
    for lower, upper in intervals:
        representative = upper - 1 if lower is None else lower
        samples = comparator_samples(representative, thresholds)
        regions.append(
            BatteryRegion(
                lower,
                upper,
                tuple(samples[selector] for selector in SELECTORS),
                battery_level(samples),
            )
        )
    return tuple(regions)


def battery_model_report() -> dict[str, object]:
    """Return a JSON-serializable ROM/TilEm comparator report."""

    regions = threshold_regions()
    reachable = sorted({region.level for region in regions})
    return {
        "selector_order": [f"0x{selector:02X}" for selector in SELECTORS],
        "rom_test_order": [f"0x{selector:02X}" for selector in ROM_TEST_ORDER],
        "tilem_threshold_volts": {
            f"0x{selector:02X}": _volts(TILEM_THRESHOLDS_TENTHS[selector])
            for selector in SELECTORS
        },
        "regions": [region.to_dict() for region in regions],
        "reachable_levels": reachable,
        "unreachable_levels": sorted(set(range(5)) - set(reachable)),
    }
