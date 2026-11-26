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
class CropObservation:
    probe: str
    zone: str
    day: int
    published_day: int
    depth_cm: int
    moisture: float
    solar: float
    temp_c: float
    humidity: float
    litres: float
    crop: str

    @classmethod
    def parse(cls, document: Mapping) -> "CropObservation":
        if not isinstance(document, Mapping):
            raise RecordError("document", "OBJECT_REQUIRED")
        probe = label(document, 'probe', max_chars=28)
        zone = label(document, 'zone', max_chars=32)
        day = magnitude(document, 'day', 1, 365, whole=True)
        published_day = magnitude(document, 'published_day', 1, 365, whole=True)
        depth_cm = magnitude(document, 'depth_cm', 5, 150, whole=True)
        moisture = magnitude(document, 'moisture', 0, 1, whole=False)
        solar = magnitude(document, 'solar', 0, 90, whole=False)
        temp_c = magnitude(document, 'temp_c', -10, 75, whole=False)
        humidity = magnitude(document, 'humidity', 0, 1, whole=False)
        litres = magnitude(document, 'litres', 0, 100000, whole=False)
        crop = label(document, 'crop', max_chars=28)
        return cls(
            probe=probe,
            zone=zone,
            day=day,
            published_day=published_day,
            depth_cm=depth_cm,
            moisture=moisture,
            solar=solar,
            temp_c=temp_c,
            humidity=humidity,
            litres=litres,
            crop=crop,
        )

    def evidence(self) -> dict:
        return {
            'probe': self.probe,
            'zone': self.zone,
            'day': self.day,
            'published_day': self.published_day,
            'depth_cm': self.depth_cm,
            'moisture': self.moisture,
            'solar': self.solar,
            'temp_c': self.temp_c,
            'humidity': self.humidity,
            'litres': self.litres,
            'crop': self.crop,
        }


@dataclass(frozen=True, slots=True)
class Rejection:
    row: int
    source: str
    field: str
    reason: str

    def evidence(self) -> dict:
        return {"row": self.row, "source": self.source, "field": self.field, "reason": self.reason}
