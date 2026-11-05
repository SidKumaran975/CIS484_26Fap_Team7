"""Startup allows faculty to supply their own avatar through the portal."""
import unittest
from unittest.mock import patch

import pipeline


class PreflightTests(unittest.TestCase):
    def test_missing_default_avatar_does_not_block_startup(self):
        with patch.object(pipeline, "MEDIA_MODE", "avatar"), \
             patch.object(pipeline.Path, "exists", return_value=True), \
             patch.object(pipeline.Path, "is_file", return_value=False), \
             self.assertLogs("pipeline", level="WARNING") as logs:
            pipeline.preflight()
        self.assertIn("Professor avatar", logs.output[0])

    def test_missing_required_component_still_blocks_startup(self):
        with patch.object(pipeline.Path, "exists", return_value=False):
            with self.assertRaisesRegex(SystemExit, "Preflight failed"):
                pipeline.preflight()
