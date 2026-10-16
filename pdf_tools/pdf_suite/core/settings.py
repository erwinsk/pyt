# -*- coding: utf-8 -*-
"""Penyimpanan pengaturan sederhana (JSON) — path alat, opsi terakhir, dsb."""
import json
import os
from pathlib import Path
from typing import Any, Optional

from .paths import config_dir


class Settings:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else config_dir() / "settings.json"
        self._data: dict = {}
        self.load()

    def load(self):
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self._data, dict):
                self._data = {}
        except (OSError, ValueError):
            self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        cur: Any = self._data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, key: str, value: Any, save: bool = True):
        parts = key.split(".")
        cur = self._data
        for part in parts[:-1]:
            nxt = cur.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[part] = nxt
            cur = nxt
        if value is None:
            cur.pop(parts[-1], None)
        else:
            cur[parts[-1]] = value
        if save:
            self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass  # pengaturan bersifat best-effort
