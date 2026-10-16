# -*- coding: utf-8 -*-
"""Skema opsi: didefinisikan SATU kali, dipakai UI, validasi, dan kunci cache."""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

BOOL, INT, FLOAT, CHOICE, TEXT, LANGS = "bool", "int", "float", "choice", "text", "langs"


@dataclass
class Option:
    key: str
    label: str
    kind: str
    default: Any
    tooltip: str = ""
    group: str = "basic"            # basic | advanced
    min: Optional[float] = None
    max: Optional[float] = None
    step: float = 1
    choices: Sequence[Tuple[Any, str]] = field(default_factory=tuple)  # (nilai, label)
    affects_ocr: bool = False       # True = mengubah ini membuat OCR diulang (↻)
    enabled_if: Optional[Callable[[Dict[str, Any]], bool]] = None
    suffix: str = ""


class OptionSet:
    def __init__(self, options: List[Option]):
        self.options = options
        self._by_key = {o.key: o for o in options}
        if len(self._by_key) != len(options):
            raise ValueError("Kunci opsi duplikat")

    def __iter__(self):
        return iter(self.options)

    def get(self, key: str) -> Option:
        return self._by_key[key]

    def defaults(self) -> Dict[str, Any]:
        return {o.key: o.default for o in self.options}

    def normalize(self, values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Lengkapi dengan default dan paksa tipe/rentang yang valid."""
        out = self.defaults()
        for k, v in (values or {}).items():
            if k in self._by_key:
                out[k] = self._coerce(self._by_key[k], v)
        return out

    @staticmethod
    def _coerce(o: Option, v: Any) -> Any:
        try:
            if o.kind == BOOL:
                return bool(v)
            if o.kind == INT:
                v = int(v)
            elif o.kind == FLOAT:
                v = float(v)
            elif o.kind == CHOICE:
                valid = [c[0] for c in o.choices]
                return v if v in valid else o.default
            else:
                return str(v)
            if o.min is not None:
                v = max(type(v)(o.min), v)
            if o.max is not None:
                v = min(type(v)(o.max), v)
            return v
        except (TypeError, ValueError):
            return o.default

    def ocr_params(self, values: Dict[str, Any]) -> Dict[str, Any]:
        return {o.key: values.get(o.key, o.default) for o in self.options if o.affects_ocr}


def bool_opt(key, label, default=False, tooltip="", group="basic", **kw) -> Option:
    return Option(key, label, BOOL, default, tooltip, group, **kw)


def int_opt(key, label, default, lo, hi, tooltip="", group="basic", suffix="", **kw) -> Option:
    return Option(key, label, INT, default, tooltip, group, min=lo, max=hi, suffix=suffix, **kw)


def float_opt(key, label, default, lo, hi, step=0.1, tooltip="", group="basic", **kw) -> Option:
    return Option(key, label, FLOAT, default, tooltip, group, min=lo, max=hi, step=step, **kw)


def choice_opt(key, label, default, choices, tooltip="", group="basic", **kw) -> Option:
    return Option(key, label, CHOICE, default, tooltip, group, choices=tuple(choices), **kw)


def text_opt(key, label, default="", tooltip="", group="basic", **kw) -> Option:
    return Option(key, label, TEXT, default, tooltip, group, **kw)


def langs_opt(key, label, default="eng", tooltip="", group="basic", **kw) -> Option:
    return Option(key, label, LANGS, default, tooltip, group, **kw)
