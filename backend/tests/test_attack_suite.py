"""The red-team suite runs as part of the tests: every attack must be stopped, offline."""
import pytest

from security.attack_suite import injection_tests, poisoning_tests, upload_tests
from security.attack_suite.base import OWASP, run

ATTACKS = [attack for module in (upload_tests, injection_tests, poisoning_tests) for attack in module.attacks()]


def test_ids_are_unique_and_mapped():
    assert len({a.id for a in ATTACKS}) == len(ATTACKS)
    assert all(a.owasp and set(a.owasp) <= set(OWASP) for a in ATTACKS)
    assert {"upload", "injection", "poisoning"} == {a.category for a in ATTACKS}


@pytest.mark.parametrize("attack", ATTACKS, ids=[a.id for a in ATTACKS])
def test_attack_is_stopped(attack):
    result = run(attack)
    assert result["result"] == "pass", result["actual"]


def test_a_crashing_attack_counts_as_not_stopped():
    from security.attack_suite.base import Attack

    def boom(_):
        raise RuntimeError("x")

    assert run(Attack("X", "upload", "crash", ("LLM10",), "", boom))["result"] == "FAIL"
