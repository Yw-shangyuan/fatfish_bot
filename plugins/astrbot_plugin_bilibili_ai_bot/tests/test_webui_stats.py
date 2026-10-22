import asyncio
import unittest
from datetime import datetime

from core import webui_bridge


class FakeMemoryAPI:
    def stats(self):
        return {"total": 0}


class FakePlugin:
    def __init__(self, values):
        self._values = values
        self.config = {
            "SESSDATA": "configured",
            "PROACTIVE_DAILY_LIMIT": 50,
            "PROACTIVE_COMMENT_DAILY_LIMIT": 2,
            "AUTONOMOUS_ACTIVITY_LEVEL": 55,
        }
        self._running = True
        self._memory = []
        self.memory_api = FakeMemoryAPI()
        self.event_runtime = None
        self.layered_runtime = None

    def _load_json(self, path, default):
        return self._values.get(path, default)

    def _get_schedule_snapshot(self):
        return {}


class WebuiStatsTests(unittest.TestCase):
    def test_proactive_watch_and_comment_are_split(self):
        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        plugin = FakePlugin({
            webui_bridge.WATCH_LOG_FILE: [{"time": today, "title": "watched"}],
            webui_bridge.PROACTIVE_LOG_FILE: [],
        })
        original_response = webui_bridge._response
        webui_bridge._response = lambda data=None, message=None: data
        try:
            stats = asyncio.run(webui_bridge.handle_get_stats(plugin))
        finally:
            webui_bridge._response = original_response

        self.assertEqual(stats["proactive_watch_used"], 1)
        self.assertEqual(stats["proactive_watch_max"], 50)
        self.assertEqual(stats["proactive_comment_used"], 0)
        self.assertEqual(stats["proactive_comment_max"], 2)
        self.assertEqual(stats["proactive_used"], 0)
        self.assertEqual(stats["proactive_max"], 50)


if __name__ == "__main__":
    unittest.main()
