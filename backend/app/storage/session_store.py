from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def persist_run_artifact(data_dir: Path, run_id: str, name: str, payload: dict[str, Any]) -> Path:
    run_dir = data_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

