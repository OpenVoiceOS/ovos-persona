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
