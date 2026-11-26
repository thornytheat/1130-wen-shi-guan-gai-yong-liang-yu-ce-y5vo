from collections import defaultdict
from dataclasses import dataclass
from math import fsum
from .contracts import ValveReading


@dataclass(frozen=True)
class ValveWindow:
    zone: str
    intervals: tuple
    delivered: float
    gap_minutes: int


def accepted_samples(readings, day, start, stop):
    if not 0 <= start < stop <= 1440:
        raise ValueError("SHIFT_WINDOW_INVALID")
    index = defaultdict(set)
    for row in readings:
        if row.day == day and start <= row.minute < stop:
            index[row.zone, row.valve, row.minute].add(row)
    valid = []
    excluded = []
    for key, candidates in sorted(index.items()):
        revision = max(x.sequence for x in candidates)
        eligible = [x for x in candidates if x.sequence == revision]
        if len(eligible) != 1:
            excluded.append({"zone":key[0],"valve":key[1],"minute":key[2],"reason":"SEQUENCE_COLLISION"})
        elif eligible[0].active and not 25 <= eligible[0].pressure_kpa <= 340:
            excluded.append({"zone":key[0],"valve":key[1],"minute":key[2],"reason":"PRESSURE_INTERLOCK"})
        else:
            valid.append(eligible[0])
    return valid, excluded


def vent_windows(readings, start, stop, max_gap=25):
    grouped = defaultdict(list)
    for row in readings:
        grouped[row.zone, row.valve].append(row)
    windows = []
    for (zone, valve), rows in sorted(grouped.items()):
        clocks = sorted(rows, key=lambda x: x.minute)
        gaps = max(0, clocks[0].minute - start) + max(0, stop - clocks[-1].minute - max_gap)
        used = []
        intervals = []
        for before, after in zip(clocks, clocks[1:]):
            elapsed = after.minute - before.minute
            if elapsed > max_gap:
                gaps += elapsed
                continue
            if before.active and after.active:
                litres = elapsed * (before.flow_l + after.flow_l) / 2
                intervals.append({"valve":valve,"from_min":before.minute,"to_min":after.minute,"litres":round(litres,2)})
                used.append(litres)
        windows.append(ValveWindow(zone, tuple(intervals), fsum(used), gaps))
    return windows
