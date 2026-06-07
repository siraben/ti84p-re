#!/usr/bin/env python3
"""Encode and render music for the Bad Apple TI-84 link-port player.

Inputs can be the upstream MilkyTracker `.mmp` file, a standard MIDI file, or a
small JSON song format. The encoder writes the four `track*.asm` files consumed
by `badapple.asm`; the renderer uses the same timing and note-counter model to
emit a real-time WAV.
"""
import argparse
import json
import math
import struct
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

INTERRUPT_HZ = 33333.3
TIMER_INTERVAL = 24
MUSIC_INTERVAL = 75
TRACKER_PERIOD = TIMER_INTERVAL * MUSIC_INTERVAL
TRACKER_POS_DIVISOR = 6
STARTUP_REST_TICKS = 16
NOISE_SEED = 0x5A
NOISE_TAP = 0x1D
TRACK_COUNT = 4
DEFAULT_MIDI_GATE = 0.70
DEFAULT_MIDI_TEMPO_US = 500000
DEFAULT_TICKS_PER_BEAT = 384

NOTE_OFF = 0.0
NOTE_INDEX = {
    "C": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
}


def key_to_count(key_no):
    freq = 1.05946309436 ** (key_no - 57) * 440.0
    count = 0.5 * INTERRUPT_HZ / freq
    return max(1.0, min(254.0, count))


def note_name_to_key(name):
    token = name.strip().upper()
    if token in {"R", "REST", "-"}:
        return None
    accidental = token[1:2]
    if accidental in {"#", "B"}:
        pitch, octave = token[:2], token[2:]
    else:
        pitch, octave = token[:1], token[1:]
    if pitch not in NOTE_INDEX or not octave.lstrip("-").isdigit():
        raise ValueError(f"invalid note name: {name!r}")
    midi = (int(octave) + 1) * 12 + NOTE_INDEX[pitch]
    return midi - 12


def count_to_bytes(count):
    if count <= 0:
        return 0, 0
    whole = math.floor(count)
    fract = math.floor((count - whole) * 256)
    return fract & 0xFF, int(whole) & 0xFF


def normalize_channels(channels):
    normalized = []
    for channel in channels[:TRACK_COUNT]:
        notes = []
        for pos, length, count in channel:
            if length <= 0:
                continue
            notes.append((int(pos), int(length), float(count)))
        normalized.append(sorted(notes))
    while len(normalized) < TRACK_COUNT:
        normalized.append([])
    return normalized


def decode_mmp(path):
    tree = ET.parse(path)
    channels = []
    for track in tree.getroot().iter("track"):
        if track.get("type") != "0":
            continue
        notes = []
        for pattern in track.iter("pattern"):
            offset = int(pattern.get("pos"))
            for note in pattern.iter("note"):
                count = key_to_count(int(note.get("key")))
                pos = (int(note.get("pos")) + offset) // TRACKER_POS_DIVISOR
                length = (int(note.get("len")) + 1) // TRACKER_POS_DIVISOR
                notes.append((pos, max(1, length), count))
        channels.append(sorted(notes))
    if len(channels) < TRACK_COUNT:
        raise ValueError(f"expected four tracks, found {len(channels)}")
    return normalize_channels(channels)


def decode_json_song(path):
    data = json.loads(path.read_text())
    tempo = float(data.get("tempo_bpm", 120))
    ticks_per_beat = data.get("ticks_per_beat")
    if ticks_per_beat is None:
        ticks_per_beat = (60.0 / tempo) * INTERRUPT_HZ / TRACKER_PERIOD
    channels = []
    for channel in data.get("channels", []):
        raw_notes = channel.get("notes", []) if isinstance(channel, dict) else channel
        notes = []
        for item in raw_notes:
            if isinstance(item, dict):
                note = item.get("note", "REST")
                beat = float(item.get("beat", item.get("start", 0)))
                duration = float(item.get("duration", 1))
            else:
                note, beat, duration = item
                beat, duration = float(beat), float(duration)
            key = note_name_to_key(str(note))
            pos = round(beat * ticks_per_beat)
            length = max(1, round(duration * ticks_per_beat))
            count = NOTE_OFF if key is None else key_to_count(key)
            notes.append((pos, length, count))
        channels.append(sorted(notes))
    return normalize_channels(channels)


