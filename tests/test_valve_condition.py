from dataclasses import replace

from greenhouse.valve_telemetry.analysis import ValveWindow
from greenhouse.valve_telemetry.contracts import ValveReading
from greenhouse.valve_telemetry.diagnostics import combine_deficits, compare_pump_timing, diagnose
from greenhouse.irrigation_quota.scheduling import PumpRun, Window
from greenhouse.pipeline import run


def pulse(minute, *, valve="RY-4", zone="棚-09", opened=True, pressure=115, flow=12):
    return ValveReading.parse(dict(valve=valve,zone=zone,day=1,minute=minute,
                                   sequence=minute+1,flow_l=flow,pressure_kpa=pressure,active=int(opened)))


def test_idle_flow_isolation_uses_two_samples_and_median():
    inputs=[pulse(5),pulse(10),pulse(20,opened=False,flow=7),pulse(25,opened=False,flow=8)]
    row,=diagnose(inputs)
    assert row.reason=="关闭后仍有流量"
    assert row.idle_flow_l==7.5
    assert row.peak_flow_l==12
    assert row.public()["静置点"]==2
    assert row.public()["压力散布（千帕）"]==0
    insufficient,=diagnose(inputs[:3])
    assert insufficient.reason=="通过"


def test_no_static_baseline_and_single_open_emit_distinct_reasons():
    open_sweeps=[pulse(1),pulse(3)]
    one,zero=diagnose(open_sweeps+[pulse(1,zone="棚-10",opened=False,flow=0)])
    assert one.reason == "无停水对照"
    assert zero.reason == "工作读数不足"
    assert zero.residual_pa is None


def test_pressure_comparison_remains_per_valve():
    dataset=[pulse(1,pressure=140),pulse(3,pressure=60),pulse(5,opened=False,flow=1),
             pulse(1,valve="RY-5"),pulse(3,valve="RY-5"),pulse(5,valve="RY-5",opened=False,flow=1)]
    unstable,okay=diagnose(dataset)
    assert unstable.reason == "压力波动较大"
    assert unstable.residual_pa == 40
    assert okay.reason == "通过"
    assert okay.residual_pa == 0
    assert diagnose(list(reversed(dataset)))==[unstable,okay]


def test_combined_followups_rank_holds_then_missing_slot_and_diagnostics():
    planned=[{"zone":"棚-01","reason":"遥测断档"},{"zone":"棚-09","reason":"已批准"},
             {"zone":"棚-12","reason":"已批准"},{"zone":"棚-10","reason":"根区过湿"}]
    possible=[{"zone":"棚-12","unassigned_l":4},{"zone":"棚-09","unassigned_l":0}]
    diagnosis=diagnose([pulse(1),pulse(4)])
    results=combine_deficits(planned,possible,diagnosis)
    assert [row["棚区"] for row in results]==["棚-01","棚-10","棚-09","棚-12"]
    assert results[2]["遥测需复核"] and not results[2]["含未排水量"]
    assert results[3]["含未排水量"] and not results[3]["遥测需复核"]


def test_pump_timing_rollup_supports_old_and_future_only_zones():
    recorded=[ValveWindow("A",(),123.25,3),ValveWindow("A",(),62.79,0),ValveWindow("C",(),5,0)]
    upcoming=[PumpRun("A","泵-1",Window(5,10),15,4),PumpRun("B","泵-2",Window(10,13),45,15)]
    output=compare_pump_timing(recorded,upcoming)
    assert output==[{"棚区":"A","已计量（升）":186.04,"待排执行（升）":15,"合计预期（升）":201.04},
                    {"棚区":"B","已计量（升）":0,"待排执行（升）":45,"合计预期（升）":45},
                    {"棚区":"C","已计量（升）":5,"待排执行（升）":0,"合计预期（升）":5}]


def test_live_dispatch_includes_actionable_telemetry_and_water_timing():
    batch=run(40)
    telemetry=batch["stages"][0]["records"]
    trouble=[line for line in telemetry if line.get("检点状态")=="关闭后仍有流量"]
    assert {line["棚区"] for line in trouble} == {"棚-04","棚-07"}
    assert any(row["原处置"]=="遥测断档" for row in batch["followups"])
    totals=batch["stages"][5]["records"]
    metrics=[row for row in totals if "合计预期（升）" in row]
    assert sum(row["待排执行（升）"] for row in metrics)==sum(row["实际可供升"] for row in batch["scheduled"])
