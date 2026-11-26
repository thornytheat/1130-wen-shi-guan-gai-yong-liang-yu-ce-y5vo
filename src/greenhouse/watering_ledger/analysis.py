from collections import defaultdict
from dataclasses import asdict
from hashlib import sha256
from json import dumps
from .contracts import WaterSlip


def audit_watering(slips, approvals, allowance=0.08):
    if not 0 <= allowance < 1:
        raise ValueError("TOLERANCE_RANGE")
    index = defaultdict(set)
    for slip in slips:
        index[slip.ticket].add(slip)
    plan = {line['zone']:line for line in approvals}
    report = []
    claimed = defaultdict(float)
    for key, variants in sorted(index.items()):
        highest = max(x.revision for x in variants)
        current = [x for x in variants if x.revision == highest]
        if len(current) > 1:
            report.append({"ticket":key,"zone":"—","litres":0,"state":"用水单重复冲突"})
            continue
        line = current[0]
        approved = plan.get(line.zone)
        litres = round(line.closing_l-line.opening_l,3)
        if litres < 0:
            state = "累计水表倒退"
        elif not approved or approved["pump"] != line.pump:
            state = "泵位或分区不符"
        elif approved["amount_l"] == 0 and litres:
            state = "未获配水授权"
        elif claimed[line.zone]+litres > approved["amount_l"]*(1+allowance):
            state = "超出授权需复核"
        else:
            state = "可归档"
            claimed[line.zone] += litres
        report.append({"ticket":line.ticket,"zone":line.zone,"litres":litres,"logged_min":line.logged_min,"state":state})
    return report


def ledger_fingerprint(inputs, config):
    payload = {"engine": "watering-v1", "readings":list(inputs), "policy":config}
    return sha256(dumps(payload,sort_keys=True,separators=(",",":"), ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def totals_over_pumps(assignments, capacity_by_pump):
    result = defaultdict(int)
    for entry in assignments:
        result[entry["pump"]] += entry["amount_l"]
    overflow = {pump:volume for pump,volume in result.items() if volume > capacity_by_pump.get(pump,0)}
    return dict(result),overflow
