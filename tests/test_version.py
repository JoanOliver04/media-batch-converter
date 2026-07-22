import unittest

import conversion_report
import runtime_environment
from generate_version_info import render_version_info, version_tuple
from version import APP_NAME, APP_VERSION


class VersionMetadataTests(unittest.TestCase):
    def test_version_is_centralized(self) -> None:
        self.assertEqual(runtime_environment.APP_VERSION, APP_VERSION)
        self.assertEqual(conversion_report.APPLICATION_VERSION, APP_VERSION)

    def test_windows_metadata_uses_public_name_and_version(self) -> None:
        metadata = render_version_info()
        self.assertIn(APP_NAME, metadata)
        self.assertIn(f'"{APP_VERSION}"', metadata)
        self.assertEqual(version_tuple(APP_VERSION), (0, 1, 0, 0))


if __name__ == "__main__":
    unittest.main()
