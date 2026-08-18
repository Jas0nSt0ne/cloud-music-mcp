import unittest
from unittest.mock import patch

from cloud_music_mcp import api


class NormalizationTests(unittest.TestCase):
    def test_song_keeps_all_artists(self):
        song = api._song(
            {
                "id": 1,
                "name": "Track",
                "ar": [{"name": "First"}, {"name": "Second"}],
                "al": {"name": "Album"},
            }
        )
        self.assertEqual(song["artist"], "First / Second")
        self.assertEqual(song["album"], "Album")

    def test_search_rejects_unknown_category_without_network(self):
        with patch.object(api, "load_session", return_value=(False, None)):
            result = api.search("x", category="video")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "invalid_category")

    def test_song_detail_normalizes_response(self):
        response = {
            "songs": [
                {"id": 7, "name": "Name", "ar": [{"name": "A"}, {"name": "B"}]}
            ]
        }
        with (
            patch.object(api, "load_session", return_value=(True, "User")),
            patch.object(api.apis.track, "GetTrackDetail", return_value=response),
        ):
            result = api.get_song_detail("7")
        self.assertTrue(result["success"])
        self.assertEqual(result["song"]["artist"], "A / B")


if __name__ == "__main__":
    unittest.main()
