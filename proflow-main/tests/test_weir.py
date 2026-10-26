import pytest

from proflow.engine.result import Status
from proflow.engine.weir import rectangular_depth, rectangular_flow


def test_flow_at_known_depth():
    # Q = 3.33 * 2 ft * 1 ft^1.5
    r = rectangular_flow(length=2.0, depth=1.0, cw=3.33, total_depth=2.0)
    assert r.ok and r.method == "weir.rectangular/1"
    assert r.value.flow == pytest.approx(6.66)
    assert r.value.area == pytest.approx(2.0)
    assert r.value.velocity == pytest.approx(3.33)
    assert r.value.top_width == 2.0


def test_depth_inverts_flow():
    depth = rectangular_depth(1.5, 4.0, 2.6, 3.0).value.depth
    assert rectangular_flow(1.5, depth, 2.6, 3.0).value.flow == pytest.approx(4.0)


def test_flow_increases_with_depth():
    flows = [rectangular_flow(1.0, h, 3.33, 2.0).value.flow for h in (0.5, 1.0, 1.5)]
    assert flows == sorted(flows)


def test_zero_flow_zero_depth():
    r = rectangular_depth(1.0, 0.0, 3.33, 1.0)
    assert r.ok and r.value.depth == 0.0 and r.value.velocity == 0.0


def test_flow_needing_more_than_total_depth_is_unsupported():
    r = rectangular_depth(length=0.9, flow=10.0, cw=3.33, total_depth=1.5)
    assert r.status is Status.UNSUPPORTED_REGIME
    assert r.value is None
    assert r.diagnostics["required_depth"] > 1.5
    assert "total depth" in r.message


def test_depth_above_total_depth_is_unsupported():
    r = rectangular_flow(0.9, 1.6, 3.33, 1.5)
    assert r.status is Status.UNSUPPORTED_REGIME


@pytest.mark.parametrize(
    "args", [(0.0, 1.0, 3.33, 1.0), (1.0, 1.0, 0.0, 1.0), (1.0, -1.0, 3.33, 1.0)]
)
def test_invalid_input(args):
    assert rectangular_depth(*args).status is Status.INVALID_INPUT
