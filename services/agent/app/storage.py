"""Firestore-shaped local JSON store. One file per collection per project.

Swap target (Phase 8): Firestore adapter with the same interface.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)
_lock = threading.Lock()

# A project id becomes a directory name, so it is the one piece of caller input
# that decides where on the disk we write. Checking it at each handler means
# checking it in twenty places and forgetting the twenty-first; the guard belongs
# on the corridor, not on each door. Everything the service generates is
# `prefix_hex`, and the tests use short words, so this is deliberately narrow:
# letters, digits, underscore and hyphen, and nothing that a filesystem reads as
# a path — no dot, no slash, no backslash (Windows treats "..\..\x" as one URL
# segment and three directories), no colon, no null byte.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class UnsafeIdError(ValueError):
    """The caller's project id is not a name we will put on the disk."""


def safe_id(project_id: str) -> str:
    if not isinstance(project_id, str) or not _SAFE_ID.match(project_id):
        raise UnsafeIdError("not a project id")
    return project_id


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else config.DATA_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, project_id: str, collection: str, *, create: bool = False) -> Path:
        """Where one collection of one project lives.

        `create` is false by default because reading used to make the directory:
        a GET for a project that does not exist left a folder behind, so anyone
        could fill the disk — on Cloud Run, /tmp is the instance's memory —
        by asking for projects that were never there. Reads now look and leave.
        """
        d = self.root / safe_id(project_id)
        if create:
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
        p = self._path(project_id, collection, create=True)
        p.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


store = Store()
