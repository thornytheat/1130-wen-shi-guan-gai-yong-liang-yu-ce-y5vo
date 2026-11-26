from collections import defaultdict
from dataclasses import dataclass
from math import fsum, sqrt
from statistics import median
from .contracts import CropObservation


@dataclass(frozen=True)
class RootVector:
    zone: str
    day: int
    crop: str
    moisture: float
    solar: float
    temp: float
    humidity: float
    water: float
    probe_count: int
    published_day: int

    def features(self):
        return (self.moisture, self.solar, self.temp, 1 - self.humidity)


def calibrated_roots(observations, *, asof: int, live: bool):
    visible = defaultdict(list)
    for item in observations:
        in_window = item.day == asof if live else item.day < asof
        if in_window and item.published_day <= asof and (live or item.published_day < asof):
            visible[item.zone,item.day].append(item)
    aggregated = []
    rejected = []
    for (zone, day), inputs in sorted(visible.items()):
        by_probe = defaultdict(set)
        for item in inputs:
            by_probe[item.probe].add(item)
        stable = [next(iter(group)) for group in by_probe.values() if len(group) == 1]
        anchor = median(item.depth_cm for item in stable) if stable else 0
        comparable = [item for item in stable if abs(item.depth_cm - anchor) <= 15]
        if len(comparable) < 2 or len({item.crop for item in comparable}) != 1:
            rejected.append({"zone":zone,"day":day,"reason":"ROOTZONE_COVERAGE"})
            continue
        count = len(comparable)
        aggregated.append(RootVector(zone,day,comparable[0].crop,median(i.moisture for i in comparable),
              fsum(i.solar for i in comparable)/count,fsum(i.temp_c for i in comparable)/count,
              fsum(i.humidity for i in comparable)/count,median(i.litres for i in comparable),count,max(i.published_day for i in comparable)))
    return aggregated, rejected


def distance(features, levels):
    squared = [(value-center)**2/(scale*scale) for value,(center,scale) in zip(features,levels,strict=True)]
    return sqrt(fsum(squared))
