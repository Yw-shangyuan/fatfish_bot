#!/usr/bin/env python3
"""Export persona assets from runtime storage into the source-backup tree.

Outputs (under /home/ubuntu/bot-src/persona):
  astrbot_personas.json        - rows of the AstrBot personas table
  knowledge_base/*.txt         - KB documents rebuilt from the chunk store
  plugin_configs/*.json        - plugin config files with credential fields masked
"""
import glob
import json
import os
import sqlite3

DATA = "/home/ubuntu/AstrBot/data"
OUT = "/home/ubuntu/bot-src/persona"
MASK_WORDS = (
    "sessdata", "bili_jct", "jct", "refresh_token", "token",
    "secret", "passw", "cookie", "api_key", "apikey", "webhook",
    "authorization", "dede_user_id",
)


def mask(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and v and any(w in str(k).lower() for w in MASK_WORDS):
                out[k] = "<MASKED>"
            else:
                out[k] = mask(v)
        return out
    if isinstance(obj, list):
        return [mask(v) for v in obj]
    return obj


def main():
    os.makedirs(os.path.join(OUT, "knowledge_base"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "plugin_configs"), exist_ok=True)

    # 1. personas table (AstrBot native persona storage)
    con = sqlite3.connect(os.path.join(DATA, "data_v4.db"))
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(personas)")]
        rows = [dict(zip(cols, r)) for r in con.execute("SELECT * FROM personas ORDER BY id")]
    except sqlite3.OperationalError as exc:
        print("WARN personas table unreadable:", exc)
        rows = []
    con.close()
    with open(os.path.join(OUT, "astrbot_personas.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)

    # 2. knowledge-base documents, rebuilt from per-kb chunk stores
    kbmeta = sqlite3.connect(os.path.join(DATA, "knowledge_base", "kb.db"))
    docs = kbmeta.execute("SELECT doc_id, kb_id, doc_name FROM kb_documents").fetchall()
    written = []
    for doc_id, kb_id, doc_name in docs:
        path = os.path.join(DATA, "knowledge_base", kb_id, "doc.db")
        if not os.path.exists(path):
            print("WARN chunk store missing:", path)
            continue
        dc = sqlite3.connect(path)
        chunks = dc.execute(
            "SELECT text, metadata FROM documents WHERE metadata LIKE ?",
            ("%" + doc_id + "%",),
        ).fetchall()
        dc.close()
        parsed = []
        for text, meta in chunks:
            try:
                idx = json.loads(meta).get("chunk_index", 0)
            except Exception:
                idx = 0
            parsed.append((idx, text))
        parsed.sort()
        full = ""
        for _, text in parsed:
            if not full:
                full = text
                continue
            overlap = 0
            n = min(80, len(full), len(text))
            for size in range(n, 0, -1):
                if full[-size:] == text[:size]:
                    overlap = size
                    break
            full += text[overlap:]
        safe = os.path.basename(doc_name).replace("/", "_")
        with open(os.path.join(OUT, "knowledge_base", safe), "w", encoding="utf-8") as fh:
            fh.write(full)
        written.append("knowledge_base/" + safe)
    kbmeta.close()

    # 3. plugin configs with credential fields masked
    for cf in glob.glob(os.path.join(DATA, "config", "astrbot_plugin_*config*.json")):
        name = os.path.basename(cf)
        if "bak" in name.lower():
            continue
        try:
            with open(cf, encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except Exception as exc:
            print("WARN skip", name, exc)
            continue
        with open(os.path.join(OUT, "plugin_configs", name), "w", encoding="utf-8") as fh:
            json.dump(mask(data), fh, ensure_ascii=False, indent=2)
        written.append("plugin_configs/" + name)

    print("persona export done:", ", ".join(written))


if __name__ == "__main__":
    main()
