"""Shared command-line builders for pinned emulator probe adapters."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import json
from pathlib import Path
from typing import Any

from ti84re.file_hashes import file_sha256
from ti84re.emulators.tilem.core import TILEM_COMMIT, TILEM_TREE
from ti84re.emulators.wabbitemu.headless import (
    WABBITEMU_COMMIT,
    WABBITEMU_TREE_SHA256,
    WabbitemuHeadlessError,
    build_headless,
)
from ti84re.paths import PROBES


BuildFunction = Callable[..., list[str]]


def _parser(description: str, compiler_option: str, compiler: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(compiler_option, default=compiler)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _prepare_output(parser: argparse.ArgumentParser, output: Path, force: bool) -> None:
    if output.exists() and not force:
        parser.error(f"refusing to overwrite existing output {output}; use --force")
    output.parent.mkdir(parents=True, exist_ok=True)


def _emit(
    report: dict[str, Any], *, as_json: bool, built_message: str | None
) -> None:
    if as_json:
        print(json.dumps(report, indent=2))
    elif built_message is None:
        print(report["output_sha256"])
    else:
        print(f"{built_message}: {report['output']}")
        print(f"binary SHA-256: {report['output_sha256']}")


def tilem_main(
    *,
    description: str,
    plain_name: str | None,
    adapter_names: Sequence[str],
    build: BuildFunction,
    error_types: tuple[type[BaseException], ...],
    adapters_as_list: bool = False,
    include_source: bool = True,
    pinned_plain: bool = True,
) -> None:
    """Build one TilEm adapter through the common guarded CLI."""

    parser = _parser(description, "--cc", "cc")
    args = parser.parse_args()
    adapters = [PROBES / "tilem" / name for name in adapter_names]
    adapter_argument: Path | list[Path] = adapters if adapters_as_list else adapters[-1]
    caught_errors = (OSError, *error_types)
    try:
        _prepare_output(parser, args.output, args.force)
        command = build(args.source, adapter_argument, args.output, cc=args.cc)
    except caught_errors as error:
        parser.error(str(error))
    report: dict[str, Any] = {
        "repository": "debrouxl/tilem",
        "commit": TILEM_COMMIT,
        "git_tree": TILEM_TREE,
        **({"source": str(args.source)} if include_source else {}),
        "adapters": [
            {"path": str(path), "sha256": file_sha256(path)} for path in adapters
        ],
        "output": str(args.output),
        "output_sha256": file_sha256(args.output),
        "command": command,
    }
    message = None
    if plain_name is not None:
        prefix = f"built pinned TilEm {TILEM_COMMIT[:8]}" if pinned_plain else "built"
        message = f"{prefix} {plain_name}"
    _emit(report, as_json=args.json, built_message=message)


def wabbitemu_main(
    *, description: str, plain_name: str | None, adapter_name: str
) -> None:
    """Build one Wabbitemu adapter through the common guarded CLI."""

    parser = _parser(description, "--cxx", "g++")
    args = parser.parse_args()
    adapter = PROBES / "wabbitemu" / adapter_name
    try:
        _prepare_output(parser, args.output, args.force)
        command = build_headless(args.source, adapter, args.output, cxx=args.cxx)
    except (OSError, WabbitemuHeadlessError) as error:
        parser.error(str(error))
    report = {
        "repository": "sputt/wabbitemu",
        "commit": WABBITEMU_COMMIT,
        "source_tree_sha256": WABBITEMU_TREE_SHA256,
        "source": str(args.source),
        "adapter": str(adapter),
        "adapter_sha256": file_sha256(adapter),
        "output": str(args.output),
        "output_sha256": file_sha256(args.output),
        "command": command,
    }
    _emit(report, as_json=args.json, built_message=plain_name)
