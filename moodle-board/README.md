# moodle-board

A TRMNL e-ink board of your HPI Moodle deadlines (live) plus your exam dates
(set once). A [`trmnlp`](https://github.com/usetrmnl/trmnlp) plugin that
polls the Moodle API directly — **no server, no Python, no venv**. Runs in trmnlp for
local preview and pushes to `byos_laravel` for your device.

## 1. Install trmnlp

```sh
gem install trmnl_preview      # or use Docker (below) — no Ruby needed
```

## 2. Setup

```sh
./setup.sh
```

Walks you through the only annoying part — the token — then your schedule:

1. **Token.** It copies Moodle's mobile-launch URL to your clipboard (log into Moodle
   first). Paste it into the address bar → a confirm/redirect page opens → right-click
   the **"Continue"** link → Copy Link Address (it's a `moodledl://token=…` link) →
   paste it back. The script decodes your wstoken **and verifies it works** (a quick
   `get_site_info` call) — if Moodle says the token is invalid, it tells you and asks again.
2. **Courses** — a **checklist** of your enrolled courses (↑/↓, space, enter).
   This semester's are pre-checked by course start date (a default, not a hard filter).
   Then, per picked course:
   - a **short label** (HPI shortnames are long),
   - its **exam day** — a **real calendar** you arrow through (←→↑↓), Enter to pick,
     Esc/Cancel for none; day only, no time.

   The pickers use [**`dialog`**](https://invisible-island.net/dialog/) (the classic
   ncurses widget toolkit) so the calendar and checklist render correctly in **any
   terminal** and survive window resizes. If `dialog` isn't installed, setup offers to
   `brew`/`apt`/`dnf`/`pacman`-install it for you. Decline (or no TTY, or
   `BOARD_NO_TUI=1 ./setup.sh`) and every picker falls back to plain typing
   (`DD.MM.` for the exam). Course IDs land in `src/settings.yml`; labels + exams in
   `src/full.liquid`.

### Re-running — it remembers

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

No Ruby? Docker instead:

```sh
docker run --rm -p 4567:4567 -v "$(pwd):/plugin" trmnl/trmnlp serve
```

`.trmnlp.yml` ships sample deadlines, so `trmnlp serve` renders even **without** a
token — the live poll just overrides them once `MOODLE_TOKEN` is set.

## 4. Onto your device (byos_laravel)

Import the plugin, then paste your token into the **Moodle Token** custom field.

## Layout

```
src/full.liquid              the board (deadlines + Klausuren)
src/half_*.liquid, quadrant  compact deadline-only views
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
                      ▲ this one
```

`setup.sh`'s `extract_token()` does exactly this: `base64 -d | awk -F':::' '{print $2}'`.

### 2. `core_webservice_get_site_info` → your user id

```jsonc
{
  "sitename": "moodle.hpi.de",
  "username": "first.last",
  "userid": 12345,            // ← setup.sh greps this out
  "userprivateaccesskey": "…",
  "functions": [ { "name": "mod_assign_get_assignments", "version": "…" }, … ]
}
```

### 3. `core_enrol_get_users_courses&userid=<id>` → the course list

A **bare JSON array**, one object per enrolled course. `setup.sh` parses `id`,
`shortname`, `fullname` (by field adjacency) and `startdate` (for the semester pre-check):

```jsonc
[
  {
    "id": 1127,                       // ← Moodle course id (baked into polling_url + COURSEMAP)
    "shortname": "Mathe 2",           // ← default screen label (you can override)
    "fullname": "Mathematik 2 (SoSe 2026)",
    "startdate": 1742208000,          // ← ≥ ~160 days ago ⇒ pre-checked as "this semester"
    "enddate": 0,                     // unreliable on HPI, so unused
    "visible": 1,
    "format": "topics"
    // …~20 more fields, ignored
  },
  { "id": 1107, "shortname": "PT2-26", "fullname": "…", "startdate": 1742208000, … }
]
```

### 4. `mod_assign_get_assignments&courseids[]=…` → the LIVE board data

This is the URL the TRMNL device polls every refresh. TRMNL exposes the response's
top-level `courses` key to Liquid as the `courses` variable (see `.trmnlp.yml` →
`variables.courses` for the same shape used offline). Only `id`, `shortname`, and each
assignment's `name` + `duedate` are read by the template:

```jsonc
{
  "courses": [
    {
      "id": 1127,                       // matched against the COURSEMAP {% when %} ids
      "fullname": "Mathematik 2 (SoSe 2026)",
      "shortname": "Mathe 2",
      "timemodified": 1782000000,
      "assignments": [
        {
          "id": 8842,
          "cmid": 99102,
          "course": 1127,
          "name": "Hausaufgabe Woche 11",   // ← shown
          "duedate": 1782683940,            // ← unix seconds; > now ⇒ rendered as "in N Tagen"
          "allowsubmissionsfromdate": 1782000000,
          "cutoffdate": 0,
          "grade": 100
          // …many more fields, ignored
        }
      ]
    },
    { "id": 1081, "shortname": "DBS I - 2026", "assignments": [] }   // a course with nothing due
  ],
  "warnings": []
}
```

A few Moodle gotchas this relies on: `duedate: 0` means "no due date" (filtered out by the
`> now` guard); the response always wraps the array in `{ "courses": …, "warnings": [] }`;
and an expired/invalid token returns an **error object instead**:

```jsonc
{ "exception": "moodle_exception", "errorcode": "invalidtoken", "message": "Ungültiges Token" }
```

Every view checks `{% if errorcode or exception %}` and renders **"⚠ Token ungültig —
./setup.sh"** (title bar + body) so a dead token is obvious on the panel rather than looking
like an empty week.

### 5. Baked-in data (written by `setup.sh` into `src/full.liquid`)

Not JSON — three compact string formats spliced between HTML-comment markers, chosen so
Liquid can parse them with `split`:

| Region | Format | Example |
|---|---|---|
| `<!-- COURSEMAP -->` | `{% when <id> %}{% assign clabel = "<label>" %}` | `{% when 1127 %}{% assign clabel = "MA II" %}` |
| `<!-- EXAMS -->` | one string, comma-joined rows of `unix\|label\|DD.MM.`, sorted by unix | `"1781685583\|BIS\|17.06.,1787042347\|MA II\|18.08."` |

The `unix` prefix is a 10-digit timestamp, so a plain lexical `sort` == soonest-first.
The template filters `unix > now`, then renders the nearest as a countdown ("in N Tagen").

## Notes & ceilings

- Deadlines are live; exams are set once — re-run `./setup.sh` to change them.
- The **Klausuren** block shows the next two upcoming exams as a **countdown** ("in N
  Tagen"), computed in Liquid from baked unix timestamps. Deadlines sort within each
  course, not globally.
- Announcements aren't here — they need a 2-step forum API chain a polling plugin can't
  do alone. Ask if you want them.
- `./setup.sh --selftest` checks the token decoder and date math.
- The pickers need `dialog` for the calendar/checklist UI; without it (or without a TTY)
  everything still works by typing. `dialog` is a ~1 MB install via `brew`/`apt`/`dnf`/`pacman`.
