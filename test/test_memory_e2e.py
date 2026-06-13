"""
End-to-end tests for the memory-plugins feature (feat/memory_plugs).

Tests 1-4 exercise BasicShortTermMemory in isolation, going deeper than the
smoke tests (truncation edge cases, multi-session interleaving, exact merge
content). Test 5 drives the memory-injection seam end-to-end:
build_conversation_context (what Persona.get_messages uses to assemble each
turn) must carry a persisted prior exchange into the next turn's context.
"""
from ovos_plugin_manager.templates.agents import AgentMessage, MessageRole

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
# ---------------------------------------------------------------------------
# 5. Memory injected across turns — the seam Persona.get_messages() uses
# ---------------------------------------------------------------------------

def test_memory_injected_across_turns():
    """`build_conversation_context` is exactly what `Persona.get_messages`
    calls to assemble each turn's prompt. After a turn is persisted (as
    PersonaService.handle_utterance/handle_speak do), the next turn's context
    must carry the prior exchange — proving memory is injected end-to-end."""
    mem = BasicShortTermMemory(config={"max_history": 20})
    sid = "e2e-mem-session"

    # Turn 1: empty history -> context is just the current utterance.
    q1 = "what is the capital of France?"
    ctx1 = [m.content for m in mem.build_conversation_context(q1, sid)]
    assert ctx1[-1] == q1
    assert len(ctx1) == 1

    # Persist the turn the way PersonaService persists user + assistant events.
    a1 = "Paris."
    mem.update_history([_user(q1)], sid)
    mem.update_history([_assistant(a1)], sid)

    # Turn 2: the assembled context must now carry the prior exchange.
    q2 = "and its population?"
    ctx2 = [m.content for m in mem.build_conversation_context(q2, sid)]
    assert q1 in ctx2, "prior user turn not injected"
    assert a1 in ctx2, "prior assistant turn not injected"
    assert ctx2[-1] == q2, "current utterance must be last"

    # A different session must NOT see this conversation.
    other = [m.content for m in mem.build_conversation_context("hi", "other-session")]
    assert other == ["hi"]
