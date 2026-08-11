"""Streaming file digests shared by build, emulator, and trace tooling."""

from hashlib import sha256
from pathlib import Path

DEFAULT_CHUNK_SIZE = 1024 * 1024


def file_sha256(path: Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Hash one file in bounded memory."""

    if chunk_size <= 0:
        raise ValueError("hash chunk size must be positive")
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()