def read_varlen(data, offset):
    value = 0
    while True:
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, offset


def parse_midi_track(data):
    events = []
    offset = 0
    tick = 0
    running_status = None
    active = {}
    while offset < len(data):
        delta, offset = read_varlen(data, offset)
        tick += delta
        status = data[offset]
        if status < 0x80:
            if running_status is None:
                raise ValueError("MIDI running status without previous status")
            status = running_status
        else:
            offset += 1
            if status < 0xF0:
                running_status = status

        if status == 0xFF:
            meta_type = data[offset]
            offset += 1
            length, offset = read_varlen(data, offset)
            payload = data[offset:offset + length]
            offset += length
            if meta_type == 0x2F:
                break
            if meta_type == 0x51 and length == 3:
                tempo = int.from_bytes(payload, "big")
                events.append(("tempo", tick, tempo))
            continue
        if status in {0xF0, 0xF7}:
            length, offset = read_varlen(data, offset)
            offset += length
            continue

        command = status & 0xF0
        channel = status & 0x0F
        if command in {0xC0, 0xD0}:
            offset += 1
            continue
        key = data[offset]
        value = data[offset + 1]
        offset += 2
        if command == 0x90 and value:
            active.setdefault((channel, key), []).append(tick)
        elif command in {0x80, 0x90}:
            starts = active.get((channel, key))
            if starts:
                start = starts.pop(0)
                events.append(("note", start, tick, channel, key))
    return events


def parse_midi_file(path):
    data = path.read_bytes()
    if data[:4] != b"MThd":
        raise ValueError(f"not a MIDI file: {path}")
    header_len = struct.unpack(">I", data[4:8])[0]
    fmt, track_count, division = struct.unpack(">HHH", data[8:14])
    if division & 0x8000:
        raise ValueError("SMPTE MIDI timing is not supported")
    ticks_per_beat = division or DEFAULT_TICKS_PER_BEAT
    offset = 8 + header_len
    tracks = []
    tempo_events = [(0, DEFAULT_MIDI_TEMPO_US)]
    for _ in range(track_count):
        if data[offset:offset + 4] != b"MTrk":
            raise ValueError("missing MIDI track chunk")
        length = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        track_data = data[offset + 8:offset + 8 + length]
        offset += 8 + length
        events = parse_midi_track(track_data)
        tracks.append([event for event in events if event[0] == "note"])
        tempo_events.extend((event[1], event[2]) for event in events if event[0] == "tempo")
    tempo_events.sort()
    return fmt, ticks_per_beat, tempo_events, tracks


def build_tick_seconds(tempo_events, ticks_per_beat):
    compact = []
    for tick, tempo in tempo_events:
        if compact and compact[-1][0] == tick:
            compact[-1] = (tick, tempo)
        else:
            compact.append((tick, tempo))

    def tick_to_seconds(tick):
        seconds = 0.0
        prev_tick, tempo = compact[0]
        for next_tick, next_tempo in compact[1:]:
            if tick <= next_tick:
                break
            seconds += (next_tick - prev_tick) * tempo / 1_000_000.0 / ticks_per_beat
            prev_tick, tempo = next_tick, next_tempo
        seconds += (tick - prev_tick) * tempo / 1_000_000.0 / ticks_per_beat
        return seconds

    return tick_to_seconds


def midi_track_groups(tracks):
    groups = []
    for index, track in enumerate(tracks):
        notes = [event for event in track if event[0] == "note"]
        if notes:
            groups.append((index, notes))
    if len(groups) <= 1:
        by_channel = {}
        for _, notes in groups:
            for event in notes:
                by_channel.setdefault(event[3], []).append(event)
        groups = sorted(by_channel.items())
    return [notes for _, notes in groups]


