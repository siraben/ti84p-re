# Recording a physical result

A physical result is useful only when it identifies the calculator, artifact,
conditions, and unmodified raw output. The evidence bundler retains every bit
of the exported AppVar and rejects a record that omits required physical
context.

## Required files

Keep the following together:

- the original exported `.8xv` AppVar;
- `manifest.json` from the exact probe build;
- the decoded JSON report;
- photographs of the calculator label, PCB, and ASIC marking when available;
- raw instrument captures for electrical tests; and
- a text or JSON metadata record using the fields below.

Do not replace the exported AppVar with decoded text. The decoder can change;
the original TI container preserves the checksum and byte-level result. The
decoded report includes `frame_hex`, `frame_sha256`, `appvar_file_sha256`, and
every named measurement. An unrecognized payload byte remains present in
`payload_hex` and `frame_hex`.

## Metadata fields

```json
{
  "schema": "ti84p-re.physical-probe-metadata.v1",
  "probe": "timer-physical",
  "program": "HWTMR",
  "result_appvar": "HWTMR001",
  "calculator": {
    "unit_id": "lab-ta3-01",
    "model": "TI-84 Plus",
    "pcb_revision": "TA3 rev A",
    "pcb_date": null,
    "asic_marking": "marking from package",
    "port_0x15": 69,
    "boot_version": "1.03",
    "os_version": "2.55MP"
  },
  "run": {
    "utc_time": "2026-08-25T19:30:00-04:00",
    "power_source": "fresh AAA cells",
    "launch_context": "unmodified OS 2.55MP direct Asm(",
    "cpu_speed_setting": "OS default 15 MHz",
    "interrupts_enabled_on_entry": true,
    "preexisting_hooks_or_shells": [],
    "supply_volts": null,
    "load_amps": null,
    "temperature_c": null,
    "connected_equipment": [],
    "operator_actions": ["direct Asm(prgmHWTMR)"],
    "displayed_verification_code": 3397,
    "visible_reset": false,
    "notes": null
  }
}
```

Use `null` for an optional unavailable field rather than guessing. The evidence
bundler requires a stable unit ID, PCB revision, ASIC marking, boot version,
OS version, power source, launch path, CPU-speed setting, interrupt state,
hook or shell list, operator actions, and timezone-qualified run time. It
rejects `"unknown"` for those identity fields. Omit a serial number from a
public submission if it identifies the owner.

The metadata contract adds fields when a probe depends on external state:

| Probe | Additional required fields |
|-------|----------------------------|
| Execution fetch | `calculator.backup_verified`, `run.recovery_observation` |
| USB snapshot | `run.usb_state`; nonempty `run.connected_equipment` |
| Battery level or raw battery | numeric voltage, load, temperature, and `run.supply_sweep_direction` |
| Raw link | `run.link_connector_state`; nonempty `run.connected_equipment`, using `"none"` for a disconnected jack |
| Keypad settle | nonempty `run.operator_actions` naming the held key or chord |
| RTC rollover | `run.rtc_configuration` |
| Mapper overlays | `calculator.backup_verified` |
| LCD controller | backup status, controller or revision, and `run.panel_observation` |
| Hidden LCD laboratory probe | backup status, controller or revision, panel observation, and recovery notes |

`calculator.backup_verified` must be `true` for the guarded execution, mapper,
and LCD experiments. The displayed verification code is required after a
normal return. A visible-reset record may leave it `null`.

## Self-contained evidence bundle

Build one canonical record after exporting the AppVar:

```sh
python tools/physical_probe_evidence.py \
  --appvar HWTMR001.8xv \
  --program /tmp/hardware-probes/HWTMR.8xp \
  --manifest /tmp/hardware-probes/manifest.json \
  --metadata HWTMR001-metadata.json \
  --attachment unit_photo=lab-ta3-01.png \
  --output HWTMR001-evidence.json
python tools/physical_probe_evidence.py --check HWTMR001-evidence.json
```

Each `--attachment ROLE=PATH` argument embeds the complete capture. Use roles
such as `unit_photo`, `pcb_photo`, `scope_trace`, `logic_trace`, and
`instrument_setup`. The output embeds the original `.8xv`, transferred `.8xp`,
manifest, metadata, and attachments as Base64 with a size and SHA-256 for each
file. It verifies the `.8xp` against the program hash in the manifest. The
bundle also embeds the selected artifact row, decoded report, and state-coverage
contract. The `--check` path reconstructs the record from those embedded files
and rejects any changed hash, decoded field, manifest association, ASIC byte,
or screen code.

The bundle covers all calculator-observable state defined by the selected
probe. It cannot manufacture analog voltage, contact motion, a PCB marking, or
an instrument waveform. Those values belong in the required metadata or an
embedded attachment. Preserve the standalone `.8xv` and raw captures as well.

## Acceptance checks

Before using a result as evidence:

1. Run `physical_probe_evidence.py --check` and retain its passing bundle.
2. Match both artifact hashes to the embedded build-manifest row.
3. Decode the original AppVar without checksum, length, version, or probe-ID
   errors.
4. Confirm every cleanup or restoration flag required by that probe.
5. For every normal-return probe, compare the recorded screen number with
   `verification_code_decimal` from the decoded AppVar. A reset-capable
   execution probe can leave a pending AppVar without reaching this display.
6. Check that the recorded model and OS satisfy the probe's entry guards.
7. Keep visible reset, timeout, unsupported, and normal-return outcomes
   distinct.
8. For an instrumented run, align the raw capture with the calculator trigger
   and retain the instrument configuration.

A failed cleanup does not necessarily erase the raw observation, but it
invalidates claims that depend on the intended precondition or restored state.
