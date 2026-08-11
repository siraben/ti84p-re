"""Inspect the page-3D certificate-tail rebuild machinery in OS 2.55MP.

The analysis is deliberately structural.  It validates byte signatures before
reporting fixed helper paths, certificate-relative spans, and direct mode-call
sites.  Semantic labels from external certificate documentation are not used
to derive the report.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from rom_image import RomImage, RomLocation


PAGE = 0x3D
DISPATCHER = RomLocation(PAGE, 0x40F1)
TAIL_START = 0x1DEA
TAIL_LENGTH = 0x0216


class CertificateRebuildSignatureError(ValueError):
    """A required OS 2.55MP byte signature did not match the ROM."""


@dataclass(frozen=True)
class CertificateSpan:
    """One half-relative certificate span."""

    offset: int
    length: int

    @property
    def end(self) -> int:
        return self.offset + self.length


@dataclass(frozen=True)
class ModeCall:
    """One immediate mode load followed by a direct dispatcher call."""

    mode: int
    load: RomLocation
    call: RomLocation


@dataclass(frozen=True)
class BjumpModeCall:
    """One immediate mode load followed by a page-0 bjump to the dispatcher."""

    mode: int
    load: RomLocation
    call: RomLocation
    stub: RomLocation


@dataclass(frozen=True)
class RebuildMode:
    """A byte-verified dispatcher branch and its rewritten span(s)."""

    mode: int
    branch: RomLocation
    helper_calls: tuple[RomLocation, ...]
    rewritten_spans: tuple[CertificateSpan, ...]


@dataclass(frozen=True)
class ModeOwner:
    """A ROM path that gives a rebuild mode a semantic owner."""

    mode: int
    role: str
    owner_entry: RomLocation
    dispatcher_call: RomLocation
    call_chain: tuple[RomLocation, ...]


@dataclass(frozen=True)
class AppValidityUpdate:
    """ROM-derived shape of the per-App certificate bitmap update."""

    locator: RomLocation
    set_routine: RomLocation
    clear_routine: RomLocation
    preceding_offset: int
    bitmap_offset: int
    bit_order: str
    set_rebuild_mode: int
    clear_bcall_id: int


@dataclass(frozen=True)
class OsValidityFlag:
    """Boot-page API and storage for the certificate OS-validity bit."""

    offset: int
    mask: int
    valid_when_clear: bool
    mark_invalid_bcall_id: int
    mark_invalid_entry: RomLocation
    mark_valid_bcall_id: int
    mark_valid_entry: RomLocation
    check_bcall_id: int
    check_entry: RomLocation
    write_byte_bcall_id: int
    invalid_rebuild_span: CertificateSpan


@dataclass(frozen=True)
class AppTrialTable:
    """Per-App two-byte trial records and their ROM owners."""

    model_offsets: tuple[int, ...]
    length: int
    entry_length: int
    erased_byte: int
    clear_routine: RomLocation
    write_routine: RomLocation
    query_routine: RomLocation
    display_entry: RomLocation
    display_label: str
    display_label_location: RomLocation
    delete_callers: tuple[RomLocation, ...]
    clear_rebuild_mode: int


@dataclass(frozen=True)
class CertificateTailAccessor:
    """One byte-verified certificate-relative address helper."""

    entry: RomLocation
    role: str
    fixed_offset: int | None
    direct_callers: tuple[RomLocation, ...]


@dataclass(frozen=True)
class ModelSelectedCertificateOffset:
    """Port test that chooses between two certificate-relative offsets."""

    accessor: RomLocation
    probe: RomLocation
    port: int
    mask: int
    set_bit_offset: int
    clear_bit_offset: int
    ti84_plus_observed_port_values: tuple[int, ...]
    ti84_plus_selected_offset: int


@dataclass(frozen=True)
class RestrictionTypeBehavior:
    """Storage and API behavior for one App-restriction type value."""

    value: int
    role: str
    set_behavior: str
    query_behavior: str
    remove_behavior: str


@dataclass(frozen=True)
class AppRestrictionApi:
    """Public bcall entries and storage used by App restrictions."""

    set_bcall_id: int
    set_entry: RomLocation
    remove_bcall_id: int
    remove_entry: RomLocation
    query_bcall_id: int
    query_entry: RomLocation
    control_span: CertificateSpan
    control_offset: int
    record_offset: int
    record_length: int
    app_bitmap_offset: int
    app_bitmap_length: int
    app_page_bias: int
    bitmap_bit_order: str
    base_mask: int
    logbase_mask: int
    summation_mask: int
    remove_rebuild_mode: int
    set_supported_types: tuple[int, ...]
    remove_supported_types: tuple[int, ...]
    types: tuple[RestrictionTypeBehavior, ...]


@dataclass(frozen=True)
class CertificateRebuildAnalysis:
    """Validated structural report for the certificate rebuild dispatcher."""

    rom_sha256: str
    dispatcher: RomLocation
    tail_blocks: tuple[CertificateSpan, ...]
    modes: tuple[RebuildMode, ...]
    direct_calls: tuple[ModeCall, ...]
    bjump_calls: tuple[BjumpModeCall, ...]
    mode_owners: tuple[ModeOwner, ...]
    os_validity: OsValidityFlag
    app_trials: AppTrialTable
    app_validity: AppValidityUpdate
    app_restrictions: AppRestrictionApi
    tail_accessors: tuple[CertificateTailAccessor, ...]
    model_selected_offset: ModelSelectedCertificateOffset


TAIL_BLOCKS = (
    CertificateSpan(0x1DEA, 0x0066),
    CertificateSpan(0x1E50, 0x00C8),
    CertificateSpan(0x1F18, 0x00C8),
    CertificateSpan(0x1FE0, 0x0020),
)


_MODE_PATHS = (
    (
        RebuildMode(
            0,
            RomLocation(PAGE, 0x423F),
            (RomLocation(PAGE, 0x42EA),),
            (CertificateSpan(0x1F18, 0x00E8),),
        ),
        bytes.fromhex("CDEA42"),
    ),
    (
        RebuildMode(
            1,
            RomLocation(PAGE, 0x41ED),
            tuple(
                RomLocation(PAGE, address)
                for address in (0x42C1, 0x4271, 0x42E7, 0x4290)
            ),
            (CertificateSpan(0x1E50, 0x00C8),),
        ),
        bytes.fromhex("CDC142CD7142CDE742CD90421847"),
    ),
    (
        RebuildMode(
            2,
            RomLocation(PAGE, 0x41DF),
            tuple(
                RomLocation(PAGE, address)
                for address in (0x42EA, 0x4271, 0x42BE, 0x4288)
            ),
            (CertificateSpan(0x1F18, 0x00E8),),
        ),
        bytes.fromhex("CDEA42CD7142CDBE42CD88421855"),
    ),
    (
        RebuildMode(
            3,
            RomLocation(PAGE, 0x41FB),
            tuple(
                RomLocation(PAGE, address)
                for address in (0x4274, 0x42BE, 0x42E7, 0x4298)
            ),
            (CertificateSpan(0x1DEA, 0x0066),),
        ),
        bytes.fromhex("CD7442CDBE42CDE742CD98421839"),
    ),
    (
        RebuildMode(
            4,
            RomLocation(PAGE, 0x4209),
            tuple(
                RomLocation(PAGE, address)
                for address in (0x4274, 0x430E, 0x42C9, 0x42D4, 0x42FA, 0x4298)
            ),
            (
                CertificateSpan(0x1DEA, 0x0066),
                CertificateSpan(0x1FE0, 0x0020),
            ),
        ),
        bytes.fromhex("CD7442CD0E43CDC942CDD442CDFA42CD98421825"),
    ),
    (
        RebuildMode(
            5,
            RomLocation(PAGE, 0x421D),
            tuple(
                RomLocation(PAGE, address)
                for address in (0x430E, 0x42BE, 0x42FA, 0x4271)
            ),
            (CertificateSpan(0x1FE0, 0x0020),),
        ),
        bytes.fromhex("CD0E43CDBE42CDFA42CD71421817"),
    ),
    (
        RebuildMode(
            6,
            RomLocation(PAGE, 0x422B),
            (RomLocation(PAGE, 0x48E3), RomLocation(PAGE, 0x4281)),
            (CertificateSpan(TAIL_START, TAIL_LENGTH),),
        ),
        bytes.fromhex("E1E511EA1D19E5D1CDE348EB011602CD81421803"),
    ),
)


_FIXED_SIGNATURES = (
    (
        RomLocation(0x3B, 0x52F6),
        bytes.fromhex("9B7B7D1B7C7DBA7C7D"),
    ),
    (DISPATCHER, bytes.fromhex("32209CD5C5E5CDE048CDBC45")),
    (
        RomLocation(PAGE, 0x41C5),
        bytes.fromhex(
            "3A209CB72874FE01281EFE032828FE042832FE052842FE06284C"
        ),
    ),
    (
        RomLocation(PAGE, 0x51BE),
        bytes.fromhex(
            "F5C5E5CDF651CD5D784FCDBC45F5B147F1A1200ACDA6513E05CDF140"
        ),
    ),
    (
        RomLocation(PAGE, 0x51E4),
        bytes.fromhex("F5C5E5CDF651CD5D782F4FCDBC45A14718E6"),
    ),
    (
        RomLocation(PAGE, 0x51F6),
        bytes.fromhex("D5F547EFA880200ACD6E72903C4F0600"),
    ),
    (
        RomLocation(PAGE, 0x5227),
        bytes.fromhex(
            "C501D31D180AC501E01F1804C501181FDDE5EF578009DDE1C1C9"
            "C501EA1D18F0CD371820E7C501501E18E5C501E01F18DF"
        ),
    ),
    (
        RomLocation(0x00, 0x1837),
        bytes.fromhex("C5F5DB02E680EE80C178C1C9"),
    ),
    (
        RomLocation(PAGE, 0x7D5C),
        bytes.fromhex("D6084FCD767D79CD697D"),
    ),
    (
        RomLocation(PAGE, 0x7D6B),
        bytes.fromhex("CB29CB29CB2909E6074F"),
    ),
    (
        RomLocation(PAGE, 0x7CB3),
        bytes.fromhex("CD8B73EF2180C9"),
    ),
    (
        RomLocation(PAGE, 0x7B9B),
        bytes.fromhex("FE062809FE072805FE05D01802FE08F5"),
    ),
    (
        RomLocation(PAGE, 0x7C1B),
        bytes.fromhex("B7C8FE062003B71804FE04D03FC3AA7B"),
    ),
    (
        RomLocation(PAGE, 0x7CBA),
        bytes.fromhex("E5C5BFC3AA7B"),
    ),
    (
        RomLocation(PAGE, 0x7D82),
        bytes.fromhex("F5C5E53E06CDF140CD767D2BEB217984010E00CD8142"),
    ),
    (
        RomLocation(PAGE, 0x7DCE),
        bytes.fromhex("CD767D2B117984010E00CDAC42"),
    ),
    (
        RomLocation(PAGE, 0x7C8F),
        bytes.fromhex("0EFD18060EFB18020EFEC5CDD945C1A1"),
    ),
    (
        RomLocation(PAGE, 0x7CC0),
        bytes.fromhex(
            "FE0138772846FE05286AFE062815FE07280CFE03282C3023"
            "01010118097801040818030102043A7884C5F5CDC47D"
        ),
    ),
    (
        RomLocation(PAGE, 0x7D5A),
        bytes.fromhex("D5F5D6084FCD767D79CD697DF1D1C9"),
    ),
    (
        RomLocation(PAGE, 0x7DB2),
        bytes.fromhex("C5E5CD5A7DCD5D784FCDBC45A1E1C1C9"),
    ),
    (
        RomLocation(PAGE, 0x7E35),
        bytes.fromhex("F5E5D50E00C5CD6E72210040F5CD3267FE802804FE00201D"),
    ),
    (
        RomLocation(0x07, 0x5758),
        bytes.fromhex("3E03CD91383E38C29327"),
    ),
    (
        RomLocation(0x37, 0x4E43),
        bytes.fromhex("3E21CDA1493E06CD6A4E3E29CDAD493E07CD6A4E"),
    ),
    (
        RomLocation(0x37, 0x4A42),
        b"DISABLE\x06logBASE:\x06\x00",
    ),
    (
        RomLocation(0x37, 0x4A54),
        b"DISABLE\x06\xC6(\x3A\x06\x00",
    ),
    (
        RomLocation(0x01, 0x419C),
        b"#Expired on:\x00\x00*Trials Remaining:\x00",
    ),
    (
        RomLocation(0x36, 0x70B3),
        bytes.fromhex(
            "F1F5CDB12D202421A9413E53FDCB354EC41F3ECDF33C"
            "3A7884217884CDAD3D3A7884CDDB3C3A7984CDDB3C"
        ),
    ),
    (
        RomLocation(0x35, 0x71F0),
        bytes.fromhex("CD070DCCC12FCDA53C210000224B84210941CD853ECDC32D"),
    ),
    (
        RomLocation(0x00, 0x2BFB),
        bytes.fromhex("CD092B71477D"),
    ),
    (
        RomLocation(0x00, 0x2B77),
        bytes.fromhex("CD092BF1407D"),
    ),
    (
        RomLocation(0x3C, 0x565D),
        bytes.fromhex("FE25C22E57CD002821C758CDDA273E10CD252F11100A"),
    ),
    (
        RomLocation(0x3C, 0x550D),
        bytes.fromhex("3A7F861800FE24C25D56CD002821AF58CDDA27"),
    ),
    (
        RomLocation(0x3C, 0x55B8),
        bytes.fromhex("3E0FCD252FCD812DB720173A7486FE23C0"),
    ),
    (
        RomLocation(0x3C, 0x7219),
        bytes.fromhex(
            "F300000000F53E0100F30000ED56F3D314F3CDBF02F1CD6E72"
            "3812CDD47ECDEA7DCDA572CD4A72"
        ),
    ),
    (
        RomLocation(0x3C, 0x72A5),
        bytes.fromhex("CD7F2CCD6B7E21A582060ACD371820052100800680"),
    ),
    (
        RomLocation(0x3C, 0x730E),
        bytes.fromhex("CD2D733E04CD772BC9"),
    ),
    (
        RomLocation(0x3C, 0x724A),
        bytes.fromhex(
            "CD2A7BCDE774B72817F578FE022808F1F5CD4475CD2A7BF1CD0176"
        ),
    ),
    (
        RomLocation(0x3C, 0x7544),
        bytes.fromhex(
            "F5CD5C75F5EF8480F1F5CD6875C1F1CD76753E03CD772BC9"
        ),
    ),
    (
        RomLocation(0x00, 0x2D81),
        bytes.fromhex("CD092BBE737D"),
    ),
    (
        RomLocation(0x3C, 0x56F4),
        bytes.fromhex(
            "E17CFE03C2BD577DE6F0FE002809FE20200ACDEF2B1816"
            "CDF52B1811FE102005CDFB2B1808FE30C2A057"
        ),
    ),
    (
        RomLocation(PAGE, 0x4771),
        bytes.fromhex("C5D5E5CDBC7223EF5A80CDF744C2F547CD2B472019"),
    ),
    (
        RomLocation(PAGE, 0x4000),
        bytes.fromhex(
            "F53E0100F30000ED56F3D314F3CDBF02F1CDC56BDAE65C"
            "F5CD5957F1CD3F40C3E65C"
        ),
    ),
    (
        RomLocation(PAGE, 0x5759),
        bytes.fromhex(
            "F53E01CD064847CD6E729006004F21A582CB21093EFF7723"
            "773E01CDF140F1C9"
        ),
    ),
    (
        RomLocation(PAGE, 0x5466),
        bytes.fromhex(
            "F53E0100F30000ED56F3D314F3CDBF02F147116080210040"
            "B7EF75802042CD6E7248910100004FCB21CD4752B7ED4A3E7E"
            "117884010200EF54803A7884010000FE002805CB3F0C18F7"
            "3A7984FE002805CB3F0C18F7793278843E00327984CB7FC3E65C"
        ),
    ),
    (
        RomLocation(PAGE, 0x5BB7),
        bytes.fromhex(
            "F5F53E01B7210080116080EF75802815210080115080EF7580"
            "2805118000182D1100001828233E01EF5A803E01EF5180F50609"
            "903810F1060890CDBC4E573E08CDBC4E5F18071600F1CDBC4E5F"
            "F147CD6E72900100004FCD4752CB210943EBE5CDB37CE1EB42"
            "EBCDB37CF1C9"
        ),
    ),
    (
        RomLocation(PAGE, 0x70E1),
        bytes.fromhex("CDBE51CDB75B210080CD4357"),
    ),
    (
        RomLocation(PAGE, 0x47A2),
        bytes.fromhex(
            "CD4551116D83CD2D52012000CDF148CD3352010D00CB21"
            "11A582CDF148CDB272ED438D83118E83CDF148CDEE46"
        ),
    ),
    (
        RomLocation(PAGE, 0x4704),
        bytes.fromhex(
            "110040CD4B43E1E5EF6080D1C1210040C5CD1A43CDE048"
            "C1EB7AEE2057CD7A43C8"
        ),
    ),
    (
        RomLocation(PAGE, 0x73BE),
        bytes.fromhex(
            "F53E0100F30000ED56F3D314F3CDBF02F13A348400CD5F44"
            "20403A3484210040CD845BCDEF52DAE9732029"
        ),
    ),
    (
        RomLocation(PAGE, 0x73E9),
        bytes.fromhex(
            "3A3484210040CD5F5BCDE4513A3484210040CD845BCD5653"
        ),
    ),
    (
        RomLocation(PAGE, 0x5356),
        bytes.fromhex(
            "F5CD215D38F7210040112003F1F5B7EF758020E9F1F5E523"
            "EF5A80CDE8502007E1F1F5E5CD1950E1F1C9"
        ),
    ),
    (
        RomLocation(PAGE, 0x5019),
        bytes.fromhex(
            "F5D5E5C5F5E5F523EF5A80B7ED4AF123EF5A80B7ED4AD1"
            "B7ED52E5C1EBF111A582C5EF5480C13E7ECDE048E5E5EF6080"
        ),
    ),
    (
        RomLocation(PAGE, 0x5049),
        bytes.fromhex(
            "E1EB21A5823E7EEF8780112003EF27802003EF2A80E1373E7E"
            "F5F5E5E5F523EF5A80B7ED4AF123EF5A80B7ED4AD1B7ED52"
            "E5C1E1F1C5E5CD335201E8003E7E11A582EF5480D1C17AEE20"
            "57CD7A43C22547"
        ),
    ),
    (
        RomLocation(PAGE, 0x6673),
        bytes.fromhex("CD273FF53E0100F30000ED56F3D314F3CDBF02F1"),
    ),
    (
        RomLocation(PAGE, 0x66A9),
        bytes.fromhex(
            "21A58206E83EFF772310FA3EFE216D8377CD37182806"
            "3E7F216E83773E00CDF140"
        ),
    ),
    (
        RomLocation(0x3F, 0x51F5),
        bytes.fromhex("E5D5C5CDB954CD6C48CB8747EBCD964CC1D1E1C9"),
    ),
    (
        RomLocation(0x3F, 0x5209),
        bytes.fromhex(
            "E5D5C5CDB954CD6C48CB47C2C252F5C5D5E5CD464D"
            "11181F1911A58201E800CD8648"
        ),
    ),
    (
        RomLocation(0x3F, 0x522F),
        bytes.fromhex("216D83CBC6"),
    ),
    (
        RomLocation(0x3F, 0x52C6),
        bytes.fromhex("E5CDB954CD6C48CB47E1C9"),
    ),
    (
        RomLocation(0x3F, 0x54B9),
        bytes.fromhex("C5DDE5CD464D01002009012000ED42DDE1C1C9"),
    ),
)


def _validate_bytes(rom: RomImage, location: RomLocation, expected: bytes) -> None:
    actual = rom.bytes_at(location.page, location.address, len(expected))
    if actual != expected:
        raise CertificateRebuildSignatureError(
            f"signature mismatch at {location}: expected {expected.hex()}, "
            f"got {actual.hex()}"
        )


def find_direct_mode_calls(rom: RomImage) -> tuple[ModeCall, ...]:
    """Find raw ``LD A,mode; CALL 40F1h`` candidates on physical page 3D."""

    page = rom.page(PAGE)
    origin = 0x4000
    prefix = bytes.fromhex("3E")
    suffix = bytes.fromhex("CDF140")
    calls = []
    for offset in range(len(page) - 5):
        if page[offset : offset + 1] != prefix:
            continue
        if page[offset + 2 : offset + 5] != suffix:
            continue
        calls.append(
            ModeCall(
                mode=page[offset + 1],
                load=RomLocation(PAGE, origin + offset),
                call=RomLocation(PAGE, origin + offset + 2),
            )
        )
    return tuple(calls)


def find_page_direct_callers(
    rom: RomImage, page_number: int, target: int
) -> tuple[RomLocation, ...]:
    """Find raw page-local ``CALL target`` byte sequences.

    This intentionally does not depend on a disassembler.  Callers should
    validate the complete result against a pinned ROM before treating every
    byte match as an instruction.
    """

    if not 0 <= target <= 0xFFFF:
        raise ValueError(f"call target must be 0x0000-0xFFFF, got 0x{target:X}")
    page = rom.page(page_number)
    origin = 0 if page_number == 0 else 0x4000
    call = bytes((0xCD, target & 0xFF, target >> 8))
    return tuple(
        RomLocation(page_number, origin + offset)
        for offset in range(len(page) - len(call) + 1)
        if page[offset : offset + len(call)] == call
    )


def find_bjump_mode_calls(rom: RomImage) -> tuple[BjumpModeCall, ...]:
    """Find immediate mode loads that call a page-0 dispatcher bjump stub."""

    descriptor = bytes(
        (
            0xCD,
            0x09,
            0x2B,
            DISPATCHER.address & 0xFF,
            DISPATCHER.address >> 8,
            DISPATCHER.page | 0x40,
        )
    )
    page_zero = rom.page(0)
    stub_offsets = tuple(
        offset
        for offset in range(len(page_zero) - len(descriptor) + 1)
        if page_zero[offset : offset + len(descriptor)] == descriptor
    )
    if len(stub_offsets) != 1:
        raise CertificateRebuildSignatureError(
            "dispatcher bjump descriptor mismatch: expected one descriptor, got "
            f"{len(stub_offsets)}"
        )
    stub = RomLocation(0, stub_offsets[0])
    call_bytes = bytes((0xCD, stub.address & 0xFF, stub.address >> 8))
    calls = []
    for page_number in range(rom.page_count):
        page = rom.page(page_number)
        origin = 0 if page_number == 0 else 0x4000
        for offset in range(2, len(page) - 2):
            if page[offset : offset + 3] != call_bytes:
                continue
            if page[offset - 2] != 0x3E:
                continue
            calls.append(
                BjumpModeCall(
                    mode=page[offset - 1],
                    load=RomLocation(page_number, origin + offset - 2),
                    call=RomLocation(page_number, origin + offset),
                    stub=stub,
                )
            )
    return tuple(calls)


def analyze_certificate_rebuild(rom: RomImage) -> CertificateRebuildAnalysis:
    """Validate and report the OS 2.55MP certificate rebuild structure."""

    if rom.page_count <= PAGE:
        raise CertificateRebuildSignatureError(
            f"ROM has {rom.page_count} page(s); physical page 0x{PAGE:02X} is required"
        )
    for location, expected in _FIXED_SIGNATURES:
        _validate_bytes(rom, location, expected)
    for mode, expected in _MODE_PATHS:
        _validate_bytes(rom, mode.branch, expected)

    calls = find_direct_mode_calls(rom)
    expected_calls = (
        (2, 0x437C, 0x437E),
        (5, 0x51D5, 0x51D7),
        (1, 0x5772, 0x5774),
        (0, 0x66C5, 0x66C7),
        (6, 0x7D85, 0x7D87),
    )
    actual_calls = tuple(
        (call.mode, call.load.address, call.call.address) for call in calls
    )
    if actual_calls != expected_calls:
        raise CertificateRebuildSignatureError(
            "direct mode-call set mismatch: expected "
            f"{expected_calls!r}, got {actual_calls!r}"
        )

    bjump_calls = find_bjump_mode_calls(rom)
    expected_bjump_calls = (
        (4, 0x3C, 0x7311, 0x7313, 0x2B77),
        (3, 0x3C, 0x7556, 0x7558, 0x2B77),
    )
    actual_bjump_calls = tuple(
        (
            call.mode,
            call.call.page,
            call.load.address,
            call.call.address,
            call.stub.address,
        )
        for call in bjump_calls
    )
    if actual_bjump_calls != expected_bjump_calls:
        raise CertificateRebuildSignatureError(
            "bjump mode-call set mismatch: expected "
            f"{expected_bjump_calls!r}, got {actual_bjump_calls!r}"
        )

    accessor_specs = (
        (0x5227, "App-restriction record", 0x1DD3, (0x42D4, 0x7D7A)),
        (
            0x522D,
            "OS/App-validity metadata",
            0x1FE0,
            (0x42B3, 0x4589, 0x4654, 0x47A8, 0x521D, 0x5448),
        ),
        (
            0x5233,
            "fixed 0x1F18 span",
            0x1F18,
            (
                0x414B,
                0x4288,
                0x42EA,
                0x42F2,
                0x42FD,
                0x4306,
                0x47B1,
                0x493D,
                0x4CBD,
                0x4F14,
                0x5080,
                0x5184,
                0x51A8,
                0x538F,
            ),
        ),
        (
            0x5241,
            "garbage-collection metadata",
            0x1DEA,
            (0x4274, 0x4298, 0x42A3),
        ),
        (
            0x5247,
            "model-selected App-trial table",
            None,
            (0x490F, 0x5385, 0x548F, 0x5C0E),
        ),
        (0x5252, "OS/App-validity metadata", 0x1FE0, (0x430E,)),
    )
    tail_accessors = []
    for entry, role, fixed_offset, expected_addresses in accessor_specs:
        direct_callers = find_page_direct_callers(rom, PAGE, entry)
        actual_addresses = tuple(caller.address for caller in direct_callers)
        if actual_addresses != expected_addresses:
            raise CertificateRebuildSignatureError(
                f"direct caller set mismatch for 3D:{entry:04X}: expected "
                f"{expected_addresses!r}, got {actual_addresses!r}"
            )
        tail_accessors.append(
            CertificateTailAccessor(
                entry=RomLocation(PAGE, entry),
                role=role,
                fixed_offset=fixed_offset,
                direct_callers=direct_callers,
            )
        )

    return CertificateRebuildAnalysis(
        rom_sha256=sha256(rom.data).hexdigest(),
        dispatcher=DISPATCHER,
        tail_blocks=TAIL_BLOCKS,
        modes=tuple(mode for mode, _signature in _MODE_PATHS),
        direct_calls=tuple(sorted(calls, key=lambda call: call.mode)),
        bjump_calls=tuple(sorted(bjump_calls, key=lambda call: call.mode)),
        mode_owners=(
            ModeOwner(
                mode=0,
                role="initialize the OS/App-validity tail during full reset",
                owner_entry=RomLocation(PAGE, 0x6673),
                dispatcher_call=RomLocation(PAGE, 0x66C7),
                call_chain=(
                    RomLocation(0x35, 0x7205),
                    RomLocation(0x00, 0x2DC3),
                    RomLocation(PAGE, 0x6673),
                    RomLocation(PAGE, 0x66C7),
                ),
            ),
            ModeOwner(
                mode=1,
                role="clear a two-byte per-App trial record during App deletion",
                owner_entry=RomLocation(PAGE, 0x4000),
                dispatcher_call=RomLocation(PAGE, 0x5774),
                call_chain=(
                    RomLocation(PAGE, 0x4000),
                    RomLocation(PAGE, 0x4018),
                    RomLocation(PAGE, 0x5759),
                    RomLocation(PAGE, 0x5774),
                ),
            ),
            ModeOwner(
                mode=2,
                role=(
                    "rebuild the validity tail for selector 0x10 in the "
                    "certificate receive path"
                ),
                owner_entry=RomLocation(0x3C, 0x565D),
                dispatcher_call=RomLocation(PAGE, 0x437E),
                call_chain=(
                    RomLocation(0x3C, 0x565D),
                    RomLocation(0x3C, 0x5714),
                    RomLocation(0x00, 0x2BFB),
                    RomLocation(PAGE, 0x4771),
                    RomLocation(PAGE, 0x47CC),
                    RomLocation(PAGE, 0x46EE),
                    RomLocation(PAGE, 0x4721),
                    RomLocation(PAGE, 0x437E),
                ),
            ),
            ModeOwner(
                mode=2,
                role=(
                    "rebuild the validity tail while preparing a Flash App "
                    "destination page"
                ),
                owner_entry=RomLocation(0x3C, 0x550D),
                dispatcher_call=RomLocation(PAGE, 0x437E),
                call_chain=(
                    RomLocation(0x3C, 0x550D),
                    RomLocation(0x3C, 0x55BD),
                    RomLocation(0x00, 0x2D81),
                    RomLocation(PAGE, 0x73BE),
                    RomLocation(PAGE, 0x73FE),
                    RomLocation(PAGE, 0x5356),
                    RomLocation(PAGE, 0x537A),
                    RomLocation(PAGE, 0x5019),
                    RomLocation(PAGE, 0x5094),
                    RomLocation(PAGE, 0x437E),
                ),
            ),
            ModeOwner(
                mode=3,
                role=(
                    "rewrite garbage-collection recovery metadata after a "
                    "recovery-loop archive-sector operation"
                ),
                owner_entry=RomLocation(0x3C, 0x7219),
                dispatcher_call=RomLocation(0x3C, 0x7558),
                call_chain=(
                    RomLocation(0x3C, 0x7219),
                    RomLocation(0x3C, 0x724A),
                    RomLocation(0x3C, 0x7544),
                    RomLocation(0x3C, 0x7558),
                    RomLocation(0x00, 0x2B77),
                    RomLocation(PAGE, 0x40F1),
                ),
            ),
            ModeOwner(
                mode=4,
                role=(
                    "initialize certificate-backed garbage-collection recovery "
                    "metadata before the recovery loop"
                ),
                owner_entry=RomLocation(0x3C, 0x7219),
                dispatcher_call=RomLocation(0x3C, 0x7313),
                call_chain=(
                    RomLocation(0x3C, 0x7219),
                    RomLocation(0x3C, 0x72A5),
                    RomLocation(0x3C, 0x7313),
                    RomLocation(0x00, 0x2B77),
                    RomLocation(PAGE, 0x40F1),
                ),
            ),
            ModeOwner(
                mode=6,
                role="rebuild the App-restriction control span during removal",
                owner_entry=RomLocation(PAGE, 0x7C1B),
                dispatcher_call=RomLocation(PAGE, 0x7D87),
                call_chain=(
                    RomLocation(PAGE, 0x7C1B),
                    RomLocation(PAGE, 0x7D82),
                    RomLocation(PAGE, 0x7D87),
                ),
            ),
        ),
        os_validity=OsValidityFlag(
            offset=0x1FE0,
            mask=0x01,
            valid_when_clear=True,
            mark_invalid_bcall_id=0x8093,
            mark_invalid_entry=RomLocation(0x3F, 0x5209),
            mark_valid_bcall_id=0x8099,
            mark_valid_entry=RomLocation(0x3F, 0x51F5),
            check_bcall_id=0x809C,
            check_entry=RomLocation(0x3F, 0x52C6),
            write_byte_bcall_id=0x8021,
            invalid_rebuild_span=CertificateSpan(0x1F18, 0x00E8),
        ),
        app_trials=AppTrialTable(
            model_offsets=(0x1E50, 0x1F18),
            length=0x00C8,
            entry_length=2,
            erased_byte=0xFF,
            clear_routine=RomLocation(PAGE, 0x5759),
            write_routine=RomLocation(PAGE, 0x5BB7),
            query_routine=RomLocation(PAGE, 0x5466),
            display_entry=RomLocation(0x36, 0x70B5),
            display_label="Trials Remaining:",
            display_label_location=RomLocation(0x01, 0x41AA),
            delete_callers=(
                RomLocation(PAGE, 0x4018),
                RomLocation(PAGE, 0x5F71),
            ),
            clear_rebuild_mode=1,
        ),
        app_validity=AppValidityUpdate(
            locator=RomLocation(PAGE, 0x51F6),
            set_routine=RomLocation(PAGE, 0x51BE),
            clear_routine=RomLocation(PAGE, 0x51E4),
            preceding_offset=0x1FE0,
            bitmap_offset=0x1FE1,
            bit_order="least-significant bit first",
            set_rebuild_mode=5,
            clear_bcall_id=0x8021,
        ),
        app_restrictions=AppRestrictionApi(
            set_bcall_id=0x52F6,
            set_entry=RomLocation(PAGE, 0x7B9B),
            remove_bcall_id=0x52F9,
            remove_entry=RomLocation(PAGE, 0x7C1B),
            query_bcall_id=0x52FC,
            query_entry=RomLocation(PAGE, 0x7CBA),
            control_span=CertificateSpan(0x1DD2, 0x000E),
            control_offset=0x1DD2,
            record_offset=0x1DD3,
            record_length=0x000D,
            app_bitmap_offset=0x1DD3,
            app_bitmap_length=0x000D,
            app_page_bias=8,
            bitmap_bit_order="least-significant bit first",
            base_mask=0x01,
            logbase_mask=0x02,
            summation_mask=0x04,
            remove_rebuild_mode=6,
            set_supported_types=(0, 1, 2, 3, 4, 6, 7),
            remove_supported_types=(1, 2, 3, 6),
            types=(
                RestrictionTypeBehavior(
                    0,
                    "one App selected by the name in OP1",
                    "resolve the App page and clear its bitmap bit",
                    "resolve the App page and report whether its bitmap bit is clear",
                    "unsupported",
                ),
                RestrictionTypeBehavior(
                    1,
                    "13-byte restriction record",
                    "program RAM 0x847A-0x8486 into offsets 0x1DD3-0x1DDF",
                    "report whether any record byte differs from 0xFF",
                    "replace all 13 record bytes with 0xFF through rebuild mode 6",
                ),
                RestrictionTypeBehavior(
                    2,
                    "base restriction control flag",
                    "clear control bit 0",
                    "return 1 when control bit 0 is clear",
                    "set control bit 0 through rebuild mode 6",
                ),
                RestrictionTypeBehavior(
                    3,
                    "complete restriction profile",
                    "clear control bit 0 and program the 13-byte record",
                    "return an active/profile mask derived from control and record bytes",
                    "set control bits 0-4 and erase the record through rebuild mode 6",
                ),
                RestrictionTypeBehavior(
                    4,
                    "bulk App-restriction bitmap",
                    "program control plus 13 bitmap bytes from RAM 0x848E-0x849B",
                    "count installed Apps whose bitmap bits are clear",
                    "unsupported",
                ),
                RestrictionTypeBehavior(
                    5,
                    "one App selected by the page in B",
                    "unsupported",
                    "report whether the selected page's bitmap bit is clear",
                    "unsupported",
                ),
                RestrictionTypeBehavior(
                    6,
                    "logBASE disabled",
                    "clear control bit 1",
                    "return 4 when control bit 1 is clear",
                    "set control bits 1 and 2 through rebuild mode 6",
                ),
                RestrictionTypeBehavior(
                    7,
                    "summation disabled",
                    "clear control bit 2",
                    "return 8 when control bit 2 is clear",
                    "unsupported",
                ),
            ),
        ),
        tail_accessors=tuple(tail_accessors),
        model_selected_offset=ModelSelectedCertificateOffset(
            accessor=RomLocation(PAGE, 0x5247),
            probe=RomLocation(0x00, 0x1837),
            port=0x02,
            mask=0x80,
            set_bit_offset=0x1E50,
            clear_bit_offset=0x1F18,
            ti84_plus_observed_port_values=(0xE1, 0xE3, 0xE7),
            ti84_plus_selected_offset=0x1E50,
        ),
    )
