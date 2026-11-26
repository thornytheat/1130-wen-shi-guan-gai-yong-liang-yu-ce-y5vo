import pytest

from greenhouse.moisture_band.service import inspect, ResidualBand, quantile, learn_uncertainty, dryness_index, eligibility
from greenhouse.moisture_band.contracts import WaterCandidate, RecordError


@pytest.fixture
def document():
    return {'zone': 'ZONE', 'need_l': 0.0, 'distance': 0.0, 'gap': 0, 'moisture': 0.0, 'asset_limit': 0.0}


def test_contract_round_trip(document):
    entry = WaterCandidate.parse(document)
    assert entry.evidence() == document
    assert WaterCandidate.parse(entry.evidence()) == entry


def test_record_identity_normalizes_fullwidth(document):
    document['zone'] = "　ＡＢＣ-１２　"
    entry = WaterCandidate.parse(document)
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
    document['need_l'] = True
    with pytest.raises(RecordError, match="NUMBER_REQUIRED"):
        WaterCandidate.parse(document)


def test_nonfinite_measure_isolated(document):
    corrupted = {**document, 'need_l': "nan"}
    batch = inspect([document, corrupted, document])
    assert [item.evidence() for item in batch.records] == [document, document]
    assert batch.rejected[0].row == 2
    assert batch.evidence()["reason_counts"]["NUMBER_NONFINITE"] == 1


def test_invalid_range_reserves_no_entry(document):
    document['need_l'] = 0 - 1
    intake = inspect([document])
    assert intake.accepted_count == 0
    assert intake.rejected[0].field == 'need_l'
    assert intake.rejected[0].reason == "NUMBER_RANGE"


def test_empty_validation_keeps_uncertainty_unknown(document):
    # TRAP-43
    band = learn_uncertainty([float("nan")])
    assert band.support == 0 and band.mae is None
    assert eligibility(WaterCandidate.parse(document),band)["state"] == "校准样本不足"


def test_shift_distance_disables_high_demand(document):
    # TRAP-44
    record = WaterCandidate.parse({**document,"distance":9,"asset_limit":500,"need_l":250})
    result = eligibility(record,learn_uncertainty([-80,-2,5,70]))
    assert result["lower"] < result["upper"]
    assert result["state"] == "需水工况未见"


def test_sigmoid_dryness_safe_for_extreme_candidates():
    # TRAP-31
    assert dryness_index(-800) == 0
    assert dryness_index(800) == 1
    assert round(dryness_index(-.4)+dryness_index(.4),12)==1


def test_residual_band_interpolates_quantile():
    result = learn_uncertainty([-20,-10,10,20],alpha=.25)
    assert result.low == -12.5 and result.high == 12.5
