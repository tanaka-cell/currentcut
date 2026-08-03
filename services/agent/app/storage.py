"""Firestore-shaped local JSON store. One file per collection per project.

Swap target (Phase 8): Firestore adapter with the same interface.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)
_lock = threading.Lock()


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else config.DATA_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, project_id: str, collection: str) -> Path:
        d = self.root / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{collection}.json"

    def put(self, project_id: str, collection: str, item: BaseModel) -> None:
        with _lock:
            items = self._read(project_id, collection)
            items = [i for i in items if i.get("id") != getattr(item, "id", None)]
            items.append(json.loads(item.model_dump_json()))
            self._write(project_id, collection, items)

    def put_many(self, project_id: str, collection: str, new_items: list[BaseModel]) -> None:
        with _lock:
            items = self._read(project_id, collection)
            new_ids = {getattr(i, "id") for i in new_items}
            items = [i for i in items if i.get("id") not in new_ids]
            items.extend(json.loads(i.model_dump_json()) for i in new_items)
            self._write(project_id, collection, items)

    def list(self, project_id: str, collection: str, model: Type[T]) -> list[T]:
        return [model.model_validate(i) for i in self._read(project_id, collection)]

    def get(self, project_id: str, collection: str, model: Type[T], item_id: str) -> T | None:
        for i in self._read(project_id, collection):
            if i.get("id") == item_id:
                return model.model_validate(i)
        return None

    def clear(self, project_id: str, collection: str) -> None:
        with _lock:
            self._write(project_id, collection, [])

    def _read(self, project_id: str, collection: str) -> list[dict]:
        p = self._path(project_id, collection)
        if not p.exists():
            return []
        return json.loads(p.read_text(encoding="utf-8"))

    def _write(self, project_id: str, collection: str, items: list[dict]) -> None:
        p = self._path(project_id, collection)
        p.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


store = Store()
