import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.generate_wallpapers import artist_names, main


class WorkflowTests(unittest.TestCase):
    def test_semicolons_newlines_and_duplicates(self):
        self.assertEqual(artist_names(" Artist One; artist one\nArtist Two & Friend; "),
                         ["Artist One", "Artist Two & Friend"])

    def test_collaboration_commas_remain_part_of_name(self):
        self.assertEqual(artist_names("Artist One, Artist Two & Artist Three"),
                         ["Artist One, Artist Two & Artist Three"])

    def test_shell_characters_are_kept_as_plain_data(self):
        self.assertEqual(artist_names("$(whoami);Artist $Two"), ["$(whoami)", "Artist $Two"])

    def test_empty_and_unbounded_lists_rejected(self):
        for value in (" ;\n", "a" * 201, ";".join(str(i) for i in range(101))):
            with self.assertRaises(ValueError):
                artist_names(value)

    def test_secret_fallback_and_resolution_passed_to_generator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "projectivy.example.json").write_text(
                '{"layout":{},"movies":{},"shows":{}}')
            environment = {"ARTIST_INPUT": "", "ARTIST_NAMES": "Artist One;Artist Two",
                           "RESOLUTION": "1080p"}
            with patch.dict(os.environ, environment, clear=True), \
                 patch("scripts.generate_wallpapers.ROOT", root), \
                 patch("scripts.generate_wallpapers.generate", return_value={"written": 2, "skipped": []}) as run:
                self.assertEqual(main(), 0)
                self.assertEqual(run.call_args.args[0]["layout"]["size"], [1920, 1080])
                self.assertFalse(run.call_args.args[0]["movies"]["enabled"])

    def test_movie_mode_requires_token_before_generating(self):
        with patch.dict(os.environ, {"ARTIST_INPUT": "Artist", "INCLUDE_MOVIES_SHOWS": "true"}, clear=True), \
             patch("scripts.generate_wallpapers.generate") as run:
            self.assertEqual(main(), 1)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
