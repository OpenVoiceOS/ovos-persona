"""Persona memory receives whole exchanges, keyed by the session, on the voice path.

ovos-core emits `recognizer_loop:utterance`, the pipeline matches and the
persona answers through `persona:query`, and every `speak` goes on the bus.
The tests drive that sequence on one bus with the real `ovos-memory-plugin-entity`
and `ovos-memory-plugin-recency` backends from ovos-memory-plugins. The entity
backend asks an OpenAI-compatible endpoint for facts. A local stub plays that
endpoint: it reports a fact only when the user text of the exchange states it.
"""
import json
import os
import re
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.fakebus import FakeBus

from ovos_persona import PersonaService

FACT_PATTERNS = {
    r"my name is (\w+)": "My name is {}",
    r"my dog is called (\w+)": "My dog is called {}",
}


class _ExtractionEndpoint(BaseHTTPRequestHandler):
    prompts = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = body["messages"][-1]["content"]
        self.prompts.append(prompt)
        user_text = re.search(r"User: (.*)\nAssistant:", prompt)
        facts = []
        for pattern, template in FACT_PATTERNS.items():
            found = re.search(pattern, user_text.group(1), re.I) if user_text else None
            if found:
                facts.append(template.format(found.group(1)))
        reply = {"choices": [{"message": {"role": "assistant",
                                          "content": json.dumps(facts)}}]}
        payload = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def endpoint():
    server = HTTPServer(("127.0.0.1", 0), _ExtractionEndpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()
    server.server_close()


@pytest.fixture
def device(endpoint):
    _ExtractionEndpoint.prompts.clear()
    personas = tempfile.mkdtemp()
    configs = {
        "Memo": {"memory_module": "ovos-memory-plugin-entity",
                 "ovos-memory-plugin-entity": {"api_url": endpoint, "model": "stub",
                                               "backend": "memory"}},
        "Recent": {"memory_module": "ovos-memory-plugin-recency",
                   "ovos-memory-plugin-recency": {"max_history": 20}},
    }
    for name, memory in configs.items():
        with open(os.path.join(personas, f"{name}.json"), "w") as fh:
            json.dump({"name": name, "solvers": ["ovos-solver-failure-plugin"], **memory}, fh)
    bus = FakeBus()
    svc = PersonaService(bus=bus, config={"personas_path": personas,
                                          "ignore_plugin_personas": True,
                                          "default_persona": "Memo"})
    for persona in svc.personas.values():
        persona.solvers = SimpleNamespace(
            stream_completion=lambda messages, **kw: iter(["Nice to meet you.", "How can I help?"]))
    return svc, bus


def voice_turn(bus, session, text):
    """Emit what ovos-core emits for an utterance the persona pipeline answers."""
    ctx = {"session": session.serialize()}
    bus.emit(Message("recognizer_loop:utterance", {"utterances": [text]}, ctx))
    bus.emit(Message("persona:query", {"utterance": text}, ctx))


def skill_turn(bus, session, text, reply):
    """An utterance that a non-persona skill answers."""
    ctx = {"session": session.serialize()}
    bus.emit(Message("recognizer_loop:utterance", {"utterances": [text]}, ctx))
    bus.emit(Message("speak", {"utterance": reply}, ctx))


def facts(svc, session_id):
    return svc.personas["Memo"].memory._load_facts(session_id)


def test_two_voice_turns_store_the_facts_of_their_exchange(device):
    svc, bus = device
    a = Session("A")
    voice_turn(bus, a, "my name is Bo")
    voice_turn(bus, a, "my dog is called Rex")
    assert facts(svc, "A") == ["My name is Bo", "My dog is called Rex"]


def test_each_extraction_prompt_holds_both_roles(device):
    svc, bus = device
    voice_turn(bus, Session("A"), "my name is Bo")
    assert len(_ExtractionEndpoint.prompts) == 1
    assert ("User: my name is Bo\nAssistant: Nice to meet you. How can I help?"
            in _ExtractionEndpoint.prompts[0])


def test_session_b_does_not_see_session_a(device):
    svc, bus = device
    voice_turn(bus, Session("A"), "my name is Bo")
    assert facts(svc, "B") == []
    context = svc.personas["Memo"].memory.build_conversation_context("who am I", "B")
    assert all("Bo" not in m.content for m in context)
    context = svc.personas["Memo"].memory.build_conversation_context("who am I", "A")
    assert any("My name is Bo" in m.content for m in context)


def test_a_follow_up_in_the_same_session_is_built_from_the_stored_fact(device):
    svc, bus = device
    a = Session("A")
    voice_turn(bus, a, "my dog is called Rex")
    seen = []
    svc.personas["Memo"].solvers = SimpleNamespace(
        stream_completion=lambda messages, **kw: seen.append(messages) or iter(["Rex."]))
    voice_turn(bus, a, "what is my dog called")
    assert any("My dog is called Rex" in m.content for m in seen[0])


def test_history_backend_records_whole_exchanges_per_session(device):
    svc, bus = device
    for sid, name in (("A", "Bo"), ("B", "Cy")):
        voice_turn(bus, _persona_session(sid, "Recent"),
                   f"my name is {name}")
    recent = svc.personas["Recent"].memory
    assert [(m.role.value, m.content) for m in recent.get_history("A")] == [
        ("user", "my name is Bo"), ("assistant", "Nice to meet you. How can I help?")]
    assert [m.content for m in recent.get_history("B")][0] == "my name is Cy"


def _persona_session(session_id, persona_id):
    sess = Session(session_id)
    sess.persona_id = persona_id
    return sess


def test_a_skill_reply_is_not_recorded(device):
    svc, bus = device
    a = _persona_session("A", "Recent")
    skill_turn(bus, a, "what is the weather", "It is sunny in Lisbon.")
    voice_turn(bus, a, "my name is Bo")
    texts = [m.content for m in svc.personas["Recent"].memory.get_history("A")]
    assert texts == ["my name is Bo", "Nice to meet you. How can I help?"]
    assert all("sunny" not in t for t in texts)
    assert svc.personas["Memo"].memory.get_history("A") == []
    assert not any("sunny" in p for p in _ExtractionEndpoint.prompts)


def test_another_personas_turn_stays_out_of_the_default_persona(device):
    svc, bus = device
    voice_turn(bus, _persona_session("A", "Recent"), "my name is Bo")
    assert facts(svc, "A") == []
    assert _ExtractionEndpoint.prompts == []


def _plain_persona_service(memory_config=None):
    personas = tempfile.mkdtemp()
    with open(os.path.join(personas, "Plain.json"), "w") as fh:
        json.dump({"name": "Plain", "solvers": ["ovos-solver-failure-plugin"],
                   "memory_module": "ovos-agents-short-term-memory-plugin",
                   **(memory_config or {})}, fh)
    bus = FakeBus()
    spoken = []
    bus.on("speak", lambda m: spoken.append(m.data["utterance"]))
    svc = PersonaService(bus=bus, config={"personas_path": personas,
                                          "ignore_plugin_personas": True,
                                          "default_persona": "Plain"})
    return svc, bus, spoken


def _query(session, text):
    return Message("persona:query", {"utterance": text},
                   {"session": session.serialize()})


def test_a_follow_up_during_the_memory_write_is_answered_and_recorded():
    svc, bus, spoken = _plain_persona_service()
    memory = svc.personas["Plain"].memory
    write = memory.update_history
    memory.update_history = lambda msgs, sid: (time.sleep(1.0), write(msgs, sid))

    def stream(messages, **kw):
        text = messages[-1].content
        for i in range(3):
            time.sleep(0.3)
            yield f"{text} part {i}."

    svc.personas["Plain"].solvers = SimpleNamespace(stream_completion=stream)
    session = Session("S")
    first = threading.Thread(target=svc.handle_persona_query, args=(_query(session, "first"),))
    first.start()
    time.sleep(1.2)  # the first answer is spoken and its exchange is being written
    second = threading.Thread(target=svc.handle_persona_query, args=(_query(session, "second"),))
    second.start()
    first.join()
    second.join()
    assert sorted(spoken) == sorted(f"{q} part {i}." for q in ("first", "second") for i in range(3))
    assert [m.content for m in memory.get_history("S")] == [
        "first", "first part 0. first part 1. first part 2.",
        "second", "second part 0. second part 1. second part 2."]


def test_a_stopped_answer_is_not_recorded():
    svc, bus, spoken = _plain_persona_service()
    session = Session("U")

    def stream(messages, **kw):
        yield "sentence one."
        svc.stop_session(session)
        yield "sentence two."

    svc.personas["Plain"].solvers = SimpleNamespace(stream_completion=stream)
    svc.handle_persona_query(_query(session, "long question"))
    assert spoken == ["sentence one."]
    assert svc.personas["Plain"].memory.get_history("U") == []


def test_a_memory_error_is_caught_after_the_answer_is_spoken():
    svc, bus, spoken = _plain_persona_service()
    svc.personas["Plain"].solvers = SimpleNamespace(
        stream_completion=lambda messages, **kw: iter(["ok."]))

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    svc.personas["Plain"].memory.update_history = broken
    svc.handle_persona_query(_query(Session("V"), "x"))
    assert spoken == ["ok."]
    assert svc._active_sessions["V"] is False


@pytest.mark.parametrize("max_history", [5, 7])
def test_the_context_starts_with_a_question_for_any_max_history(max_history):
    svc, bus, spoken = _plain_persona_service(
        {"ovos-agents-short-term-memory-plugin": {"max_history": max_history}})
    svc.personas["Plain"].solvers = SimpleNamespace(
        stream_completion=lambda messages, **kw: iter(["ans."]))
    session = Session("S")
    for i in range(5):
        svc.handle_persona_query(_query(session, f"question {i}"))
    context = svc.personas["Plain"].memory.build_conversation_context("question 5", "S")
    roles = [m.role.value for m in context]
    assert roles[0] == "user"
    assert roles == ["user", "assistant"] * ((len(roles) - 1) // 2) + ["user"]
    assert context[0].content == f"question {5 - (len(roles) - 1) // 2}"
