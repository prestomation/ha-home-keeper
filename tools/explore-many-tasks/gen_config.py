#!/usr/bin/env python3
"""EXPLORATION TOOL (not product code). Build a Home Assistant config dir with N tasks.

Copies tests/integration/ha_config to OUT, then replaces the task store with N
generated tasks. Also writes an area registry and more labels, so the panel has
real areas and labels to show. The fixture in the repo is never changed.

Usage:
    python3 tools/explore-many-tasks/gen_config.py N OUT_DIR [--seed 1]
    HA_CONFIG=OUT_DIR docker compose -f tests/integration/docker-compose.yml up -d

The tasks are built with the real `models.build_task`, so they have the shape the
integration writes. A share of the tasks get a long completion history.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import shutil
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMP = ROOT / "custom_components" / "home_keeper"
PKG = "custom_components.home_keeper"
TZ = timezone(timedelta(hours=-4))


def load_core():
    """Load the pure core modules under their real names, without Home Assistant."""
    for name in ("custom_components", PKG):
        mod = types.ModuleType(name)
        mod.__path__ = [str(COMP)]
        sys.modules[name] = mod
    for name in ("const", "recurrence", "models"):
        spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", COMP / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{PKG}.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{PKG}.models"]


AREAS = [
    "Kitchen", "Garage", "Basement", "Attic", "Living room", "Master bedroom",
    "Guest bedroom", "Kids room", "Office", "Laundry room", "Garden", "Front porch",
    "Back deck", "Bathroom 1", "Bathroom 2", "Hall", "Pantry", "Workshop", "Shed",
    "Cellar", "Gästezimmer", "Küche", "客厅", "厨房", "Sala de estar",
]
LABELS = [
    "home", "dog", "safety", "seasonal", "firmware", "battery", "filter", "outdoor",
    "monthly", "quarterly", "yearly", "urgent", "清洁", "Wartung",
]
BASES = [
    "Replace furnace filter", "Clean dryer vent", "Test smoke alarm", "Descale kettle",
    "Check tire pressure", "Flush water heater", "Wipe window tracks", "Update firmware",
    "Replace battery", "Rinse HVAC drain", "Oil door hinges", "Clean gutters",
    "Inspect fire extinguisher", "Vacuum fridge coils", "Rotate mattress",
]
LONG = (
    "Replace the very long named filter cartridge in the whole house water treatment "
    "system and also write down the reading of the pressure gauge on the left side"
)
UNICODE = ["更换空调滤网", "清洁抽油烟机 (chōuyóuyānjī)", "Büro Pflanzen gießen", "🔥 Test the 🔋 alarm", "Ölwechsel Rasenmäher"]


def make(n: int, seed: int):
    rnd = random.Random(seed)
    models = load_core()
    now = datetime(2026, 10, 30, 9, 0, tzinfo=TZ)
    tasks: dict[str, dict] = {}
    area_ids = [f"area_{i}" for i in range(len(AREAS))]
    for i in range(n):
        kind = rnd.choices(
            ["floating", "fixed", "one-off", "triggered"], [60, 25, 10, 5]
        )[0]
        r = rnd.random()
        if i % 97 == 0:
            name = LONG + f" ({i})"
        elif i % 53 == 0:
            name = f"{UNICODE[i % len(UNICODE)]} {i}"
        else:
            name = f"{BASES[i % len(BASES)]} #{i + 1}"
        data: dict = {
            "name": name,
            "notes": ("Note line.\n" * rnd.randint(0, 6)) if r < 0.3 else "",
            "recurrence_type": kind,
            "enabled": rnd.random() > 0.05,
            "labels": rnd.sample(LABELS, rnd.randint(0, 3)),
        }
        if rnd.random() < 0.7:
            data["area_id"] = rnd.choice(area_ids)
        if kind == "floating":
            data["interval"] = rnd.choice([1, 2, 3, 6, 12, 30, 90])
            data["unit"] = rnd.choice(["days", "weeks", "months"])
        elif kind == "fixed":
            data["freq"] = rnd.choice(["DAILY", "WEEKLY", "MONTHLY"])
            data["interval"] = rnd.choice([1, 1, 2])
            data["anchor"] = (now - timedelta(days=rnd.randint(30, 400))).isoformat()
        elif kind == "one-off":
            data["due"] = (now + timedelta(days=rnd.randint(-30, 120))).isoformat()
        task = models.build_task(data, now=now - timedelta(days=rnd.randint(1, 700)))
        # Completion history: 5% of tasks get 50-500 entries, 25% get 1-10.
        h = rnd.random()
        count = rnd.randint(50, 500) if h < 0.05 else rnd.randint(1, 10) if h < 0.30 else 0
        if count:
            start = now - timedelta(days=count * 3 + 5)
            comps = []
            for k in range(count):
                c: dict = {"ts": (start + timedelta(days=3 * k, minutes=k % 60)).isoformat()}
                if k % 5 == 0:
                    c["note"] = "Done. " * rnd.randint(1, 8)
                if k % 7 == 0:
                    c["cost"] = round(rnd.uniform(1, 90), 2)
                comps.append(c)
            task["completions"] = comps
            task["last_completed"] = comps[-1]["ts"]
        # Spread the due state: a share overdue, a share soon, a share far.
        if kind in ("floating", "fixed") and task.get("next_due"):
            shift = rnd.choice([-40, -10, -2, 0, 1, 3, 10, 40, 200])
            task["next_due"] = (now + timedelta(days=shift)).isoformat()
        tasks[task["id"]] = task
    return tasks, area_ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("n", type=int)
    ap.add_argument("out")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "tests/integration/ha_config", out, symlinks=True)
    store_path = out / ".storage" / "home_keeper"
    doc = json.loads(store_path.read_text())
    tasks, area_ids = make(a.n, a.seed)
    doc["data"]["tasks"] = tasks
    store_path.write_text(json.dumps(doc))
    stamp = "2026-10-01T00:00:00+00:00"
    areas = [
        {
            "aliases": [], "floor_id": None, "humidity_entity_id": None, "icon": None,
            "id": aid, "labels": [], "name": name, "picture": None,
            "temperature_entity_id": None, "created_at": stamp, "modified_at": stamp,
        }
        for aid, name in zip(area_ids, AREAS)
    ]
    (out / ".storage" / "core.area_registry").write_text(
        json.dumps(
            {"version": 1, "minor_version": 8, "key": "core.area_registry", "data": {"areas": areas}}
        )
    )
    lab = json.loads((out / ".storage" / "core.label_registry").read_text())
    have = {x["label_id"] for x in lab["data"]["labels"]}
    for name in LABELS:
        if name not in have:
            lab["data"]["labels"].append(
                {
                    "label_id": name, "name": name.title(), "color": "green", "icon": None,
                    "description": None, "created_at": stamp, "modified_at": stamp,
                }
            )
    (out / ".storage" / "core.label_registry").write_text(json.dumps(lab))
    size = store_path.stat().st_size
    print(f"wrote {a.n} tasks to {out} (store {size} bytes)")


if __name__ == "__main__":
    main()
