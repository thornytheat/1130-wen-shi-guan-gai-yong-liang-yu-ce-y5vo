import pytest

from greenhouse.irrigation_quota.service import inspect, target_minimum, fair_share, distribute
from greenhouse.irrigation_quota.contracts import IrrigationOrder, RecordError


@pytest.fixture
def document():
    return {'zone': 'ZONE', 'pump': 'PUMP', 'crop': 'CROP', 'state': 'STATE', 'upper': 0.0, 'lower': 0.0, 'urgency': 0.0, 'per_min': 1, 'window': 0}


def test_contract_round_trip(document):
    entry = IrrigationOrder.parse(document)
    assert entry.evidence() == document
    assert IrrigationOrder.parse(entry.evidence()) == entry


def test_record_identity_normalizes_fullwidth(document):
    document['zone'] = "　ＡＢＣ-１２　"
    entry = IrrigationOrder.parse(document)
    assert getattr(entry, 'zone') == "ABC-12"


def test_missing_identity_isolated(document):
    missing = dict(document)
    del missing['zone']
    intake = inspect([missing, document])
    assert intake.read_count == 2
    assert intake.accepted_count == 1
    assert intake.rejection_counts() == {"TEXT_REQUIRED": 1}
    assert intake.rejected[0].row == 1
    assert intake.rejected[0].field == 'zone'


def test_boolean_is_not_magnitude(document):
    document['upper'] = True
    with pytest.raises(RecordError, match="NUMBER_REQUIRED"):
        IrrigationOrder.parse(document)


def test_nonfinite_measure_isolated(document):
    corrupted = {**document, 'upper': "nan"}
    batch = inspect([document, corrupted, document])
    assert [item.evidence() for item in batch.records] == [document, document]
    assert batch.rejected[0].row == 2
    assert batch.evidence()["reason_counts"]["NUMBER_NONFINITE"] == 1


def test_invalid_range_reserves_no_entry(document):
    document['upper'] = 0 - 1
    intake = inspect([document])
    assert intake.accepted_count == 0
    assert intake.rejected[0].field == 'upper'
    assert intake.rejected[0].reason == "NUMBER_RANGE"


from dataclasses import replace


def test_largest_remainder_conserves_shift_litres():
    # TRAP-24
    assert fair_share(8,{"B":5,"A":5,"C":5})=={"B":3,"A":3,"C":2}
    assert fair_share(0,{"A":0}) == {"A":0}


def test_pump_and_valve_window_limits_both_hold(document):
    row = IrrigationOrder.parse({**document,"state":"允许配水","upper":400,"lower":180,"per_min":10,"window":16})
    another = replace(row,zone="Z-3",urgency=.9)
    approved, pumps = distribute([row,another],900,{row.pump:235})
    assert pumps[row.pump] == 235
    assert max(x["amount_l"] for x in approved) <= 160
    assert sum(x["amount_l"] for x in approved) == 235


def test_quota_is_independent_of_upload_order(document):
    first = IrrigationOrder.parse({**document,"state":"允许配水","upper":40,"lower":10,"per_min":10,"window":4})
    second = replace(first,zone="Z-9")
    assert distribute([first,second],30,{first.pump:50}) == distribute([second,first],30,{first.pump:50})
