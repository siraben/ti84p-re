"""Byte-verified model of the page-3C link-to-Flash staging path.

The ROM analysis and the state model live here so documentation and command-line
tools can share the same signatures, page predicates, and edge-case behavior.
The write model describes the ROM's register and pointer flow; it does not claim
that a physical Flash command succeeded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256

from ti84re.rom.image import RomImage, RomLocation


class LinkFlashStagingSignatureError(ValueError):
    """A required OS 2.55MP staging-path byte signature did not match."""


@dataclass(frozen=True)
class PageRangeProfile:
    """One model branch selected by ``3C:6B79``."""

    key: str
    mask: int
    upper_exclusive: int
    selection: str


PAGE_RANGE_PROFILES = {
    profile.key: profile
    for profile in (
        PageRangeProfile(
            "ti84-plus",
            0x3F,
            0x2A,
            "port 0x02 bit 7 set and port 0x21 bits 0-1 clear",
        ),
        PageRangeProfile(
            "legacy",
            0x1F,
            0x16,
            "port 0x02 bit 7 clear",
        ),
        PageRangeProfile(
            "expanded",
            0x7F,
            0x6A,
            "port 0x02 bit 7 set and port 0x21 bits 0-1 nonzero",
        ),
    )
}


@dataclass(frozen=True)
class PageClassification:
    """The masked page and both comparisons made before ``_WriteFlash``."""

    profile: str
    input_page: int
    normalized_page: int
    lower_inclusive: int
    upper_exclusive: int
    below_upper: bool
    eligible: bool


@dataclass(frozen=True)
class FlashStagingAbi:
    """Register and RAM-state ABI assembled by ``3C:6AB1``."""

    entry: str = "3C:6AB1"
    bcall_name: str = "_WriteFlash"
    bcall_id: int = 0x80C9
    page_register: str = "A"
    destination_register: str = "DE"
    count_register: str = "BC (B=0, C=(0x9834))"
    source_register: str = "HL=0x983A"
    destination_state: int = 0x84DB
    page_state: int = 0x83EE
    count_state: int = 0x9834
    cursor_state: int = 0x9836
    buffer: int = 0x983A


STAGING_ABI = FlashStagingAbi()


@dataclass(frozen=True)
class FlashFlushResult:
    """Modeled state after one ``3C:6AB1`` invocation."""

    profile: str
    input_page: int
    normalized_page: int
    input_destination: int
    count: int
    write_bcall_invoked: bool
    write_attempted: bool
    output_destination: int
    output_page: int
    page_incremented: bool
    reason: str


@dataclass(frozen=True)
class ReceiveStagingResult:
    """RAM-direct or Flash-buffered result for one DATA payload."""

    storage: str
    input_destination: int
    input_page: int
    length: int
    direct_ram_bytes: int
    flushes: tuple[FlashFlushResult, ...]
    output_destination: int
    output_page: int


@dataclass(frozen=True)
class SignatureRegion:
    """One exact ROM span required by the staging analysis."""

    name: str
    location: RomLocation
    expected: bytes


@dataclass(frozen=True)
class DirectReference:
    """One direct CALL or JP to the staging flush."""

    location: RomLocation
    kind: str
    condition: str
    target: RomLocation


@dataclass(frozen=True)
class DispatcherCaller:
    """One direct caller of the page-0 staging dispatcher stub."""

    location: RomLocation
    mode: int
    stub: RomLocation
    target: RomLocation


@dataclass(frozen=True)
class UsbReceiveOwner:
    """The endpoint-to-memory chain containing the dispatcher mode-3 call."""

    entry: RomLocation
    endpoint_call: RomLocation
    endpoint_stub: RomLocation
    endpoint_helper: RomLocation
    endpoint_data_read: RomLocation
    endpoint_data_port: int
    staging_buffer: int
    mode_load: RomLocation
    dispatcher_call: RomLocation


@dataclass(frozen=True)
class LinkFlashStagingAnalysis:
    """Pinned ROM signatures, ABI, and complete direct caller sets."""

    rom_sha256: str
    signatures: tuple[SignatureRegion, ...]
    abi: FlashStagingAbi
    direct_references: tuple[DirectReference, ...]
    dispatcher_callers: tuple[DispatcherCaller, ...]
    usb_receive_owner: UsbReceiveOwner

    def as_dict(self) -> dict[str, object]:
        return {
            "rom_sha256": self.rom_sha256,
            "signatures": [
                {
                    "name": region.name,
                    "location": str(region.location),
                    "length": len(region.expected),
                    "sha256": sha256(region.expected).hexdigest(),
                    "bytes": region.expected.hex(),
                }
                for region in self.signatures
            ],
            "abi": asdict(self.abi),
            "direct_references": [
                {
                    "location": str(reference.location),
                    "kind": reference.kind,
                    "condition": reference.condition,
                    "target": str(reference.target),
                }
                for reference in self.direct_references
            ],
            "dispatcher_callers": [
                {
                    "location": str(caller.location),
                    "mode": caller.mode,
                    "stub": str(caller.stub),
                    "target": str(caller.target),
                }
                for caller in self.dispatcher_callers
            ],
            "usb_receive_owner": {
                "entry": str(self.usb_receive_owner.entry),
                "endpoint_call": str(self.usb_receive_owner.endpoint_call),
                "endpoint_stub": str(self.usb_receive_owner.endpoint_stub),
                "endpoint_helper": str(self.usb_receive_owner.endpoint_helper),
                "endpoint_data_read": str(self.usb_receive_owner.endpoint_data_read),
                "endpoint_data_port": self.usb_receive_owner.endpoint_data_port,
                "staging_buffer": self.usb_receive_owner.staging_buffer,
                "mode_load": str(self.usb_receive_owner.mode_load),
                "dispatcher_call": str(self.usb_receive_owner.dispatcher_call),
            },
        }


_SIGNATURES = (
    SignatureRegion(
        "receive_data_route_and_flush",
        RomLocation(0x3C, 0x4292),
        bytes.fromhex(
            "ed4b7686110000ed53788679b0284e213a98223698af3234982adb84cdd61f"
            "c29927c5cd3f44cb7c2018e52a36987723223698e13a34983c323498fe10cc"
            "b16a18027723eb06002a788609227886ebc10b78b1c2ae423a3498b7c4b16a"
        ),
    ),
    SignatureRegion(
        "flush_paged_flash_block",
        RomLocation(0x3C, 0x6AB1),
        bytes.fromhex(
            "c5d5e53a34984faf323498213a98223698ed5bdb843aee83d532eb83ed57ea"
            "d46aed57f3f53aeb83f53e0100f30000ed56f3d314f3cdbf02f10600cd796b"
            "3007fe083803efc980cdd56632eb83f1e2036bfb3aeb83ed53db84e1b7ed52"
            "38073aee833c32ee83e1d1c1c9"
        ),
    ),
    SignatureRegion(
        "page_range_classifier",
        RomLocation(0x3C, 0x6B79),
        bytes.fromhex("cd3718200acd2f18280ae67ffe6ac9e61ffe16c9e63ffe2ac9"),
    ),
    SignatureRegion(
        "model_port_probes",
        RomLocation(0x00, 0x182F),
        bytes.fromhex("c5f5db21e6031808c5f5db02e680ee80c178c1c9"),
    ),
    SignatureRegion(
        "dispatcher_mode_3",
        RomLocation(0x3C, 0x6F4B),
        bytes.fromhex("fe00ca336efe01cafd6ffe03cab16afe04ca2970fe05caaa"),
    ),
    SignatureRegion(
        "dispatcher_bjump_stub",
        RomLocation(0x00, 0x2D45),
        bytes.fromhex("cd092b4b6f7c"),
    ),
    SignatureRegion(
        "usb_receive_to_memory",
        RomLocation(0x36, 0x40E7),
        bytes.fromhex(
            "c5f522db84cb7c2004af323498fdcb416e2038fdcb4346c2b141fdcb436e2813"
            "fdcb1296fdcb08decd85033a4984fe01cab141fdcb416e2012e5c5219141cdda"
            "27cdd26fcd0028c1e118c2fdcb12d6fdcb089ecb7c202ec5211000b7ed424130"
            "020610213a98cd172e3859cd8b7379323498c53e03cd452dc1e1b70600ed4228"
            "50444d1888"
        ),
    ),
    SignatureRegion(
        "usb_endpoint_receive_stub",
        RomLocation(0x00, 0x2E17),
        bytes.fromhex("cd092ba14f75"),
    ),
    SignatureRegion(
        "usb_endpoint_receive_entry",
        RomLocation(0x35, 0x4FA1),
        bytes.fromhex(
            "78b7c83e40b8d82001007832809c3a279cb72807b830044732809cdb8f"
        ),
    ),
    SignatureRegion(
        "usb_endpoint_a1_read_loop",
        RomLocation(0x35, 0x5008),
        bytes.fromhex("3a809c470e00dba1fdcb40562003771803cdff2d230c10ee"),
    ),
)

USB_RECEIVE_OWNER = UsbReceiveOwner(
    entry=RomLocation(0x36, 0x40E7),
    endpoint_call=RomLocation(0x36, 0x414D),
    endpoint_stub=RomLocation(0x00, 0x2E17),
    endpoint_helper=RomLocation(0x35, 0x4FA1),
    endpoint_data_read=RomLocation(0x35, 0x500E),
    endpoint_data_port=0xA1,
    staging_buffer=0x983A,
    mode_load=RomLocation(0x36, 0x415A),
    dispatcher_call=RomLocation(0x36, 0x415C),
)

_CALL_CONDITIONS = {
    0xCD: "always",
    0xC4: "NZ",
    0xCC: "Z",
    0xD4: "NC",
    0xDC: "C",
    0xE4: "PO",
    0xEC: "PE",
    0xF4: "P",
    0xFC: "M",
}
_JUMP_CONDITIONS = {
    0xC3: "always",
    0xC2: "NZ",
    0xCA: "Z",
    0xD2: "NC",
    0xDA: "C",
    0xE2: "PO",
    0xEA: "PE",
    0xF2: "P",
    0xFA: "M",
}
_EXPECTED_DIRECT_REFERENCES = (
    (0x42CF, "call", "Z"),
    (0x42EC, "call", "NZ"),
    (0x6F57, "jump", "Z"),
)
_EXPECTED_DISPATCHER_CALLERS = (
    (0x415C, 0x03),
    (0x50FD, 0x0D),
    (0x513C, 0x15),
    (0x5169, 0x00),
    (0x5B35, 0x01),
    (0x5E17, 0x14),
)


def _byte(value: int, name: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be between 0x00 and 0xFF")
    return value


def _word(value: int, name: str) -> int:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"{name} must be between 0x0000 and 0xFFFF")
    return value


def classify_page(page: int, profile: str = "ti84-plus") -> PageClassification:
    """Apply ``3C:6B79`` and the subsequent lower-bound comparison."""

    page = _byte(page, "page")
    try:
        selected = PAGE_RANGE_PROFILES[profile]
    except KeyError:
        raise ValueError(f"unknown page-range profile {profile!r}") from None
    normalized = page & selected.mask
    below_upper = normalized < selected.upper_exclusive
    return PageClassification(
        profile=profile,
        input_page=page,
        normalized_page=normalized,
        lower_inclusive=0x08,
        upper_exclusive=selected.upper_exclusive,
        below_upper=below_upper,
        eligible=below_upper and normalized >= 0x08,
    )


def _advance_worker_destination(destination: int, count: int) -> int:
    """Model the copied worker's pre-byte ``DE > 0x7FFF`` check."""

    current = destination
    for _ in range(count):
        if current > 0x7FFF:
            current = 0x4000
        current = (current + 1) & 0xFFFF
    return current


