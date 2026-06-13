"""Smoke tests — verify the package imports and ships its pipeline plugin
entry-point (and no longer the bundled HiveMind agent plugin)."""
from importlib.metadata import entry_points


def test_package_imports():
    import ovos_persona
    from ovos_persona import Persona, PersonaService
    assert Persona is not None
    assert PersonaService is not None


def test_pipeline_entrypoint_registered():
    names = [e.name for e in entry_points(group="opm.pipeline")]
    assert "ovos-persona-pipeline-plugin" in names


def test_no_bundled_hivemind_agent_plugin():
    # the HiveMind agent bridge moved to the standalone hivemind-persona-agent-plugin
    providers = [e.value for e in entry_points(group="hivemind.agent.protocol")
                 if "ovos_persona" in e.value]
    assert providers == []


def test_memory_plugin_import():
    """BasicShortTermMemory must import cleanly."""
    from ovos_persona.memory import BasicShortTermMemory
    assert BasicShortTermMemory is not None


def test_basic_short_term_memory_session_isolation():
    """History stored for session A must not appear in session B."""
    from ovos_persona.memory import BasicShortTermMemory
    from ovos_plugin_manager.templates.agents import AgentMessage, MessageRole

    mem = BasicShortTermMemory(config={"max_history": 10})

    msg_a = AgentMessage(role=MessageRole.USER, content="hello from A")
    mem.update_history([msg_a], session_id="session-a")

    assert mem.get_history("session-b") == []
    history_a = mem.get_history("session-a")
    assert len(history_a) == 1
    assert history_a[0].content == "hello from A"


def test_basic_short_term_memory_merge_consecutive_assistant():
    """Consecutive assistant messages are merged to avoid multi-turn clutter."""
    from ovos_persona.memory import BasicShortTermMemory
    from ovos_plugin_manager.templates.agents import AgentMessage, MessageRole

    mem = BasicShortTermMemory()
    sess = "test-session"

    mem.update_history([AgentMessage(role=MessageRole.USER, content="q")], session_id=sess)
    mem.update_history([AgentMessage(role=MessageRole.ASSISTANT, content="part one")], session_id=sess)
    mem.update_history([AgentMessage(role=MessageRole.ASSISTANT, content="part two")], session_id=sess)

    history = mem.get_history(sess)
    # Two consecutive assistant messages should be merged into one
    assistant_msgs = [m for m in history if m.role == MessageRole.ASSISTANT]
    assert len(assistant_msgs) == 1
    assert "part one" in assistant_msgs[0].content
    assert "part two" in assistant_msgs[0].content
