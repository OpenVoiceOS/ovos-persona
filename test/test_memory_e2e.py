"""
End-to-end tests for the memory-plugins feature (feat/memory_plugs).

Tests 1-4 exercise BasicShortTermMemory in isolation, going deeper than the
smoke tests (truncation edge cases, multi-session interleaving, exact merge
content).  Test 5 is the full Persona-level e2e: a deterministic fake solver
records every message list it receives; we drive two chat turns through the
same session and assert that the second turn's context contains the prior
exchange.
"""
from typing import List, Optional, Iterable

import pytest

from ovos_plugin_manager.templates.agents import AgentMessage, MessageRole
from ovos_plugin_manager.templates.solvers import ChatMessageSolver

from ovos_persona.memory import BasicShortTermMemory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(text: str) -> AgentMessage:
    return AgentMessage(role=MessageRole.USER, content=text)


def _assistant(text: str) -> AgentMessage:
    return AgentMessage(role=MessageRole.ASSISTANT, content=text)


# ---------------------------------------------------------------------------
# 1. max_history truncation
# ---------------------------------------------------------------------------

def test_max_history_truncation():
    """After pushing more messages than max_history, only the most recent N remain."""
    mem = BasicShortTermMemory(config={"max_history": 4})
    sess = "trunc-session"

    # Push 6 alternating messages (user + assistant × 3)
    for i in range(3):
        mem.update_history([_user(f"question {i}")], session_id=sess)
        mem.update_history([_assistant(f"answer {i}")], session_id=sess)

    history = mem.get_history(sess)
    assert len(history) == 4, f"expected 4 messages, got {len(history)}"
    # The retained messages must be the *last* 4 (question 1, answer 1, question 2, answer 2)
    contents = [m.content for m in history]
    assert "question 2" in contents
    assert "answer 2" in contents
    assert "question 0" not in contents
    assert "answer 0" not in contents


# ---------------------------------------------------------------------------
# 2. Hanging user-message drop
# ---------------------------------------------------------------------------

def test_hanging_user_message_dropped():
    """If the last stored message is USER and the next incoming is also USER,
    the previous USER is dropped before appending."""
    mem = BasicShortTermMemory(config={"max_history": 10})
    sess = "hang-session"

    mem.update_history([_user("first question")], session_id=sess)
    mem.update_history([_user("corrected question")], session_id=sess)

    history = mem.get_history(sess)
    user_msgs = [m for m in history if m.role == MessageRole.USER]
    assert len(user_msgs) == 1, f"expected 1 USER message, got {len(user_msgs)}"
    assert user_msgs[0].content == "corrected question"


# ---------------------------------------------------------------------------
# 3. Consecutive assistant merge (exact content)
# ---------------------------------------------------------------------------

def test_consecutive_assistant_merge_content():
    """Two consecutive ASSISTANT messages are merged with a newline; the result
    must be 'first\\nsecond', not 'second\\nfirst'."""
    mem = BasicShortTermMemory(config={"max_history": 10})
    sess = "merge-session"

    mem.update_history([_user("q")], session_id=sess)
    mem.update_history([_assistant("first")], session_id=sess)
    mem.update_history([_assistant("second")], session_id=sess)

    history = mem.get_history(sess)
    assistant_msgs = [m for m in history if m.role == MessageRole.ASSISTANT]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].content == "first\nsecond"


# ---------------------------------------------------------------------------
# 4. Multi-session isolation (interleaved updates)
# ---------------------------------------------------------------------------

def test_multi_session_isolation_interleaved():
    """Interleaved updates across three sessions must not bleed across sessions."""
    mem = BasicShortTermMemory(config={"max_history": 20})

    for i in range(3):
        mem.update_history([_user(f"A-q{i}")], session_id="alpha")
        mem.update_history([_assistant(f"A-a{i}")], session_id="alpha")
        mem.update_history([_user(f"B-q{i}")], session_id="beta")
        mem.update_history([_assistant(f"B-a{i}")], session_id="beta")
        mem.update_history([_user(f"C-q{i}")], session_id="gamma")
        mem.update_history([_assistant(f"C-a{i}")], session_id="gamma")

    alpha = mem.get_history("alpha")
    beta = mem.get_history("beta")
    gamma = mem.get_history("gamma")

    # Each session must have exactly its own 6 messages
    assert len(alpha) == 6
    assert len(beta) == 6
    assert len(gamma) == 6

    assert all(m.content.startswith("A-") for m in alpha)
    assert all(m.content.startswith("B-") for m in beta)
    assert all(m.content.startswith("C-") for m in gamma)

    # Spot-check no cross-contamination
    alpha_contents = {m.content for m in alpha}
    assert "B-q0" not in alpha_contents
    assert "C-q0" not in alpha_contents


