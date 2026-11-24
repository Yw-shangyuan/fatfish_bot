#!/usr/bin/env python3
"""Create an online, per-file consistent snapshot of FatFish memory data."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

DB_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
EXCLUDED_DIRS = {".git", "__pycache__", "logs", "node_modules"}
ASTRBOT_EXCLUDED_TOP_LEVEL = {"dist", "plugins", "temp", "workspaces"}
EXCLUDED_FILES = {"dashboard.zip", "vnc-password"}
MAX_ATTEMPTS = 5


def is_db_sidecar(name: str) -> bool:
    lower = name.lower()
    return any(
        lower.endswith(suffix + sidecar)
        for suffix in DB_SUFFIXES
        for sidecar in ("-wal", "-shm")
    )


def is_excluded_file(path: Path) -> bool:
    lower = path.name.lower()
    return (
        lower in EXCLUDED_FILES
        or lower.endswith((".log", ".pyc", ".tmp"))
        or ".bak" in lower
        or is_db_sidecar(lower)
    )


def source_signature(path: Path) -> tuple[int, int]:
    info = path.stat()
    return info.st_size, info.st_mtime_ns


def preserve_metadata(source: Path, destination: Path) -> None:
    shutil.copystat(source, destination, follow_symlinks=False)


def copy_stable_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(MAX_ATTEMPTS):
        before = source_signature(source)
        with source.open("rb") as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        after = source_signature(source)
        if before == after:
            preserve_metadata(source, destination)
            return
        if attempt + 1 < MAX_ATTEMPTS:
            time.sleep(0.2 * (attempt + 1))
    raise RuntimeError(f"Source file kept changing during backup: {source}")


def copy_json_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            before = source_signature(source)
            payload = source.read_bytes()
            after = source_signature(source)
            if before != after:
                raise RuntimeError("source changed while reading")
            json.loads(payload.decode("utf-8-sig"))
            destination.write_bytes(payload)
            preserve_metadata(source, destination)
            return
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < MAX_ATTEMPTS:
                time.sleep(0.2 * (attempt + 1))
    raise RuntimeError(f"Unable to snapshot valid JSON file: {source}: {last_error}")


def backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise RuntimeError(f"Database file is not SQLite 3: {source}")

    uri = "file:" + quote(str(source.resolve()), safe="/") + "?mode=ro"
    src = sqlite3.connect(uri, uri=True, timeout=30)
    dst = sqlite3.connect(str(destination), timeout=30)
    try:
        src.execute("PRAGMA busy_timeout = 30000")
        src.execute("PRAGMA query_only = ON")
        src.backup(dst, pages=256, sleep=0.1)
        rows = dst.execute("PRAGMA integrity_check").fetchall()
        if not rows or any(row[0].lower() != "ok" for row in rows):
            raise RuntimeError(f"SQLite integrity_check failed for {source}: {rows}")
    finally:
        dst.close()
        src.close()
    preserve_metadata(source, destination)


def snapshot_file(source: Path, destination: Path) -> str:
    if source.is_symlink():
        raise RuntimeError(f"Refusing to follow symbolic link: {source}")
    suffix = source.suffix.lower()
    if suffix in DB_SUFFIXES:
        backup_sqlite(source, destination)
        return "sqlite"
    if suffix == ".json":
        copy_json_file(source, destination)
    else:
        copy_stable_file(source, destination)
    return "file"


def snapshot_tree(
    source_root: Path,
    archive_root: Path,
    excluded_top_level: set[str],
    counters: dict[str, int],
    databases: list[str],
    snapshot_root: Path,
) -> None:
    if not source_root.is_dir():
        raise FileNotFoundError(f"Required source directory is missing: {source_root}")

    for root, dirs, files in os.walk(source_root, followlinks=False):
        root_path = Path(root)
        filtered = []
        for name in dirs:
            path = root_path / name
            if name in EXCLUDED_DIRS or path.is_symlink():
                continue
            if root_path == source_root and name in excluded_top_level:
                continue
            filtered.append(name)
        dirs[:] = sorted(filtered)

        for name in sorted(files):
            source = root_path / name
            if is_excluded_file(source):
                continue
            relative = source.relative_to(source_root)
            destination = archive_root / relative
            kind = snapshot_file(source, destination)
            counters["files"] += 1
            counters["bytes"] += destination.stat().st_size
            if kind == "sqlite":
                counters["databases"] += 1
                databases.append(str(destination.relative_to(snapshot_root)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--astrbot-data",
        type=Path,
        default=Path("/home/ubuntu/AstrBot/data"),
    )
    parser.add_argument(
        "--snowluma-config",
        type=Path,
        default=Path("/srv/snowluma/data/config"),
    )
    parser.add_argument(
        "--service-file",
        type=Path,
        default=Path("/etc/systemd/system/astrbot.service"),
    )
    args = parser.parse_args()

    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise RuntimeError(f"Destination directory must be empty: {destination}")

    counters = {"files": 0, "databases": 0, "bytes": 0}
    databases: list[str] = []
    snapshot_tree(
        args.astrbot_data,
        destination / "home/ubuntu/AstrBot/data",
        ASTRBOT_EXCLUDED_TOP_LEVEL,
        counters,
        databases,
        destination,
    )
    snapshot_tree(
        args.snowluma_config,
        destination / "srv/snowluma/data/config",
        set(),
        counters,
        databases,
        destination,
    )

    if args.service_file:
        if not args.service_file.is_file():
            raise FileNotFoundError(f"Required service file is missing: {args.service_file}")
        target = destination / "etc/systemd/system/astrbot.service"
        snapshot_file(args.service_file, target)
        counters["files"] += 1
        counters["bytes"] += target.stat().st_size

    manifest = {
        "format_version": 1,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "consistency": "per-file online snapshot; SQLite uses the online backup API",
        "qq_runtime_or_login_state_included": False,
        "napcat_included": False,
        "files": counters["files"],
        "databases": counters["databases"],
        "bytes": counters["bytes"],
        "sqlite_files": databases,
    }
    (destination / "BACKUP-MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
