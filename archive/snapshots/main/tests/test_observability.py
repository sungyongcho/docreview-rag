from app.observability.cost import est_cost_usd


def test_est_cost_usd():
    # gpt-4.1-mini: (0.40, 1.60) USD / 1M
    # 1M input + 1M output = 0.40 + 1.60 = 2.0
    assert est_cost_usd("gpt-4.1-mini", 1_000_000, 1_000_000) == 2.0
    assert est_cost_usd("gpt-4.1-mini", 0, 0) == 0.0
    # 모르는 모델 → 0 (추정 불가)
    assert est_cost_usd("unknown-model", 1000, 1000) == 0.0
