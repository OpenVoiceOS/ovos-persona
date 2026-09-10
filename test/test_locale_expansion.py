"""No single locale intent file may explode combinatorially — oversized alternation products slow intent
training to the point of timing out on constrained devices."""
import glob
import os

import pytest
from ovos_spec_tools.expansion import expand

LOCALE_ROOT = os.path.join(os.path.dirname(__file__), "..", "ovos_persona", "locale")
MAX_EXPANSIONS_PER_FILE = 2000

INTENT_FILES = sorted(glob.glob(os.path.join(LOCALE_ROOT, "**", "*.intent"), recursive=True))


@pytest.mark.parametrize("path", INTENT_FILES, ids=lambda p: os.path.relpath(p, LOCALE_ROOT))
def test_intent_file_expands_within_bounds(path):
    total = 0
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            samples = expand(line)
        except Exception:
            # malformed lines are covered by the template-validity suite;
            # this test only bounds the combinatorial volume
            continue
        total += len(samples)
    assert total <= MAX_EXPANSIONS_PER_FILE, (
        f"{os.path.relpath(path, LOCALE_ROOT)} expands to {total} samples "
        f"(limit {MAX_EXPANSIONS_PER_FILE})")
