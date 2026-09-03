"""Validate local retail-page AppVars and assemble the pinned complete ROM."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from ti84re.flash.hardware import FLASH_SIZE
from ti84re.hardware.probe import APPVAR_TYPE, ProbeFormatError, decode_ti_variable_file
from ti84re.rom.signatures import (
    D84PBE1_APPVAR_SHA256,
    D84PBE1_PAGE_SHA256,
    D84PBE2_APPVAR_SHA256,
    D84PBE2_PAGE_SHA256,
    TI84_PLUS_OS_255MP_SHA256,
    TI84_PLUS_PATCHED_BASE_SHA256,
)


PAGE_SIZE = 0x4000


class RomAssemblyError(ValueError):
    """A local ROM input violates an identity or container invariant."""


@dataclass(frozen=True)
class RetailPageSpec:
    """Expected identity and destination for one ignored page artifact."""

    filename: str
    variable_name: str
    page: int
    appvar_sha256: str
    page_sha256: str


@dataclass(frozen=True)
class RetailPageArtifact:
    """One validated TI AppVar and its decoded 16 KiB page."""

    spec: RetailPageSpec
    payload: bytes
    comment: str


@dataclass(frozen=True)
class RomPagePatch:
    """One installed page and how many base-image bytes it changes."""

    filename: str
    variable_name: str
    page: int
    appvar_sha256: str
    page_sha256: str
    changed_bytes: int


@dataclass(frozen=True)
class CompleteRomAssembly:
    """Validated complete ROM bytes, page-0 slice, and patch accounting."""

    image: bytes
    page0: bytes
    base_sha256: str
    output_sha256: str
    patches: tuple[RomPagePatch, ...]


RETAIL_PAGE_SPECS = (
    RetailPageSpec(
        filename="D84PBE2.8Xv",
        variable_name="D84PBE2",
        page=0x2F,
        appvar_sha256=D84PBE2_APPVAR_SHA256,
        page_sha256=D84PBE2_PAGE_SHA256,
    ),
    RetailPageSpec(
        filename="D84PBE1.8Xv",
        variable_name="D84PBE1",
        page=0x3F,
        appvar_sha256=D84PBE1_APPVAR_SHA256,
        page_sha256=D84PBE1_PAGE_SHA256,
    ),
)


def digest(data: bytes) -> str:
    """Return the SHA-256 identity used by the assembly reports."""

    return sha256(data).hexdigest()


def decode_retail_page(blob: bytes, spec: RetailPageSpec) -> RetailPageArtifact:
    """Decode and validate one exact TI application-variable page artifact."""

    try:
        variable = decode_ti_variable_file(blob)
    except ProbeFormatError as error:
        raise RomAssemblyError(f"{spec.filename}: {error}") from error
    if variable.variable_type != APPVAR_TYPE:
        raise RomAssemblyError(
            f"{spec.filename}: expected AppVar type 0x{APPVAR_TYPE:02X}, got "
            f"0x{variable.variable_type:02X}"
        )
    if variable.name != spec.variable_name:
        raise RomAssemblyError(
            f"{spec.filename}: variable name is {variable.name!r}; "
            f"expected {spec.variable_name!r}"
        )
    if variable.version != 0 or variable.archived:
        raise RomAssemblyError(
            f"{spec.filename}: expected unarchived version-zero AppVar"
        )
    if len(variable.data) != PAGE_SIZE + 2:
        raise RomAssemblyError(
            f"{spec.filename}: AppVar data must contain 0x{PAGE_SIZE + 2:X} "
            f"bytes, got 0x{len(variable.data):X}"
        )
    declared_size = int.from_bytes(variable.data[:2], "little")
    if declared_size != PAGE_SIZE:
        raise RomAssemblyError(
            f"{spec.filename}: internal page size is 0x{declared_size:X}; "
            f"expected 0x{PAGE_SIZE:X}"
        )
    appvar_hash = digest(blob)
    if appvar_hash != spec.appvar_sha256:
        raise RomAssemblyError(
            f"{spec.filename}: SHA-256 is {appvar_hash}; "
            f"expected {spec.appvar_sha256}"
        )
    payload = variable.data[2:]
    payload_hash = digest(payload)
    if payload_hash != spec.page_sha256:
        raise RomAssemblyError(
            f"{spec.filename}: page SHA-256 is {payload_hash}; "
            f"expected {spec.page_sha256}"
        )
    return RetailPageArtifact(spec=spec, payload=payload, comment=variable.comment)


def assemble_complete_rom(
    base: bytes,
    appvars: dict[str, bytes],
) -> CompleteRomAssembly:
    """Validate exact inputs and install retail pages `2F` and `3F`."""

    if len(base) != FLASH_SIZE:
        raise RomAssemblyError(
            f"base ROM must contain 0x{FLASH_SIZE:X} bytes, got 0x{len(base):X}"
        )
    base_hash = digest(base)
    if base_hash != TI84_PLUS_PATCHED_BASE_SHA256:
        raise RomAssemblyError(
            f"base ROM SHA-256 is {base_hash}; "
            f"expected {TI84_PLUS_PATCHED_BASE_SHA256}"
        )
    expected_names = {spec.filename for spec in RETAIL_PAGE_SPECS}
    if set(appvars) != expected_names:
        missing = sorted(expected_names - set(appvars))
        extra = sorted(set(appvars) - expected_names)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise RomAssemblyError("AppVar inputs differ: " + "; ".join(details))

    image = bytearray(base)
    patches = []
    for spec in RETAIL_PAGE_SPECS:
        artifact = decode_retail_page(appvars[spec.filename], spec)
        start = spec.page * PAGE_SIZE
        previous = image[start : start + PAGE_SIZE]
        changed = sum(left != right for left, right in zip(previous, artifact.payload))
        image[start : start + PAGE_SIZE] = artifact.payload
        patches.append(
            RomPagePatch(
                filename=spec.filename,
                variable_name=spec.variable_name,
                page=spec.page,
                appvar_sha256=spec.appvar_sha256,
                page_sha256=spec.page_sha256,
                changed_bytes=changed,
            )
        )
    output = bytes(image)
    output_hash = digest(output)
    if output_hash != TI84_PLUS_OS_255MP_SHA256:
        raise RomAssemblyError(
            f"assembled ROM SHA-256 is {output_hash}; "
            f"expected {TI84_PLUS_OS_255MP_SHA256}"
        )
    return CompleteRomAssembly(
        image=output,
        page0=output[:PAGE_SIZE],
        base_sha256=base_hash,
        output_sha256=output_hash,
        patches=tuple(patches),
    )
