from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from unicodedata import normalize


class RecordError(ValueError):
    def __init__(self, field: str, reason: str):
        super().__init__(f"{field}:{reason}")
        self.field = field
        self.reason = reason


def label(document: Mapping, key: str, *, max_chars: int) -> str:
    raw = document.get(key)
    if not isinstance(raw, str):
        raise RecordError(key, "TEXT_REQUIRED")
    value = normalize("NFKC", raw).strip()
    if not value or len(value) > max_chars:
        raise RecordError(key, "TEXT_LENGTH")
    if not all(ch.isprintable() for ch in value):
        raise RecordError(key, "TEXT_CONTROL")
    return value


def magnitude(document: Mapping, key: str, lower: float, upper: float, *, whole: bool) -> int | float:
    raw = document.get(key)
    if isinstance(raw, bool) or raw is None:
        raise RecordError(key, "NUMBER_REQUIRED")
    try:
        number = float(raw)
    except (ValueError, TypeError, OverflowError) as error:
        raise RecordError(key, "NUMBER_INVALID") from error
    if not isfinite(number):
        raise RecordError(key, "NUMBER_NONFINITE")
    if number < lower or number > upper:
        raise RecordError(key, "NUMBER_RANGE")
    if whole:
        if not number.is_integer():
            raise RecordError(key, "INTEGER_REQUIRED")
        return int(number)
    return number


@dataclass(frozen=True, slots=True)
class ValveReading:
    valve: str
    zone: str
    day: int
    minute: int
    sequence: int
    flow_l: float
    pressure_kpa: float
    active: int

    @classmethod
    def parse(cls, document: Mapping) -> "ValveReading":
        if not isinstance(document, Mapping):
            raise RecordError("document", "OBJECT_REQUIRED")
        valve = label(document, 'valve', max_chars=34)
        zone = label(document, 'zone', max_chars=24)
        day = magnitude(document, 'day', 1, 365, whole=True)
        minute = magnitude(document, 'minute', 0, 1439, whole=True)
        sequence = magnitude(document, 'sequence', 1, 100000, whole=True)
        flow_l = magnitude(document, 'flow_l', 0, 8000, whole=False)
        pressure_kpa = magnitude(document, 'pressure_kpa', 0, 800, whole=False)
        active = magnitude(document, 'active', 0, 1, whole=True)
        return cls(
            valve=valve,
            zone=zone,
            day=day,
            minute=minute,
            sequence=sequence,
            flow_l=flow_l,
            pressure_kpa=pressure_kpa,
            active=active,
        )

    def evidence(self) -> dict:
        return {
            'valve': self.valve,
            'zone': self.zone,
            'day': self.day,
            'minute': self.minute,
            'sequence': self.sequence,
            'flow_l': self.flow_l,
            'pressure_kpa': self.pressure_kpa,
            'active': self.active,
        }


@dataclass(frozen=True, slots=True)
class Rejection:
    row: int
    source: str
    field: str
    reason: str

    def evidence(self) -> dict:
        return {"row": self.row, "source": self.source, "field": self.field, "reason": self.reason}
