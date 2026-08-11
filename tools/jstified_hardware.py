"""Pinned source profile for the deployed jsTIfied emulator."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

JSTIFIED_PROJECT_URL = "https://www.cemetech.net/projects/item.php?id=42"
JSTIFIED_ARTIFACT_URL = (
    "https://www.cemetech.net/projects/jstified/"
    "jstified_compressed.js?20170706a"
)
JSTIFIED_ARTIFACT_SHA256 = (
    "c7325a38f976f64eaa34182da17d838fe4831eece4650b92d5db710cf7a8fc5b"
)
JSTIFIED_ARTIFACT_SIZE = 297_128
JSTIFIED_READABLE_COMMIT = "56246a1181f90123a843ea17eb9e0f2fcda65113"
JSTIFIED_READABLE_URL = (
    "https://github.com/Quuxplusone/ti83/blob/"
    f"{JSTIFIED_READABLE_COMMIT}/jstified.js"
)
JSTIFIED_READABLE_SHA256 = (
    "05aeb2925b5d7b5793480052437eae9eac4db330c99b21951134b7538038e5ec"
)


@dataclass(frozen=True)
class SourceFingerprint:
    """One exact byte fragment and the feature it identifies."""

    feature: str
    fragment: bytes


FINGERPRINTS = (
    SourceFingerprint(
        "flash unlock decode",
        b"170==d&&2730==(c&4095)?flash.phase++",
    ),
    SourceFingerprint("immediate Flash programming", b"flash.mem[c]&=d"),
    SourceFingerprint(
        "protected-sector erase gate",
        b"function flash_erase(c){if(!flash.pages[c][0])",
    ),
    SourceFingerprint("mapping-mode latch", b"i6.mmap=d&1"),
    SourceFingerprint("execution-protection reset", b"z8.halted=2"),
    SourceFingerprint("timer source decoder", b"function timer_duration(c,d)"),
    SourceFingerprint("LCD busy model", b"lcd.tmin=25;lcd.tjit=22"),
    SourceFingerprint("link-assist output", b"i6.la_outstamp=1"),
    SourceFingerprint(
        "fixed USB identity reads",
        b"case 76:return 34;case 77:return 165;",
    ),
)

FEATURES: dict[str, dict[str, object]] = {
    "flash": {
        "implemented": True,
        "geometry": "1 MiB with 15x64 KiB, 32 KiB, 8 KiB, 8 KiB, 16 KiB",
        "commands": ["program", "sector erase", "chip erase", "ID"],
        "mutation": "immediate; no busy or toggle-bit state",
        "quirks": [
            "sector protection is consulted for erase but not program",
            "a recognized ID read immediately returns to array mode",
        ],
    },
    "paging": {
        "implemented": True,
        "ports": ["0x04-0x07", "0x0E-0x0F", "0x27-0x28"],
        "paired_mode": True,
        "overlays": True,
    },
    "execution_protection": {
        "implemented": True,
        "flash_page_groups": True,
        "ram_groups": True,
        "byte_bounds_0x25_0x26": False,
    },
    "timers": {
        "implemented": True,
        "ports": "0x30-0x38",
        "cpu_and_crystal_sources": True,
    },
    "interrupts": {
        "implemented": True,
        "standard_timer": True,
        "on_key": True,
    },
    "keypad": {"implemented": True, "active_low_matrix": True},
    "lcd": {
        "implemented": True,
        "storage": "120x64",
        "visible_width": 96,
        "dummy_read": True,
        "busy_jitter": True,
    },
    "link": {
        "implemented": True,
        "raw_link": True,
        "link_assist": True,
    },
    "usb": {
        "implemented": False,
        "fixed_reads": {
            "0x4C": "0x22",
            "0x4D": "0xA5",
            "0x55": "0x1F",
            "0x56": "0x00",
            "0x57": "0x50",
        },
        "endpoint_or_fdrc_model": False,
    },
    "md5": {"implemented": True, "ports": "0x18-0x1F"},
}


def verify_fingerprints(data: bytes) -> tuple[str, ...]:
    """Return verified feature labels, rejecting source-shape drift."""

    missing = [item.feature for item in FINGERPRINTS if item.fragment not in data]
    if missing:
        raise ValueError("missing jsTIfied source fingerprints: " + ", ".join(missing))
    return tuple(item.feature for item in FINGERPRINTS)


def describe_artifact(path: Path) -> dict[str, object]:
    """Verify and describe the exact deployed jsTIfied JavaScript artifact."""

    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != JSTIFIED_ARTIFACT_SIZE:
        raise ValueError(
            f"jsTIfied artifact size is {len(data)}; expected {JSTIFIED_ARTIFACT_SIZE}"
        )
    if digest != JSTIFIED_ARTIFACT_SHA256:
        raise ValueError(
            f"jsTIfied artifact SHA-256 is {digest}; expected {JSTIFIED_ARTIFACT_SHA256}"
        )
    verified = verify_fingerprints(data)
    return {
        "emulator": "jsTIfied",
        "project_url": JSTIFIED_PROJECT_URL,
        "artifact_url": JSTIFIED_ARTIFACT_URL,
        "artifact": str(path),
        "artifact_size": len(data),
        "artifact_sha256": digest,
        "readable_mirror": {
            "url": JSTIFIED_READABLE_URL,
            "commit": JSTIFIED_READABLE_COMMIT,
            "sha256": JSTIFIED_READABLE_SHA256,
            "scope": "readability aid; not byte-identical to the deployed artifact",
        },
        "verified_fingerprints": list(verified),
        "features": FEATURES,
        "evidence_limit": (
            "source behavior of the pinned deployed emulator; not physical TI-84 Plus "
            "behavior or dynamic execution of the emulator"
        ),
    }
