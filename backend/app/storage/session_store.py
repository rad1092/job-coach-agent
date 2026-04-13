from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "job_coach.db"


def _connect(data_dir: Path) -> sqlite3.Connection:
    path = _db_path(data_dir)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    _initialize_schema(connection)
    return connection


def _initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            latest_stage TEXT,
            selected_target_json TEXT,
            metadata_json TEXT
        );

        CREATE TABLE IF NOT EXISTS stage_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            request_json TEXT,
            response_json TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_stage_snapshots_run_stage
        ON stage_snapshots(run_id, stage, id DESC);

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            meta_json TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chat_messages_run_id
        ON chat_messages(run_id, id ASC);
        """
    )
    connection.commit()


def persist_run_artifact(data_dir: Path, run_id: str, name: str, payload: dict[str, Any]) -> Path:
    run_dir = data_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def persist_stage_snapshot(
    data_dir: Path,
    run_id: str,
    stage: str,
    request_payload: dict[str, Any] | None,
    response_payload: dict[str, Any] | None,
    *,
    selected_target: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    timestamp = _utcnow()
    with _connect(data_dir) as connection:
        connection.execute(
            """
            INSERT INTO runs(run_id, created_at, updated_at, latest_stage, selected_target_json, metadata_json)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                latest_stage = excluded.latest_stage,
                selected_target_json = COALESCE(excluded.selected_target_json, runs.selected_target_json),
                metadata_json = COALESCE(excluded.metadata_json, runs.metadata_json)
            """,
            (
                run_id,
                timestamp,
                timestamp,
                stage,
                json.dumps(selected_target, ensure_ascii=False) if selected_target else None,
                json.dumps(metadata, ensure_ascii=False) if metadata else None,
            ),
        )
        connection.execute(
            """
            INSERT INTO stage_snapshots(run_id, stage, request_json, response_json, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (
                run_id,
                stage,
                json.dumps(request_payload, ensure_ascii=False) if request_payload else None,
                json.dumps(response_payload, ensure_ascii=False) if response_payload else None,
                timestamp,
            ),
        )
        connection.commit()


def append_chat_message(
    data_dir: Path,
    run_id: str,
    role: str,
    content: str,
    *,
    meta: dict[str, Any] | None = None,
) -> None:
    timestamp = _utcnow()
    with _connect(data_dir) as connection:
        connection.execute(
            """
            INSERT INTO runs(run_id, created_at, updated_at, latest_stage, metadata_json)
            VALUES(?, ?, ?, ?, NULL)
            ON CONFLICT(run_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                latest_stage = excluded.latest_stage
            """,
            (run_id, timestamp, timestamp, "coach_chat"),
        )
        connection.execute(
            """
            INSERT INTO chat_messages(run_id, role, content, meta_json, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (
                run_id,
                role,
                content,
                json.dumps(meta, ensure_ascii=False) if meta else None,
                timestamp,
            ),
        )
        connection.commit()


def _safe_json_loads(raw_value: str | None) -> dict[str, Any] | list[Any] | None:
    if not raw_value:
        return None
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return None


def load_chat_messages(data_dir: Path, run_id: str) -> list[dict[str, Any]]:
    with _connect(data_dir) as connection:
        rows = connection.execute(
            """
            SELECT role, content, meta_json, created_at
            FROM chat_messages
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()

    messages: list[dict[str, Any]] = []
    for row in rows:
        meta = _safe_json_loads(row["meta_json"])
        if not isinstance(meta, dict):
            meta = {}
        messages.append(
            {
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
                "preparation_tips": list(meta.get("preparation_tips", [])),
                "suggested_questions": list(meta.get("suggested_questions", [])),
            }
        )
    return messages


def _load_stage_responses_from_db(data_dir: Path, run_id: str) -> dict[str, dict[str, Any]]:
    stages = ("explore", "prepare_summary", "prep_artifacts")
    loaded: dict[str, dict[str, Any]] = {}
    with _connect(data_dir) as connection:
        for stage in stages:
            row = connection.execute(
                """
                SELECT response_json
                FROM stage_snapshots
                WHERE run_id = ? AND stage = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (run_id, stage),
            ).fetchone()
            if row:
                payload = _safe_json_loads(row["response_json"])
                if isinstance(payload, dict):
                    loaded[stage] = payload
    return loaded


def _load_stage_responses_from_files(data_dir: Path, run_id: str) -> dict[str, dict[str, Any]]:
    run_dir = data_dir / "runs" / run_id
    loaded: dict[str, dict[str, Any]] = {}
    for stage in ("explore", "prepare_summary", "prep_artifacts"):
        path = run_dir / f"{stage}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            loaded[stage] = payload
    return loaded


def load_run_context(data_dir: Path, run_id: str) -> dict[str, Any]:
    context = _load_stage_responses_from_db(data_dir, run_id)
    file_context = _load_stage_responses_from_files(data_dir, run_id)
    for key, value in file_context.items():
        context.setdefault(key, value)

    selected_target: dict[str, Any] | None = None
    with _connect(data_dir) as connection:
        row = connection.execute(
            """
            SELECT selected_target_json
            FROM runs
            WHERE run_id = ?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        if row:
            loaded_target = _safe_json_loads(row["selected_target_json"])
            if isinstance(loaded_target, dict):
                selected_target = loaded_target

    if selected_target is None:
        for stage in ("prep_artifacts", "prepare_summary"):
            request_path = data_dir / "runs" / run_id / f"{stage}.json"
            if not request_path.exists():
                continue
            try:
                payload = json.loads(request_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("selected_target"), dict):
                selected_target = payload["selected_target"]
                break

    return {
        "run_id": run_id,
        "selected_target": selected_target,
        "explore": context.get("explore", {}),
        "prepare_summary": context.get("prepare_summary", {}),
        "prep_artifacts": context.get("prep_artifacts", {}),
        "messages": load_chat_messages(data_dir, run_id),
    }
