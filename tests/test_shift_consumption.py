from decimal import Decimal

import pytest

from greenhouse.pipeline import run
from greenhouse.watering_ledger.consumption import plan_outcome, shift_summary


def plan(zone, approved, scheduled, missing):
    return {"zone":zone,"authorized_l":approved,"scheduled_l":scheduled,"unassigned_l":missing}


def receipt(zone, charge, state="可归档"):
    return {"zone":zone,"litres":charge,"state":state}


def test_uncertain_receipts_are_reported_separately_from_booked_volume():
    rows=plan_outcome([plan("A",99,69,30)], [receipt("A",31.02),receipt("A",7.011,"累计水表倒退"),receipt("A",16.1)])
    first,=rows
    assert first.metered_l == Decimal("54.131")
    assert first.uncertain_l == Decimal("7.011")
    assert first.discrepancy == "核查计量单"
    assert first.evidence()["其中待查（升）"] == 7.011
    assert first.evidence()["未排量（升）"] == 30


def test_awaiting_report_unscheduled_and_over_assignment_are_distinct():
    shift=[plan("A",33,33,0),plan("B",50,20,30),plan("C",10,10,0),plan("D",5,5,0)]
    statements=[receipt("A",50),receipt("D",5),receipt("E",11,"泵位或分区不符")]
    details=plan_outcome(shift, statements)
    assert [row.discrepancy for row in details] == ["已报量超可执行水量","未排部分顺延","等待现场计量回报","已交接","核查计量单"]
    res=shift_summary(details)
    assert res["授权棚区"]==4
    assert res["已排升"]==68
    assert res["未排升"]==30
    assert res["授权可排比例"]==round(68/98,4)
    assert res["待查棚区"]==4
    assert res["表差登记总升"]==66


def test_schedule_integrity_missing_and_repeated_plan_are_distinct():
    with pytest.raises(ValueError,match="CONSERVATION"):
        plan_outcome([plan("A",10,5,3)],[])
    row=plan("A",10,5,5)
    with pytest.raises(ValueError,match="REPEATED_ZONE"):
        plan_outcome([row,row],[])
    assert shift_summary([])["授权可排比例"] is None
    assert shift_summary([])["表差登记总升"] == 0.0


@pytest.mark.parametrize("cap",[1,17,50,100])
def test_shift_conservation_survives_current_pump_downtime(cap):
    result=run(cap)
    summary=result["shift_summary"]
    assert summary["授权棚区"] == sum(row["amount_l"]>0 for row in result["rows"])
    assert summary["已排升"] + summary["未排升"] == result["metrics"]["已配水（升）"]
    assert 0 <= summary["授权可排比例"] <= 1
    assert summary["已排升"] == sum(item["实际可供升"] for item in result["scheduled"])
    assert summary["待查棚区"] >= 1


def test_unauthorized_receipt_enters_handover_with_zero_schedule():
    orphan, = plan_outcome([], [receipt("边缘棚", 2.75, "泵位或分区不符")])
    assert orphan.authorized_l == 0
    assert orphan.scheduled_l == 0
    assert orphan.uncertain_l == Decimal("2.75")
    assert orphan.discrepancy == "核查计量单"
    assert shift_summary([orphan])["待查棚区"] == 1
