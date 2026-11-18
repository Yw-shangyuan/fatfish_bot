#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publish one file to the temporary download port of the fatfish panel.

Usage:
    python3 dropfile.py <path> [minutes] [--name 别名] [--host 1.2.3.4] [--port 8765]

Creates /home/ubuntu/ops/drop/<random-token>/<file> with a .meta.json holding
the expiry. The portal's background cleaner deletes the folder when it lapses.
"""
import argparse
import json
import os
import secrets
import shutil
import sys
import time
from urllib.parse import quote

DROP_DIR = "/home/ubuntu/ops/drop"
DEFAULT_PORT = 8765
DEFAULT_HOST_FILE = "/home/ubuntu/ops/drop/.host"


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0


def default_host():
    try:
        with open(DEFAULT_HOST_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "127.0.0.1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("minutes", nargs="?", type=float, default=20)
    ap.add_argument("--name", default="")
    ap.add_argument("--host", default="")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    src = os.path.abspath(args.path)
    if not os.path.isfile(src):
        sys.exit(f"不是文件：{src}")
    if not 1 <= args.minutes <= 1440:
        sys.exit("分钟数要在 1 到 1440 之间")

    name = os.path.basename(args.name or src)
    name = name.replace("/", "_")
    token = secrets.token_hex(16)
    folder = os.path.join(DROP_DIR, token)
    os.makedirs(folder, mode=0o711, exist_ok=False)
    dst = os.path.join(folder, name)
    try:
        os.link(src, dst)          # same filesystem: instant, no extra space
    except OSError:
        shutil.copyfile(src, dst)
    os.chmod(dst, 0o644)

    meta = {
        "name": name,
        "size": os.path.getsize(dst),
        "source": src,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "expires": time.time() + args.minutes * 60,
    }
    with open(os.path.join(folder, ".meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    os.chmod(os.path.join(folder, ".meta.json"), 0o644)

    host = args.host or default_host()
    print(f"文件：{name}（{human(meta['size'])}）")
    print(f"有效期：{args.minutes:g} 分钟")
    print(f"链接：http://{host}:{args.port}/f/{token}/{quote(name)}")


if __name__ == "__main__":
    main()
