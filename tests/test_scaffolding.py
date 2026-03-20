import json
import os

from tests.conftest import PROJECT_ROOT


def _load_vercel_json():
    path = os.path.join(PROJECT_ROOT, "vercel.json")
    with open(path) as f:
        return json.load(f)


class TestVercelConfig:
    """Guard against accidental edits to cron schedules and function limits."""

    def test_has_two_cron_entries(self):
        cfg = _load_vercel_json()
        assert len(cfg["crons"]) == 2

    def test_cron_paths(self):
        cfg = _load_vercel_json()
        paths = {c["path"] for c in cfg["crons"]}
        assert paths == {"/api/fetch", "/api/deliver"}

    def test_cron_schedules(self):
        cfg = _load_vercel_json()
        schedules = {c["path"]: c["schedule"] for c in cfg["crons"]}
        assert schedules["/api/fetch"] == "0 6 * * *"
        assert schedules["/api/deliver"] == "0 8 * * *"

    def test_has_three_function_configs(self):
        cfg = _load_vercel_json()
        assert len(cfg["functions"]) == 3

    def test_function_max_durations(self):
        cfg = _load_vercel_json()
        fns = cfg["functions"]
        assert fns["api/fetch.py"]["maxDuration"] == 60
        assert fns["api/deliver.py"]["maxDuration"] == 60
        assert fns["api/telegram.py"]["maxDuration"] == 10
