#!/usr/bin/env python3
"""Extract TI-84 link-port (port 0x00) audio from a headless TilEm instruction trace.

The TI-83+/84+ plays sound by toggling the two link lines (bits 0/1 of port 0x00,
the tip/ring of the I/O jack) under a periodic interrupt; a speaker/headphone across
the lines turns that bit-stream into sound. This tool replays every `OUT (0x00),A`
in the trace, reconstructs the line state over emulated CPU clocks (zero-order hold),
and resamples it to a WAV.

CPU clock: the trace's `clk` field counts Z80 cycles. The 84+ runs the player at
15 MHz (the app sets port 0x20=1), so we map clocks->seconds with --cpu-hz.

Usage:
  extract_linkport_audio.py TRACE -o out.wav [--cpu-hz 15000000] [--rate 44100]
"""
import argparse, importlib.util, os, struct, sys, wave

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ttr", os.path.join(HERE, "tilem_trace_resolve.py"))
ttr = importlib.util.module_from_spec(spec); spec.loader.exec_module(ttr)


def collect_port0(path):
    """Return (events, clk_first, clk_last): events = list of (clk, value)."""
    events = []
    with open(path, "rb") as fp:
        ttr.read_header(fp)
        for rtype, payload in ttr.iter_records(fp):
            if rtype != 0x01:
                continue
            op = payload[ttr.IDX_OPCODE]
            low = op & 0xFF
            port = value = None
            if (op & 0xFFFF0000) == 0 and (op & 0xFF00) == 0 and low == 0xD3:
                wz = payload[ttr.IDX_WZ]
                port, value = wz & 0xFF, (wz >> 8) & 0xFF
            elif (op & 0xFFFF) in ttr.OUT_C_REG and (op & 0xFFFF0000) == 0:
                reg = ttr.OUT_C_REG[op & 0xFFFF]
                port = payload[ttr.IDX_BC] & 0xFF
                value = {
                    "A": payload[ttr.IDX_AF] >> 8, "B": payload[ttr.IDX_BC] >> 8,
                    "C": payload[ttr.IDX_BC] & 0xFF, "D": payload[ttr.IDX_DE] >> 8,
                    "E": payload[ttr.IDX_DE] & 0xFF, "H": payload[ttr.IDX_HL] >> 8,
                    "L": payload[ttr.IDX_HL] & 0xFF,
                }[reg]
            if port == 0x00:
                events.append((payload[ttr.IDX_CLOCK], value))
    return events


# Link-port bits -> a 4-level differential amplitude. On the I/O jack the two
# lines are pulled high and driven low; bit set => line LOW. The speaker sits
# across tip/ring, so the audible signal tracks (line0 - line1).
def level(value):
    b0 = (value >> 0) & 1   # tip line driver
    b1 = (value >> 1) & 1   # ring line driver
    return b1 - b0          # -1, 0, or +1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace")
    ap.add_argument("-o", "--out", default="linkport.wav")
    ap.add_argument("--cpu-hz", type=float, default=15.0e6,
                    help="emulated Z80 clock (default 15e6; the app sets 15 MHz)")
    ap.add_argument("--rate", type=int, default=44100, help="output sample rate")
    ap.add_argument("--gain", type=float, default=0.9)
    args = ap.parse_args()

    ev = collect_port0(args.trace)
    if not ev:
        print("No OUT (0x00) writes found in the trace.", file=sys.stderr)
        sys.exit(1)
    # Drop the sparse boot-time port-0 writes (link reset etc.): keep from the
    # first event whose following window is dense (the app's steady sound ISR).
    win = int(args.cpu_hz * 0.05)          # 50 ms of clocks
    start = 0
    for i in range(len(ev) - 20):
        if ev[i + 20][0] - ev[i][0] < win:  # >=20 writes within 50ms => audio running
            start = i
            break
    if start:
        print(f"trimmed {start} leading boot writes", file=sys.stderr)
    ev = ev[start:]
    clk0, clk1 = ev[0][0], ev[-1][0]
    dur = (clk1 - clk0) / args.cpu_hz
    vals = sorted({v for _, v in ev})
    print(f"port-0 writes: {len(ev)}", file=sys.stderr)
    print(f"clock span: {clk0}..{clk1} ({dur:.3f}s @ {args.cpu_hz/1e6:.1f}MHz)", file=sys.stderr)
    print(f"avg write rate: {len(ev)/dur:.0f} Hz", file=sys.stderr)
    print(f"distinct values written: {[hex(v) for v in vals]}", file=sys.stderr)

    # Zero-order-hold resample: walk events, hold each level until the next event.
    nsamp = int(dur * args.rate)
    if nsamp <= 0:
        print("trace too short", file=sys.stderr); sys.exit(1)
    samples = bytearray()
    ei = 0
    cur = level(ev[0][1])
    for n in range(nsamp):
        t_clk = clk0 + n * args.cpu_hz / args.rate
        while ei + 1 < len(ev) and ev[ei + 1][0] <= t_clk:
            ei += 1
            cur = level(ev[ei][1])
        s = int(max(-1.0, min(1.0, cur)) * 32767 * args.gain)
        samples += struct.pack("<h", s)

    with wave.open(args.out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(args.rate)
        w.writeframes(bytes(samples))
    print(f"wrote {args.out}: {nsamp} samples, {dur:.2f}s @ {args.rate}Hz", file=sys.stderr)


if __name__ == "__main__":
    main()
