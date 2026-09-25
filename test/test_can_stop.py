"""PersonaService answers the stop pipeline's "can you stop?" ping.

ovos-workshop raises NotImplementedError from ``can_stop`` for any skill that
implements ``stop_session`` without it, so a stop ping to an active persona
failed and "stop" could not interrupt a streaming answer.
"""
import json
import os
import tempfile

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.fakebus import FakeBus

from ovos_persona import PersonaService


def _service():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "Alice.json"), "w") as fh:
        json.dump({"name": "Alice", "solvers": ["ovos-solver-failure-plugin"]}, fh)
    return PersonaService(bus=FakeBus(), config={"personas_path": tmpdir, "ignore_plugin_personas": True})


def _ping(session_id):
    sess = Session(session_id)
    return Message("ovos.stop.ping", {}, {"session": sess.serialize()}), sess


def test_a_streaming_answer_can_be_stopped():
    svc = _service()
    ping, sess = _ping("s-streaming")
    svc._active_sessions[sess.session_id] = True
    assert svc.can_stop(ping) is True
    assert svc.stop_session(sess) is True
    # once stopped there is nothing left to stop
    assert svc.can_stop(ping) is False


def test_an_idle_persona_has_nothing_to_stop_and_does_not_raise():
    svc = _service()
    ping, _ = _ping("s-idle")
    assert svc.can_stop(ping) is False
