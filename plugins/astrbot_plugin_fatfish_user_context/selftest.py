from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

from export import export_user
from store import (
    StoreError,
    UserContextStore,
    atomic_write_text,
    build_user_prompt,
    qq_user_hash,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_main_kb_lifecycle(store: UserContextStore, qq: str) -> None:
    class DecoratorFilter:
        def __getattr__(self, name):
            def register(*args, **kwargs):
                return lambda function: function

            return register

    class Logger:
        def info(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    class Star:
        pass

    class FakeSp:
        def __init__(self):
            self.values = {}

        async def session_get(self, umo, key, default=None):
            return copy.deepcopy(self.values.get((umo, key), default))

        async def session_put(self, umo, key, value):
            self.values[(umo, key)] = copy.deepcopy(value)

        async def session_remove(self, umo, key):
            self.values.pop((umo, key), None)

    class Event:
        def __init__(self, sender):
            self.sender = sender
            self.platform_name = "aiocqhttp"
            self.platform_id = "napcat-qq"
            self.unified_msg_origin = "test:private"

        def get_group_id(self):
            return None

        def get_platform_name(self):
            return self.platform_name

        def get_platform_id(self):
            return self.platform_id

        def get_sender_id(self):
            return self.sender

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event_module = types.ModuleType("astrbot.api.event")
    provider_module = types.ModuleType("astrbot.api.provider")
    star_module = types.ModuleType("astrbot.api.star")
    api.AstrBotConfig = dict
    api.logger = Logger()
    api.sp = FakeSp()
    event_module.AstrMessageEvent = Event
    event_module.filter = DecoratorFilter()
    provider_module.ProviderRequest = type("ProviderRequest", (), {})
    star_module.Context = type("Context", (), {})
    star_module.Star = Star
    star_module.register = lambda *args, **kwargs: lambda cls: cls
    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.event": event_module,
            "astrbot.api.provider": provider_module,
            "astrbot.api.star": star_module,
        }
    )

    spec = importlib.util.spec_from_file_location(
        "fatfish_user_context_main_test",
        Path(__file__).resolve().parent / "main.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake_sp = FakeSp()
    module.sp = fake_sp

    plugin = object.__new__(module.FatFishUserContext)
    plugin.config = {"enable": True, "top_k": 5}
    plugin.store = store
    plugin._kb_lock = asyncio.Lock()

    async def scenario():
        event = Event(qq)
        original = {"kb_ids": ["kb-original"], "top_k": 9}
        await fake_sp.session_put(event.unified_msg_origin, "kb_config", original)
        store.add_kb(qq, "kb-personal")
        await plugin._apply_kb(event)
        selected = await fake_sp.session_get(event.unified_msg_origin, "kb_config")
        check(selected["kb_ids"] == ["kb-personal"], "main must apply personal KB")
        state = await fake_sp.session_get(
            event.unified_msg_origin,
            module.KB_STATE_KEY,
        )
        check(state["previous"] == original, "main must preserve original KB config")

        bindings = store.read_bindings()
        del bindings["users"][qq_user_hash(qq)]
        atomic_write_text(
            store.bindings_path,
            json.dumps(bindings, ensure_ascii=False, indent=2) + "\n",
        )
        await plugin._apply_kb(event)
        restored = await fake_sp.session_get(event.unified_msg_origin, "kb_config")
        check(restored == original, "unbinding must restore original KB config")
        state = await fake_sp.session_get(
            event.unified_msg_origin,
            module.KB_STATE_KEY,
            default={},
        )
        check(not state, "unbinding must clear plugin state")

        never_bound = Event("10003")
        await plugin._apply_kb(never_bound)
        unchanged = await fake_sp.session_get(never_bound.unified_msg_origin, "kb_config")
        check(unchanged == original, "never-bound users must remain untouched")

        other_platform = Event(qq)
        other_platform.platform_name = "other"
        other_platform.platform_id = "third-party-qq"
        check(
            not plugin._is_qq_private(other_platform),
            "platform IDs containing qq are not trusted as QQ identities",
        )

    asyncio.run(scenario())


def main() -> None:
    test_parent = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(
        prefix=".selftest-",
        dir=test_parent,
    ) as temp:
        root = Path(temp)
        store = UserContextStore(root / "data")
        qq_a = "10001"
        qq_b = "10002"
        hash_a = qq_user_hash(qq_a)
        hash_b = qq_user_hash(qq_b)

        check(hash_a != hash_b, "different QQ accounts must have different hashes")
        check(len(hash_a) == 64, "full SHA-256 hash required")
        check(store.get_binding(qq_a) is None, "new user must start unbound")

        store.ensure_user(qq_a)
        check(store.load_document(qq_a, "intro") == "", "missing intro is allowed")
        check(store.load_document(qq_a, "memory") == "", "empty memory is allowed")

        store.write_document(qq_a, "intro", "这是用户 A 的基本介绍。")
        store.update_memory(qq_a, "回复保持简短。")
        docs_a = store.load_user_documents(qq_a)
        check(docs_a["intro"] == "这是用户 A 的基本介绍。", "intro round trip")
        check(docs_a["memory"] == "回复保持简短。", "memory round trip")

        check(store.add_kb(qq_a, "kb-family"), "first KB addition")
        check(not store.add_kb(qq_a, "kb-family"), "KB addition must be idempotent")
        check(store.add_kb(qq_a, "kb-general"), "second KB addition")
        check(store.remove_kb(qq_a, "kb-family"), "KB removal")
        check(not store.remove_kb(qq_a, "kb-family"), "KB removal must be idempotent")
        check(store.get_binding(qq_a)["kb_ids"] == ["kb-general"], "KB list content")
        store.remove_kb(qq_a, "kb-general")
        check(store.get_binding(qq_a)["kb_ids"] == [], "empty list means no KB")

        store.ensure_user(qq_b)
        store.write_document(qq_b, "intro", "这是用户 B 的基本介绍。")
        check(
            store.load_document(qq_b, "intro") == "这是用户 B 的基本介绍。",
            "users must remain isolated",
        )
        check(store.load_document(qq_b, "memory") == "", "memory must not leak")

        mismatch = store.document_path(qq_a, "memory")
        text = mismatch.read_text(encoding="utf-8").replace(hash_a, hash_b)
        mismatch.write_text(text, encoding="utf-8")
        try:
            store.load_document(qq_a, "memory")
        except StoreError:
            pass
        else:
            raise AssertionError("hash mismatch must be rejected")
        store.update_memory(qq_a, "修复后的记忆。")

        overlay = build_user_prompt(docs_a["intro"], docs_a["memory"])
        check("用户基本信息" in overlay, "intro prompt section")
        check("用户长期记忆" in overlay, "memory prompt section")
        check(build_user_prompt("", "") == "", "empty documents need no prompt")
        check("已截断" in build_user_prompt("x" * 50, "", max_intro_chars=10), "length cap")

        export_root = root / "exports"
        target = export_user(store, qq_a, export_root)
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        check(manifest["user_hash"] == hash_a, "export hash")
        check(qq_a not in json.dumps(manifest), "export must not contain raw QQ")
        check((target / "intro.md").exists(), "intro export")
        check((target / "memory.md").exists(), "memory export")
        check(
            (target / "memory.md").read_text(encoding="utf-8")
            == store.document_path(qq_a, "memory").read_text(encoding="utf-8"),
            "export must preserve the source document",
        )

        persisted = json.loads(store.bindings_path.read_text(encoding="utf-8"))
        check(persisted["version"] == 1, "binding schema version")
        check(set(persisted["users"]) == {hash_a, hash_b}, "binding isolation")
        check_main_kb_lifecycle(store, qq_a)

    print(
        "selftest ok: hash binding, isolation, empty files, KB add/remove, "
        "unbind restore, platform guard, export, prompt"
    )


if __name__ == "__main__":
    main()
