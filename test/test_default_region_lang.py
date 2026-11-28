"""A bare language tag resolves to its default region.

The default region of a language is the region where it first appeared and
is still spoken: bare ``en`` is ``en-GB`` and bare ``pt`` is ``pt-PT``. When a
device runs persona intents in both regional variants, a request in the bare
tag must use the default-region matcher, never the other region.
"""
import json
import os
import tempfile

import pytest

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from ovos_persona import PersonaService


class RecordingMatcher:
    """Stands in for an IntentContainer and records the queries it gets."""

    def __init__(self):
        self.queries = []

    def calc_intent(self, utterance):
        self.queries.append(utterance)
        return {}


def _persona_dir(*names):
    tmpdir = tempfile.mkdtemp()
    for name in names:
        with open(os.path.join(tmpdir, f"{name}.json"), "w") as fh:
            json.dump({"name": name, "solvers": ["ovos-solver-failure-plugin"]}, fh)
    return tmpdir


@pytest.fixture(scope="module")
def svc():
    service = PersonaService(
        bus=FakeBus(),
        config={"personas_path": _persona_dir("Alice"),
                "ignore_plugin_personas": True},
    )
    assert "Alice" in service.personas
    return service


# The other region is listed first, so a tie broken by order cannot pass.
CASES = [
    ("en", ["en-US", "en-GB"], "en-GB"),
    ("pt", ["pt-BR", "pt-PT"], "pt-PT"),
]


@pytest.mark.parametrize("lang, regions, expected", CASES)
def test_match_high_uses_the_default_region_matcher(svc, lang, regions, expected):
    matchers = {region: RecordingMatcher() for region in regions}
    svc.intent_matchers = matchers
    msg = Message("recognizer_loop:utterance", {"utterances": ["hello"]})
    svc.match_high(["hello"], lang, msg)
    assert {region: m.queries for region, m in matchers.items()} == {
        region: (["hello"] if region == expected else []) for region in regions}


@pytest.mark.parametrize("lang, regions, expected", CASES)
def test_match_medium_reads_vocabulary_in_the_default_region(
        svc, lang, regions, expected, monkeypatch):
    svc.intent_matchers = {region: RecordingMatcher() for region in regions}
    langs_read = []

    def voc_match(utterance, voc_filename, lang=None, **kwargs):
        langs_read.append(lang)
        return False

    monkeypatch.setattr(svc, "voc_match", voc_match)
    msg = Message("recognizer_loop:utterance", {"utterances": ["ask alice"]})
    svc.match_medium(["ask alice"], lang, msg)
    assert langs_read and set(langs_read) == {expected}
