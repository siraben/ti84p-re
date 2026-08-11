"""Decode TI-84 Plus ASIC bus-delay registers."""

from __future__ import annotations

from dataclasses import asdict, dataclass


TIMING_PORTS = frozenset({0x20, 0x29, 0x2A, 0x2B, 0x2C, 0x2E, 0x2F})


@dataclass(frozen=True)
class MemoryWaits:
    """One-T-state additions selected for each memory access class."""

    flash_opcode: int
    flash_read: int
    flash_write: int
    ram_opcode: int
    ram_read: int
    ram_write: int


class BusTiming:
    """Track speed-dependent LCD and memory wait-state registers."""

    def __init__(
        self,
        *,
        speed_mode: int = 0,
        port29: int = 0,
        port2a: int = 0,
        port2b: int = 0,
        port2c: int = 0,
        port2e: int = 0,
        port2f: int = 0,
    ) -> None:
        self.speed_mode = self._speed(speed_mode)
        self.delay_ports = [
            self._byte(port29),
            self._byte(port2a),
            self._byte(port2b),
            self._byte(port2c),
        ]
        self.port2e = self._byte(port2e)
        self.port2f = self._byte(port2f)

    @staticmethod
    def _byte(value: int) -> int:
        if not 0 <= value <= 0xFF:
            raise ValueError("register values must be bytes")
        return value

    @staticmethod
    def _speed(value: int) -> int:
        if not 0 <= value <= 3:
            raise ValueError("CPU speed mode must be between 0 and 3")
        return value

    @classmethod
    def ti84p_os(cls, speed_mode: int = 1) -> "BusTiming":
        """Return the register values written by the retail boot page."""

        return cls(
            speed_mode=speed_mode,
            port29=0x17,
            port2a=0x27,
            port2b=0x2F,
            port2c=0x3B,
            port2e=0x45,
            port2f=0x4B,
        )

    def write_port(self, port: int, value: int) -> bool:
        """Apply a timing-register write and return whether it was handled."""

        if port not in TIMING_PORTS:
            return False
        value = self._byte(value)
        if port == 0x20:
            self.speed_mode = value & 3
        elif 0x29 <= port <= 0x2C:
            self.delay_ports[port - 0x29] = value
        elif port == 0x2E:
            self.port2e = value
        else:
            self.port2f = value
        return True

    def active_delay_port(self, speed_mode: int | None = None) -> tuple[int, int]:
        """Return ``(port, value)`` selected by the CPU-speed mode."""

        mode = self.speed_mode if speed_mode is None else self._speed(speed_mode)
        return 0x29 + mode, self.delay_ports[mode]

    def lcd_access_wait(self, speed_mode: int | None = None) -> int:
        """Return the modeled T-states added to each LCD-port instruction."""

        _, value = self.active_delay_port(speed_mode)
        return value >> 2

    def memory_waits(self, speed_mode: int | None = None) -> MemoryWaits:
        """Return enabled one-T-state memory additions for one speed mode."""

        _, enable = self.active_delay_port(speed_mode)
        flash = bool(enable & 0x01)
        ram = bool(enable & 0x02)
        return MemoryWaits(
            flash_opcode=int(flash and bool(self.port2e & 0x01)),
            flash_read=int(flash and bool(self.port2e & 0x02)),
            flash_write=int(flash and bool(self.port2e & 0x04)),
            ram_opcode=int(ram and bool(self.port2e & 0x10)),
            ram_read=int(ram and bool(self.port2e & 0x20)),
            ram_write=int(ram and bool(self.port2e & 0x40)),
        )

    def port2f_field(self, speed_mode: int | None = None) -> int | None:
        """Return the speed-selected port-0x2F field, or ``None`` for mode 0."""

        mode = self.speed_mode if speed_mode is None else self._speed(speed_mode)
        if mode == 0:
            return None
        if mode == 1:
            return self.port2f & 0x03
        if mode == 2:
            return (self.port2f >> 2) & 0x07
        return (self.port2f >> 5) & 0x07

    def lcd_ready_hold(self, speed_mode: int | None = None) -> int:
        """Return modeled port-0x02 not-ready T-states after an LCD access."""

        field = self.port2f_field(speed_mode)
        return 0 if field is None else 48 + 64 * field

    def documented_mode3_divisor(self, speed_mode: int | None = None) -> int:
        """Return the public mode-3 programmable-timer divisor."""

        field = self.port2f_field(speed_mode)
        return 1 if field is None else field + 1

    def row(self, speed_mode: int) -> dict[str, object]:
        """Return one serializable speed-mode summary."""

        port, value = self.active_delay_port(speed_mode)
        return {
            "speed_mode": speed_mode,
            "delay_port": port,
            "delay_value": value,
            "lcd_access_wait": self.lcd_access_wait(speed_mode),
            "memory_waits": asdict(self.memory_waits(speed_mode)),
            "lcd_ready_hold": self.lcd_ready_hold(speed_mode),
            "documented_mode3_divisor": self.documented_mode3_divisor(speed_mode),
        }

    def rows(self) -> list[dict[str, object]]:
        """Return summaries for all four CPU-speed selector values."""

        return [self.row(mode) for mode in range(4)]
