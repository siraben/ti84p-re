# Summary

[System overview](system-overview.md)

# Orientation

- [Subsystem map](subsystem-map.md)
- [Conventions and evidence](conventions.md)
- [Build and evidence provenance](provenance.md)
- [Glossary](glossary.md)

# Architecture and memory

- [Memory map](memory-map.md)
- [Paging](paging.md)
- [Bus timing and wait states](bus-timing.md)
- [ASIC status, identity, protection, and GPIO](asic-status-gpio.md)
- [Execution protection](execution-protection.md)
- [The bcall mechanism](bcall-mechanism.md)
- [Interrupts (IM1)](interrupts.md)
    - [Clock, timers, and power](clock-timers-power.md)
- [Boot, contexts, and errors](boot-contexts-errors.md)
    - [Retail boot page](retail-boot.md)
        - [Retail boot hardware initialization](boot-hardware.md)
- [Memory management](memory-management.md)
    - [Variables, archive and unarchive](sub-vat-archive.md)
    - [Resident assembly programs](sub-resident-programs.md)
    - [Resident scratch RAM](sub-resident-scratch.md)
    - [Apps, memory reset, and settings](sub-apps-mem-settings.md)
- [Flash memory](flash-memory.md)
    - [Flash bcall programming guide](flash-bcall-guide.md)
    - [Flash emulator comparison](flash-emulator-comparison.md)
- [MD5 accelerator and boot API](md5-hardware.md)
- [Flash page map](flash-page-map.md)
- [RAM pages](ram-pages.md)
- [Physical hardware probes](hardware-probes.md)
    - [Measurements needed from physical calculators](needed-probes/physical-measurements.md)
        - [Calculator-readable probes](needed-probes/calculator-readable.md)
        - [Guarded mapper, LCD, and interrupt probes](needed-probes/additional-calculator-probes.md)
        - [External measurements](needed-probes/external-measurements.md)
        - [Emulator comparison matrix](needed-probes/emulator-matrix.md)
        - [Online evidence and physical closure](needed-probes/evidence-closure.md)
        - [Recording a physical result](needed-probes/recording-results.md)
        - [Adversarial safety review](needed-probes/safety-review.md)

# Core subsystems

- [Variables and the VAT](variables-vat.md)
- [Floating-point engine](floating-point.md)
    - [Calculation engine](sub-calculation.md)
    - [Statistics](sub-statistics.md)
    - [Matrices and lists](sub-matrix-list.md)
    - [Solver and numerical methods](sub-solver-numeric.md)
- [Tokenizer and TI-BASIC tokens](tokenizer-basic.md)
  - [TI-BASIC execution](sub-tibasic.md)
    - [TI-BASIC programming patterns](sub-tibasic-programming.md)
      - [TI-BASIC examples and ASM interop](sub-tibasic-examples.md)
    - [TI-BASIC dynamic tracing](sub-tibasic-tracing.md)
    - [TI-BASIC `For(` parenthesis trap](sub-tibasic-for-paren.md)
- [Display and LCD](display-lcd.md)
    - [LCD controller and display bus](lcd-hardware.md)
    - [Graphing](sub-graphing.md)
    - [Table and Y= variables](sub-table-yvars.md)
    - [Equation display (MathPrint)](sub-equation-display.md)
        - [MathPrint live editor and settled drawing](sub-mathprint-editor.md)
        - [MathPrint validation and browser model](sub-mathprint-validation.md)
- [Keyboard and link port](keyboard-link.md)
    - [Keypad and ON-key hardware](keypad-on-hardware.md)
    - [Two-wire link port hardware](link-port-hardware.md)
    - [Link and data transfer](sub-link-transfer.md)
    - [USB ASIC and link assist](sub-usb-asic.md)

# Reference

- [bcall index](bcall-index.md)
- [2-byte token tables](token-tables.md)

# Project

- [Open questions and roadmap](open-questions.md)
