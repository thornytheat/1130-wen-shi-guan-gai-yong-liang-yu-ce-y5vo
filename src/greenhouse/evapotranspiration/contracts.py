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
class DailyTarget:
    zone: str
    crop: str
    day: int
    water_l: float
    reference_l: float
    solar: float

    @classmethod
    def parse(cls, document: Mapping) -> "DailyTarget":
        if not isinstance(document, Mapping):
            raise RecordError("document", "OBJECT_REQUIRED")
        zone = label(document, 'zone', max_chars=36)
        crop = label(document, 'crop', max_chars=28)
        day = magnitude(document, 'day', 1, 365, whole=True)
        water_l = magnitude(document, 'water_l', 0, 100000, whole=False)
        reference_l = magnitude(document, 'reference_l', 0, 100000, whole=False)
        solar = magnitude(document, 'solar', 0, 90, whole=False)
        return cls(
            zone=zone,
            crop=crop,
            day=day,
            water_l=water_l,
            reference_l=reference_l,
            solar=solar,
        )

    def evidence(self) -> dict:
        return {
            'zone': self.zone,
            'crop': self.crop,
            'day': self.day,
            'water_l': self.water_l,
            'reference_l': self.reference_l,
            'solar': self.solar,
        }


@dataclass(frozen=True, slots=True)
class Rejection:
    row: int
    source: str
    field: str
    reason: str

    def evidence(self) -> dict:
        return {"row": self.row, "source": self.source, "field": self.field, "reason": self.reason}
