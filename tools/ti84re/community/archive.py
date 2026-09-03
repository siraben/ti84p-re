#!/usr/bin/env python3
"""Inventory and safely extract the public ticalc.org assembly archive.

This tool treats every downloaded ZIP as untrusted data. It never executes an
archive member, rejects paths that escape their per-archive destination, stores
links as inert metadata, and rejects other special files.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
from typing import Iterable, NamedTuple
import zipfile
import zlib


SOURCE_SUFFIXES = {
    ".a68",
    ".asm",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hh",
    ".hpp",
    ".inc",
    ".s",
    ".src",
    ".z80",
}


class Member(NamedTuple):
    path: str
    occurrence: int
    size: int
    compressed_size: int
    crc32: str
    compression_method: int
    kind: str
    is_source: bool


class Archive(NamedTuple):
    path: Path
    relative_path: str
    sha256: str
    size: int
    members: tuple[Member, ...]
    uncompressed_size: int
    source_member_count: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member_path(name: str) -> PurePosixPath:
    if "\x00" in name:
        raise ValueError("NUL byte in member name")
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe member path: {name!r}")
    if path.parts and ":" in path.parts[0]:
        raise ValueError(f"drive-qualified member path: {name!r}")
    return path


def _member_kind(info: zipfile.ZipInfo) -> str:
    unix_mode = info.external_attr >> 16
    file_type = stat.S_IFMT(unix_mode)
    if info.is_dir() or file_type == stat.S_IFDIR:
        return "directory"
    if file_type == stat.S_IFLNK:
        return "symlink"
    if file_type in {0, stat.S_IFREG}:
        return "file"
    raise ValueError(f"special-file member is not allowed: {info.filename!r}")


def inspect_archive(path: Path, root: Path) -> Archive:
    members: list[Member] = []
    seen: dict[str, int] = {}
    total_size = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            safe_path = _safe_member_path(info.filename)
            member_path = safe_path.as_posix()
            occurrence = seen.get(member_path, 0) + 1
            seen[member_path] = occurrence
            kind = _member_kind(info)
            total_size += info.file_size
            members.append(
                Member(
                    path=member_path,
                    occurrence=occurrence,
                    size=info.file_size,
                    compressed_size=info.compress_size,
                    crc32=f"{info.CRC:08x}",
                    compression_method=info.compress_type,
                    kind=kind,
                    is_source=(
                        kind == "file" and safe_path.suffix.lower() in SOURCE_SUFFIXES
                    ),
                )
            )
    relative_path = path.relative_to(root).as_posix()
    return Archive(
        path=path,
        relative_path=relative_path,
        sha256=sha256_file(path),
        size=path.stat().st_size,
        members=tuple(members),
        uncompressed_size=total_size,
        source_member_count=sum(member.is_source for member in members),
    )


def inspect_tree(root: Path) -> list[Archive]:
    root = root.resolve()
    return [
        inspect_archive(path, root)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() == ".zip"
    ]


def write_inventory(
    archives: Iterable[Archive], archive_csv: Path, member_csv: Path
) -> None:
    archive_list = list(archives)
    duplicate_counts: dict[str, int] = {}
    for archive in archive_list:
        duplicate_counts[archive.sha256] = duplicate_counts.get(archive.sha256, 0) + 1

    archive_csv.parent.mkdir(parents=True, exist_ok=True)
    with archive_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            (
                "archive_path",
                "sha256",
                "archive_size",
                "member_count",
                "uncompressed_size",
                "source_member_count",
                "identical_archive_count",
            )
        )
        for archive in archive_list:
            writer.writerow(
                (
                    archive.relative_path,
                    archive.sha256,
                    archive.size,
                    len(archive.members),
                    archive.uncompressed_size,
                    archive.source_member_count,
                    duplicate_counts[archive.sha256],
                )
            )

    member_csv.parent.mkdir(parents=True, exist_ok=True)
    with member_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            (
                "archive_path",
                "archive_sha256",
                "member_path",
                "occurrence",
                "size",
                "compressed_size",
                "crc32",
                "compression_method",
                "kind",
                "is_source",
            )
        )
        for archive in archive_list:
            for member in archive.members:
                writer.writerow(
                    (
                        archive.relative_path,
                        archive.sha256,
                        member.path,
                        member.occurrence,
                        member.size,
                        member.compressed_size,
                        member.crc32,
                        member.compression_method,
                        member.kind,
                        int(member.is_source),
                    )
                )


def extract_archive(archive: Archive, destination: Path) -> None:
    final = destination / f"{archive.relative_path}.contents"
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise FileExistsError(f"refusing to replace existing extraction: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        unsupported = [
            member
            for member in archive.members
            if member.compression_method
            not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
        ]
        if unsupported:
            if any(member.kind == "symlink" for member in archive.members):
                raise ValueError("external extraction of symlink members is not allowed")
            if any(member.occurrence > 1 for member in archive.members):
                raise ValueError("external extraction of duplicate members is not allowed")
            subprocess.run(
                ["unzip", "-qq", str(archive.path), "-d", str(temporary)],
                check=True,
            )
            expected = Counter(
                (member.size, member.crc32)
                for member in archive.members
                if member.kind == "file"
            )
            actual: Counter[tuple[int, str]] = Counter()
            for directory, directory_names, file_names in os.walk(
                temporary, followlinks=False
            ):
                for name in directory_names:
                    if (Path(directory) / name).is_symlink():
                        raise ValueError("external extractor created a directory link")
                for name in file_names:
                    target = Path(directory) / name
                    if target.is_symlink() or not target.is_file():
                        raise ValueError("external extractor created a special file")
                    crc32 = 0
                    size = 0
                    with target.open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            size += len(block)
                            crc32 = zlib.crc32(block, crc32)
                    actual[(size, f"{crc32 & 0xFFFFFFFF:08x}")] += 1
            if actual != expected:
                raise ValueError("external extraction does not match ZIP size/CRC records")
            os.replace(temporary, final)
            return
        with zipfile.ZipFile(archive.path) as source:
            for info, member in zip(source.infolist(), archive.members, strict=True):
                target = temporary.joinpath(*PurePosixPath(member.path).parts)
                if member.occurrence > 1:
                    target = (
                        temporary
                        / "__archive_duplicates__"
                        / str(member.occurrence)
                        / PurePosixPath(member.path)
                    )
                if member.kind == "directory":
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if member.kind == "symlink":
                    link_path = PurePosixPath(f"{member.path}.link-target")
                    if member.occurrence > 1:
                        link_path = (
                            PurePosixPath("__archive_duplicates__")
                            / str(member.occurrence)
                            / link_path
                        )
                    target = temporary / "__archive_symlinks__" / link_path
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as input_stream, target.open("xb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
        os.replace(temporary, final)
    except BaseException:
        shutil.rmtree(temporary)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="root of the mirrored archive tree")
    parser.add_argument("--archive-csv", type=Path, required=True)
    parser.add_argument("--member-csv", type=Path, required=True)
    parser.add_argument("--extract-to", type=Path)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip atomically completed archive directories",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archives = inspect_tree(args.root)
    write_inventory(archives, args.archive_csv, args.member_csv)
    if args.extract_to is not None:
        for archive in archives:
            final = args.extract_to / f"{archive.relative_path}.contents"
            if args.resume and final.exists():
                continue
            extract_archive(archive, args.extract_to)
    print(
        f"inventoried {len(archives)} ZIP archives, "
        f"{sum(len(archive.members) for archive in archives)} members, "
        f"{sum(archive.source_member_count for archive in archives)} source members"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
