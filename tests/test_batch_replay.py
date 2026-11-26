from greenhouse.pipeline import run


def test_seed_reconciles_pumps_and_holds_unobserved_zones():
    result=run(31)
    assert len(result["stages"])==6
    assert 0 < result["metrics"]["已配水（升）"] <= 3100
    reasons={item["reason"] for item in result["rows"]}
    assert {"根区探头不足","遥测断档","需水工况未见"} <= reasons
    assert result["metrics"]["待查计量单"]>=2


def test_budget_refresh_keeps_held_stages_fixed():
    restricted, expanded=run(1),run(85)
    assert restricted["metrics"]["已配水（升）"] < expanded["metrics"]["已配水（升）"]
    assert restricted["audit_id"] != expanded["audit_id"]
    assert [x["records"] for x in restricted["stages"][:4]] == [x["records"] for x in expanded["stages"][:4]]
