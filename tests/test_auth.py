import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from cloud_music_mcp import auth


class StorageTests(unittest.TestCase):
    def temporary_directory(self):
        return tempfile.TemporaryDirectory(dir=Path(__file__).parent)

    def test_new_data_dir_environment_variable_takes_precedence(self):
        with self.temporary_directory() as preferred, self.temporary_directory() as legacy:
            with patch.dict(
                os.environ,
                {
                    auth.DATA_DIR_ENV: preferred,
                    auth.LEGACY_DATA_DIR_ENV: legacy,
                },
                clear=False,
            ):
                self.assertEqual(auth.get_storage_dir(), Path(preferred).resolve())

    def test_legacy_data_dir_environment_variable_remains_supported(self):
        with self.temporary_directory() as legacy:
            with patch.dict(
                os.environ,
                {auth.LEGACY_DATA_DIR_ENV: legacy},
                clear=False,
            ):
                os.environ.pop(auth.DATA_DIR_ENV, None)
                self.assertEqual(auth.get_storage_dir(), Path(legacy).resolve())

    def test_loading_session_clears_stale_cookies(self):
        with self.temporary_directory() as directory:
            cookie_file = Path(directory) / "cookies.json"
            cookie_file.write_text(
                json.dumps({"MUSIC_U": "replacement"}), encoding="utf-8"
            )
            session = requests.Session()
            session.cookies.set("stale", "value")

            with patch.dict(os.environ, {auth.DATA_DIR_ENV: directory}, clear=False):
                with patch.object(auth, "GetCurrentSession", return_value=session):
                    loaded, nickname = auth.load_session(verify=False)

            self.assertTrue(loaded)
            self.assertIsNone(nickname)
            self.assertEqual(session.cookies.get_dict(), {"MUSIC_U": "replacement"})


if __name__ == "__main__":
    unittest.main()
