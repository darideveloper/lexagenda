"""The per-instance `config.yaml` a human edits, read once at boot (PLAN.md D15)."""

import os
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
DELIVERY_MODES = ("auto", "draft")


class ConfigError(ValueError):
    pass


@lru_cache(maxsize=8)
def load_config(path=None) -> dict:
    path = Path(path or os.environ.get("LEXAGENDA_CONFIG", DEFAULT_PATH))
    try:
        cfg = yaml.safe_load(path.read_text()) or {}
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path} must hold a mapping")

    if cfg.get("delivery_mode") not in DELIVERY_MODES:
        raise ConfigError(
            f"delivery_mode must be one of {DELIVERY_MODES}, got {cfg.get('delivery_mode')!r}"
        )
    for kind, spec in (cfg.get("kinds") or {}).items():
        if not isinstance(spec, dict) or not {"duration", "buffer"} <= spec.keys():
            raise ConfigError(f"kinds.{kind} needs duration and buffer")
    for key in ("hourly", "daily", "delay_seconds"):
        if key not in (cfg.get("caps") or {}):
            raise ConfigError(f"caps.{key} is missing")

    cfg.setdefault("name", "lexagenda")
    cfg.setdefault("reminders", [7, 3, 1])
    return cfg
