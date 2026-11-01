# Shared shape of a red-team attack: what it tries, the OWASP LLM risk it maps to, and how its outcome is judged
import tempfile
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ATTACKS_DIR = REPO_ROOT / "data" / "attacks"

# OWASP Top 10 for LLM Applications 2025
OWASP = {
    "LLM01": "Prompt Injection",
    "LLM02": "Sensitive Information Disclosure",
    "LLM03": "Supply Chain",
    "LLM04": "Data and Model Poisoning",
    "LLM05": "Improper Output Handling",
    "LLM06": "Excessive Agency",
    "LLM07": "System Prompt Leakage",
    "LLM08": "Vector and Embedding Weaknesses",
    "LLM09": "Misinformation",
    "LLM10": "Unbounded Consumption",
}


@dataclass
class Attack:
    """`check` runs the attack in a fresh temporary folder and returns (stopped, what actually happened)."""

    id: str
    category: str
    title: str
    owasp: tuple[str, ...]
    expected: str
    check: Callable[[Path], tuple[bool, str]]
    tags: tuple[str, ...] = field(default_factory=tuple)


def run(attack: Attack) -> dict:
    with tempfile.TemporaryDirectory(prefix="hirewall-attack-") as folder:
        try:
            stopped, actual = attack.check(Path(folder))
        except Exception as error:  # an attack that crashes the system has not been stopped
            stopped, actual = False, f"crashed: {type(error).__name__}"
            traceback.print_exc()
    return {
        "id": attack.id, "category": attack.category, "title": attack.title,
        "owasp": [f"{code} {OWASP[code]}" for code in attack.owasp],
        "expected": attack.expected, "actual": actual, "result": "pass" if stopped else "FAIL",
    }
