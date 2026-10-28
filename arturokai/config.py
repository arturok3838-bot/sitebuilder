from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for key in ("output_dir", "workspace_dir"):
        p = Path(cfg[key])
        cfg[key] = p if p.is_absolute() else ROOT / p
        cfg[key].mkdir(parents=True, exist_ok=True)
    db = Path(cfg["billing"]["db"])
    cfg["billing"]["db"] = db if db.is_absolute() else ROOT / db
    cfg["billing"]["db"].parent.mkdir(parents=True, exist_ok=True)
    return cfg
