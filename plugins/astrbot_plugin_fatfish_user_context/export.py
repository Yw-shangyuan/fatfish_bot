from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from store import StoreError, UserContextStore, atomic_write_text, now_iso, qq_user_hash


def export_user(
    store: UserContextStore,
    qq: str,
    export_root: str | Path,
) -> Path:
    user_hash = qq_user_hash(qq)
    binding = store.get_binding_by_hash(user_hash)
    if binding is None:
        raise StoreError("该 QQ 尚未绑定，没有可导出的用户配置")

    # Validate both documents before copying any source bytes.
    store.load_user_documents(qq)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    target = Path(export_root) / f"{stamp}-{user_hash[:12]}"
    target.mkdir(parents=True, exist_ok=False)

    exported_files = []
    for kind in ("intro", "memory"):
        source = store.document_path(qq, kind)
        if not source.exists():
            continue
        output = target / f"{kind}.md"
        atomic_write_text(output, source.read_text(encoding="utf-8"))
        exported_files.append(output.name)

    manifest = {
        "schema_version": 1,
        "user_hash": user_hash,
        "enabled": binding["enabled"],
        "kb_ids": binding["kb_ids"],
        "exported_at": now_iso(),
        "files": exported_files,
        "note": "The source QQ number is intentionally not included.",
    }
    atomic_write_text(
        target / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Export one user's profile and memory.")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--qq", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    target = export_user(
        UserContextStore(args.data_dir),
        args.qq,
        args.output_dir,
    )
    print(target)


if __name__ == "__main__":
    main()
