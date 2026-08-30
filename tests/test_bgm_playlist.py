import unittest
from datetime import date
from unittest.mock import Mock

from cloud_music_mcp.bgm_playlist import (
    build_playlist_name,
    import_bgm_playlist,
    preview_bgm_playlist,
)


def search_result(*songs):
    return {"success": True, "items": list(songs), "count": len(songs)}


class BgmPlaylistTests(unittest.TestCase):
    def test_playlist_name_has_no_separator(self):
        today = date(2026, 8, 30)
        self.assertEqual(build_playlist_name("影视剧博主BGM", today), "20260830影视剧博主BGM")
        self.assertEqual(build_playlist_name("", today), "20260830歌单")
        self.assertEqual(build_playlist_name("20260830自定义", today), "20260830自定义")

    def test_preview_matches_exact_title_and_artist_and_deduplicates_source(self):
        search = Mock(
            return_value=search_result(
                {"id": 11, "name": "晴天", "artist": "周杰伦", "album": "叶惠美"}
            )
        )
        result = preview_bgm_playlist(
            [
                {"name": "晴天", "artist": "周杰伦"},
                {"name": " 晴天 ", "artist": "周杰伦"},
            ],
            today=date(2026, 8, 30),
            search_fn=search,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["unique_count"], 1)
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["duplicate_sources"][0]["duplicate_of"], 1)

    def test_preview_matches_one_artist_from_multi_artist_result(self):
        result = preview_bgm_playlist(
            [{"name": "Track", "artist": "First"}],
            search_fn=Mock(
                return_value=search_result(
                    {"id": 8, "name": "Track", "artist": "First / Second"}
                )
            ),
        )
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["results"][0]["match"]["id"], 8)

    def test_preview_does_not_match_short_artist_substring(self):
        result = preview_bgm_playlist(
            [{"name": "零距离的思念", "artist": "en"}],
            search_fn=Mock(
                return_value=search_result(
                    {"id": 9, "name": "零距离的思念", "artist": "Lov1en"}
                )
            ),
        )
        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(result["results"][0]["status"], "ambiguous")

    def test_preview_prefers_exact_artist_over_collaboration_versions(self):
        result = preview_bgm_playlist(
            [{"name": "零距离的思念", "artist": "TINY7"}],
            search_fn=Mock(
                return_value=search_result(
                    {"id": 10, "name": "零距离的思念", "artist": "TINY7"},
                    {
                        "id": 11,
                        "name": "零距离的思念",
                        "artist": "TINY7 / Sazablue",
                    },
                )
            ),
        )
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["results"][0]["match"]["id"], 10)

    def test_preview_uses_first_ranked_duplicate_release(self):
        result = preview_bgm_playlist(
            [{"name": "Lost Myself", "artist": "SYML / Guy Garvey"}],
            search_fn=Mock(
                return_value=search_result(
                    {
                        "id": 12,
                        "name": "Lost Myself",
                        "artist": "SYML / Guy Garvey",
                        "album": "Album",
                    },
                    {
                        "id": 13,
                        "name": "Lost Myself",
                        "artist": "SYML / Guy Garvey",
                        "album": "Single",
                    },
                )
            ),
        )
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["results"][0]["match"]["id"], 12)
        self.assertEqual(result["results"][0]["alternate_matches"][0]["id"], 13)

    def test_preview_marks_same_title_different_artists_as_ambiguous(self):
        result = preview_bgm_playlist(
            [{"name": "Stay", "artist": ""}],
            search_fn=Mock(
                return_value=search_result(
                    {"id": 1, "name": "Stay", "artist": "A"},
                    {"id": 2, "name": "Stay", "artist": "B"},
                )
            ),
        )
        self.assertEqual(result["ambiguous_count"], 1)
        self.assertEqual(result["results"][0]["status"], "ambiguous")

    def test_preview_does_not_treat_live_version_as_exact(self):
        result = preview_bgm_playlist(
            [{"name": "泪桥", "artist": "伍佰"}],
            search_fn=Mock(
                return_value=search_result(
                    {"id": 1, "name": "泪桥 (Live)", "artist": "伍佰"}
                )
            ),
        )
        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(result["results"][0]["status"], "ambiguous")

    def test_import_reuses_playlist_skips_existing_and_reverses_api_order(self):
        songs = {
            "One": {"id": 1, "name": "One", "artist": "A"},
            "Two": {"id": 2, "name": "Two", "artist": "B"},
            "Three": {"id": 3, "name": "Three", "artist": "C"},
        }

        def search(keyword, **_kwargs):
            return search_result(songs[keyword.split()[0]])

        add = Mock(return_value={"success": True, "added_count": 2})
        create = Mock()
        result = import_bgm_playlist(
            [
                {"name": "One", "artist": "A"},
                {"name": "Two", "artist": "B"},
                {"name": "Three", "artist": "C"},
            ],
            "BGM",
            today=date(2026, 8, 30),
            search_fn=search,
            get_playlists_fn=Mock(
                return_value={
                    "success": True,
                    "playlists": [
                        {"id": 99, "name": "20260830BGM", "is_mine": True}
                    ],
                }
            ),
            get_playlist_fn=Mock(
                return_value={"success": True, "songs": [{"id": 2}]}
            ),
            create_playlist_fn=create,
            add_tracks_fn=add,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["playlist_action"], "reused")
        self.assertEqual(result["added_track_ids_in_source_order"], [1, 3])
        add.assert_called_once_with(99, [3, 1])
        create.assert_not_called()

    def test_import_creates_nothing_without_safe_matches(self):
        create = Mock()
        result = import_bgm_playlist(
            [{"name": "Stay", "artist": ""}],
            search_fn=Mock(
                return_value=search_result(
                    {"id": 1, "name": "Stay", "artist": "A"},
                    {"id": 2, "name": "Stay", "artist": "B"},
                )
            ),
            create_playlist_fn=create,
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "no_safe_matches")
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
