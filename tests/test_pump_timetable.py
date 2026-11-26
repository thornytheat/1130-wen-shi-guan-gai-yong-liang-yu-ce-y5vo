from dataclasses import replace
from itertools import pairwise

import pytest

from greenhouse.irrigation_quota.contracts import IrrigationOrder
from greenhouse.irrigation_quota.scheduling import (
    PumpRun,
    Window,
    feasible_pumping,
    pump_availability,
    schedule,
    schedule_coverage,
    subtract,
)
from greenhouse.pipeline import run


def irrigation(zone, *, pump="南泵", flow=20, cap=7, urgency=.5):
    return IrrigationOrder.parse(dict(zone=zone, pump=pump, crop="西红柿", state="允许配水",
                                     upper=300, lower=100, urgency=urgency, per_min=flow, window=cap))


@pytest.mark.parametrize("opened,closed", [(-1,5),(19,19),(99,70),(70,1450)])
def test_invalid_pump_windows_refused(opened, closed):
    with pytest.raises(ValueError,match="WINDOW_INVALID"):
        Window(opened,closed)


def test_misaligned_outages_leave_half_open_available_ranges():
    outcomes = pump_availability({"南泵":[(10,30),(20,40),(51,55),(40,50)]},
                                 {"南泵":[(0,17),(22,26),(25,40),(49,53)]})
    assert outcomes=={"南泵":[Window(17,22),Window(40,49),Window(53,55)]}
    assert subtract(outcomes["南泵"],Window(22,40)) == outcomes["南泵"]
    whole = Window(10,20)
    assert whole.overlapping(Window(20,21)) is None
    assert whole.overlapping(Window(5,14)) == Window(10,14)


def test_ceiling_slot_cannot_deliver_more_than_request():
    runs, balance=feasible_pumping([Window(10,12),Window(18,26)],pump="泵-A",zone="棚-A",
                                   volume=57,flow=20,minutes_remaining=5)
    assert balance == 0
    assert [(row.span, row.litres) for row in runs] == [(Window(10,12),40),(Window(18,19),17)]
    assert sum(line.litres for line in runs) == 57
    assert runs[1].public()["额定每分升"] == 20
    assert runs[1].public()["实际可供升"] == 17


def test_zone_cap_applies_across_nonadjacent_windows():
    runs, pending = feasible_pumping([Window(10,12),Window(18,27)], pump="泵-B", zone="棚-A",
                                     volume=180,flow=20,minutes_remaining=4)
    assert pending==100
    assert sum(row.litres for row in runs)==80
    assert runs[-1].span==Window(18,20)
    assert sum(row.span.closed-row.span.opened for row in runs)==4


def test_pump_runs_use_disjoint_windows_and_urgency_breaks_ties():
    low=irrigation("Z-AA", urgency=.2)
    urgent=irrigation("Z-BB", urgency=.9)
    other=irrigation("Z-CC", pump="东泵", urgency=.4)
    options=[{"zone":row.zone,"amount_l":120} for row in (low,urgent,other)]
    available={"东泵":[(5,15)], "南泵":[(5,15)]}
    outages={"东泵":[], "南泵":[(8,10)]}
    result,warning=schedule([low,urgent,other], options,available,outages)
    assert [row.zone for row in result]==[other.zone,urgent.zone,urgent.zone,low.zone]
    assert warning==[{"棚区":"Z-AA","未排入（升）":80,"状态":"泵窗口不足"}]
    assert schedule([urgent,other,low],list(reversed(options)),available,outages)==(result,warning)
    coverage=schedule_coverage(result,options)
    assert coverage[0]=={"zone":"Z-AA","authorized_l":120,"scheduled_l":40,"unassigned_l":80}
    assert coverage[1]["scheduled_l"]==120


def test_unknown_pump_slot_reports_every_litre_unscheduled():
    order=irrigation("Z-01", pump="高位换水")
    approval = [{"zone":order.zone, "amount_l":21}]
    schedule_rows,warnings=schedule([order],approval,{"南泵":[(1,50)]},{})
    assert not schedule_rows
    assert warnings[0]["未排入（升）"]==21
    assert schedule_coverage(schedule_rows, approval)[0]["scheduled_l"]==0


def test_overlap_or_excess_caught_by_independent_coverage_checker():
    a=PumpRun("A","pump",Window(6,9),40,20)
    b=PumpRun("B","pump",Window(8,9),10,20)
    with pytest.raises(ValueError,match="OVERLAPPING"):
        schedule_coverage([a,b],[])
    with pytest.raises(ValueError,match="EXCEEDS_AUTHORIZATION"):
        schedule_coverage([a],[{"zone":"A","amount_l":39}])


@pytest.mark.parametrize("cap",[1,4,32,65,100])
def test_live_timetable_respects_pump_outage_and_budget(cap):
    snapshot=run(cap)
    entries=snapshot["scheduled"]
    available={"北井":((450,484),(495,560)),"西渠":((450,475),(507,520),(560,600))}
    assert sum(line["实际可供升"] for line in entries)<=cap*100
    for pump, windows in available.items():
        rows=sorted((row for row in entries if row["泵组"]==pump),key=lambda row:row["开始分钟"])
        assert all(any(begin<=row["开始分钟"]<row["结束分钟"]<=end for begin,end in windows) for row in rows)
        assert all(a["结束分钟"]<=b["开始分钟"] for a,b in pairwise(rows))
        assert all(row["实际可供升"]<=row["额定每分升"]*(row["结束分钟"]-row["开始分钟"]) for row in rows)
