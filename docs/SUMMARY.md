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
        - [Shell loaders and writeback](sub-shell-loaders.md)
    - [Resident scratch RAM](sub-resident-scratch.md)
    - [Apps, memory reset, and settings](sub-apps-mem-settings.md)
        - [Flash Apps as resident runtimes](sub-flash-app-runtime.md)
- [Flash memory](flash-memory.md)
- [MD5 accelerator and boot API](md5-hardware.md)
- [Flash page map](flash-page-map.md)
- [RAM pages](ram-pages.md)
- [Physical hardware probes](hardware-probes.md)

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
    - [TI-BASIC dynamic tracing](sub-tibasic-tracing.md)
    - [TI-BASIC `For(` parenthesis trap](sub-tibasic-for-paren.md)
- [Display and LCD](display-lcd.md)
    - [LCD controller and display bus](lcd-hardware.md)
    - [Graphing](sub-graphing.md)
    - [Table and Y= variables](sub-table-yvars.md)
    - [Equation display (MathPrint)](sub-equation-display.md)
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
