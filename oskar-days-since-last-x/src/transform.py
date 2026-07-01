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

MEME_ENDPOINT = "https://meme.hpi.church/meme?days=7"


def fetch_random(input):
    return COUNTERS[random.choice(list(COUNTERS.keys()))](input)


def fetch_meme(input):
    res = requests.get(MEME_ENDPOINT)
    res.raise_for_status()
    data = res.json()
    return {
        "display_mode": "meme",
        "meme_image_url": data["url"],
        "meme_message": data.get("message", ""),
    }


def run(input):
    args = (input or {}).get("args", {})
    mode = args.get("mode", "days_since")

    if mode == "meme":
        try:
            return fetch_meme(input)
        except Exception as e:
            return {"display_mode": "meme", "meme_image_url": "", "error": str(e)}

    counter_type = args.get("counter", "random")
    fetcher = COUNTERS.get(counter_type) or fetch_random
    try:
        result = fetcher(input)
        result["display_mode"] = "days_since"
        return result
    except Exception as e:
        return {
            "display_mode": "days_since",
            "days": "?",
            "counter_label": "Error fetching counter",
            "counter_type": counter_type,
            "error": str(e),
        }
