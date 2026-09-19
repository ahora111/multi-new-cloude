from __future__ import annotations
import importlib
from .base import Source
from .csv_source import CsvSource
from .eways import EwaysSource
from .hamrahtel import HamrahtelSource
from .html_source import HtmlSource
from .json_source import JsonSource

REGISTRY = {c.type_name: c for c in (JsonSource, HtmlSource, CsvSource, EwaysSource, HamrahtelSource)}


def build_source(cfg, settings=None, base_dir=".", http=None) -> Source:
    cls_path = cfg.options.get("class")
    if cls_path:
        mod, _, name = cls_path.partition(":")
        cls = getattr(importlib.import_module(mod), name)
    else:
        cls = REGISTRY.get(cfg.type)
        if cls is None:
            raise ValueError(f"source {cfg.name}: unknown type {cfg.type!r}; known: {sorted(REGISTRY)} or use 'class'")
    return cls(cfg, settings=settings, base_dir=base_dir, http=http)
