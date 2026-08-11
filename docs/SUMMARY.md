# Summary

[System overview](system-overview.md)

# Orientation

- [Subsystem map](subsystem-map.md)
- [Conventions & methodology](conventions.md)
- [Glossary](glossary.md)

# Architecture & memory

- [Memory map](memory-map.md)
- [Paging](paging.md)
- [The bcall mechanism](bcall-mechanism.md)
- [Interrupts (IM1)](interrupts.md)
    - [Clock, timers, and power](clock-timers-power.md)
- [Boot, contexts & errors](boot-contexts-errors.md)
- [Memory management](memory-management.md)
    - [Variables, archive & unarchive](sub-vat-archive.md)
    - [Apps, memory reset & settings](sub-apps-mem-settings.md)
- [Flash memory](flash-memory.md)
- [MD5 accelerator and boot API](md5-hardware.md)
- [Flash page map](flash-page-map.md)
- [RAM pages](ram-pages.md)

# Core subsystems

- [Variables & the VAT](variables-vat.md)
- [Floating-point engine](floating-point.md)
    - [Calculation engine](sub-calculation.md)
    - [Statistics](sub-statistics.md)
    - [Matrices & lists](sub-matrix-list.md)
    - [Solver & numerical methods](sub-solver-numeric.md)
- [Tokenizer & TI-BASIC](tokenizer-basic.md)
    - [TI-BASIC programs](sub-tibasic.md)
    - [TI-BASIC programming patterns](sub-tibasic-programming.md)
    - [TI-BASIC dynamic tracing](sub-tibasic-tracing.md)
    - [TI-BASIC `For(` paren trap](sub-tibasic-for-paren.md)
- [Display and LCD](display-lcd.md)
    - [LCD controller and display bus](lcd-hardware.md)
    - [Graphing](sub-graphing.md)
    - [Table & Y= variables](sub-table-yvars.md)
    - [Equation display (MathPrint)](sub-equation-display.md)
- [Keyboard and link port](keyboard-link.md)
    - [Keypad and ON-key hardware](keypad-on-hardware.md)
    - [Link / data transfer](sub-link-transfer.md)
    - [USB ASIC and link assist](sub-usb-asic.md)

# Reference

- [bcall index](bcall-index.md)
- [2-byte token tables](token-tables.md)

# Project

- [Open questions & roadmap](open-questions.md)
