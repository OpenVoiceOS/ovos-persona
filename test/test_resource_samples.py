"""Every sample the loader returns has to be a sample.

Some ca, gl and it intent files end with a newline. Split on "\n", that
newline became a blank sample, expand_template raised on it, and the whole
pipeline plugin failed to load, for every language.
"""
import os
from unittest.mock import patch

import pytest
from ovos_spec_tools import expand

from ovos_persona import PersonaService

LOCALE_ROOT = os.path.join(os.path.dirname(__file__), "..", "ovos_persona", "locale")
LANGS = ["en-US", "fr-FR", "ca-ES", "gl-ES", "it-IT", "de-DE"]


def _loaded(langs):
    config = {"lang": langs[0], "secondary_langs": langs[1:]}
    with patch("ovos_persona.Configuration", return_value=config):
        return PersonaService.load_resource_files()


@pytest.mark.parametrize("lang", LANGS)
def test_no_sample_is_blank(lang):
    for intent_name, samples in _loaded([lang])[lang].items():
        for sample in samples:
            assert sample.strip(), f"{lang}/{intent_name} yielded a blank sample"


@pytest.mark.parametrize("lang", LANGS)
def test_every_sample_expands(lang):
    for intent_name, samples in _loaded([lang])[lang].items():
        for sample in samples:
            assert expand(sample), f"{lang}/{intent_name}: {sample!r} did not expand"


def test_trailing_newline_adds_no_sample():
    path = os.path.join(LOCALE_ROOT, "ca-ES", "ask.intent")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert text.endswith("\n")
    written = [line for line in text.split("\n") if line.strip()]
    assert len(_loaded(["ca-ES"])["ca-ES"]["ask.intent"]) == len(written)
