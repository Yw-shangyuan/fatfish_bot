import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


def _ensure_astrbot_stub():
    astrbot = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
    api = sys.modules.setdefault("astrbot.api", types.ModuleType("astrbot.api"))
    api.logger = _Logger()
    astrbot.api = api
    # core/bilibili.py 在模块级 import aiohttp，但只在函数体内使用；
    # 测试环境没装 aiohttp 时用空模块兜底，不影响已安装的环境。
    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))


def _make_package(package_name):
    package = sys.modules.setdefault(package_name, types.ModuleType(package_name))
    package.__path__ = [str(ROOT / "core")]
    return package


def _load_module(package_name, name, filename):
    module_name = f"{package_name}.{name}"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "core" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_bilibili_module():
    _ensure_astrbot_stub()
    package_name = "comment_context_bilibili_core"
    _make_package(package_name)

    config = types.ModuleType(f"{package_name}.config")
    for name in (
        "BILI_COOKIE_CONFIRM_URL", "BILI_COOKIE_INFO_URL", "BILI_COOKIE_REFRESH_URL",
        "BILI_DYNAMIC_IMAGE_URL", "BILI_DYNAMIC_TEXT_URL", "BILI_NAV_URL",
        "BILI_PRIVATE_MSG_SEND_URL", "BILI_QR_GENERATE_URL", "BILI_QR_POLL_URL",
        "BILI_REPLY_URL", "BILI_UPLOAD_IMAGE_URL",
    ):
        setattr(config, name, "https://example.test")
    config.BILI_RSA_PUBLIC_KEY = ""
    config.MIXIN_KEY_ENC_TAB = []
    config.USER_AGENT = "test"
    sys.modules[config.__name__] = config

    return _load_module(package_name, "bilibili", "bilibili.py")


def _load_reply_module():
    _ensure_astrbot_stub()
    package_name = "comment_context_reply_core"
    _make_package(package_name)

    config = types.ModuleType(f"{package_name}.config")
    config.AFFECTION_FILE = ""
    config.DATA_DIR = ""
    config.LEVEL_NAMES = {"stranger": "陌生人"}
    config.REPLIED_AT_FILE = ""
    config.REPLIED_FILE = ""
    config.REPLIED_CONTENT_KEYS_FILE = ""
    config.REPLY_LOG_FILE = ""
    config.BILI_AT_NOTIFY_URL = "https://example.test/at"
    config.BILI_NOTIFY_URL = "https://example.test/reply"
    config.VIDEO_MEMORY_FILE = ""
    sys.modules[config.__name__] = config

    _load_module(package_name, "output_protocol", "output_protocol.py")
    _load_module(package_name, "runtime", "runtime.py")
    return _load_module(package_name, "reply", "reply.py")


_DETAIL = {
    "code": 0,
    "data": {
        "root": {
            "rpid": 100,
            "member": {"uname": "老王"},
            "content": {"message": "视频太棒了"},
            "replies": [
                {"rpid": 200, "member": {"uname": "小明"}, "content": {"message": "同意楼主"}},
                {"rpid": 300, "member": {"uname": "路人"}, "content": {"message": "楼中楼回复"}},
            ],
        },
    },
}


def _client(module, payload=None, raises=False, max_chars=300):
    calls = []

    class Client(module.BilibiliAPIMixin):
        def __init__(self):
            self.config = {"PARENT_COMMENT_CONTEXT_MAX_CHARS": max_chars}

        async def _http_get(self, url, params=None, **_kwargs):
            calls.append((url, params))
            if raises:
                raise RuntimeError("network down")
            return payload, None

    return Client(), calls


class CommentContextFetchTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_bilibili_module()

    async def test_parses_root_and_parent_comment(self):
        client, calls = _client(self.module, payload=_DETAIL)
        context = await client._get_comment_context(
            123, 1, root_rpid="100", parent_rpid="200"
        )
        self.assertEqual(context, "楼主 老王：视频太棒了\n上一层 小明：同意楼主")
        url, params = calls[0]
        self.assertEqual(url, "https://api.bilibili.com/x/v2/reply/detail")
        self.assertEqual(params["root"], "100")
        self.assertEqual(params["oid"], 123)
        self.assertEqual(params["type"], 1)

    async def test_parent_equal_to_root_is_not_duplicated(self):
        client, _ = _client(self.module, payload=_DETAIL)
        context = await client._get_comment_context(
            123, 1, root_rpid="100", parent_rpid="100"
        )
        self.assertEqual(context, "楼主 老王：视频太棒了")

    async def test_context_is_truncated_to_configured_limit(self):
        client, _ = _client(self.module, payload=_DETAIL, max_chars=10)
        context = await client._get_comment_context(
            123, 1, root_rpid="100", parent_rpid="200"
        )
        self.assertEqual(len(context), 11)
        self.assertTrue(context.endswith("…"))

    async def test_second_call_uses_memory_cache(self):
        client, calls = _client(self.module, payload=_DETAIL)
        first = await client._get_comment_context(123, 1, root_rpid="100")
        second = await client._get_comment_context(123, 1, root_rpid="100")
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)

    async def test_http_failure_degrades_to_empty_string(self):
        client, _ = _client(self.module, raises=True)
        context = await client._get_comment_context(123, 1, root_rpid="100")
        self.assertEqual(context, "")

    async def test_missing_root_rpid_skips_http(self):
        client, calls = _client(self.module, payload=_DETAIL)
        context = await client._get_comment_context(123, 1)
        self.assertEqual(context, "")
        self.assertEqual(calls, [])


_VALID_ENVELOPE = json.dumps({
    "decision": "reply",
    "reply": "收到啦",
    "score_delta": 1,
    "impression": "",
    "user_facts": [],
    "signals": {
        "interaction_type": "normal",
        "feedback_type": "none",
        "attack_level": 0,
        "feedback_topic": None,
        "reflection_candidate": None,
        "confidence": 0.5,
    },
    "tool_request": {"name": "none", "query": ""},
}, ensure_ascii=False)


class _StubBot:
    def __init__(self, module):
        self.config = {}
        self._affection = {}
        self.captured_prompts = []
        self.sanitized = []
        self._reply_module = module

    async def _get_system_prompt(self):
        return ""

    def _is_owner(self, mid):
        return False

    def _get_level(self, cs, mid):
        return "stranger"

    def _get_level_prompts(self):
        return {"stranger": "友善自然"}

    def _sanitize_user_input(self, content, username, mid):
        self.sanitized.append(str(content))
        return str(content), False, ""

    @staticmethod
    def _wrap_user_content(content):
        return f"<user_comment>\n{content}\n</user_comment>"

    async def _build_memory_context(self, *_args, **_kwargs):
        return ""

    async def _relevant_feedback_context(self, *_args, **_kwargs):
        return ""

    def _get_today_mood(self):
        return ("平静", "保持自然")

    def _get_festival_prompt(self):
        return ""

    def _get_personality_prompt(self, content):
        return ""

    async def _llm_call(self, prompt, system_prompt="", **_kwargs):
        self.captured_prompts.append(prompt)
        return _VALID_ENVELOPE


class ThreadContextPromptTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_reply_module()

    def _bot(self):
        class Bot(_StubBot, self.module.ReplyMixin):
            pass
        return Bot(self.module)

    async def test_context_injected_before_target_comment(self):
        bot = self._bot()
        result = await bot._generate_reply(
            "这层说得对", "999", "路人甲", "t1", 123, 1,
            thread_context="楼主 老王：视频太棒了\n上一层 小明：同意楼主",
        )
        self.assertEqual(result["decision"], "reply")
        prompt = bot.captured_prompts[-1]
        self.assertIn("【楼中楼上下文】", prompt)
        self.assertIn("楼主 老王：视频太棒了", prompt)
        # 上下文是背景，必须出现在待回复评论之前
        self.assertLess(prompt.index("楼主 老王"), prompt.index("你现在要回复"))
        # 父评论内容经过了用户输入消毒
        self.assertIn("楼主 老王：视频太棒了\n上一层 小明：同意楼主", bot.sanitized)

    async def test_context_not_injected_for_private_channel(self):
        bot = self._bot()
        await bot._generate_reply(
            "你好", "999", "路人甲", "t1", 123, 1,
            channel="private",
            thread_context="楼主 老王：视频太棒了",
        )
        prompt = bot.captured_prompts[-1]
        self.assertNotIn("【楼中楼上下文】", prompt)
        self.assertNotIn("楼主 老王", prompt)

    async def test_empty_context_leaves_prompt_unchanged(self):
        bot = self._bot()
        await bot._generate_reply("这层说得对", "999", "路人甲", "t1", 123, 1)
        prompt = bot.captured_prompts[-1]
        self.assertNotIn("【楼中楼上下文】", prompt)


if __name__ == "__main__":
    unittest.main()
