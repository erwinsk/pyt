# -*- coding: utf-8 -*-
"""Lokasi folder kerja aplikasi.

Semua yang dibuat aplikasi selain hasil akhir berada di SATU folder kerja
(cache bawaan OS), bukan tersebar di /tmp atau di samping file PDF.
"""
import os
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir

APP_NAME = "pdf-tools-suite"


def workspace_root() -> Path:
    env = os.environ.get("PDFSUITE_WORKSPACE")
    if env:
        return Path(env)
    return Path(user_cache_dir(APP_NAME, appauthor=False)) / "workspace"


def scratch_root() -> Path:
    return workspace_root() / "scratch"


def cache_root() -> Path:
    return workspace_root() / "cache"


def config_dir() -> Path:
    env = os.environ.get("PDFSUITE_CONFIG")
    if env:
        return Path(env)
    return Path(user_config_dir(APP_NAME, appauthor=False))
