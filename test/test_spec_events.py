"""OVOS-PERSONA-1 §8.5 / §8.7 / §11 bus-surface tests.

- §11  summon broadcasts ``ovos.persona.activated``; release broadcasts
       ``ovos.persona.dismissed`` (best-effort, ``{persona_id, session_id}``).
- §8.5 out-of-band ``ovos.persona.query`` -> ``ovos.persona.answer``
       (request/response, bypasses the pipeline); unsupported persona_id still
       answers with ``response=None``.
- §8.7 ``ovos.persona.list`` -> ``ovos.persona.list.response`` enumerating
       supported identities.

All drive the real PersonaService over a FakeBus, no network.
"""
import json
import os
import tempfile

import pytest

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
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
        config={"personas_path": _persona_dir("Alice", "Bob"),
                "ignore_plugin_personas": True},
    )
    assert "Alice" in service.personas and "Bob" in service.personas
    return service


@pytest.fixture
def captured(svc):
    recs = []
    svc.bus.on("message", lambda m: recs.append(
        Message.deserialize(m) if isinstance(m, str) else m))
    return recs


def _msg(session, msg_type, data=None):
    return Message(msg_type, data or {}, {"session": session.serialize()})


def _types(recs):
    return [m.msg_type for m in recs]


class TestActivationBroadcasts:
    def test_summon_broadcasts_activated(self, svc, captured):
        """§11: summon broadcasts ovos.persona.activated {persona_id, session_id}."""
        sess = Session("bc-summon")
        svc.handle_persona_summon(_msg(sess, "persona:summon", {"persona": "Alice"}))
        evt = next((m for m in captured
                    if m.msg_type == "ovos.persona.activated"), None)
        assert evt is not None, f"no activated broadcast: {_types(captured)}"
        assert evt.data == {"persona_id": "Alice", "session_id": "bc-summon"}

    def test_release_broadcasts_dismissed(self, svc, captured):
        """§11: release broadcasts ovos.persona.dismissed {persona_id, session_id}."""
        sess = Session("bc-release")
        sess.persona_id = "Alice"
        svc.handle_persona_release(_msg(sess, "persona:release", {"persona": "Alice"}))
        evt = next((m for m in captured
                    if m.msg_type == "ovos.persona.dismissed"), None)
        assert evt is not None, f"no dismissed broadcast: {_types(captured)}"
        assert evt.data == {"persona_id": "Alice", "session_id": "bc-release"}


class TestOutOfBandQuery:
    def test_query_answers(self, svc, captured):
        """§8.5: ovos.persona.query is answered on ovos.persona.answer."""
        svc.handle_oob_query(Message("ovos.persona.query",
                                     {"persona_id": "Alice", "utterance": "hi"}, {}))
        ans = next((m for m in captured
                    if m.msg_type == "ovos.persona.answer"), None)
        assert ans is not None, f"no answer: {_types(captured)}"
        assert ans.data["persona_id"] == "Alice"
        assert ans.data["utterance"] == "hi"
        assert "response" in ans.data

    def test_unsupported_query_still_answers_none(self, svc, captured):
        """§8.5 MUST: an unsupported persona_id is answered with response=None,
        not silently dropped."""
        svc.handle_oob_query(Message("ovos.persona.query",
                                     {"persona_id": "no-such-xyz",
                                      "utterance": "hi"}, {}))
        ans = next((m for m in captured
                    if m.msg_type == "ovos.persona.answer"), None)
        assert ans is not None, f"no answer for unsupported persona: {_types(captured)}"
        assert ans.data["response"] is None

    def test_query_does_not_mutate_active_persona(self, svc):
        """§8.5 MUST NOT mutate session.persona_id / active persona state."""
        before = dict(svc.active_personas)
        svc.handle_oob_query(Message("ovos.persona.query",
                                     {"persona_id": "Alice", "utterance": "hi"}, {}))
        assert svc.active_personas == before


class TestDiscovery:
    def test_list_responds(self, svc, captured):
        """§8.7: ovos.persona.list is answered on ovos.persona.list.response."""
        svc.handle_persona_list_request(Message("ovos.persona.list", {}, {}))
        resp = next((m for m in captured
                     if m.msg_type == "ovos.persona.list.response"), None)
        assert resp is not None, f"no list response: {_types(captured)}"
        ids = {p["persona_id"] for p in resp.data["personas"]}
        assert {"Alice", "Bob"} <= ids
        assert resp.data["pipeline_id"] == "persona.openvoiceos"
