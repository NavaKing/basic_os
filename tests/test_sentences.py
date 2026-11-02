"""Sentence splitting: rankings and name suffixes don't end a sentence (podcast lines were cut at 'No.')."""
import os
import re
import shutil
import subprocess
import unittest

from tests import APP_DIR
import coaches
import sentences

TEXT = "Starting with No. 10 Oregon taking down No. 9 USC. Michigan St. and Cameron Ward Jr. were great! Wyoming vs. Hawaii next? Yes."
EXPECTED = ["Starting with No. 10 Oregon taking down No. 9 USC.", "Michigan St. and Cameron Ward Jr. were great!",
            "Wyoming vs. Hawaii next?", "Yes."]


class Split(unittest.TestCase):
    def test_python(self):
        self.assertEqual(sentences.split(TEXT), EXPECTED)
        self.assertEqual(sentences.split(""), [""])

    def test_quote_keeps_rankings_whole(self):
        self.assertEqual(coaches.tidy_quote("We beat No. 6 Indiana. That matters. Next week too."), "We beat No. 6 Indiana. That matters.")

    @unittest.skipUnless(shutil.which("node"), "needs Node.js")
    def test_javascript_matches(self):
        source = open(os.path.join(APP_DIR, "static", "js", "stories.js"), encoding="utf-8").read()
        pattern = re.search(r"const SENTENCE_END = (/.+/);", source).group(1)
        script = f"console.log(JSON.stringify({TEXT!r}.split({pattern})))"
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), str(EXPECTED).replace("'", '"').replace('", "', '","'))


if __name__ == "__main__":
    unittest.main()
