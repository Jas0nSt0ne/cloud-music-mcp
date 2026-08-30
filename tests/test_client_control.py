import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from cloud_music_mcp import visible_client
from cloud_music_mcp.client_control import (
    ClientConfig,
    ClientControlError,
    ClientNotReadyError,
    NetEaseClientController,
    PlaybackResult,
    _click_script,
    _is_useful_visible_window,
    _navigate_to_playlist_script,
    _playlist_playall_script,
    _select_debug_target,
    _show_client_script,
    _state_script,
)
from cloud_music_mcp.windows_desktop import WindowInfo


def window(*, visible=True, width=1000, height=800):
    return WindowInfo(
        handle=1,
        process_id=2,
        class_name="OrpheusBrowserHost",
        title="Song - Artist",
        visible=visible,
        left=10,
        top=20,
        right=10 + width,
        bottom=20 + height,
    )


class ClientConfigTests(unittest.TestCase):
    def test_reads_debug_port_from_environment(self):
        with patch.dict(os.environ, {"CLOUD_MUSIC_DEBUG_PORT": "9333"}, clear=False):
            self.assertEqual(ClientConfig.from_env().debug_port, 9333)

    def test_rejects_invalid_debug_port(self):
        with patch.dict(os.environ, {"CLOUD_MUSIC_DEBUG_PORT": "70000"}, clear=False):
            with self.assertRaises(ClientControlError):
                ClientConfig.from_env()


class DebugTargetSelectionTests(unittest.TestCase):
    def target(self, url, target_id):
        return {
            "id": target_id,
            "url": url,
            "webSocketDebuggerUrl": f"ws://unused/{target_id}",
        }

    def test_prefers_main_app_when_subapp_is_listed_first(self):
        subapp = self.target(
            "orpheus://orpheus/pub/subApp.html?route=musicDesktop", "subapp"
        )
        main = self.target("orpheus://orpheus/pub/app.html", "main")

        self.assertIs(_select_debug_target([subapp, main]), main)

    def test_main_app_selection_does_not_depend_on_target_order(self):
        main = self.target("orpheus://orpheus/pub/app.html?startup=1", "main")
        subapp = self.target(
            "orpheus://orpheus/pub/subApp.html?route=musicDesktop", "subapp"
        )

        self.assertIs(_select_debug_target([main, subapp]), main)

    def test_ignores_subapp_when_main_app_is_not_ready(self):
        subapp = self.target(
            "orpheus://orpheus/pub/subApp.html?route=musicDesktop", "subapp"
        )

        self.assertIsNone(_select_debug_target([subapp]))


class WindowVerificationTests(unittest.TestCase):
    def test_visible_window_requires_real_size(self):
        self.assertTrue(_is_useful_visible_window(window()))
        self.assertFalse(_is_useful_visible_window(window(visible=False)))
        self.assertFalse(_is_useful_visible_window(window(width=1, height=1)))

    def test_hidden_desktop_target_has_specific_error(self):
        controller = NetEaseClientController(ClientConfig())
        with (
            patch.object(controller, "_get_debug_target", return_value={"id": "x"}),
            patch.object(controller, "_client_windows", return_value=[]),
        ):
            with self.assertRaises(ClientNotReadyError) as raised:
                controller._ensure_debug_target()
        self.assertEqual(raised.exception.code, "client_on_hidden_desktop")

    def test_missing_client_requests_visible_desktop_launcher(self):
        controller = NetEaseClientController(ClientConfig(launch_timeout=2.0))
        with (
            patch.object(
                controller,
                "_get_debug_target",
                side_effect=[None, {"id": "x"}],
            ),
            patch.object(controller, "_client_windows", side_effect=[[], [window()]]),
            patch.object(controller, "_request_visible_launcher") as request,
        ):
            target = controller._ensure_debug_target()
        request.assert_called_once_with()
        self.assertEqual(target["id"], "x")

    def test_status_requires_target_and_input_desktop_window(self):
        controller = NetEaseClientController(ClientConfig())
        with (
            patch.object(controller, "_get_debug_target", return_value={"id": "x"}),
            patch.object(controller, "_client_windows", return_value=[window()]),
            patch("cloud_music_mcp.client_control.current_desktop_name", return_value="Sandbox"),
            patch("cloud_music_mcp.client_control.input_desktop_name", return_value="Default"),
        ):
            status = controller.status()
        self.assertTrue(status["ready"])
        self.assertTrue(status["main_window_visible"])
        self.assertEqual(status["current_desktop"], "Sandbox")


class EventLoopBridgeTests(unittest.TestCase):
    def test_play_song_runs_inside_an_existing_event_loop(self):
        controller = NetEaseClientController(ClientConfig())
        expected = PlaybackResult(
            success=True,
            song_id="1",
            name="Song",
            artist="Artist",
            current="Song - Artist",
            client_visible=True,
        )

        async def invoke() -> dict[str, object]:
            with (
                patch.object(
                    controller,
                    "_ensure_debug_target",
                    return_value={"webSocketDebuggerUrl": "ws://unused"},
                ),
                patch.object(
                    controller,
                    "_play_song_async",
                    new=AsyncMock(return_value=expected),
                ) as play,
            ):
                result = controller.play_song("1", "Song", "Artist")
                play.assert_awaited_once_with("ws://unused", "1", "Song", "Artist")
                return result

        result = asyncio.run(invoke())
        self.assertTrue(result["success"])
        self.assertEqual(result["song_id"], "1")


class VisibleLauncherRequestTests(unittest.TestCase):
    def test_request_starts_background_helper_on_default_desktop(self):
        controller = NetEaseClientController(ClientConfig())
        with (
            patch(
                "cloud_music_mcp.client_control.launch_process_on_desktop"
            ) as launch,
            patch("cloud_music_mcp.client_control.Path.is_file", return_value=False),
        ):
            controller._request_visible_launcher()

        command = launch.call_args.args[0]
        self.assertEqual(
            command[1:],
            ["-m", "cloud_music_mcp.visible_client", "--background"],
        )
        self.assertEqual(launch.call_args.kwargs["desktop_name"], "Default")

    def test_background_helper_suppresses_success_output(self):
        with (
            patch("sys.argv", ["netease-cloud-music-mcp-client", "--background"]),
            patch.object(
                visible_client,
                "launch_visible_client",
                return_value={"success": True, "already_running": False},
            ) as launch,
            patch("builtins.print") as output,
        ):
            visible_client.main()

        launch.assert_called_once_with()
        output.assert_not_called()


class JavascriptTests(unittest.TestCase):
    def test_click_script_contains_id_and_unicode(self):
        script = _click_script("123", 'A "Song"', "歌手 / Guest")
        self.assertIn('const wantedId = "123"', script)
        self.assertIn("歌手 / Guest", script)
        self.assertIn("matchedBy", script)

    def test_state_script_prefers_song_id(self):
        script = _state_script("456", "Song", "Artist")
        self.assertIn('currentId === "456"', script)
        self.assertIn("textMatches", script)

    def test_show_script_exposes_page_readiness(self):
        script = _show_client_script()
        self.assertIn("page_not_ready", script)
        self.assertIn("hasNative", script)
        self.assertIn("hasSearch", script)

    def test_playlist_scripts_verify_target_id(self):
        navigation = _navigate_to_playlist_script("123")
        playall = _playlist_playall_script("123")
        self.assertIn('const wanted = "123"', navigation)
        self.assertIn("s_playlistId", playall)
        self.assertIn("播放按钮不属于目标歌单", playall)


if __name__ == "__main__":
    unittest.main()
