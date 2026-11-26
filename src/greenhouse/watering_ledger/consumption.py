from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from math import fsum


@dataclass(frozen=True, slots=True)
class ForecastBalance:
    zone: str
    authorized_l: int
    scheduled_l: int
    unassigned_l: int
    metered_l: Decimal
    uncertain_l: Decimal
    discrepancy: str

    def evidence(self):
        return {
            "棚区": self.zone,
            "授权量（升）": self.authorized_l,
            "排水量（升）": self.scheduled_l,
            "未排量（升）": self.unassigned_l,
            "登记合计（升）": float(self.metered_l),
            "其中待查（升）": float(self.uncertain_l),
            "次班交接": self.discrepancy,
        }


def plan_outcome(schedule_checks, slips):
    active = {}
    for row in schedule_checks:
        zone=row["zone"]
        if zone in active:
            raise ValueError("REPEATED_ZONE_RECONCILIATION")
        if row["authorized_l"] != row["scheduled_l"] + row["unassigned_l"]:
            raise ValueError("SCHEDULE_CONSERVATION_VIOLATED")
        active[zone]=row
    approved=defaultdict(list)
    suspect=defaultdict(list)
    for receipt in slips:
        amount=Decimal(str(receipt["litres"]))
        location=receipt["zone"]
        if receipt["state"]=="可归档":
            approved[location].append(amount)
        else:
            suspect[location].append(amount)
    consolidated=[]
    for zone in sorted(active.keys() | approved.keys() | suspect.keys()):
        expected=active.get(zone,{"authorized_l":0,"scheduled_l":0,"unassigned_l":0})
        unassigned=expected["unassigned_l"]
        booked=sum(approved[zone],Decimal(0))
        quarantined=sum(suspect[zone],Decimal(0))
        if suspect[zone]:
            state="核查计量单"
        elif booked > expected["scheduled_l"]:
            state="已报量超可执行水量"
        elif unassigned:
            state="未排部分顺延"
        elif booked < expected["scheduled_l"]:
            state="等待现场计量回报"
        else:
            state="已交接"
        consolidated.append(ForecastBalance(zone,expected["authorized_l"],expected["scheduled_l"],unassigned,
                                             booked+quarantined,quarantined,state))
    return consolidated


def shift_summary(reconciled):
    authorized=sum(row.authorized_l for row in reconciled)
    scheduled=sum(row.scheduled_l for row in reconciled)
    unassigned=sum(row.unassigned_l for row in reconciled)
    if scheduled+unassigned != authorized:
        raise ValueError("SHIFT_CONSERVATION_VIOLATED")
    return {"授权棚区":sum(row.authorized_l>0 for row in reconciled),"已排升":scheduled,"未排升":unassigned,
            "待查棚区":sum(row.discrepancy!="已交接" for row in reconciled),
            "授权可排比例":round(scheduled/authorized,4) if authorized else None,
            "表差登记总升":round(fsum(float(row.metered_l) for row in reconciled),3)}