def flush_paged_flash_block(
    page: int,
    destination: int,
    count: int,
    profile: str = "ti84-plus",
) -> FlashFlushResult:
    """Model one call to ``3C:6AB1`` through a successful worker path.

    ``write_attempted`` means the ROM reaches a nonzero ``_WriteFlash`` call.
    It deliberately does not mean that an emulator or physical chip accepted
    every command.
    """

    page = _byte(page, "page")
    destination = _word(destination, "destination")
    count = _byte(count, "count")
    classification = classify_page(page, profile)
    bcall_invoked = classification.eligible
    write_attempted = bcall_invoked and count != 0
    output_destination = (
        _advance_worker_destination(destination, count)
        if write_attempted
        else destination
    )
    page_incremented = destination >= output_destination
    output_page = (page + int(page_incremented)) & 0xFF
    if not classification.eligible:
        reason = "page-outside-program-range"
    elif count == 0:
        reason = "zero-count"
    elif page_incremented:
        reason = "destination-wrap"
    else:
        reason = "write-path"
    return FlashFlushResult(
        profile=profile,
        input_page=page,
        normalized_page=classification.normalized_page,
        input_destination=destination,
        count=count,
        write_bcall_invoked=bcall_invoked,
        write_attempted=write_attempted,
        output_destination=output_destination,
        output_page=output_page,
        page_incremented=page_incremented,
        reason=reason,
    )


