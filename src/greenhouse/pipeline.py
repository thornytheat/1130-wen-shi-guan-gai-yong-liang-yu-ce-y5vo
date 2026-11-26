from datetime import time
from hashlib import sha256
from json import loads
from pathlib import Path
from collections import defaultdict

from .valve_telemetry import service as valves
from .rootzone_history import service as soil
from .evapotranspiration import service as model
from .moisture_band import service as safety
from .irrigation_quota import service as quota
from .watering_ledger import service as ledger

BASE = Path(__file__).resolve().parents[2]


def stage(title,summary,records):
    return dict(title=title,summary=summary,records=records)


def documents(filename):
    payload=(BASE/"sample_data"/filename).read_bytes()
    return [loads(line) for line in payload.splitlines() if line.strip()], sha256(payload).hexdigest()


def load_policy():
    return loads((BASE/"configs"/"spring_shift.json").read_text(encoding="utf-8"))


def model_by_crop(previous, current, controls, penalty):
    calibration_day=controls["day"]-6
    all_earlier=[row for row in previous if row.day < calibration_day and row.published_day < calibration_day]
    portfolios={}
    for crop in sorted({row.crop for row in current}):
        fit=[(row.features(),row.water) for row in all_earlier if row.crop==crop]
        fitted=model.train(fit, ridge=penalty)
        errors=[row.water-model.forecast(fitted,row.features()) for row in previous if row.crop==crop and row.day>=calibration_day]
        portfolios[crop]=(fitted,safety.learn_uncertainty(errors),model.rule_reference(fit))
    return portfolios


def run(capacity: int | None = None) -> dict:
    config=load_policy()
    dispatch_budget=config["budget"] if capacity is None else capacity
    if not 1 <= dispatch_budget <= 100:
        raise ValueError("CAPACITY_OUT_OF_RANGE")
    (raw_meter,raw_soil,raw_receipts), hashes=zip(*(documents(name) for name in ("valve_pulse_log.ndjson","root_probe_daily.ndjson","water_shift_slips.ndjson")),strict=True)
    pulses=valves.inspect(raw_meter)
    observations=soil.inspect(raw_soil)
    statements=ledger.inspect(raw_receipts)
    live, quality_issues=soil.calibrated_roots(observations.records,asof=config["day"],live=True)
    past, _=soil.calibrated_roots(observations.records,asof=config["day"],live=False)
    accepted, valve_issues=valves.accepted_samples(pulses.records,config["day"],config["start"],config["stop"])
    windows=valves.vent_windows(accepted,config["start"],config["stop"])
    windows_by_zone=defaultdict(list)
    for span in windows:
        windows_by_zone[span.zone].append(span)
    penalty, sensitivity = model.benchmark_choice(past, config["replay"])
    trials = model.backtest(past, boundary=config["day"], days=5, penalty=penalty)
    diagnostic = valves.diagnose(accepted)
    packs=model_by_crop(past,live,config,penalty)
    measured=[]
    planning=[]
    fitted_evidence=[]
    for site in live:
        fitted,interval,reference = packs[site.crop]
        total=model.forecast(fitted,site.features())
        spans=windows_by_zone[site.zone]
        supplied=sum(span.delivered for span in spans)
        residual=max(0,total-supplied)
        gap=max((span.gap_minutes for span in spans),default=1440)
        distance=soil.distance(site.features(),fitted.features)
        checking=safety.WaterCandidate.parse(dict(zone=site.zone,need_l=residual,distance=distance,gap=gap,moisture=site.moisture,asset_limit=config["valve_max_l"]))
        result=safety.eligibility(checking,interval)
        fitted_evidence.append(dict(棚区=site.zone,作物=site.crop,根区含水=round(site.moisture,3),总需水=round(total,1),
                                    已供水=round(supplied,1),历史中位值=round(reference,1),当期断档=gap,拟合样本=fitted.trained))
        measured.append(result)
        pump="北井" if int(site.zone.rsplit("-",1)[1])%2==0 else "西渠"
        planning.append(dict(result,pump=pump,crop=site.crop,per_min=config["flow_l_min"],window=config["window"]))
    orders=quota.inspect(planning)
    drafted, pump_usage=quota.distribute(orders.records,dispatch_budget*100,config["pump_caps"])
    _, overflow=ledger.totals_over_pumps(drafted,config["pump_caps"])
    if overflow:
        raise RuntimeError("PUMP_LIMIT_EXCEEDED")
    for issue in quality_issues:
        drafted.append(dict(zone=issue["zone"],pump="—",crop="—",amount_l=0,min_l=0,max_l=0,reason="根区探头不足"))
    timetable, unscheduled = quota.schedule(orders.records, drafted, config["pump_windows"], config["breakdowns"])
    coverage = quota.schedule_coverage(timetable, drafted)
    followups = valves.combine_deficits(drafted, coverage, diagnostic)
    evidence=ledger.audit_watering(statements.records,drafted)
    accepted_count=sum(item["state"]=="可归档" for item in evidence)
    handover=ledger.plan_outcome(coverage,evidence)
    shift_summary=ledger.shift_summary(handover)
    summary=[dict(作物=name,校准样本=parts[1].support,误差下界=round(parts[1].low,2),误差上界=round(parts[1].high,2)) for name,parts in packs.items()]
    initials=[dict(棚区=span.zone,已供升=round(span.delivered,2),断档分钟=span.gap_minutes,有效片段=len(span.intervals)) for span in windows]
    return {
        "metrics":{"已配水（升）":sum(row["amount_l"] for row in drafted),"有效棚区":len(live),"配水泵组":len(pump_usage),"待查计量单":len(evidence)-accepted_count},
        "columns":{"zone":"棚区","pump":"泵组","crop":"作物","amount_l":"批准供水（升）","min_l":"保底（升）","max_l":"需水上界（升）","reason":"处置"},
        "rows":drafted, "scheduled": [line.public() for line in timetable], "followups": followups,
        "replay": [trial.public() for trial in trials], "shift_summary": shift_summary, "series":[dict(label=row["zone"],value=row["amount_l"]) for row in drafted],
        "stages":[stage("阀门遥测",f"有效点 {len(accepted)}，质量告警 {len(valve_issues)+len(pulses.rejected)}",initials+valve_issues+[row.public() for row in diagnostic]),
                  stage("根区水分",f"当天 {len(live)} 个棚区具备双探头，历史 {len(past)} 条有效聚合",quality_issues+[{"zone":row.zone,"moisture":row.moisture,"probes":row.probe_count} for row in live]),
                  stage("蒸腾回归",f"按 {len(packs)} 类作物拟合",fitted_evidence+model.summarize(trials)+sensitivity),
                  stage("偏差检验",f"校准估计与遥测缺测联锁复核 {len(measured)} 区",measured+summary),
                  stage("分区拨水",f"水源总额度 {dispatch_budget*100} 升，使用 {sum(pump_usage.values())} 升",drafted + [row.public() for row in timetable] + unscheduled),
                  stage("农事账目",f"累计表和授权对账通过 {accepted_count} 张",evidence + valves.compare_pump_timing(windows, timetable) + [row.evidence() for row in handover])],
        "audit_id":ledger.ledger_fingerprint(hashes,{**config,"capacity":dispatch_budget}),
    }
