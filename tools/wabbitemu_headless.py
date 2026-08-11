"""Build and run the pinned Wabbitemu core without its Windows GUI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import re
import subprocess


WABBITEMU_COMMIT = "48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422"
WABBITEMU_ARCHIVE_URL = (
    "https://codeload.github.com/sputt/wabbitemu/tar.gz/" + WABBITEMU_COMMIT
)
WABBITEMU_ARCHIVE_SHA256 = (
    "e65e20f5b45dbf5312e92a2619e3fbc0dfe228d4464134753fdc4930b7d12ac4"
)
WABBITEMU_TREE_SHA256 = (
    "a8a4f97fc7952770bed317b4a477f80345894da38d14fad8f0bf0ee60aae71ba"
)
FLASH_SIZE = 0x100000

SOURCE_HASHES = {
    "stdafx.h": "d0f54379a6837f20576ef498474ba663726fe18ae0f82532b3e6e6f0ed4465f0",
    "core/core.c": "7e7552577b9934a8e344d0bea8152e2b46ddf6840e997e478723cfde7c170c2b",
    "core/device.c": "c4db4da57e60a752274a58974284c442f5085b34d0e8152cf04fe7ab71996d8b",
    "core/alu.c": "07913115373e5a7581c2d44051f9fe30127ae69d6bf2d515a1177206e54cd5c6",
    "core/control.c": "8f00848f99c2492fb7c345b94357ecd7b5f28313ce9f82fead2c178aff3033fc",
    "core/indexcb.c": "ab22139ff8d2f81d5fdbd8b10ea15c30f17a089b3d41fe8c32b3153563e196d9",
    "hardware/83psehw.c": "3acba050bde4df46348aac703899e2980efb24b5fec83f3f0b5940a47f8327c4",
    "hardware/83phw.c": "a0ef5de56ea1c108c62c21128697e82da17518a6c9beb21459f14bbcd965307a",
    "hardware/lcd.c": "d5740860bb8ac31d2837242d792cce5628c9756f9754db03e78c42b5f1b34dec",
    "hardware/colorlcd.c": "5ff7bddd637e9dbd35b53c2d4a65d014922ca480dd16c749b293780d20f561cc",
    "hardware/keys.c": "76bd42cddd50634495b01a4ff6d89f75f5448f0c869aa926b492aab021fd57d9",
}

COMPILE_SOURCES = tuple(path for path in SOURCE_HASHES if path.endswith(".c"))
REPORT_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")


class WabbitemuHeadlessError(ValueError):
    """A pinned-source, build, execution, or report invariant failed."""


@dataclass(frozen=True)
class WabbitemuRunReport:
    """Stable fields emitted by the native headless runner."""

    steps: int
    tstates: int
    pc: int
    halted: bool
    changed_bytes: int
    input_fnv1a64: str
    output_fnv1a64: str
    wake: str
    settled: bool
    visits: tuple[str, ...]
    input_sha256: str = ""
    output_sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def file_sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest for *path*."""

    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_tree_sha256(source: Path) -> str:
    """Hash paths and contents in a checkout, excluding Git administration."""

    digest = sha256()
    paths = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(source).parts
    )
    for path in paths:
        relative = path.relative_to(source).as_posix().encode()
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def validate_pinned_source(source: Path) -> dict[str, str]:
    """Verify every Wabbitemu translation unit used by the runner."""

    try:
        tree_digest = source_tree_sha256(source)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot hash Wabbitemu source tree: {error}") from error
    if tree_digest != WABBITEMU_TREE_SHA256:
        raise WabbitemuHeadlessError(
            f"source tree SHA-256 is {tree_digest}; expected {WABBITEMU_TREE_SHA256}"
        )
    actual = {}
    for relative, expected in SOURCE_HASHES.items():
        path = source / relative
        try:
            digest = file_sha256(path)
        except OSError as error:
            raise WabbitemuHeadlessError(f"cannot read pinned source {path}: {error}") from error
        if digest != expected:
            raise WabbitemuHeadlessError(
                f"{relative} SHA-256 is {digest}; expected {expected}"
            )
        actual[relative] = digest
    return actual


