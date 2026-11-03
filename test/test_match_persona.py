"""match_persona: an exact name wins, and a shared word does not tie with it."""
import json
from unittest.mock import patch

import pytest
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from ovos_persona import PersonaService


def _service(*names):
    with patch.object(PersonaService, "__init__", lambda self: None):
        svc = PersonaService()
    svc.personas = {name: object() for name in names}
    return svc


def test_exact_id_beats_substring_name():
    svc = _service("remotestream", "oldremotestream")
    assert svc.match_persona("oldremotestream") == "oldremotestream"
    assert svc.match_persona("remotestream") == "remotestream"


def test_exact_match_ignores_case():
    svc = _service("remotestream", "OldRemoteStream")
    assert svc.match_persona("oldremotestream") == "OldRemoteStream"


# en-US and pt-PT summon.intent phrasings, and the persona slot they capture
@pytest.mark.parametrize("utterance", [
    "stub agent",
    "connect me to stub agent",
    "conecta-me com stub agent",
])
def test_shared_word_does_not_tie_with_exact_name(utterance):
    svc = _service("remote agent", "stub agent")
    assert svc.match_persona(utterance) == "stub agent"


def test_shared_word_other_order():
    svc = _service("stub agent", "remote agent")
    assert svc.match_persona("remote agent") == "remote agent"
    assert svc.match_persona("connect me to remote agent") == "remote agent"


def test_unrelated_name_is_rejected():
    assert _service("remote agent", "stub agent").match_persona("zebra") is None


def test_no_personas_or_empty_name():
    assert _service().match_persona("stub agent") is None
    assert _service("stub agent").match_persona("") is None


def test_word_order_variant_does_not_shadow_exact_name():
    # both names have the same words: only the exact-first rule picks "stub agent"
    svc = _service("agent stub", "stub agent")
    assert svc.match_persona("stub agent") == "stub agent"


def test_registered_spelling_wins_over_case_variant():
    svc = _service("Stub Agent", "stub agent")
    assert svc.match_persona("stub agent") == "stub agent"
    assert svc.match_persona("Stub Agent") == "Stub Agent"


@pytest.mark.parametrize("order", [("remotestream", "oldremotestream"),
                                   ("oldremotestream", "remotestream")])
def test_summon_names_the_longest_persona_in_the_utterance(tmp_path, order):
    for name in order:
        (tmp_path / f"{name}.json").write_text(
            json.dumps({"name": name, "solvers": ["ovos-solver-failure-plugin"]}))
    svc = PersonaService(bus=FakeBus(), config={"personas_path": str(tmp_path),
                                                "ignore_plugin_personas": True})
    # load_personas reads the directory with os.listdir, whose order the filesystem decides
    svc.personas = {name: svc.personas[name] for name in order}
    utt = "please summon oldremotestream now"
    msg = Message("recognizer_loop:utterance", {"utterances": [utt]})
    match = svc.match_medium([utt], "en-US", msg)
    assert match.match_type == "persona:summon"
    assert match.updated_session.persona_id == "oldremotestream"
