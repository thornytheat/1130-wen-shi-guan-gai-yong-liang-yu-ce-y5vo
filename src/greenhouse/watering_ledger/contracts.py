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
class WaterSlip:
    ticket: str
    zone: str
    pump: str
    opening_l: float
    closing_l: float
    logged_min: int
    revision: int

    @classmethod
    def parse(cls, document: Mapping) -> "WaterSlip":
        if not isinstance(document, Mapping):
            raise RecordError("document", "OBJECT_REQUIRED")
        ticket = label(document, 'ticket', max_chars=40)
        zone = label(document, 'zone', max_chars=28)
        pump = label(document, 'pump', max_chars=28)
        opening_l = magnitude(document, 'opening_l', 0, 500000, whole=False)
        closing_l = magnitude(document, 'closing_l', 0, 500000, whole=False)
        logged_min = magnitude(document, 'logged_min', 0, 1439, whole=True)
        revision = magnitude(document, 'revision', 1, 10000, whole=True)
        return cls(
            ticket=ticket,
            zone=zone,
            pump=pump,
            opening_l=opening_l,
            closing_l=closing_l,
            logged_min=logged_min,
            revision=revision,
        )

    def evidence(self) -> dict:
        return {
            'ticket': self.ticket,
            'zone': self.zone,
            'pump': self.pump,
            'opening_l': self.opening_l,
            'closing_l': self.closing_l,
            'logged_min': self.logged_min,
            'revision': self.revision,
        }


@dataclass(frozen=True, slots=True)
class Rejection:
    row: int
    source: str
    field: str
    reason: str

    def evidence(self) -> dict:
        return {"row": self.row, "source": self.source, "field": self.field, "reason": self.reason}