def build_command(
    source: Path,
    harness: Path,
    output: Path,
    *,
    cxx: str = "g++",
) -> list[str]:
    """Return the exact Linux compilation command for the pinned core."""

    includes = (source, source / "core", source / "hardware", source / "utilities")
    return [
        cxx,
        "-std=gnu++11",
        "-O2",
        "-D_LINUX",
        "-D__pragma(x)=",
        *(f"-I{path}" for path in includes),
        str(harness),
        *(str(source / relative) for relative in COMPILE_SOURCES),
        "-lm",
        "-o",
        str(output),
    ]


def build_headless(
    source: Path,
    harness: Path,
    output: Path,
    *,
    cxx: str = "g++",
) -> list[str]:
    """Validate the pinned sources and compile the native runner."""

    validate_pinned_source(source)
    command = build_command(source, harness, output, cxx=cxx)
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise WabbitemuHeadlessError(f"Wabbitemu headless build failed: {error}") from error
    return command


def parse_run_report(line: str) -> WabbitemuRunReport:
    """Parse one native runner status line, rejecting missing fields."""

    fields = {match["key"]: match["value"] for match in REPORT_PATTERN.finditer(line)}
    required = {
        "steps",
        "tstates",
        "pc",
        "halted",
        "changed_bytes",
        "input_fnv1a64",
        "output_fnv1a64",
        "wake",
        "settled",
        "visits",
    }
    missing = sorted(required - fields.keys())
    if missing:
        raise WabbitemuHeadlessError(
            "native runner report omits " + ", ".join(missing)
        )
    try:
        return WabbitemuRunReport(
            steps=int(fields["steps"], 0),
            tstates=int(fields["tstates"], 0),
            pc=int(fields["pc"], 0),
            halted=bool(int(fields["halted"], 0)),
            changed_bytes=int(fields["changed_bytes"], 0),
            input_fnv1a64=fields["input_fnv1a64"],
            output_fnv1a64=fields["output_fnv1a64"],
            wake=fields["wake"],
            settled=fields["settled"] == "yes",
            visits=(
                ()
                if fields["visits"] == "-"
                else tuple(filter(None, fields["visits"].split(",")))
            ),
        )
    except ValueError as error:
        raise WabbitemuHeadlessError(f"invalid native runner report: {line.strip()}") from error


def run_headless(
    binary: Path,
    input_image: Path,
    output_image: Path,
    *,
    max_steps: int = 200_000_000,
    min_steps: int = 20_000_000,
    sample_interval: int = 1_000_000,
    settle_samples: int = 10,
) -> WabbitemuRunReport:
    """Cold-boot one image, wake it, and return a hash-complete run report."""

    try:
        input_size = input_image.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot inspect input image: {error}") from error
    if input_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"input image must contain 0x{FLASH_SIZE:X} bytes, got 0x{input_size:X}"
        )
    command = [
        str(binary),
        str(input_image),
        str(output_image),
        str(max_steps),
        str(min_steps),
        str(sample_interval),
        str(settle_samples),
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise WabbitemuHeadlessError(f"cannot execute native runner: {error}") from error
    if completed.returncode not in (0, 3):
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise WabbitemuHeadlessError(f"native runner failed: {detail}")
    report = parse_run_report(completed.stdout)
    try:
        output_size = output_image.stat().st_size
    except OSError as error:
        raise WabbitemuHeadlessError(f"native runner produced no output image: {error}") from error
    if output_size != FLASH_SIZE:
        raise WabbitemuHeadlessError(
            f"output image must contain 0x{FLASH_SIZE:X} bytes, got 0x{output_size:X}"
        )
    return WabbitemuRunReport(
        **{
            **report.to_dict(),
            "input_sha256": file_sha256(input_image),
            "output_sha256": file_sha256(output_image),
        }
    )
