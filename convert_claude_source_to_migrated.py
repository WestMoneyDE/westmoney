#!/usr/bin/env python3
import json, zipfile, sqlite3
from pathlib import Path
from datetime import datetime

SRC_ZIP = "claude_source_export.zip"
OUT_SQLITE = "claude_export.sqlite"
OUT_ZIP = "claude_migrated_export.zip"

def first_key(d, keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default

def norm_ts(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.utcfromtimestamp(v).isoformat() + "Z"
        except Exception:
            return str(v)
    return str(v)

def ensure_schema(conn):
    conn.executescript("""
    DROP TABLE IF EXISTS conversations;
    DROP TABLE IF EXISTS messages;
    DROP TABLE IF EXISTS message_content;
    DROP TABLE IF EXISTS attachments;
    DROP TABLE IF EXISTS files;
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS projects;
    DROP TABLE IF EXISTS project_docs;
    DROP TABLE IF EXISTS memories;
    DROP TABLE IF EXISTS project_memories;

    CREATE TABLE conversations (
        conversation_uuid TEXT PRIMARY KEY,
        name TEXT,
        created_at TEXT,
        updated_at TEXT,
        messages INTEGER,
        human_messages INTEGER,
        assistant_messages INTEGER,
        text_characters INTEGER
    );

    CREATE TABLE messages (
        conversation_uuid TEXT,
        conversation_name TEXT,
        conversation_summary TEXT,
        conversation_created_at TEXT,
        conversation_updated_at TEXT,
        account TEXT,
        message_index INTEGER,
        message_uuid TEXT PRIMARY KEY,
        sender TEXT,
        text TEXT,
        message_created_at TEXT,
        message_updated_at TEXT
    );

    CREATE TABLE message_content (
        conversation_uuid TEXT,
        message_uuid TEXT,
        content_index INTEGER,
        type TEXT,
        text TEXT,
        start_timestamp TEXT,
        stop_timestamp TEXT,
        flags TEXT,
        citations TEXT,
        PRIMARY KEY(message_uuid, content_index)
    );

    CREATE TABLE attachments (
        conversation_uuid TEXT,
        message_uuid TEXT,
        attachment_index INTEGER,
        file_name TEXT,
        file_size INTEGER,
        file_type TEXT,
        extracted_content TEXT,
        PRIMARY KEY(message_uuid, attachment_index)
    );

    CREATE TABLE files (
        conversation_uuid TEXT,
        message_uuid TEXT,
        file_index INTEGER,
        file_name TEXT,
        PRIMARY KEY(message_uuid, file_index)
    );

    CREATE TABLE users (
        uuid TEXT PRIMARY KEY,
        full_name TEXT,
        email_address TEXT,
        verified_phone_number TEXT
    );

    CREATE TABLE projects (
        uuid TEXT PRIMARY KEY,
        name TEXT,
        description TEXT,
        is_private INTEGER,
        is_starter_project INTEGER,
        prompt_template TEXT,
        created_at TEXT,
        updated_at TEXT,
        creator_uuid TEXT,
        creator_full_name TEXT
    );

    CREATE TABLE project_docs (
        project_uuid TEXT,
        doc_uuid TEXT,
        filename TEXT,
        created_at TEXT,
        content TEXT,
        PRIMARY KEY(project_uuid, doc_uuid)
    );

    CREATE TABLE memories (
        account_uuid TEXT PRIMARY KEY,
        conversations_memory TEXT
    );

    CREATE TABLE project_memories (
        account_uuid TEXT,
        project_uuid TEXT,
        project_memory TEXT,
        PRIMARY KEY(account_uuid, project_uuid)
    );
    """)
    conn.commit()

def msg_text_from_any(m):
    t = first_key(m, ["text", "content_text", "message", "body"], None)
    if isinstance(t, str) and t.strip():
        return t
    c = first_key(m, ["content", "contents", "blocks"], None)
    if isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                bt = first_key(b, ["text", "content", "value"], None)
                if isinstance(bt, str):
                    parts.append(bt)
        joined = "\n".join([p for p in parts if p and p.strip()])
        if joined.strip():
            return joined
    return ""

def content_blocks_from_any(m):
    c = first_key(m, ["content", "contents", "blocks"], None)
    if isinstance(c, list) and c:
        blocks = []
        for b in c:
            if isinstance(b, str):
                blocks.append({"type": "text", "text": b})
            elif isinstance(b, dict):
                blocks.append({
                    "type": first_key(b, ["type", "kind"], "unknown"),
                    "text": first_key(b, ["text", "content", "value"], "")
                })
        return blocks
    return [{"type": "text", "text": msg_text_from_any(m)}]

def iter_messages_from_conversation(conv):
    for key in ["messages", "chat_messages", "conversation_messages", "items", "turns"]:
        v = conv.get(key) if isinstance(conv, dict) else None
        if isinstance(v, list):
            return v
    return []

def main():
    if not Path(SRC_ZIP).exists():
        raise SystemExit(f"[ERROR] Missing {SRC_ZIP}")

    with zipfile.ZipFile(SRC_ZIP, "r") as z:
        conversations = json.loads(z.read("conversations.json").decode("utf-8", errors="replace"))
        users = json.loads(z.read("users.json").decode("utf-8", errors="replace"))
        projects = json.loads(z.read("projects.json").decode("utf-8", errors="replace"))
        memories = json.loads(z.read("memories.json").decode("utf-8", errors="replace"))

    if isinstance(conversations, dict):
        for k in ["conversations", "data", "items"]:
            if k in conversations and isinstance(conversations[k], list):
                conversations = conversations[k]
                break

    if not isinstance(conversations, list):
        raise SystemExit("[ERROR] conversations.json format not recognized (expected list).")

    if Path(OUT_SQLITE).exists():
        Path(OUT_SQLITE).unlink()

    conn = sqlite3.connect(OUT_SQLITE)
    ensure_schema(conn)

    for conv in conversations:
        if not isinstance(conv, dict):
            continue
        conv_id = first_key(conv, ["uuid", "id", "conversation_uuid", "conversation_id"], None)
        if not conv_id:
            continue

        name = first_key(conv, ["name", "title", "conversation_name"], "")
        created_at = norm_ts(first_key(conv, ["created_at", "createdAt", "created", "create_time"], None))
        updated_at = norm_ts(first_key(conv, ["updated_at", "updatedAt", "updated", "update_time"], None))
        summary = first_key(conv, ["summary", "conversation_summary"], None)

        msgs = iter_messages_from_conversation(conv)
        human = assistant = total_chars = 0

        for idx, m in enumerate(msgs):
            if not isinstance(m, dict):
                continue
            mid = first_key(m, ["uuid", "id", "message_uuid", "message_id"], None) or f"{conv_id}:{idx}"
            sender = first_key(m, ["sender", "role", "author", "type"], "")
            if isinstance(sender, dict):
                sender = first_key(sender, ["role", "type", "name"], "")
            sender = str(sender).lower()

            if sender in ("human", "user"):
                human += 1
            elif sender in ("assistant", "claude", "bot"):
                assistant += 1

            m_created = norm_ts(first_key(m, ["created_at", "createdAt", "created", "timestamp"], None))
            m_updated = norm_ts(first_key(m, ["updated_at", "updatedAt", "updated"], None))

            text = msg_text_from_any(m)
            total_chars += len(text or "")

            conn.execute("""
                INSERT OR REPLACE INTO messages
                (conversation_uuid, conversation_name, conversation_summary, conversation_created_at, conversation_updated_at,
                 account, message_index, message_uuid, sender, text, message_created_at, message_updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (conv_id, name, summary, created_at, updated_at, None, idx, mid, sender, text, m_created, m_updated))

            for bidx, b in enumerate(content_blocks_from_any(m)):
                conn.execute("""
                    INSERT OR REPLACE INTO message_content
                    (conversation_uuid, message_uuid, content_index, type, text, start_timestamp, stop_timestamp, flags, citations)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (conv_id, mid, bidx, first_key(b, ["type"], "unknown"), first_key(b, ["text"], ""), None, None, None, None))

        conn.execute("""
            INSERT OR REPLACE INTO conversations
            (conversation_uuid, name, created_at, updated_at, messages, human_messages, assistant_messages, text_characters)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (conv_id, name, created_at, updated_at, len(msgs), human, assistant, total_chars))

    # optional: store the whole memories blob
    if isinstance(memories, dict):
        conn.execute("INSERT OR REPLACE INTO memories(account_uuid, conversations_memory) VALUES (?,?)",
                     (first_key(memories, ["account_uuid","uuid","id"], "unknown"), json.dumps(memories, ensure_ascii=False)))

    conn.commit()
    conn.close()

    # Create zip for the importer (must contain claude_export.sqlite)
    if Path(OUT_ZIP).exists():
        Path(OUT_ZIP).unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(OUT_SQLITE, arcname="claude_export.sqlite")

    print("[OK] Created:", OUT_SQLITE)
    print("[OK] Created:", OUT_ZIP)

if __name__ == "__main__":
    main()
