from collections import defaultdict
from dataclasses import dataclass
from math import fsum
from statistics import median

from .analysis import forecast, train


@dataclass(frozen=True, slots=True)
class CropTrial:
    crop: str
    day: int
    zone: str
    estimate: float
    actual: float
    benchmark: float
    prefix_support: int

    def public(self):
        return {
            "作物":self.crop,
            "回放日":self.day,
            "棚区":self.zone,
            "估计（升）":round(self.estimate,2),
            "实际（升）":round(self.actual,2),
            "基线（升）":round(self.benchmark,2),
            "前缀训练量":self.prefix_support,
        }


def backtest(previous, *, boundary, days, penalty):
    if days <= 0 or boundary <= 0:
        raise ValueError("BACKTEST_WINDOW_INVALID")
    available=defaultdict(list)
    for sample in previous:
        if sample.day < boundary and sample.published_day < boundary:
            available[sample.crop].append(sample)
    trials=[]
    for crop, history in sorted(available.items()):
        historical=sorted(history,key=lambda line:(line.day,line.zone))

        by_day=defaultdict(list)
        for record in historical:
            by_day[record.day].append(record)
        for day, fixtures in sorted(by_day.items()):
            fitting=[row for row in historical if row.day < day and row.published_day < day]
            if day >= boundary-days and len(fitting) >= 4:
                training=[(row.features(),row.water) for row in fitting]
                estimator=train(training,ridge=penalty)
                benchmark=median(row.water for row in fitting if row.day>=day-7) if any(row.day>=day-7 for row in fitting) else median(row.water for row in fitting)
                trials.extend(CropTrial(crop,day,row.zone,forecast(estimator,row.features()),row.water,benchmark,len(training)) for row in fixtures)
    return trials


def summarize(trials):
    groups=defaultdict(list)
    for row in trials:
        groups[row.crop].append(row)
    output=[]
    for crop, fields in sorted(groups.items()):
        count=len(fields)
        estimated=fsum(abs(row.actual-row.estimate) for row in fields)
        benchmark=fsum(abs(row.actual-row.benchmark) for row in fields)
        signed=fsum(row.actual-row.estimate for row in fields)
        denominator=fsum(row.actual for row in fields)
        output.append({"作物":crop,"回放行":count,"平均误差（升）":round(estimated/count,2),
                       "基线误差（升）":round(benchmark/count,2),"欠供偏差（升）":round(signed/count,2),
                       "总量相对误差":round(estimated/denominator,4) if denominator else None,
                       "留出棚区":len({row.zone for row in fields})})
    return output


def benchmark_choice(history, spec):
    results=[]
    fractions=[]
    for penalty in spec["candidates"]:
        trials=backtest(history,boundary=spec["cutoff"],days=spec["days"],penalty=penalty)
        if not trials:
            continue
        total=fsum(abs(row.actual-row.estimate) for row in trials)
        fractions.append((total/len(trials),penalty))
        results.append({"岭回归惩罚":penalty,"验证平均绝对误差":round(total/len(trials),2),"回放量":len(trials)})
    if not fractions:
        return spec["default"],results
    return min(fractions)[1],results
