from dataclasses import replace
from statistics import mean

import pytest

from greenhouse.evapotranspiration.forecast_audit import CropTrial, backtest, benchmark_choice, summarize
from greenhouse.rootzone_history.analysis import RootVector


def growing_days(n=28, delayed=0):
    return [RootVector(f"西-{zone}",day,crop,.28+.012*(day%5),day*1.5,18+zone,.52,
                       60+45*day+20*zone, 2,day+delayed)
            for day in range(1,n+1) for zone,crop in [(1,"黄瓜"),(3,"黄瓜"),(4,"番茄")]]


def test_rolling_origin_does_not_train_on_labels_publishedthat_day():
    rows=growing_days()
    late=replace(rows[7],zone="西-晚录",day=1,published_day=23,water=100000)
    clean=backtest(rows,boundary=28,days=8,penalty=1)
    with_late=backtest(rows+[late],boundary=28,days=8,penalty=1)
    early_clean=[row for row in clean if row.day<=23]
    late_after=[row for row in with_late if row.day>23 and row.crop==late.crop]
    assert [row for row in with_late if row.day<=23]==early_clean
    assert late_after and all(row.prefix_support > next(r.prefix_support for r in clean if (r.day,r.zone)==(row.day,row.zone)) for row in late_after)


def test_forward_evidence_counts_distinct_holdout_zones_and_error_totals():
    observed=backtest(growing_days(),boundary=28,days=6,penalty=.3)
    assert len(observed)==18
    assert {line.day for line in observed}==set(range(22,28))
    metrics={line["作物"]:line for line in summarize(observed)}
    assert metrics["黄瓜"]["留出棚区"]==2
    assert metrics["番茄"]["留出棚区"]==1
    assert metrics["黄瓜"]["回放行"]==12
    assert metrics["黄瓜"]["平均误差（升）"] < metrics["黄瓜"]["基线误差（升）"]
    cucumber=[line for line in observed if line.crop=="黄瓜"]
    assert round(mean(line.actual-line.estimate for line in cucumber),2)==metrics["黄瓜"]["欠供偏差（升）"]
    for line in cucumber:
        result=line.public()
        assert result["前缀训练量"]==2*(line.day-1)
        assert result["回放日"]==line.day


def test_zero_volume_group_has_undefined_relative_error():
    predictions=[CropTrial("叶菜",10,"A",3,0,0,12),CropTrial("叶菜",11,"B",1,0,0,12)]
    line,=summarize(predictions)
    assert line["基线误差（升）"]==0
    assert line["平均误差（升）"]==2
    assert line["欠供偏差（升）"]==-2
    assert line["总量相对误差"] is None


def test_penalty_tuning_uses_folds_before_policy_boundary():
    policy={"candidates":[.2,1,10],"cutoff":23,"days":6,"default":1}
    records=growing_days()
    ideal, curve=benchmark_choice(records,policy)
    future=replace(records[-1],zone="未知",day=30,published_day=30,water=100000)
    assert benchmark_choice(records+[future],policy)==(ideal,curve)
    assert ideal==.2
    assert [line["回放量"] for line in curve]==[18,18,18]
    assert all(line["岭回归惩罚"] in policy["candidates"] for line in curve)


def test_insufficient_training_is_an_explicit_empty_trial_set():
    assert backtest(growing_days(2),boundary=3,days=2,penalty=1)==[]
    assert benchmark_choice(growing_days(2),{"candidates":[1],"cutoff":3,"days":2,"default":4})==(4,[])
    with pytest.raises(ValueError,match="INVALID"):
        backtest([],boundary=2,days=0,penalty=1)



def test_report_label_published_after_tuning_cutoff_is_unusable():
    baseline=growing_days()
    control=next(row for row in baseline if row.zone=="西-1" and row.day==21)
    shifted=replace(control,published_day=29,water=57000)
    altered=[shifted if row==control else row for row in baseline]
    results=backtest(altered,boundary=28,days=9,penalty=.25)
    assert all((row.day,row.zone)!=(21,"西-1") for row in results)
    assert len(results)==26
    planned={"candidates":[0.1,1.0],"cutoff":28,"days":9,"default":1.0}
    _, scores=benchmark_choice(altered,planned)
    assert all(row["回放量"]==26 for row in scores)


def test_validation_order_is_invariant_when_input_timestamps_arrive_out_of_order():
    stable=backtest(growing_days(),boundary=27,days=7,penalty=2.4)
    reversed_rows=backtest(list(reversed(growing_days())),boundary=27,days=7,penalty=2.4)
    assert stable==reversed_rows
    assert summarize(stable)==summarize(reversed_rows)
    baseline=sorted({(row.crop,row.day) for row in stable})
    assert len(baseline)==14
    assert baseline[0]==("番茄",20)
