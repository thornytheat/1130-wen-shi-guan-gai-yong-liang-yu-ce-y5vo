import pytest

from greenhouse.watering_ledger.service import inspect, audit_watering, ledger_fingerprint, totals_over_pumps
from greenhouse.watering_ledger.contracts import WaterSlip, RecordError


@pytest.fixture
def document():
    return {'ticket': 'TICKET', 'zone': 'ZONE', 'pump': 'PUMP', 'opening_l': 0.0, 'closing_l': 0.0, 'logged_min': 0, 'revision': 1}


def test_contract_round_trip(document):
    entry = WaterSlip.parse(document)
    assert entry.evidence() == document
    assert WaterSlip.parse(entry.evidence()) == entry


def test_record_identity_normalizes_fullwidth(document):
    document['ticket'] = "　ＡＢＣ-１２　"
    entry = WaterSlip.parse(document)
    assert getattr(entry, 'ticket') == "ABC-12"


def test_missing_identity_isolated(document):
    missing = dict(document)
    del missing['ticket']
    intake = inspect([missing, document])
    assert intake.read_count == 2
    assert intake.accepted_count == 1
    assert intake.rejection_counts() == {"TEXT_REQUIRED": 1}
    assert intake.rejected[0].row == 1
    assert intake.rejected[0].field == 'ticket'


def test_boolean_is_not_magnitude(document):
    document['opening_l'] = True
    with pytest.raises(RecordError, match="NUMBER_REQUIRED"):
        WaterSlip.parse(document)


def test_nonfinite_measure_isolated(document):
    corrupted = {**document, 'opening_l': "nan"}
    batch = inspect([document, corrupted, document])
    assert [item.evidence() for item in batch.records] == [document, document]
    assert batch.rejected[0].row == 2
    assert batch.evidence()["reason_counts"]["NUMBER_NONFINITE"] == 1


def test_invalid_range_reserves_no_entry(document):
    document['opening_l'] = 0 - 1
    intake = inspect([document])
    assert intake.accepted_count == 0
    assert intake.rejected[0].field == 'opening_l'
    assert intake.rejected[0].reason == "NUMBER_RANGE"


from dataclasses import replace


def test_stale_meter_revision_never_replaces_latest(document):
    # TRAP-26
    first = WaterSlip.parse({**document,"closing_l":5})
    fresh = replace(first,revision=2,closing_l=9)
    result = audit_watering([fresh,first],[{"zone":first.zone,"pump":first.pump,"amount_l":30}])
    assert len(result)==1 and result[0]["litres"]==9
    assert result[0]["state"]=="可归档"


def test_meter_rollback_is_detected(document):
    line = WaterSlip.parse({**document,"opening_l":10,"closing_l":6})
    assert audit_watering([line],[])[0]["state"]=="累计水表倒退"


def test_upstream_settings_invalidate_fingerprint():
    assert ledger_fingerprint(["hash"],{"pump":200}) != ledger_fingerprint(["hash"],{"pump":201})


def test_pump_zero_capacity_is_enforced():
    total, overflow = totals_over_pumps([{"pump":"LP2","amount_l":20}],{"LP2":0})
    assert total == overflow == {"LP2":20}
