from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, order=True, slots=True)
class Window:
    opened: int
    closed: int

    def __post_init__(self):
        if self.opened < 0 or self.opened >= self.closed or self.closed > 1440:
            raise ValueError("IRRIGATION_TIME_WINDOW_INVALID")

    def overlapping(self, other):
        left = max(self.opened, other.opened)
        right = min(self.closed, other.closed)
        return Window(left, right) if left < right else None


@dataclass(frozen=True, slots=True)
class PumpRun:
    zone: str
    pump: str
    span: Window
    litres: int
    flow: int

    def public(self):
        return {
            "棚区": self.zone,
            "泵组": self.pump,
            "开始分钟": self.span.opened,
            "结束分钟": self.span.closed,
            "实际可供升": self.litres,
            "额定每分升": self.flow,
        }


def subtract(spans, removed):
    remaining=[]
    for window in spans:
        intersection=window.overlapping(removed)
        if intersection is None:
            remaining.append(window)
            continue
        if window.opened < intersection.opened:
            remaining.append(Window(window.opened, intersection.opened))
        if intersection.closed < window.closed:
            remaining.append(Window(intersection.closed, window.closed))
    return sorted(remaining)


def pump_availability(configured, breakdowns):
    available={}
    for pump, raw in sorted(configured.items()):
        windows=sorted(Window(*item) for item in raw)
        merged=[]
        for interval in windows:
            if merged and merged[-1].closed >= interval.opened:
                tail=merged.pop()
                merged.append(Window(tail.opened,max(tail.closed,interval.closed)))
            else:
                merged.append(interval)
        for outage in sorted(Window(*item) for item in breakdowns.get(pump,())):
            merged=subtract(merged,outage)
        available[pump]=merged
    return available


def feasible_pumping(spans, *, pump, zone, volume, flow, minutes_remaining):
    if flow < 1 or minutes_remaining < 0 or volume < 0:
        raise ValueError("SCHEDULER_ALLOCATION_INVALID")
    used=[]
    still_due=volume
    for span in spans:
        if not still_due or minutes_remaining <= 0:
            break
        duration=min(span.closed-span.opened, minutes_remaining, (still_due+flow-1)//flow)
        delivered=min(still_due, flow*duration)
        used.append(PumpRun(zone,pump,Window(span.opened,span.opened+duration),delivered,flow))
        still_due-=delivered
        minutes_remaining-=duration
    return used,still_due


def schedule(orders, approvals, pump_windows, outages):
    available=pump_availability(pump_windows,outages)
    selected={row.zone:row for row in orders}
    requested=[record for record in approvals if record["amount_l"]>0]
    requests=sorted(requested,key=lambda row:(-selected[row["zone"]].urgency,row["zone"]))
    recorded=[]
    issues=[]
    for row in requests:
        order=selected[row["zone"]]
        amount=row["amount_l"]
        timeline=available.get(order.pump,[])
        windows, gap=feasible_pumping(timeline,pump=order.pump,zone=order.zone,volume=amount,flow=order.per_min,minutes_remaining=order.window)
        if gap:
            issues.append({"棚区":order.zone,"未排入（升）":gap,"状态":"泵窗口不足"})
        for segment in windows:
            timeline=subtract(timeline,segment.span)
            recorded.append(segment)
        available[order.pump]=timeline
    return sorted(recorded,key=lambda line:(line.pump,line.span,line.zone)),issues


def schedule_coverage(runs, tentative):
    usage=defaultdict(int)
    windows_by_pump=defaultdict(list)
    for run in runs:
        usage[run.zone]+=run.litres
        windows_by_pump[run.pump].append(run.span)
    for spans in windows_by_pump.values():
        ordered=sorted(spans)
        if any(a.closed > b.opened for a,b in zip(ordered,ordered[1:])):
            raise ValueError("PUMP_OVERLAPPING_ALLOCATION")
    evidence=[]
    for request in tentative:
        planned=request["amount_l"]
        scheduled=usage.get(request["zone"],0)
        if scheduled > planned:
            raise ValueError("PUMP_EXCEEDS_AUTHORIZATION")
        evidence.append({"zone":request["zone"],"authorized_l":planned,"scheduled_l":scheduled,
                         "unassigned_l":planned-scheduled})
    return evidence
