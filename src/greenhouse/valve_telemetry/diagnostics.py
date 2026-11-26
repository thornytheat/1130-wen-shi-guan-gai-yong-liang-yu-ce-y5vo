from collections import defaultdict
from dataclasses import dataclass
from math import fsum
from statistics import median


@dataclass(frozen=True, slots=True)
class ValveDiagnosis:
    zone: str
    valve: str
    active_samples: int
    idle_samples: int
    residual_pa: float | None
    idle_flow_l: float
    peak_flow_l: float
    reason: str

    def public(self):
        return {
            "棚区": self.zone,
            "阀位": self.valve,
            "供水点": self.active_samples,
            "静置点": self.idle_samples,
            "压力散布（千帕）": self.residual_pa,
            "静置流量（升每分）": self.idle_flow_l,
            "峰流量（升每分）": self.peak_flow_l,
            "检点状态": self.reason,
        }


def diagnose(readings, *, max_idle_flow=4.5, pressure_deviation=35):
    traces=defaultdict(list)
    for sample in readings:
        traces[sample.zone,sample.valve].append(sample)
    results=[]
    for (zone,valve), readings in sorted(traces.items()):
        open_points=[line for line in readings if line.active]
        static=[line for line in readings if not line.active]
        idle=median(line.flow_l for line in static) if static else 0.0
        peak=max((sample.flow_l for sample in readings),default=0.0)
        central=median(line.pressure_kpa for line in open_points) if open_points else None
        variation=median(abs(line.pressure_kpa-central) for line in open_points) if central is not None else None
        if len(open_points)<2:
            reason="工作读数不足"
        elif len(static)>=2 and idle>max_idle_flow:
            reason="关闭后仍有流量"
        elif variation is not None and variation>pressure_deviation:
            reason="压力波动较大"
        elif not static:
            reason="无停水对照"
        else:
            reason="通过"
        results.append(ValveDiagnosis(zone,valve,len(open_points),len(static),variation,idle,peak,reason))
    return results


def combine_deficits(draft, schedule, diagnoses):
    without_assignment={row["zone"] for row in schedule if row["unassigned_l"]>0}
    defect_zones={row.zone for row in diagnoses if row.reason!="通过"}
    priorities={"遥测断档":10,"根区探头不足":9,"需水工况未见":8,"根区过湿":7,"校准样本不足":6,"最小需水额度不足":5}
    warnings=[]
    for proposal in draft:
        status=proposal["reason"]
        zone=proposal["zone"]
        if status not in priorities and zone not in without_assignment and zone not in defect_zones:
            continue
        warnings.append({
            "棚区":zone,
            "原处置":status,
            "含未排水量":zone in without_assignment,
            "遥测需复核":zone in defect_zones,
            "优先级":priorities.get(status,0)+(zone in without_assignment)+(zone in defect_zones),
        })
    return sorted(warnings,key=lambda warning:(-warning["优先级"],warning["棚区"]))


def compare_pump_timing(windows, runs):
    historical=defaultdict(list)
    future=defaultdict(list)
    for window in windows:
        historical[window.zone].append(window.delivered)
    for allocation in runs:
        future[allocation.zone].append(allocation.litres)
    by_zone={}
    for zone in sorted(historical.keys() | future.keys()):
        delivered=fsum(historical.get(zone,()))
        plan=sum(future.get(zone,()))
        by_zone[zone]={"棚区":zone,"已计量（升）":round(delivered,2),"待排执行（升）":plan,
                       "合计预期（升）":round(delivered+plan,2)}
    return list(by_zone.values())