def decode_midi_song(path):
    _, ticks_per_beat, tempo_events, tracks = parse_midi_file(path)
    tick_to_seconds = build_tick_seconds(tempo_events, ticks_per_beat)
    ticks_per_second = INTERRUPT_HZ / TRACKER_PERIOD
    channels = []
    for group in midi_track_groups(tracks)[:3]:
        notes = []
        for _, start_tick, end_tick, _, key in group:
            start = round(tick_to_seconds(start_tick) * ticks_per_second)
            raw_length = max(1, round((tick_to_seconds(end_tick) - tick_to_seconds(start_tick)) *
                                      ticks_per_second * DEFAULT_MIDI_GATE))
            notes.append((start, raw_length, key_to_count(key - 12)))
        channels.append(sorted(notes))
    return normalize_channels(channels)


def read_song(path):
    suffix = path.suffix.lower()
    if suffix == ".mmp":
        return decode_mmp(path)
    if suffix in {".mid", ".midi"}:
        return decode_midi_song(path)
    if suffix == ".json":
        return decode_json_song(path)
    raise ValueError(f"unsupported song format: {path}")


def split_duration(pos, length, count):
    remaining = int(length)
    cursor = int(pos)
    while remaining > 0:
        chunk = min(remaining, 256)
        yield cursor, chunk, count
        cursor += chunk
        remaining -= chunk


def scheduled_track_events(notes):
    events = []
    cursor = 0
    for pos, length, count in sorted(notes):
        if pos > cursor:
            events.extend(split_duration(cursor, pos - cursor, NOTE_OFF))
        start = max(pos, cursor)
        end = max(cursor, pos + length)
        if end > start:
            events.extend(split_duration(start, end - start, count))
        cursor = end
    events.append((0, STARTUP_REST_TICKS, NOTE_OFF))
    events.sort()
    return events


def encode_track_events(notes):
    events = scheduled_track_events(notes)
    cursor = sum(length for _, length, _ in events)
    events.extend(split_duration(cursor, 256 * 3, NOTE_OFF))
    return events


