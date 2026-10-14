"""Accuracy guard on the real scanned packets and phone photos in references/ (skipped when they aren't present, e.g. on GitHub).

Thresholds sit just under today's measured accuracy so a regression fails loudly. Run alone with:
    python -m pytest tests/test_real_packets.py -s"""
import pytest
from conftest import refs_available

pytestmark = [pytest.mark.slow, pytest.mark.skipif(not refs_available(), reason="references/ with real packets not present")]

def test_extraction_accuracy_on_real_packets():
    from tools.benchmark import run
    tot, found, extra = run(verbose=False)
    pct = {k: v[0] / v[1] for k, v in tot.items()}
    assert found[0] >= found[1] - 1, found            # 23 payments: 3 packets + 2 phone photos; only the blank Smith & Sons may miss
    assert pct["method"] >= 0.9 and pct["payref"] >= 0.9, pct
    assert pct["amount"] >= 0.8, pct
    assert pct["customer"] >= 0.7 and pct["ticket"] >= 0.65, pct
    assert extra <= 2
