import pytest

from greenhouse.rootzone_history.service import inspect, RootVector, calibrated_roots, distance
from greenhouse.rootzone_history.contracts import CropObservation, RecordError


@pytest.fixture
def document():
    return {'probe': 'PROBE', 'zone': 'ZONE', 'day': 1, 'published_day': 1, 'depth_cm': 5, 'moisture': 0.0, 'solar': 0.0, 'temp_c': -10.0, 'humidity': 0.0, 'litres': 0.0, 'crop': 'CROP'}


def test_contract_round_trip(document):
    entry = CropObservation.parse(document)
    assert entry.evidence() == document
    assert CropObservation.parse(entry.evidence()) == entry


def test_record_identity_normalizes_fullwidth(document):
    document['probe'] = "　ＡＢＣ-１２　"
    entry = CropObservation.parse(document)
    assert getattr(entry, 'probe') == "ABC-12"


def test_missing_identity_isolated(document):
    missing = dict(document)
    del missing['probe']
    intake = inspect([missing, document])
    assert intake.read_count == 2
    assert intake.accepted_count == 1
    assert intake.rejection_counts() == {"TEXT_REQUIRED": 1}
    assert intake.rejected[0].row == 1
    assert intake.rejected[0].field == 'probe'


def test_boolean_is_not_magnitude(document):
    document['day'] = True
    with pytest.raises(RecordError, match="NUMBER_REQUIRED"):
        CropObservation.parse(document)


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


def probes(document):
    return [CropObservation.parse({**document,"probe":f"P-{x}","depth_cm":v,"moisture":h})
            for x,v,h in [(1,20,.31),(2,30,.43),(3,100,.97)]]


def test_visible_dates_prevent_retrospective_leakage(document):
    # TRAP-42
    records = probes(document)
    late = [replace(x, day=2, published_day=5) for x in records]
    visible, errors = calibrated_roots(records + late,asof=4,live=False)
    assert not errors and [row.day for row in visible] == [1]


def test_deep_probe_does_not_feed_crop_zone(document):
    observed, dropped = calibrated_roots(probes(document),asof=1,live=True)
    assert not dropped
    assert observed[0].moisture == .37 and observed[0].probe_count == 2


def test_duplicate_conflict_can_invalidate_root_zone(document):
    original = probes(document)[:2]
    result, issues = calibrated_roots(original+[replace(original[0],moisture=.1)],asof=2,live=False)
    assert not result and issues[0]["reason"] == "ROOTZONE_COVERAGE"
