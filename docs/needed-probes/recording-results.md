# Recording a physical result

A physical result is useful only when it identifies the calculator, artifact,
conditions, and unmodified raw output. Record these fields before interpreting
the payload.

## Required files

Keep the following together:

- the original exported `.8xv` AppVar;
- `manifest.json` from the exact probe build;
- the decoded JSON report;
- photographs of the calculator label, PCB, and ASIC marking when available;
- raw instrument captures for electrical tests; and
- a text or JSON metadata record using the fields below.

Do not replace the exported AppVar with decoded text. The decoder can change;
the original TI container preserves the checksum and byte-level result.

## Metadata fields

```json
{
  "probe": "timer-physical",
  "program": "HWTMR",
  "result_appvar": "HWTMR001",
  "calculator": {
    "model": "TI-84 Plus",
    "serial": null,
    "pcb_revision": null,
    "pcb_date": null,
    "asic_marking": null,
    "port_0x15": null,
    "boot_version": null,
    "os_version": "2.55MP"
  },
  "artifact": {
    "machine_code_sha256": null,
    "program_file_sha256": null,
    "manifest_sha256": null
  },
  "run": {
    "utc_time": null,
    "supply_volts": null,
    "load_amps": null,
    "temperature_c": null,
    "connected_equipment": [],
    "operator_actions": [],
    "displayed_verification_code": null,
    "visible_reset": false,
    "notes": null
  },
  "files": {
    "appvar": "HWTMR001.8xv",
    "decoded_json": "HWTMR001.json",
    "instrument_capture": null
  }
}
```

Use `null` for an unavailable field rather than guessing. Omit a serial number
from a public submission if it identifies the owner; assign a stable local
unit ID instead.

## Acceptance checks

Before using a result as evidence:

1. Match both artifact hashes to the retained build manifest.
2. Decode the original AppVar without checksum, length, version, or probe-ID
   errors.
3. Confirm every cleanup or restoration flag required by that probe.
4. For `HWPRTC`, `HWPMAP`, `HWPLCD`, or `HWPIRQ`, compare any recorded screen
   number with `verification_code_decimal` from the decoded AppVar.
5. Check that the recorded model and OS satisfy the probe's entry guards.
6. Keep visible reset, timeout, unsupported, and normal-return outcomes
   distinct.
7. For an instrumented run, align the raw capture with the calculator trigger
   and retain the instrument configuration.

A failed cleanup does not necessarily erase the raw observation, but it
invalidates claims that depend on the intended precondition or restored state.
