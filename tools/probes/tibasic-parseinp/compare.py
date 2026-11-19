"""Replay matched OS 2.55MP parser calls and check the final LCD text rows."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from ti84re.rom.provenance import digest
from ti84re.tibasic.samples import SAMPLES, asm_payload, ti83p_program_file

HERE = Path(__file__).resolve().parent
PROGRAMS = ("ASMPARSE.8xp", "ZZPARSE.8xp", "ZZBASIC.8xp")


def write_programs(directory: Path, bcall: int) -> None:
    source = SAMPLES["zzparse"][0]
    machine = bytearray.fromhex(source.splitlines()[1])
    offset = machine.index(bytes.fromhex("EF 07 4B C9")) + 1
    machine[offset:offset + 2] = bcall.to_bytes(2, "little")
    _, tokens = asm_payload(machine.hex().upper())
    (directory / "ZZPARSE.8xp").write_bytes(ti83p_program_file("ZZPARSE", tokens))
    for name in ("ASMPARSE", "ZZBASIC"):
        _, tokens = SAMPLES[name.lower()]
        (directory / f"{name}.8xp").write_bytes(ti83p_program_file(name, tokens))


def text_rows_hash(screenshot: Path) -> str:
    # Rows 0–47 include the wrapper, target and Done, or the full error menu.
    # Exclude the homescreen's blinking cursor on the next line.
    pixels = subprocess.check_output([
        "magick", str(screenshot), "-crop", "96x48+0+0", "+repage",
        "-colorspace", "Gray", "-threshold", "50%", "-depth", "8", "gray:-",
    ])
    if len(pixels) != 96 * 48:
        raise ValueError("expected a 96-pixel-wide calculator screenshot")
    return hashlib.sha256(pixels).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tilem", required=True, type=Path,
                        help="TilEm binary with headless positional file transfer")
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path,
                        help="new directory for the two independent runs")
    args = parser.parse_args()
    reference = json.loads((HERE / "result.json").read_text())
    tilem = args.tilem.resolve()
    replay = {
        "rom_sha256": digest(args.rom),
        "emulator_sha256": digest(tilem),
        "macro_sha256": digest(HERE / "run.macro"),
        "cases": {},
    }
    if replay["rom_sha256"] != reference["rom_sha256"]:
        parser.error("this comparison requires the canonical retail OS 2.55MP image")
    if replay["macro_sha256"] != reference["macro_sha256"]:
        parser.error("macro differs from the recorded comparison")
    args.out_dir.mkdir(parents=True, exist_ok=False)
    for case, expected in reference["cases"].items():
        directory = args.out_dir / case
        directory.mkdir()
        write_programs(directory, int(expected["bcall_id"], 16))
        programs = {name: digest(directory / name) for name in PROGRAMS}
        if programs != expected["programs_sha256"]:
            raise ValueError(f"{case}: generated programs differ from the recorded inputs")
        shutil.copyfile(args.rom, directory / "ti84p.rom")
        subprocess.run([
            str(tilem), "--headless", "--rom", "ti84p.rom", "--model", "ti84p",
            "--normal-speed", "--reset", "--macro", str(HERE / "run.macro"),
            "--headless-record", "lcd.gif", *PROGRAMS,
        ], cwd=directory, check=True, timeout=120)
        text_hash = text_rows_hash(directory / "final.png")
        replay["cases"][case] = {
            "programs_sha256": programs,
            "final_png_sha256": digest(directory / "final.png"),
            "final_ram_sha256": digest(directory / "final.ram"),
            "text_rows_sha256": text_hash,
        }
        (args.out_dir / "manifest.json").write_text(json.dumps(replay, indent=2) + "\n")
        if text_hash != expected["text_rows_sha256"]:
            raise ValueError(f"{case}: LCD text differs; inspect {directory / 'final.png'}")
        print(f"{case}: {' / '.join(expected['visible_text'])}")


if __name__ == "__main__":
    main()
