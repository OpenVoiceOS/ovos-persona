"""Intent-file locale resolution no longer relies on the deprecated
``ovos_utils.lang.get_language_dir`` helper."""
import unittest
import warnings
from unittest.mock import patch

import ovos_utils.lang

import ovos_persona
from ovos_persona import PersonaService

# What load_resource_files() builds its keys from. Left to whatever the host is
# configured with, this test asserted "en-US" was present and failed on a
# machine whose primary language was anything else -- a locale-resolution test
# failing for a reason that has nothing to do with locale resolution.
DETERMINISTIC_CONFIG = {"lang": "en-US", "secondary_langs": []}


class TestLocaleResolution(unittest.TestCase):
    def test_the_deprecated_helper_is_not_imported_under_any_name(self):
        # `hasattr(ovos_persona, "get_language_dir")` alone proves little: an
        # aliased import binds the same function under a different name and
        # passes it. Compare the objects, not the spelling.
        deprecated = ovos_utils.lang.get_language_dir
        aliases = [name for name, value in vars(ovos_persona).items()
                   if value is deprecated]
        self.assertEqual(aliases, [], f"imported as {aliases}")

    def test_the_deprecated_helper_is_not_called(self):
        # The other half: a call through `ovos_utils.lang` needs no import into
        # this namespace at all, so nothing above would see it.
        with patch.object(ovos_utils.lang, "get_language_dir") as deprecated:
            with patch("ovos_persona.Configuration",
                       return_value=DETERMINISTIC_CONFIG):
                PersonaService.load_resource_files()
        deprecated.assert_not_called()

    def test_load_resource_files_resolves_locale_without_deprecation(self):
        with patch("ovos_persona.Configuration", return_value=DETERMINISTIC_CONFIG):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                intents = PersonaService.load_resource_files()
        self.assertIn("en-US", intents)
        self.assertTrue(any(intents["en-US"].values()))
        self.assertEqual(
            [w for w in caught if "get_language_dir" in str(w.message)], [])


if __name__ == "__main__":
    unittest.main()