# ---------------------------------------------------------------------------
# 5. Persona-level e2e — memory is injected across turns
# ---------------------------------------------------------------------------

class _FakeChatSolver(ChatMessageSolver):
    """Deterministic fake solver that records every message list it receives
    and returns a fixed answer, requiring no network or model access."""

    FIXED_ANSWER = "fake-answer"

    def __init__(self, config=None):
        super().__init__(config=config or {})
        self.received_messages: List[List[AgentMessage]] = []

    # ChatMessageSolver uses get_chat_completion; override it.
    def get_chat_completion(self, messages, lang=None, units=None):
        self.received_messages.append(list(messages))
        return self.FIXED_ANSWER

    # Also cover stream path used by Persona.stream()
    def stream_chat_utterances(self, messages, lang=None, units=None) -> Iterable[str]:
        self.received_messages.append(list(messages))
        yield self.FIXED_ANSWER


def _make_persona_with_fake_solver(max_history: int = 10):
    """
    Build a Persona whose only solver is _FakeChatSolver, bypassing all
    plugin discovery (no entry-points, no network).

    Persona.__init__ calls QuestionSolversService which walks every installed
    solver plugin; 'fake-solver' is not a real entry-point so it would raise
    ImportError.  We build the object with __new__ and hand-wire every
    attribute that __init__ would have set, then inject BasicShortTermMemory
    directly (same class the entry-point would return).

    Returns (persona, fake_solver).
    """
    from ovos_persona import Persona
    from ovos_persona.solvers import QuestionSolversService

    fake = _FakeChatSolver()

    # Build Persona without calling __init__ to avoid plugin-registry lookups.
    persona = Persona.__new__(Persona)
    persona.name = "test-persona"
    persona.config = {}

    # Wire up memory directly — same class the entry-point would have returned.
    persona.memory = BasicShortTermMemory(config={"max_history": max_history})

    # Build a minimal QuestionSolversService without calling load_plugins().
    svc = QuestionSolversService.__new__(QuestionSolversService)
    svc.loaded_modules = {"fake-solver": fake}
    svc.sort_order = ["fake-solver"]
    svc.config = {}
    persona.solvers = svc

    return persona, fake


def test_persona_memory_injected_across_turns():
    """Drive two consecutive chat turns through the same Persona + session and
    assert that the second turn's solver receives the first turn's exchange in
    its message context — proving memory is used end-to-end."""
    from ovos_bus_client import Session

    persona, fake = _make_persona_with_fake_solver(max_history=20)
    assert persona.memory is not None, "Persona did not load a memory plugin"

    sess = Session()
    sess.session_id = "e2e-test-session"

    # --- Turn 1 ---
    utt1 = "what is the capital of France?"
    msgs1 = persona.get_messages(utt1, sess)
    answer1 = persona.chat(msgs1, sess)

    assert answer1 == _FakeChatSolver.FIXED_ANSWER

    # Simulate what PersonaService.handle_utterance / handle_speak do after
    # the turn completes (they update memory on bus events).
    persona.memory.update_history([_user(utt1)], session_id=sess.session_id)
    persona.memory.update_history([_assistant(answer1)], session_id=sess.session_id)

    # --- Turn 2 ---
    utt2 = "and what language do they speak?"
    msgs2 = persona.get_messages(utt2, sess)
    answer2 = persona.chat(msgs2, sess)

    assert answer2 == _FakeChatSolver.FIXED_ANSWER
    assert len(fake.received_messages) == 2

    # The second call must have received the first turn's user+assistant messages
    second_call_messages = fake.received_messages[1]
    contents = [m.content for m in second_call_messages]

    assert utt1 in contents, (
        f"Turn 1 user message not found in second call context: {contents}"
    )
    assert _FakeChatSolver.FIXED_ANSWER in contents, (
        f"Turn 1 assistant answer not found in second call context: {contents}"
    )
    # The current utterance must also be present
    assert utt2 in contents, (
        f"Turn 2 user message not found in second call context: {contents}"
    )
    # Context must have grown: more messages than a single-turn call would give
    assert len(second_call_messages) > len(fake.received_messages[0]), (
        "Second call did not receive more context than the first — memory not injected"
    )
