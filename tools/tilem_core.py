"""Reusable pinned-TilEm source, build, hashing, and process helpers."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

TILEM_COMMIT = "f56ad637d0524ee841dd381be6ecbaf5b8975600"
TILEM_TREE = "58316afe35d69e69353f0f743698144153051d4a"
TILEM_SOURCE_COUNT = 65


class TilemCoreError(ValueError):
    """A pinned-source, build, executable, or native-process invariant failed."""


@dataclass(frozen=True)
class NativeProbeOutput:
    """Captured output and identity for one successful native probe run."""

    stdout: str
    stderr_lines: tuple[str, ...]
    binary_sha256: str


def file_sha256(path: Path) -> str:
    """Hash one file without loading it all into memory."""

    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tilem_sources(source: Path) -> tuple[Path, ...]:
    """Enumerate the complete pinned libtilemcore C source set."""

    return tuple(
        sorted((source / "emu").glob("*.c")) + sorted((source / "emu").glob("*/*.c"))
    )


def validate_tilem_source(source: Path) -> None:
    """Require the exact clean tracked TilEm worktree used by native probes."""

    try:
        commit = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD^{tree}"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(source), "diff", "--quiet", "HEAD", "--"],
            check=False,
        )
        sources = tilem_sources(source)
    except (OSError, subprocess.CalledProcessError) as error:
        raise TilemCoreError(f"cannot validate TilEm source: {error}") from error
    if commit != TILEM_COMMIT or tree != TILEM_TREE:
        raise TilemCoreError("TilEm source is not the pinned f56ad637 tree")
    if dirty.returncode != 0:
        raise TilemCoreError("TilEm source contains tracked modifications")
    if len(sources) != TILEM_SOURCE_COUNT:
        raise TilemCoreError(
            "pinned TilEm build requires "
            f"{TILEM_SOURCE_COUNT} emulator C files, found {len(sources)}"
        )


def build_command(
    source: Path,
    adapters: Sequence[Path],
    output: Path,
    *,
    cc: str = "cc",
) -> list[str]:
    """Return a complete direct-core native-probe compiler command."""

    validate_tilem_source(source)
    if not adapters:
        raise TilemCoreError("a native TilEm probe requires at least one adapter")
    return [
        cc,
        "-std=c99",
        "-O2",
        "-ffunction-sections",
        "-fdata-sections",
        '-DPACKAGE_VERSION="2.1"',
        f"-I{source / 'emu'}",
        *(str(path) for path in adapters),
        *(str(path) for path in tilem_sources(source)),
        "-Wl,--gc-sections",
        "-lm",
        "-o",
        str(output),
    ]


def build_probe(
    source: Path,
    adapters: Sequence[Path],
    output: Path,
    *,
    cc: str = "cc",
) -> list[str]:
    """Validate pinned sources and compile one direct-core native probe."""

    command = build_command(source, adapters, output, cc=cc)
    try:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError as error:
        raise TilemCoreError(f"cannot execute TilEm compiler: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise TilemCoreError(f"TilEm native-probe build failed: {detail}")
    return command


def run_probe(binary: Path, arguments: Iterable[str]) -> NativeProbeOutput:
    """Run one native probe and retain exact nonempty diagnostic lines."""

    try:
        completed = subprocess.run(
            [str(binary), *arguments],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise TilemCoreError(f"cannot execute TilEm native probe: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise TilemCoreError(f"TilEm native probe failed: {detail}")
    return NativeProbeOutput(
        stdout=completed.stdout,
        stderr_lines=tuple(line for line in completed.stderr.splitlines() if line),
        binary_sha256=file_sha256(binary),
    )
