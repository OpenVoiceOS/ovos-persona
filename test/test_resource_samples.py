"""Every sample the loader hands out has to be a sample.

`expand_template` rejects a blank string, and it is the loader that decides
what reaches it. Splitting a file on "\n" makes a blank string out of the
newline that ends it, so a locale file written the ordinary way -- fr, ca,
gl and it all are -- used to cost `PersonaService` its whole pipeline load:

    ERROR - Failed to load pipeline plugin 'ovos-persona-pipeline-plugin':
            template '' yields an empty sample

One unusable line in one language, and no language gets a persona.
"""
import os
from unittest.mock import patch

import pytest
from ovos_spec_tools.expansion import expand

from ovos_persona import PersonaService

LOCALE_ROOT = os.path.join(os.path.dirname(__file__), "..", "ovos_persona", "locale")
# The languages whose files end with a newline, which is what broke this.
LANGS = ["en-US", "fr-FR", "ca-ES", "gl-ES", "it-IT", "de-DE"]


def _loaded(langs):
    config = {"lang": langs[0], "secondary_langs": langs[1:]}
    with patch("ovos_persona.Configuration", return_value=config):
        return PersonaService.load_resource_files()


@pytest.mark.parametrize("lang", LANGS)
def test_no_sample_is_blank(lang):
    for intent_name, samples in _loaded([lang]).get(lang, {}).items():
        for sample in samples:
            assert sample.strip(), f"{lang}/{intent_name} yielded a blank sample"


@pytest.mark.parametrize("lang", LANGS)
def test_every_sample_expands(lang):
    """What the loader returns is passed straight to expand_template."""
    for intent_name, samples in _loaded([lang]).get(lang, {}).items():
        for sample in samples:
            assert expand(sample), f"{lang}/{intent_name}: {sample!r} did not expand"


def test_a_file_that_ends_with_a_newline_is_read_whole():
    """The trailing newline must cost no sample, and add none."""
    path = os.path.join(LOCALE_ROOT, "fr", "ask.intent")
    if not os.path.exists(path):
        pytest.skip("fr/ask.intent is not shipped")
    with open(path, encoding="utf-8") as handle:
        written = [line for line in handle.read().split("\n") if line.strip()]
    loaded = _loaded(["fr-FR"])["fr-FR"]["ask.intent"]
    assert len(loaded) == len(written)
