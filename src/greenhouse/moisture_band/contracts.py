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
class WaterCandidate:
    zone: str
    need_l: float
    distance: float
    gap: int
    moisture: float
    asset_limit: float

    @classmethod
    def parse(cls, document: Mapping) -> "WaterCandidate":
        if not isinstance(document, Mapping):
            raise RecordError("document", "OBJECT_REQUIRED")
        zone = label(document, 'zone', max_chars=28)
        need_l = magnitude(document, 'need_l', 0, 80000, whole=False)
        distance = magnitude(document, 'distance', 0, 10000, whole=False)
        gap = magnitude(document, 'gap', 0, 1440, whole=True)
        moisture = magnitude(document, 'moisture', 0, 1, whole=False)
        asset_limit = magnitude(document, 'asset_limit', 0, 100000, whole=False)
        return cls(
            zone=zone,
            need_l=need_l,
            distance=distance,
            gap=gap,
            moisture=moisture,
            asset_limit=asset_limit,
        )

    def evidence(self) -> dict:
        return {
            'zone': self.zone,
            'need_l': self.need_l,
            'distance': self.distance,
            'gap': self.gap,
            'moisture': self.moisture,
            'asset_limit': self.asset_limit,
        }


@dataclass(frozen=True, slots=True)
class Rejection:
    row: int
    source: str
    field: str
    reason: str

    def evidence(self) -> dict:
        return {"row": self.row, "source": self.source, "field": self.field, "reason": self.reason}