def receive_data_staging(
    destination: int,
    length: int,
    *,
    page: int = 0x08,
    profile: str = "ti84-plus",
) -> ReceiveStagingResult:
    """Model the destination split and 16-byte batching at ``3C:4292``."""

    destination = _word(destination, "destination")
    page = _byte(page, "page")
    if not 0 <= length <= 0xFFFF:
        raise ValueError("length must be between 0x0000 and 0xFFFF")
    if destination & 0x8000:
        return ReceiveStagingResult(
            storage="ram-direct",
            input_destination=destination,
            input_page=page,
            length=length,
            direct_ram_bytes=length,
            flushes=(),
            output_destination=(destination + length) & 0xFFFF,
            output_page=page,
        )

    counts = [0x10] * (length // 0x10)
    if length & 0x0F:
        counts.append(length & 0x0F)
    current_destination = destination
    current_page = page
    flushes = []
    for count in counts:
        flush = flush_paged_flash_block(
            current_page,
            current_destination,
            count,
            profile,
        )
        flushes.append(flush)
        current_destination = flush.output_destination
        current_page = flush.output_page
    return ReceiveStagingResult(
        storage="flash-buffered",
        input_destination=destination,
        input_page=page,
        length=length,
        direct_ram_bytes=0,
        flushes=tuple(flushes),
        output_destination=current_destination,
        output_page=current_page,
    )


def _validate_signatures(rom: RomImage) -> None:
    if rom.page_count <= 0x3C:
        raise LinkFlashStagingSignatureError(
            f"ROM has {rom.page_count} page(s); physical page 0x3C is required"
        )
    for region in _SIGNATURES:
        actual = rom.bytes_at(
            region.location.page,
            region.location.address,
            len(region.expected),
        )
        if actual != region.expected:
            raise LinkFlashStagingSignatureError(
                f"{region.name} signature mismatch at {region.location}: "
                f"expected {region.expected.hex()}, got {actual.hex()}"
            )


def _direct_flush_references(rom: RomImage) -> tuple[DirectReference, ...]:
    page = rom.page(0x3C)
    target = 0x6AB1
    found = []
    for offset in range(len(page) - 2):
        opcode = page[offset]
        kind = None
        condition = None
        if opcode in _CALL_CONDITIONS:
            kind = "call"
            condition = _CALL_CONDITIONS[opcode]
        elif opcode in _JUMP_CONDITIONS:
            kind = "jump"
            condition = _JUMP_CONDITIONS[opcode]
        if kind is None or int.from_bytes(page[offset + 1 : offset + 3], "little") != target:
            continue
        found.append(
            DirectReference(
                RomLocation(0x3C, 0x4000 + offset),
                kind,
                condition,
                RomLocation(0x3C, target),
            )
        )
    observed = tuple(
        (reference.location.address, reference.kind, reference.condition)
        for reference in found
    )
    if observed != _EXPECTED_DIRECT_REFERENCES:
        raise LinkFlashStagingSignatureError(
            "direct 3C:6AB1 reference set mismatch: "
            f"expected {_EXPECTED_DIRECT_REFERENCES!r}, got {observed!r}"
        )
    return tuple(found)


def _dispatcher_callers(rom: RomImage) -> tuple[DispatcherCaller, ...]:
    stub = 0x2D45
    found = []
    for page_number in range(rom.page_count):
        page = rom.page(page_number)
        origin = 0 if page_number == 0 else 0x4000
        for offset in range(2, len(page) - 2):
            if page[offset : offset + 3] != bytes((0xCD, stub & 0xFF, stub >> 8)):
                continue
            if page[offset - 2] != 0x3E:
                raise LinkFlashStagingSignatureError(
                    "dispatcher caller does not have an adjacent LD A,n at "
                    f"{page_number:02X}:{origin + offset:04X}"
                )
            found.append(
                DispatcherCaller(
                    RomLocation(page_number, origin + offset),
                    page[offset - 1],
                    RomLocation(0x00, stub),
                    RomLocation(0x3C, 0x6F4B),
                )
            )
    observed = tuple(
        (caller.location.address, caller.mode) for caller in found
    )
    if observed != _EXPECTED_DISPATCHER_CALLERS or any(
        caller.location.page != 0x36 for caller in found
    ):
        raise LinkFlashStagingSignatureError(
            "dispatcher caller set mismatch: "
            f"expected page 0x36 {_EXPECTED_DISPATCHER_CALLERS!r}, "
            f"got {tuple((str(c.location), c.mode) for c in found)!r}"
        )
    return tuple(found)


def analyze_link_flash_staging(rom: RomImage) -> LinkFlashStagingAnalysis:
    """Validate and report the complete pinned staging path and caller sets."""

    _validate_signatures(rom)
    return LinkFlashStagingAnalysis(
        rom_sha256=sha256(rom.data).hexdigest(),
        signatures=_SIGNATURES,
        abi=STAGING_ABI,
        direct_references=_direct_flush_references(rom),
        dispatcher_callers=_dispatcher_callers(rom),
        usb_receive_owner=USB_RECEIVE_OWNER,
    )