def write_track_asm(channels, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for index, notes in enumerate(channels, 1):
        path = out_dir / f"track{index}.asm"
        with path.open("w", newline="\n") as fp:
            fp.write(".org $4000\n")
            fp.write(".db 04\n")
            fp.write(f"Track{index}Data:\n")
            for pos, length, count in encode_track_events(notes):
                fract, whole = count_to_bytes(count)
                fp.write(f".db {length % 256}, {fract}, {whole} ;{pos}\n")
            fp.write("\n")
            fp.write(".block $8000 - $\n")


def build_timeline(track_events):
    timeline = []
    cursor = 0
    for _, length, count in track_events:
        timeline.append((cursor, count))
        cursor += length
    timeline.append((cursor, NOTE_OFF))
    return timeline, cursor


def build_note_timeline(notes):
    timeline = []
    for pos, length, count in notes:
        timeline.append((pos, count))
        timeline.append((pos + length, NOTE_OFF))
    timeline.sort()
    return timeline


class Voice:
    def __init__(self, events):
        self.events = events
        self.index = 0
        self.count = NOTE_OFF
        self.phase_count = 1.0
        self.frac_error = 0.0
        self.level = 0

    def tracker_tick(self, tick):
        while self.index < len(self.events) and self.events[self.index][0] <= tick:
            self.count = self.events[self.index][1]
            self.phase_count = max(1.0, self.count)
            self.frac_error = 0.0
            self.index += 1

    def step(self):
        if self.count <= 0.0:
            return 0, False
        fired = False
        self.phase_count -= 1.0
        if self.phase_count <= 0.0:
            whole = math.floor(self.count)
            frac = self.count - whole
            self.frac_error += frac
            adjust = 1.0 if self.frac_error >= 1.0 else 0.0
            if adjust:
                self.frac_error -= 1.0
            self.phase_count += max(1.0, whole + adjust)
            self.level ^= 1
            fired = True
        return self.level, fired


def next_noise_bit(state):
    state = ((state << 1) ^ (NOISE_TAP if state & 0x80 else 0)) & 0xFF
    return state, 1 if state & 1 else -1


def next_noise_port_bit(state, level):
    state = ((state << 1) ^ (NOISE_TAP if state & 0x80 else 0)) & 0xFF
    return state, level ^ (state & 1)


def append_sample(samples, sample, gain):
    sample_i = int(max(-1.0, min(1.0, sample * gain)) * 32767)
    samples += struct.pack("<h", sample_i)


def render_wav_frames(channels, rate, gain, profile):
    if profile == "tracker":
        timelines = [build_note_timeline(ch) for ch in channels]
        end_tick = max((pos + length for ch in channels for pos, length, _ in ch), default=0)
        total_interrupts = (end_tick + STARTUP_REST_TICKS) * TRACKER_PERIOD
    else:
        scheduled = [scheduled_track_events(ch) for ch in channels]
        timelines_and_ends = [build_timeline(ch) for ch in scheduled]
        timelines = [timeline for timeline, _ in timelines_and_ends]
        end_tick = max((end for _, end in timelines_and_ends), default=0)
        total_interrupts = end_tick * TRACKER_PERIOD
    voices = [Voice(timeline) for timeline in timelines[:3]]
    noise_voice = Voice(timelines[3])
    total_samples = round(total_interrupts * rate / INTERRUPT_HZ)
    samples = bytearray()
    noise_state = NOISE_SEED
    noise_level = 0
    current_interrupt = 0
    current_sample = 0.0

    def step_interrupt():
        nonlocal current_interrupt, current_sample, noise_state, noise_level
        if current_interrupt % TRACKER_PERIOD == 0:
            tick = current_interrupt // TRACKER_PERIOD
            for voice in voices:
                voice.tracker_tick(tick)
            noise_voice.tracker_tick(tick)

        if profile == "tracker":
            value = 0
            for voice in voices:
                level, _ = voice.step()
                if voice.count > 0.0:
                    value += 1 if level else -1
            if noise_voice.count > 0.0:
                noise_voice.step()
                noise_state, value_noise = next_noise_bit(noise_state)
                value += value_noise
            current_sample = value / 4
            current_interrupt += 1
            return

        ch1, _ = voices[0].step()
        ch2, _ = voices[1].step()
        ch3, _ = voices[2].step()
        _, noise_fired = noise_voice.step()
        if noise_voice.count > 0.0 and noise_fired:
            noise_state, noise_level = next_noise_port_bit(noise_state, noise_level)
        elif noise_voice.count <= 0.0:
            noise_level = 0
        bit1 = ch1 | ch2
        bit0 = ch3 | noise_level
        current_sample = bit1 - bit0
        current_interrupt += 1

    step_interrupt()
    for sample_index in range(total_samples):
        target_interrupt = int(sample_index * INTERRUPT_HZ / rate)
        while current_interrupt <= target_interrupt and current_interrupt < total_interrupts:
            step_interrupt()
        append_sample(samples, current_sample, gain)
    return samples


def write_wav(channels, out_path, rate, gain, profile):
    frames = render_wav_frames(channels, rate, gain, profile)
    with wave.open(str(out_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)
    print(f"wrote {out_path}: {len(frames) // 2} samples @ {rate} Hz ({profile})")


def add_common_args(parser):
    parser.add_argument("song", type=Path, help="input .mmp, .mid/.midi, or .json song")
    parser.add_argument("--rate", type=int, default=44100)
    parser.add_argument("--gain", type=float, default=0.85)
    parser.add_argument("--profile", choices=("tracker", "raw-port"), default="tracker",
                        help="tracker is the listening mix; raw-port renders link-line differential")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    encode = sub.add_parser("encode", help="write track1.asm through track4.asm")
    add_common_args(encode)
    encode.add_argument("--asm-dir", type=Path, required=True)
    encode.add_argument("--render", type=Path, help="also render a WAV")

    render = sub.add_parser("render", help="render a WAV")
    add_common_args(render)
    render.add_argument("-o", "--out", type=Path, required=True)

    args = parser.parse_args()
    channels = read_song(args.song)
    if args.command == "encode":
        write_track_asm(channels, args.asm_dir)
        if args.render:
            write_wav(channels, args.render, args.rate, args.gain, args.profile)
    elif args.command == "render":
        write_wav(channels, args.out, args.rate, args.gain, args.profile)


if __name__ == "__main__":
    main()
