from dataclasses import dataclass
from math import fsum, exp, isfinite
from .contracts import WaterCandidate


@dataclass(frozen=True)
class ResidualBand:
    low: float
    high: float
    support: int
    mae: float | None


def quantile(points, probability):
    edge = probability * (len(points)-1)
    left = int(edge)
    right = min(left+1,len(points)-1)
    return points[left] + (edge-left)*(points[right]-points[left])


def learn_uncertainty(errors, alpha=.10):
    if not 0 < alpha < 0.5:
        raise ValueError("ALPHA_OUTSIDE_SUPPORT")
    usable = sorted(value for value in errors if isfinite(value))
    if not usable:
        return ResidualBand(0.0,0.0,0,None)
    return ResidualBand(quantile(usable,alpha),quantile(usable,1-alpha),len(usable),fsum(abs(x) for x in usable)/len(usable))


def dryness_index(value):
    if value >= 0:
        return 1 / (1 + exp(-value))
    exponent = exp(value)
    return exponent / (1 + exponent)


def eligibility(candidate: WaterCandidate, bands: ResidualBand):
    lower = min(candidate.asset_limit, max(0.0,candidate.need_l + bands.low))
    upper = min(candidate.asset_limit, max(lower,candidate.need_l + bands.high))
    if candidate.gap > 40:
        flag = "遥测断档"
    elif bands.support < 3:
        flag = "校准样本不足"
    elif candidate.distance > 6.5:
        flag = "需水工况未见"
    elif candidate.moisture > 0.68:
        flag = "根区过湿"
    else:
        flag = "允许配水"
    return {"zone":candidate.zone,"state":flag,"lower":round(lower,1),"upper":round(upper,1),
            "urgency":dryness_index(27*(0.40-candidate.moisture)),"distance":round(candidate.distance,2)}
