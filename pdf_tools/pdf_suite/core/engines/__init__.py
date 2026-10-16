# -*- coding: utf-8 -*-
"""Registry engine kompresi."""
from typing import List

from .base import Engine, EngineError, EngineResult, JobContext, CacheStatus
from .ghostscript import GhostscriptEngine
from .full_image import FullImageEngine
from .ocrmypdf_engine import OcrmypdfEngine
from .mrc_engine import MrcEngine

ENGINES: List[Engine] = [GhostscriptEngine(), FullImageEngine(), OcrmypdfEngine(), MrcEngine()]


def get_engine(engine_id: str) -> Engine:
    for e in ENGINES:
        if e.id == engine_id:
            return e
    raise KeyError(engine_id)


__all__ = ["ENGINES", "get_engine", "Engine", "EngineError", "EngineResult", "JobContext", "CacheStatus"]
