"""An utterance message carrying no utterance is nothing to answer.

`recognizer_loop:utterance` with `utterances: []` reached
`handle_utterance`, which did `message.data.get("utterances")[0]` and raised
IndexError. The harness saw it as
"persona.openvoiceos - ERROR - list index out of range" in the ovos-e2e
shard, and the message was lost rather than answered.

`match_high` reads `utterances[0]` on the same shape, so it is covered here
too: it raised for any session with an active persona.
"""
import json
import os
import tempfile

import pytest

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from ovos_persona import PersonaService


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


class TestEmptyUtteranceList:

    @pytest.mark.parametrize("data", [
        {"utterances": []},
        {"utterances": None},
        {},
    ])
    def test_handle_utterance_records_nothing(self, svc, data):
        msg = Message("recognizer_loop:utterance", data)
        # the defect: this raised IndexError on [] and TypeError on the other
        # two, and the message was dropped with an error in the log.
        svc.handle_utterance(msg)

    @pytest.mark.parametrize("utterances", [[], None])
    def test_match_high_returns_none(self, svc, utterances):
        msg = Message("recognizer_loop:utterance",
                      {"utterances": utterances or []})
        assert svc.match_high(utterances or [], "en-US", msg) is None

    def test_a_real_utterance_still_reaches_the_history(self, svc):
        # the control: the guard must not swallow a turn that does exist.
        # Without this, returning early unconditionally would pass the rows
        # above and break the feature.
        msg = Message("recognizer_loop:utterance",
                      {"utterances": ["what is the weather"]})
        from ovos_bus_client.session import SessionManager
        svc.handle_utterance(msg)
        persona = svc.personas.get(
            svc.get_active_persona(msg, include_default=True))
        # asserted, not guarded by an `if`: a control that can skip itself
        # proves nothing. If this fixture ever stops giving the persona a
        # memory, this line must fail rather than quietly pass.
        assert persona is not None and persona.memory is not None
        sess = SessionManager.get(msg)
        history = persona.memory.get_history(session_id=sess.session_id)
        assert any("what is the weather" in str(entry)
                   for entry in history), \
            "a real utterance did not reach the session history"

    @pytest.mark.parametrize("utterances", [[], None])
    def test_match_medium_returns_none(self, svc, utterances):
        msg = Message("recognizer_loop:utterance",
                      {"utterances": utterances or []})
        assert svc.match_medium(utterances or [], "en-US", msg) is None

    @pytest.mark.parametrize("utterances", [[], None])
    def test_match_low_returns_none(self, svc, utterances):
        msg = Message("recognizer_loop:utterance",
                      {"utterances": utterances or []})
        assert svc.match_low(utterances or [], "en-US", msg) is None

    def test_the_pipeline_itself_survives_an_empty_list(self, svc):
        # ConfidenceMatcherPipeline.match chains the three matchers with `or`,
        # so a guard on match_high alone only moves the IndexError down to
        # match_medium and then to match_low. This drives the entry point the
        # pipeline really calls.
        msg = Message("recognizer_loop:utterance", {"utterances": []})
        assert svc.match([], "en-US", msg) is None

    def test_the_pipeline_still_answers_a_real_utterance(self, svc):
        # the control: match() must still reach a persona when something was
        # said, or a guard that always returned None would pass every row
        # above.
        msg = Message("recognizer_loop:utterance",
                      {"utterances": ["what is the weather"]})
        # match_low answers only when a persona resolves, and the default
        # persona is reached through handle_fallback, so the control turns it
        # on rather than asserting a None that would prove nothing.
        svc.config["handle_fallback"] = True
        try:
            match = svc.match(["what is the weather"], "en-US", msg)
        finally:
            svc.config.pop("handle_fallback", None)
        assert match is not None, "a real utterance produced no match"
        assert match.match_type == "persona:query"
        assert match.match_data["utterance"] == "what is the weather"
