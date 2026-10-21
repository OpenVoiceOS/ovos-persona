"""Validate that every locale resource file contains well-formed templates."""
import os
import unittest

from ovos_spec_tools.expansion import expand

PACKAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "ovos_persona")
LOCALE_EXTENSIONS = (".voc", ".intent", ".dialog", ".entity", ".rx")


def iter_locale_files():
    """Yield the path of every locale resource file in the package."""
    for root, _dirs, files in os.walk(PACKAGE_DIR):
        if os.sep + "locale" + os.sep not in root + os.sep:
            continue
        for fname in sorted(files):
            if fname.endswith(LOCALE_EXTENSIONS):
                yield os.path.join(root, fname)


class TestLocaleTemplates(unittest.TestCase):
    def test_all_locale_templates_expand(self):
        failures = []
        for path in iter_locale_files():
            with open(path, encoding="utf-8") as f:
                for lineno, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        expand(line)
                    except Exception as e:
                        rel = os.path.relpath(path, PACKAGE_DIR)
                        failures.append(f"{rel}:{lineno}: {line!r} -> {e}")
        self.assertEqual(failures, [],
                         "Malformed locale templates found:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
