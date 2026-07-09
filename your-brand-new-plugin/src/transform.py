import os
import json
from datetime import datetime, timezone


STATE_FILE = os.path.join(os.path.dirname(__file__), ".watering_state.json")


def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"last_run": None, "plants": {}}


def _save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _normalize_schedule(days_field):
    # Accept either an int or a list of ints
    if isinstance(days_field, list):
        return [int(d) for d in days_field]
    try:
        return [int(days_field)]
    except Exception:
        return [0]


def run(input):
    # Input may provide the plants under several keys; handle common cases
    data = None
    if isinstance(input, dict):
        if "data" in input and isinstance(input["data"], dict) and "plants" in input["data"]:
            data = input["data"]
        elif "static_data" in input:
            try:
                data = json.loads(input["static_data"]) if isinstance(input["static_data"], str) else input["static_data"]
            except Exception:
                data = None

    if not data:
        return {"plants": []}

    plants = data.get("plants", [])
    state = _load_state()

    # compute how many whole days passed since last run
    last_run_date = None
    if state.get("last_run"):
        try:
            last_run_date = datetime.fromisoformat(state["last_run"]).date()
        except Exception:
            last_run_date = None

    today = datetime.now(timezone.utc).date()
    days_elapsed = 0
    if last_run_date:
        days_elapsed = (today - last_run_date).days

    updated_plants = []
    for p in plants:
        pid = str(p.get("id"))
        schedule = _normalize_schedule(p.get("days", 0))

        # initialize state for this plant
        pst = state.get("plants", {}).get(pid)
        if not pst:
            pst = {"schedule": schedule, "index": 0, "days_left": schedule[0] if schedule else 0}
            state.setdefault("plants", {})[pid] = pst

        # if schedule definition changed in static_data, update stored schedule
        if pst.get("schedule") != schedule:
            pst["schedule"] = schedule
            pst.setdefault("index", 0)
            pst.setdefault("days_left", schedule[pst["index"]])

        # decrement by number of days passed
        if days_elapsed > 0:
            pst["days_left"] = int(pst.get("days_left", 0)) - days_elapsed

        watered = False
        # if it's time (or past time) to water, advance cycles until days_left > 0
        if pst.get("days_left", 0) <= 0:
            watered = True
            # consume cycles (in case many cycles passed while offline)
            while pst.get("days_left", 0) <= 0:
                # advance index to next interval
                if pst["schedule"]:
                    pst["index"] = (pst.get("index", 0) + 1) % len(pst["schedule"]) if len(pst["schedule"]) > 1 else 0
                    pst["days_left"] += pst["schedule"][pst["index"]]
                else:
                    pst["days_left"] = 0
                    break

        # ensure non-negative integer
        pst["days_left"] = max(0, int(pst.get("days_left", 0)))

        # expose days_left to template as 'days'
        out = dict(p)
        out["days"] = pst["days_left"]
        if watered:
            out["watered"] = True

        updated_plants.append(out)

    # update last_run and persist state
    state["last_run"] = today.isoformat()
    _save_state(state)

    return {"plants": updated_plants}
