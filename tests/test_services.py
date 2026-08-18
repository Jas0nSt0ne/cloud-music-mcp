import unittest
from unittest.mock import patch

from cloud_music_mcp import services
from cloud_music_mcp.client_control import ClientControlError


class PlaybackServiceTests(unittest.TestCase):
    def test_daily_position_is_one_based(self):
        daily = {
            "success": True,
            "songs": [
                {"id": 1, "name": "One", "artist": "A", "album": ""},
                {"id": 2, "name": "Two", "artist": "B", "album": ""},
            ],
        }
        with (
            patch.object(services, "get_daily_recommendations", return_value=daily),
            patch.object(services, "play_song_record", return_value={"success": True}) as play,
        ):
            result = services.play_daily_recommendation(2)
        self.assertTrue(result["success"])
        play.assert_called_once_with(daily["songs"][1], position=2, source="daily")

    def test_daily_rejects_out_of_range_position(self):
        daily = {"success": True, "songs": [{"id": 1}]}
        with patch.object(services, "get_daily_recommendations", return_value=daily):
            result = services.play_daily_recommendation(0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "invalid_position")

    def test_play_returns_stable_client_error_code(self):
        song = {"id": 1, "name": "One", "artist": "A"}
        error = ClientControlError("not ready", code="client_not_running")
        with patch.object(services, "play_song", side_effect=error):
            result = services.play_song_record(song)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "client_not_running")

    def test_search_validates_position_before_network(self):
        with patch.object(services, "search") as search:
            result = services.search_and_play("anything", 0)
        self.assertFalse(result["success"])
        search.assert_not_called()

    def test_playlist_play_uses_first_track_for_verification(self):
        detail = {
            "success": True,
            "id": 99,
            "name": "My list",
            "count": 2,
            "songs": [{"id": 1, "name": "First", "artist": "Artist"}],
        }
        with (
            patch.object(services, "get_playlist_detail", return_value=detail),
            patch.object(
                services, "play_playlist", return_value={"success": True}
            ) as play,
        ):
            result = services.play_playlist_by_id(99)
        self.assertTrue(result["success"])
        play.assert_called_once_with(99, "My list", detail["songs"][0])


if __name__ == "__main__":
    unittest.main()
