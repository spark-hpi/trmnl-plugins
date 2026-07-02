import requests
import re
import random

from datetime import date


def fetch_student_telegram(input):
    res = requests.get("https://counter.vieledatengutedaten.de/")
    res.raise_for_status()
    match = re.search(r"<div[^>]+class=['\"][^'\"]*head-lg[^'\"]*['\"][^>]*>([\s\S]*?)<\/div>", res.text)
    return {
        "days": match.group(1) if match else "?",
        "counter_label": "Student-Telegram last blew up",
        "counter_type": "student_telegram",
    }


def fetch_rust_mc_server(input):
    src = requests.get("https://raw.githubusercontent.com/GoldenStack/dayssincelastrustmcserver/refs/heads/main/src/pages/index.astro").text
    dates = re.findall(r'date: new Date\("([\d-]+)"\)', src)
    if not dates:
        return {"days": "?", "counter_label": "Rust Minecraft server released", "counter_type": "rust_mc_server"}
    latest = max(date.fromisoformat(d) for d in dates)
    days = (date.today() - latest).days
    return {
        "days": str(days),
        "counter_label": "Rust Minecraft server released",
        "counter_type": "rust_mc_server",
    }


COUNTERS = {"student_telegram": fetch_student_telegram, "rust_mc_server": fetch_rust_mc_server}


def fetch_random(input):
    return COUNTERS[random.choice(list(COUNTERS.keys()))](input)


def run(input):
    args = (input or {}).get("args", {})
    counter_type = args.get("counter", "random")
    fetcher = COUNTERS.get(counter_type) or fetch_random
    try:
        return fetcher(input)
    except Exception as e:
        return {
            "days": "?",
            "counter_label": "Error fetching counter",
            "counter_type": counter_type,
            "error": str(e),
        }
