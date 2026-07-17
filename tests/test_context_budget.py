from mewcode.context.budget import TokenEstimator


def test_estimator_uses_usage_anchor_and_reserves() -> None:
    estimator = TokenEstimator()
    assert estimator.estimate(40) == 10
    estimator.record_usage(100, 400)
    assert estimator.estimate(440) == 110
    assert estimator.exceeds(440, 13_100)
    assert not estimator.exceeds(440, 13_100, manual=True)
