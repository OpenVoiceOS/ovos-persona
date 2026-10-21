"""OVOS-PIPELINE-1 §8 handler done-signal.

PersonaService is dispatched out-of-process from ovos-core's IntentDispatcher
(pipeline-1.md:970), so its ``persona:*`` handlers must emit the private
cross-process handshake (``mycroft.skill.handler.start/complete``) any
out-of-process handler needs, the same one ovos-workshop's ``OVOSSkill``
emits via ``add_event(..., handler_info=...)``. Without it the orchestrator's
IntentDispatcher only resolves the ``ovos.utterance.handled`` end-marker via
its timeout instead of promptly.
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


@pytest.fixture
def captured(svc):
    recs = []
    svc.bus.on("message", lambda m: recs.append(
        Message.deserialize(m) if isinstance(m, str) else m))
    return recs


def _types(recs):
    return [m.msg_type for m in recs]


def test_persona_query_emits_handler_lifecycle(svc, captured):
    """§8: persona:query dispatch is bracketed by the handler done-signal."""
    svc.bus.emit(Message("persona:query", {"utterance": "hi Alice", "lang": "en-us"}, {}))
    types = _types(captured)
    assert "mycroft.skill.handler.start" in types, f"no start signal: {types}"
    assert "mycroft.skill.handler.complete" in types, f"no complete signal: {types}"
    start = next(m for m in captured if m.msg_type == "mycroft.skill.handler.start")
    complete = next(m for m in captured if m.msg_type == "mycroft.skill.handler.complete")
    assert start.data["name"] == "PersonaService.handle_persona_query"
    assert complete.data["name"] == "PersonaService.handle_persona_query"
    assert types.index("mycroft.skill.handler.start") < types.index("mycroft.skill.handler.complete")


def test_persona_summon_emits_handler_lifecycle(svc, captured):
    """§8: persona:summon dispatch is also bracketed by the done-signal."""
    svc.bus.emit(Message("persona:summon", {"persona": "Alice"},
                         {"session": {"session_id": "hl-summon"}}))
    types = _types(captured)
    assert "mycroft.skill.handler.start" in types, f"no start signal: {types}"
    assert "mycroft.skill.handler.complete" in types, f"no complete signal: {types}"
