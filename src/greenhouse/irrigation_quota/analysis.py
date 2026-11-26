from collections import defaultdict
from fractions import Fraction
from .contracts import IrrigationOrder


def target_minimum(order):
    return min(int(order.lower),int(order.upper),order.per_min*order.window)


def fair_share(remaining, demands):
    required = sum(demands.values())
    if not required:
        return dict.fromkeys(demands,0)
    lot = min(required,max(0,remaining))
    fractions = {zone:Fraction(value*lot,required) for zone,value in demands.items()}
    shares = {zone:int(quota) for zone,quota in fractions.items()}
    rest = lot-sum(shares.values())
    for zone in sorted(fractions, key=lambda zone:(-(fractions[zone]-shares[zone]),zone))[:rest]:
        shares[zone] += 1
    return shares


def distribute(orders, shift_l, pump_caps):
    if shift_l < 0 or any(cap < 0 for cap in pump_caps.values()):
        raise ValueError("PUMP_CAPACITY_RANGE")
    if len({row.zone for row in orders}) != len(orders):
        raise ValueError("ZONE_ORDER_DUPLICATED")
    contenders = [item for item in orders if item.state == "允许配水" and item.pump in pump_caps]
    pump_used = defaultdict(int)
    active = {item.zone: item for item in contenders}
    guaranteed = {item.zone:target_minimum(item) for item in contenders}
    for pump, cap in sorted(pump_caps.items()):
        chosen = {zone:need for zone,need in guaranteed.items() if active[zone].pump == pump}
        guaranteed.update(fair_share(cap,chosen))
    assigned = fair_share(shift_l,guaranteed)
    for zone, volume in assigned.items():
        pump_used[active[zone].pump] += volume
    remaining = shift_l - sum(assigned.values())
    for order in sorted(contenders, key=lambda x:(-x.urgency,x.zone)):
        headroom = min(int(order.upper),order.per_min*order.window)-assigned[order.zone]
        additional = min(headroom,remaining,pump_caps[order.pump]-pump_used[order.pump])
        assigned[order.zone] += additional
        remaining -= additional
        pump_used[order.pump] += additional
    evidence = []
    for item in sorted(orders,key=lambda x:x.zone):
        amount = assigned.get(item.zone,0)
        if item.state != "允许配水":
            reason = item.state
        elif item.pump not in pump_caps:
            reason = "泵位未配置"
        elif amount < target_minimum(item):
            reason = "最小需水额度不足"
        elif amount:
            reason = "已批准"
        else:
            reason = "无额外用水"
        evidence.append({"zone":item.zone,"pump":item.pump,"crop":item.crop,"amount_l":amount,
                         "min_l":target_minimum(item),"max_l":round(item.upper,1),"reason":reason})
    return evidence, dict(pump_used)
