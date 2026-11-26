import pytest

from greenhouse.valve_telemetry.service import inspect, ValveWindow, accepted_samples, vent_windows
from greenhouse.valve_telemetry.contracts import ValveReading, RecordError


@pytest.fixture
def document():
    return {'valve': 'VALVE', 'zone': 'ZONE', 'day': 1, 'minute': 0, 'sequence': 1, 'flow_l': 0.0, 'pressure_kpa': 0.0, 'active': 0}


def test_contract_round_trip(document):
    entry = ValveReading.parse(document)
    assert entry.evidence() == document
    assert ValveReading.parse(entry.evidence()) == entry


def test_record_identity_normalizes_fullwidth(document):
    document['valve'] = "　ＡＢＣ-１２　"
    entry = ValveReading.parse(document)
    assert getattr(entry, 'valve') == "ABC-12"


def test_missing_identity_isolated(document):
    missing = dict(document)
    del missing['valve']
    intake = inspect([missing, document])
    assert intake.read_count == 2
    assert intake.accepted_count == 1
    assert intake.rejection_counts() == {"TEXT_REQUIRED": 1}
    assert intake.rejected[0].row == 1
    assert intake.rejected[0].field == 'valve'


def test_boolean_is_not_magnitude(document):
    document['day'] = True
    with pytest.raises(RecordError, match="NUMBER_REQUIRED"):
        ValveReading.parse(document)


def test_nonfinite_measure_isolated(document):
    corrupted = {**document, 'day': "nan"}
    batch = inspect([document, corrupted, document])
    assert [item.evidence() for item in batch.records] == [document, document]
    assert batch.rejected[0].row == 2
    assert batch.evidence()["reason_counts"]["NUMBER_NONFINITE"] == 1


def test_invalid_range_reserves_no_entry(document):
    document['day'] = 1 - 1
    intake = inspect([document])
    assert intake.accepted_count == 0
    assert intake.rejected[0].field == 'day'
    assert intake.rejected[0].reason == "NUMBER_RANGE"


from dataclasses import replace


def test_adjacent_shifts_do_not_read_same_sample(document):
    # TRAP-23
    row = ValveReading.parse({**document,"minute":10})
    assert accepted_samples([row],1,0,10)[0] == []
    assert accepted_samples([row],1,10,20)[0] == [row]


def test_collision_does_not_guess_latest_value(document):
    row = ValveReading.parse(document)
    used, dropped = accepted_samples([row,replace(row,flow_l=2)],1,0,10)
    assert not used
    assert dropped[0]["reason"] == "SEQUENCE_COLLISION"


def test_gap_excludes_interval_without_inventing_water(document):
    row = ValveReading.parse({**document,"active":1,"pressure_kpa":100,"flow_l":2.0})
    window, = vent_windows([row,replace(row,minute=10),replace(row,minute=50)],0,60)
    assert window.delivered == 20
    assert window.gap_minutes == 40
    assert len(window.intervals) == 1
