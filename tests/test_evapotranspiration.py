import pytest

from greenhouse.evapotranspiration.service import inspect, WaterModel, spread, solve, train, forecast, predict, rule_reference
from greenhouse.evapotranspiration.contracts import DailyTarget, RecordError


@pytest.fixture
def document():
    return {'zone': 'ZONE', 'crop': 'CROP', 'day': 1, 'water_l': 0.0, 'reference_l': 0.0, 'solar': 0.0}


def test_contract_round_trip(document):
    entry = DailyTarget.parse(document)
    assert entry.evidence() == document
    assert DailyTarget.parse(entry.evidence()) == entry


def test_record_identity_normalizes_fullwidth(document):
    document['zone'] = "　ＡＢＣ-１２　"
    entry = DailyTarget.parse(document)
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
    document['day'] = True
    with pytest.raises(RecordError, match="NUMBER_REQUIRED"):
        DailyTarget.parse(document)


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


def test_stable_variance_on_near_constant_history():
    # TRAP-32
    assert spread([1e12+.1,1e12+.2,1e12+.3])[1] == pytest.approx(.08165,rel=.004)
    assert spread([18.0]*4) == (18,.001)


def test_ridge_is_finite_when_columns_identical():
    dataset = [((x,x,1),x*10+10) for x in range(8)]
    fitted = train(dataset)
    assert fitted.coefficients[0] == pytest.approx(fitted.coefficients[1])
    estimate = forecast(fitted,(5,5,1))
    assert abs(estimate-60) < abs(rule_reference(dataset)-60)


def test_one_zone_prediction_is_independent_of_batch_population():
    # TRAP-53
    fitted = train([((x,2*x),30+5*x) for x in range(10)])
    point = (6,12)
    assert predict(fitted,[point])[0] == predict(fitted,[(30,30),point])[1]


def test_fit_rejects_undersized_dataset():
    with pytest.raises(ValueError,match="NEEDS_HISTORY"):
        train([((1,2),20)])
