# Summary

[Overview](00-system-overview.md)

# Orientation

- [Subsystem map](10-subsystem-map.md)
- [Conventions & methodology](conventions.md)
- [Glossary](glossary.md)

# Architecture & memory

- [Memory map](01-memory-map.md)
- [Paging](02-paging.md)
- [The bcall mechanism](03-bcall-mechanism.md)
- [Interrupts (IM1)](04-interrupts.md)
- [Boot, contexts & errors](11-boot-contexts-errors.md)
- [Memory management](12-memory-management.md)
    - [Variables, archive & unarchive](sub-vat-archive.md)
    - [Apps, memory reset & settings](sub-apps-mem-settings.md)
- [Flash page map](13-flash-page-map.md)
- [RAM pages](14-ram-pages.md)

# Core subsystems

- [Variables & the VAT](05-variables-vat.md)
- [Floating-point engine](06-floating-point.md)
    - [Calculation engine](sub-calculation.md)
    - [Statistics](sub-statistics.md)
    - [Matrices & lists](sub-matrix-list.md)
    - [Solver & numerical methods](sub-solver-numeric.md)
- [Tokenizer & TI-BASIC](07-tokenizer-basic.md)
    - [TI-BASIC programs](sub-tibasic.md)
    - [TI-BASIC programming patterns](sub-tibasic-programming.md)
    - [TI-BASIC dynamic tracing](sub-tibasic-tracing.md)
    - [TI-BASIC `For(` paren trap](sub-tibasic-for-paren.md)
- [Display & LCD](08-display-lcd.md)
    - [Graphing](sub-graphing.md)
    - [Table & Y= variables](sub-table-yvars.md)
    - [Equation display (MathPrint)](sub-equation-display.md)
- [Keyboard & link port](09-keyboard-link.md)
    - [Link / data transfer](sub-link-transfer.md)
    - [USB ASIC & link assist](sub-usb-asic.md)

# Reference

- [bcall index](bcall-index.md)
- [2-byte token tables](token-tables.md)

# Project

- [Open questions & roadmap](99-open-questions.md)
