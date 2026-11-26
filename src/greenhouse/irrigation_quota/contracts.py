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
class IrrigationOrder:
    zone: str
    pump: str
    crop: str
    state: str
    upper: float
    lower: float
    urgency: float
    per_min: int
    window: int

    @classmethod
    def parse(cls, document: Mapping) -> "IrrigationOrder":
        if not isinstance(document, Mapping):
            raise RecordError("document", "OBJECT_REQUIRED")
        zone = label(document, 'zone', max_chars=28)
        pump = label(document, 'pump', max_chars=20)
        crop = label(document, 'crop', max_chars=26)
        state = label(document, 'state', max_chars=30)
        upper = magnitude(document, 'upper', 0, 100000, whole=False)
        lower = magnitude(document, 'lower', 0, 100000, whole=False)
        urgency = magnitude(document, 'urgency', 0, 1, whole=False)
        per_min = magnitude(document, 'per_min', 1, 1000, whole=True)
        window = magnitude(document, 'window', 0, 480, whole=True)
        return cls(
            zone=zone,
            pump=pump,
            crop=crop,
            state=state,
            upper=upper,
            lower=lower,
            urgency=urgency,
            per_min=per_min,
            window=window,
        )

    def evidence(self) -> dict:
        return {
            'zone': self.zone,
            'pump': self.pump,
            'crop': self.crop,
            'state': self.state,
            'upper': self.upper,
            'lower': self.lower,
            'urgency': self.urgency,
            'per_min': self.per_min,
            'window': self.window,
        }


@dataclass(frozen=True, slots=True)
class Rejection:
    row: int
    source: str
    field: str
    reason: str

    def evidence(self) -> dict:
        return {"row": self.row, "source": self.source, "field": self.field, "reason": self.reason}
