# moodle-board — handoff

A TRMNL e-ink dashboard for HPI Moodle, built to share with friends. Shows **live
assignment deadlines** plus a **set-once** exam countdown. It is a
[`trmnlp`](https://github.com/usetrmnl/trmnlp) plugin that **polls the Moodle API
directly** — no backend service, no Docker sidecar, no Python at runtime.

UI text is **English by default**, switchable to German in `setup.sh` (assignment/exam
*names* stay whatever Moodle returns). Each view file is **self-contained** — there is no
longer a `shared.liquid`; see §1 for why.

---

## 1. How it works (the one big idea)

Two data sources, merged in one Liquid template:

| Shown on screen | Source | When |
|---|---|---|
| **Assignments** (deadlines) | Moodle web service `mod_assign_get_assignments`, polled by the BYOS server | live, every refresh |
| **Exams** (countdowns) | baked into `src/full.liquid`, days computed in Liquid | set once in `setup.sh` |
| **Next exam / Next assignment** (the two hero blocks, top-left) | derived: nearest future exam + nearest future assignment | live / set-once |
| **⚠ Token invalid** | `errorcode`/`exception` in the poll response | live, when the token dies |

There is **no server in the middle**. The BYOS plugin's polling URL points straight at
`…/webservice/rest/server.php?...&wsfunction=mod_assign_get_assignments`, and the Liquid
template shapes the raw response. The static schedule lives inside the template itself.

**Every view is self-contained — there is NO `shared.liquid`.** trmnlp (local preview)
prepends a `shared.liquid` to every view, but a real `byos_laravel` device does **not**, so
anything defined only in `shared.liquid` is `undefined` on hardware. That silently broke the
"Next assignment" hero on-device (it read a `deadlines` list built in `shared.liquid` → showed
"no assignment", while the Assignments column — which built its own list inline — worked). Fix:
each view now builds its own sorted assignment list inline from the poll's `courses`. In the full
view the list is built **once at the top** and drives both the hero (`rows[0]`) and the column, so
they can't diverge. ⚠ **"tested with real data" via trmnlp is NOT a device test.**

**Full view (800×480) layout** — 3 columns:
1. **Two hero items** stacked and split by a `divider`: *Next exam* (days to next exam) and
   *Next assignment* (days to next assignment). Each has an eyebrow label on top, a giant
   `value--xxxlarge` number, then a `{{ days }} · {detail}` line under it (`·` separator; the
   day/days word is singular-aware — `Day`/`Tag` when 1). The column is `self--stretch` and each
   item is `grow basis--0`, so the two heroes are a **true 50/50 vertical split that fills to the
   title bar**. (`h--full` does NOT work here — it can't resolve against a content-sized
   `.columns` parent; `self--stretch` + `basis--0` does.)
2. **Exams** — all future exams. Number size is chosen in Liquid from the exam **count**
   (`value--xxlarge`→`--small`) and `item grow` distributes them, so they **shrink to fit and
   never overflow** instead of getting an "and N more".
3. **Assignments** — upcoming assignments in a `data-overflow` container with a
   `data-overflow-max-height` budget; excess rows collapse to an **"and N more"** counter. Each
   row shows the **module label as an eyebrow above the title**.

⚠ **Do NOT use `data-fit-value` anywhere.** The framework runs fit-value / overflow / clamp
in one JS pass; a fit-value throw silently aborts the pass and kills the overflow engine on
the whole page. That's why exam numbers are sized in Liquid, not by fit-value.

⚠ **Overflow counter placement depends on the mode.** Single column: `data-overflow` +
`data-overflow-counter` on the `.column`. Multi-column fan (`data-overflow-max-cols` on
`.columns`, used by half_horizontal): the counter must sit on the **`.columns`** container — on
the inner `.column` it's ignored and items are dropped with no "and N more".

Why no sidecar: deadlines are a single API call a polling plugin can do alone; exams
aren't in Moodle's API anyway, so they're entered once. Announcements were
considered and dropped — they need a 2-call forum chain (`get_forums_by_courses` →
`get_forum_discussions`) that a polling plugin can't do without code.

---

## 2. Files

```
setup.sh            one-time interactive config (pure bash). The bulk of the work lives here.
src/settings.yml    plugin def: polling strategy, polling_url (token + course ids), moodle_token custom field
src/full.liquid     the board. 800x480 full view. Builds the sorted assignment list inline, then
                    renders 3 columns. Schedule + course map + labels spliced between HTML markers.
src/half_horizontal.liquid  compact deadline list, fans into up to 3 columns (data-overflow-max-cols). Self-contained.
src/half_vertical.liquid    compact deadline list, single column (portrait). Self-contained.
src/quadrant.liquid         compact deadline list, single column (tightest view). Self-contained.
.trmnlp.yml         local preview config: Europe/Berlin tz, token from $MOODLE_TOKEN, sample data
.env                (gitignored, optional) MOODLE_TOKEN=… for live local preview
README.md           user-facing quick start
```

There is **no `shared.liquid`** (removed — it only works under trmnlp, not on a real device;
see §1). Each of the three compact views builds its own sorted deadline list inline from
`courses` (`duedate|name|shortname`, lexically sorted = soonest first) and differs only by
column count. Minor duplication, but every size renders on hardware. Each row shows the module
`shortname` as an eyebrow above the assignment title.

`src/full.liquid` has **three** splice regions that `setup.sh` rewrites (all matched by marker
substring anywhere in the file, so their position doesn't matter):

- `<!-- I18N -->` … `<!-- /I18N -->` — one line of `{% assign l_… = "…" %}` label vars for the
  chosen language. Present in **all four** view files; `setup.sh` rewrites the region in each.
  Templates reference `{{ l_exams }}`, `{{ l_days }}`, etc. Defaults to English in the committed files.
- `<!-- COURSEMAP -->` … `<!-- /COURSEMAP -->` — `{% when <id> %}{% assign clabel = "<label>" %}`
  lines mapping Moodle course id → your short screen label. **Full view only, exactly one region**
  (it now sits near the top, where the assignment list is built).
- `<!-- EXAMS -->` … `<!-- /EXAMS -->` — a single `{% assign exams = "unix|label|DD.MM.,…" %}`
  string (sorted by unix). The surrounding Liquid filters future exams, sorts, and renders them.

`setup.sh`'s `splice()` replaces the lines between two markers; the markers stay put. For the
I18N region it loops `splice()` over all four view files.

---

## 3. The token (the genuinely hard part)

HPI uses SSO, so there's no username/password token endpoint. `setup.sh` uses **moodle-dl's
SSO launch flow** (verified against moodle-dl's own source):

1. Open `https://moodle.hpi.de/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodledl`
   while logged in (setup.sh copies this URL to the clipboard).
2. Moodle shows a **confirm/redirect page** (NOT an error — the endpoint sets a
   `tool_mobile_launch` cookie with `confirmed:0`). The `moodledl://token=…` is the
   **"Continue" link** on that page (right-click → Copy Link Address), or the redirect
   you grab from Chrome's Network tab.
3. The pasted `moodledl://token=BASE64` decodes as `base64 → split ":::" → field 2` = the
   `wstoken`. (`extract_token()` in setup.sh.)

The token then goes into the BYOS plugin's `moodle_token` **custom field** (so it stays out
of git), and `polling_url` templates it in as `{{ moodle_token }}`.

---

## 4. setup.sh flow

`./setup.sh` (bash + coreutils + optional `dialog`, no Python). **Stateful** — if
`full.liquid` already has baked `{% when %}` course mappings (`configured()`), it opens a
menu (`dialog --menu`, else numbered prompt) to pick a mode; flags skip the menu:

- `--full` (or first run): domain → `get_token` → fetch/parse courses → checklist → per
  course label + exam → language pick → write `settings.yml` + splice `COURSEMAP`/`EXAMS` into
  `full.liquid` + splice `I18N` into all four views.
- `--exams`: re-uses the existing labels parsed out of the `COURSEMAP` region, runs only the
  exam calendar per course, rewrites the `EXAMS` region. No token, no network.
- `--token`: re-runs `get_token` and prints a fresh verified token. Courses/exams untouched.
- `--lang`: pick language (English default / German) and re-splice the `I18N` region in all four
  view files. No token, no network. Also on the interactive menu. Only fixed UI labels change;
  Moodle-provided assignment/exam names are never translated.

`get_token` does domain → SSO launch → paste → **verify** via `core_webservice_get_site_info`
(`"userid"` present ⇒ ok; `invalidtoken` ⇒ reject and re-prompt; network failure ⇒ warn but
proceed). It sets `DOMAIN/BASE/TOKEN/MUID`. The full path then calls
`core_enrol_get_users_courses` and parses id/shortname/fullname/startdate (grep/sed adjacency);
current-semester courses are pre-checked by `startdate` (≥ ~160 days ago; `enddate` too
unreliable). Exam day is calendar, date-only.

The pickers (`checklist`, `exam_pick`) and the `menu` use **`dialog`** (ncurses) — robust in
any terminal, resize-safe. **Each has a typed fallback** when `dialog` is absent, there's no
TTY, or `BOARD_NO_TUI=1` (`DD.MM.` for exams, a number for the menu) — also how tests drive it.
The lecture grid was removed (the template has no lecture section).

Cross-platform `date` helpers (`ymd_to_epoch`, `epoch_fmt`, `exam_to_unix`) try GNU `date`
then BSD/macOS `date` syntax.

---

## 5. Run / preview / deploy

```sh
gem install trmnl_preview            # or use the trmnl/trmnlp Docker image
./setup.sh                           # configure (token + courses + schedule)
export MOODLE_TOKEN=<token>          # the token setup.sh printed
trmnlp serve                         # http://localhost:4567
# docker alt: docker run --rm -p 4567:4567 -v "$(pwd):/plugin" trmnl/trmnlp serve
```

`.trmnlp.yml` ships sample `variables.courses`, so `trmnlp serve` renders the board even
**without** a token (the sample also demos the overflow / "and N more" / clamping). Note
trmnlp deep-merges `variables` **on top of** the poll, so the sample *masks* live polling
locally — to preview **your real data**, comment out `variables:` in `.trmnlp.yml`, put your
token in `.env` (`MOODLE_TOKEN=…`, gitignored), then:

```sh
set -a; . ./.env; set +a; trmnlp serve
```

On a real device `.trmnlp.yml` isn't used, so live polling always drives the board.

**Deploy to a device:** import the plugin into a self-hosted `byos_laravel`, choose
strategy **Polling**, and paste the token into the **Moodle Token** custom field. Each
friend runs their own BYOS + their own `setup.sh`.

---

## 6. How it was tested

- `./setup.sh --selftest` — token decoder, date math.
- **Typed-fallback flow** (piped stdin, non-TTY) per mode: `--full` (asserts course ids +
  sorted exam string), `--exams` (re-uses baked labels, honours empty-skip, leaves courses
  untouched), `--token` valid + invalid, and the numbered menu (`3` → full). Renders through
  the real `trmnl/trmnlp` build.
- **`dialog` widgets** (calendar, checklist, menu) driven through a real pseudo-terminal —
  confirmed they render auto-sized, navigate, and write the picked value to `--output-fd 3`.
- Test/offline **seams** (env vars): `BOARD_FAKE_RESP` = canned `core_enrol_get_users_courses`
  JSON; `BOARD_FAKE_SITEINFO` = canned `core_webservice_get_site_info` JSON (drives token
  verify — `{"userid":N}` = valid, `{"errorcode":"invalidtoken"}` = rejected);
  `BOARD_NO_TUI=1` forces the typed fallbacks.

Caveat: a *fully clean automated keystroke* run through the live `dialog` UI is racy (feeding
keys faster than ncurses redraws desyncs in a way human input never does). Each widget's
render + output and each mode's parse/splice logic are verified independently; the
human-in-the-loop seam is exercised by hand.

**Layout / overflow** was verified visually across **all four view sizes** (full 800×480,
half_horizontal 800×240, half_vertical 400×480, quadrant 400×240) with a headless Chromium
(Playwright) against `trmnlp`'s `/render/<view>.html` at exact device dimensions — including a
stress dataset (13 assignments, 7 exams, an overlong title) to confirm the "and N more"
counter, the exam shrink-to-fit, and title clamping all fire.

⚠ **`trmnlp` is NOT a device test.** trmnlp prepended a `shared.liquid` that a real
`byos_laravel` device doesn't, so a plugin can pass every trmnlp check and still break on
hardware (this is exactly how the "Next assignment" hero bug shipped — caught only on a real
`larapaper` device). Views are now self-contained precisely to remove that gap. When possible,
sanity-check the real device, not just trmnlp.

⚠ **Don't trust `trmnlp`'s `/render/<view>.png` route for overflow** — headless Firefox
screenshots *before* the framework's post-render JS settles, so "and N more" can be missing
in that PNG even when the markup is correct. It also clamps viewport width to ~500px (can't
render true 400px). Use Chromium/Playwright on the `.html` route to verify overflow layouts.

---

## 7. Known limitations / ceilings

- **No announcements.** Needs the 2-call forum chain → would require a small fetch step.
- **Deadlines sort globally**: assignments are flattened into a `duedate|name|label` string,
  then sorted lexically — the 10-digit unix prefix makes lexical == numeric == soonest first.
  (Breaks in year ~2286 when the timestamp gains an 11th digit.) This list is built once per
  view (in the full view, once at the top and reused by both hero and column).
- **Compact views use `c.shortname` as the module label**, not the short `COURSEMAP` label
  (only the full view has the `COURSEMAP` map; setup.sh splices `COURSEMAP` into `full.liquid`
  only). So the same module can read e.g. "DBS" in the full view and "DBS I - 2026" in a
  compact view. Fixing it would mean giving the compact views their own label map.
- **Language is applied by re-splicing**, not a runtime flag: switching language rewrites the
  `I18N` region in all four files. Adding a language = adding a string table in `setup.sh`.
- **Exam column shows all future exams**, sized to fit (number size picked from the count);
  date-only (no time), days floored. The top-left hero shows the single nearest exam.
- **Semester pre-check is a heuristic** (course start date). Toggle in the checklist if wrong.
- **Course parse keys on `id,shortname,fullname` field adjacency** in the JSON — true on
  HPI today; if a Moodle reorders those fields the list comes up empty and setup falls back
  to manual ID entry.
- **`dialog`-less terminals fall back to typing.** With `dialog` the pickers scroll/resize
  fine; without it (and without a TTY) you type instead (`DD.MM.`, a menu number).
- **`--exams` replaces all exam dates** (it re-collects every course; skipping one drops its
  exam) — there's no per-exam merge.
- **Token verify trusts the network.** An explicit `invalidtoken` is rejected, but a failed
  verify (offline/wrong domain) only warns and proceeds.
- The committed `src/full.liquid` and `src/settings.yml` contain **real personal data**
  (current courses/labels/exams) — regenerated by re-running `setup.sh`. A fresh clone is
  therefore `configured()`, so it opens the menu; a new user picks **Full setup**.

---

## 8. Related infra (for context / sharing)

The proven Moodle web-service client this reuses lives on the Proxmox box `pve`
(192.168.178.41):

- **LXC 104 (`nextcloud`)** — `/opt/moodle-sync/`: a mature moodle-dl pipeline. Its
  `moodle_assignments.py` is the original `moodle_call` / `mod_assign_get_assignments`
  client and the source of truth for HPI's API shape. moodle-dl's `moodle_service.py`
  (`extract_token`) + `moodle_wizard.py` are where the SSO token flow came from.
- **LXC 103 (`trmnl`)** — runs `terminus` (the official BYOS) + a `trmnl-caldav` container.
  This is the author's own TRMNL server; friends are expected to run `byos_laravel`.

---

## 9. Next steps / ideas

- Add announcements (per-course news forum) if wanted — needs a tiny fetch step or pasted
  forum IDs.
- **Layout pass is done** (all four sizes verified in Chromium; heroes 50/50, module eyebrows,
  singular-aware Day/Tag, header underline spacing, overflow counters). The "Next assignment"
  hero + all compact views are now self-contained and confirmed against a real device. Still
  worth a glance on a *physical* panel for dither/contrast — the hero `meta` bars sit at the
  very left screen edge and read subtly; nudge with spacing if they look too faint on hardware.
- **Compact views use the raw `shortname`** as the module label (see §7); unify with the full
  view's `COURSEMAP` labels if the mismatch bothers you on a device.
- **Sample dates age.** `.trmnlp.yml`'s sample `duedate`s are fixed future timestamps; once
  they slip into the past the offline preview's Abgaben column empties. Refresh them (or
  regenerate from a live poll) if the demo board goes blank.
- `--exams` rewrites the whole `EXAMS` region; a true per-course *amend* (keep others, change
  one) would need to parse + merge the existing string rather than re-collect all.
