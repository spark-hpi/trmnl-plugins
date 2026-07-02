# moodle-board

A TRMNL e-Paper dashboard of your (HPI) Moodle deadlines (live) plus your exam dates
(set once). It's [`trmnlp`](https://github.com/usetrmnl/trmnlp) plugin that
polls the Moodle API directly, with no serverless transforms.  

## 1. Install trmnlp

```sh
gem install trmnl_preview      # or use Docker (below) — no Ruby needed
```

## 2. Setup

```sh
./setup.sh
```

Run this script to set everything up. You only need to run it once. 

1. It copies Moodle's mobile-launch URL to your clipboard (you need to be logged into Moodle already). Paste it into the address bar → a confirm/redirect page opens → right-click
   the **"Continue"** link → Copy Link Address (it's a `moodledl://token=…` link) →
   paste it back. The script decodes your wstoken **and verifies it works**. If Moodle says the token is invalid, it tells you and asks again.
2. **Courses** — a **checklist** of your enrolled courses (↑/↓, space, enter).
   This semester's are pre-checked by course start date (a default, not a hard filter).
   Then, per picked course:
   - a **short label** (HPI shortnames are long),
   - its **exam day** — a **real calendar** you arrow through (←→↑↓), Enter to pick,
     Esc/Cancel for none; day only, no time.

   The pickers use [**`dialog`**](https://invisible-island.net/dialog/)  so the calendar and checklist render correctly in **any
   terminal**. If `dialog` isn't installed, setup offers to
   `brew`/`apt`/`dnf`/`pacman`-install it for you. Decline (or no TTY, or
   `BOARD_NO_TUI=1 ./setup.sh`) and every picker falls back to plain typing
   (`DD.MM.` for the exam). Course IDs land in `src/settings.yml`; labels + exams in
   `src/full.liquid`.

### Re-running

`setup.sh` is **stateful**: once it's been set up, re-running it shows a menu instead of
starting over —

| Pick | Flag | What it touches |
|---|---|---|
| **Update exam dates** | `./setup.sh --exams` | Just the exams (re-uses your existing course labels — no token, no network). Replaces all exam dates; skip a course to drop its exam. |
| **Get / fix the token** | `./setup.sh --token` | Re-runs the token flow and verifies it, then prints a fresh working token to paste into the plugin. Courses + exams untouched. |
| **Full setup** | `./setup.sh --full` | Re-pick courses from scratch (the original flow). |

When the device's token expires, the board itself shows **"⚠ Token ungültig — ./setup.sh"**
(it detects Moodle's `invalidtoken` error response), so you know to run `--token`.

## 3. Preview locally

```sh
export MOODLE_TOKEN=<the token setup.sh printed>
trmnlp serve            # http://localhost:4567
```

`.trmnlp.yml` ships sample deadlines, so `trmnlp serve` renders even **without** a
token — the live poll just overrides them once `MOODLE_TOKEN` is set.

## 4. Onto your device (byos_laravel)

Import the plugin (trmnlp push), then paste your token into the **Moodle Token** custom field.

## Layout

```
src/full.liquid              the board (deadlines + Klausuren)
src/half_*.liquid, quadrant  hero numbers (days to next exam / assignment); halves add the deadline list
src/settings.yml             polling URL + custom field (course IDs baked by setup.sh)
.trmnlp.yml                  local dev: Berlin tz, token-from-env, sample data
```

## Data shapes (JSON)

Everything that flows through this plugin, end to end.

### 1. The token blob — `moodledl://token=…`

What you paste back during setup. The part after `token=` is **base64**; decoded it is
three colon-triple-separated fields, and field 2 is your `wstoken`:

```
base64decode("moodledl://token=…".split("token=")[1])
  ->  "<signature>:::<wstoken>:::<privatetoken>"
                      ▲
```
