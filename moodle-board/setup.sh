#!/usr/bin/env bash
# Setup for the Moodle TRMNL board (trmnlp project). Bash + coreutils + optional `dialog`.
# Token -> pick courses (checklist) -> per course: label + exam day (calendar).
# Writes src/settings.yml (poll URL) and src/full.liquid (labels + exams).
# Stateful: re-running shows a menu (or use a flag) once it's been set up before.
#
#   ./setup.sh             interactive (menu if already configured)
#   ./setup.sh --full      force full setup (re-pick courses)
#   ./setup.sh --exams     update exam dates only (reuse existing courses)
#   ./setup.sh --token     get / fix the Moodle token only
#   ./setup.sh --lang      switch board language (English default / Deutsch) only
#   ./setup.sh --selftest  parser self-checks
#
# The dialog pickers need a real terminal; without `dialog`/a TTY they fall back to
# typing ("DD.MM." for exams), which is also how the self-tests drive them.
set -u  # ponytail: NOT -e/pipefail — this skips bad input, it doesn't die on it
cd "$(dirname "$0")"

# Pickers use `dialog` (ncurses) for a real calendar/checklist that survive any
# terminal + resize. No dialog (or no TTY, or BOARD_NO_TUI=1) -> typed fallback.
DIALOG=$(command -v dialog 2>/dev/null || true)
DLGOUT=""  # tmpfile for dialog's result, created on first use
ui() { [ -n "$DIALOG" ] && [ -z "${BOARD_NO_TUI:-}" ] && [ -t 0 ] && [ -t 1 ]; }

extract_token() {  # moodledl://token=BASE64 (or raw) -> wstoken, matches moodle-dl
  local b64 dec
  b64="${1##*token=}"
  dec=$(printf '%s' "$b64" | { base64 -d 2>/dev/null || base64 -D 2>/dev/null; })
  printf '%s' "$dec" | awk -F':::' '{print $2}' | tr -cd 'A-Za-z0-9'
}
# cross-platform date helpers (GNU date first, then BSD/macOS)
ymd_to_epoch() { # Y M D -> epoch at noon
  local s; s=$(printf '%04d-%02d-%02d 12:00:00' "$1" "$2" "$3")
  date -d "$s" +%s 2>/dev/null || date -j -f "%Y-%m-%d %H:%M:%S" "$s" +%s 2>/dev/null
}
epoch_fmt() { date -d "@$1" "+$2" 2>/dev/null || date -r "$1" "+$2" 2>/dev/null; }
exam_to_unix() { # "DD.MM" -> epoch, inferring this year or next
  local dd mm y tm td
  dd=$((10#$(printf '%s' "$1" | cut -d. -f1))); mm=$((10#$(printf '%s' "$1" | cut -d. -f2)))
  y=$((10#$(date +%Y))); tm=$((10#$(date +%m))); td=$((10#$(date +%d)))
  if [ "$mm" -lt "$tm" ] || { [ "$mm" -eq "$tm" ] && [ "$dd" -lt "$td" ]; }; then y=$((y+1)); fi
  ymd_to_epoch "$y" "$mm" "$dd"
}

if [ "${1:-}" = "--selftest" ]; then
  blob=$(printf 'sig:::TOKEN123:::priv' | base64 | tr -d '\n')
  [ "$(extract_token "moodledl://token=$blob")" = TOKEN123 ] || { echo FAIL token; exit 1; }
  [ "$(epoch_fmt "$(ymd_to_epoch 2026 7 20)" %d.%m)" = 20.07 ] || { echo FAIL date; exit 1; }
  [ "$(epoch_fmt "$(exam_to_unix 31.12)" %m)" = 12 ] || { echo FAIL exam; exit 1; }
  echo "selftest ok"; exit 0
fi

copy_clip() {
  if   command -v pbcopy >/dev/null 2>&1; then pbcopy
  elif command -v wl-copy >/dev/null 2>&1; then wl-copy
  elif command -v xclip  >/dev/null 2>&1; then xclip -selection clipboard
  elif command -v xsel   >/dev/null 2>&1; then xsel --clipboard --input
  else cat >/dev/null; return 1; fi
}
splice() { awk -v s="$2" -v e="$3" -v cf="$4" '
  index($0,s){print; while((getline l<cf)>0) print l; b=1; next} index($0,e){b=0} !b' "$1" > "$1.tmp" && mv "$1.tmp" "$1"; }
# dialog draws its UI on stderr (the terminal) and writes the picked value to fd 3,
# which we point at $DLGOUT. rc 0 = OK, non-zero (Esc/Cancel) = skip.
dlg() { [ -z "$DLGOUT" ] && DLGOUT=$(mktemp); "$DIALOG" --output-fd 3 "$@" 3>"$DLGOUT"; }

# ---- course checklist (ITEM[1..N], CHECK[k]=0/1, updated in place) ----------
checklist() {
  if ! ui; then local k
    for ((k=1;k<=N;k++)); do printf "  %2d [%s] %s\n" "$k" "$([ "${CHECK[$k]}" = 1 ]&&echo x||echo ' ')" "${ITEM[$k]}"; done
    read -rp "toggle which numbers (space-sep), empty=accept: " tg
    for k in $tg; do [ -n "${CHECK[$k]:-}" ] && CHECK[$k]=$((1-CHECK[$k])); done; return; fi
  local args=() k
  for ((k=1;k<=N;k++)); do args+=("$k" "${ITEM[$k]}" "$([ "${CHECK[$k]}" = 1 ]&&echo on||echo off)"); done
  dlg --separate-output --no-tags --title "Courses" \
      --checklist "↑/↓ move · space toggle · enter done   (this semester pre-checked)" \
      0 0 0 "${args[@]}" || { echo "  (cancelled)"; exit 1; }
  for ((k=1;k<=N;k++)); do CHECK[$k]=0; done
  while read -r k; do [ -n "${CHECK[$k]:-}" ] && CHECK[$k]=1; done < "$DLGOUT"
}

# ---- exam day calendar: appends "unix|label|DD.MM." to EXAMRAW ---------------
exam_pick() {
  local label="$1"
  if ! ui; then local ex when u
    read -rp "     $label exam day (DD.MM.), empty=none: " ex
    when=$(printf '%s' "$ex" | grep -oE '^[0-9]{1,2}\.[0-9]{1,2}' || true); [ -z "$when" ] && return
    u=$(exam_to_unix "$when"); printf '%s|%s|%s.\n' "$u" "$label" "$when" >> "$EXAMRAW"; return; fi
  dlg --date-format "%Y-%m-%d" --title "$label — exam day" \
      --calendar "Pick $label exam day · ←→↑↓ move · enter pick · esc/cancel = none" \
      0 0 "$((10#$(date +%d)))" "$((10#$(date +%m)))" "$(date +%Y)" || return  # cancel = no exam
  local sel y m d u; sel=$(cat "$DLGOUT"); [ -z "$sel" ] && return
  y=${sel%%-*}; m=${sel#*-}; m=${m%%-*}; d=${sel##*-}
  u=$(ymd_to_epoch "$((10#$y))" "$((10#$m))" "$((10#$d))")
  printf '%s|%s|%02d.%02d.\n' "$u" "$label" "$((10#$d))" "$((10#$m))" >> "$EXAMRAW"
}

# ---- pick-one menu: "title" tag1 label1 tag2 label2 ...  -> echoes chosen tag --
menu() {
  local title="$1"; shift
  if ui; then local args=()
    while [ "$#" -ge 2 ]; do args+=("$1" "$2"); shift 2; done
    dlg --no-tags --title "Moodle Board" --menu "$title" 0 0 0 "${args[@]}" || return 1
    cat "$DLGOUT"; return; fi
  echo "$title" >&2; local i=1 tags=()
  while [ "$#" -ge 2 ]; do tags+=("$1"); printf '  %d) %s\n' "$i" "$2" >&2; shift 2; i=$((i+1)); done
  local c; read -rp "  choose [1]: " c; c=${c:-1}; echo "${tags[$((c-1))]:-${tags[0]}}"
}

# ---- token: domain + SSO launch + paste + VERIFY; sets DOMAIN BASE TOKEN MUID -
get_token() {
  read -rp "Moodle domain [moodle.hpi.de]: " DOMAIN; DOMAIN=${DOMAIN:-moodle.hpi.de}
  BASE="https://$DOMAIN/webservice/rest/server.php"
  LAUNCH="https://$DOMAIN/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodledl"
  echo; echo "GET YOUR TOKEN  — log into $DOMAIN first (any browser)"
  if printf '%s' "$LAUNCH" | copy_clip; then echo "  ✓ launch URL copied to your clipboard"; else echo "  (copy the URL below by hand)"; fi
  cat <<EOF
      $LAUNCH

  1. while logged in, paste the URL above into the address bar and hit Enter
  2. a page opens (NOT an error). If it asks to confirm / "open the app", click that.
  3. on the Moodle "Redirect / Continue" page, RIGHT-CLICK the "Continue" link
     → Copy Link Address. That link is your  moodledl://token=...
  4. fallback (Chrome): DevTools → Network tab, find the moodledl://token=... entry.
EOF
  while :; do
    read -rp "  paste that moodledl://token=... link here: " TOKURL
    TOKEN=$(extract_token "$TOKURL")
    if [ -z "$TOKEN" ]; then echo "  ✗ couldn't read a token from that — paste the WHOLE moodledl://… url"; [ -n "${BOARD_NO_TUI:-}" ] && return 1; continue; fi
    echo "  ✓ got token (${#TOKEN} chars)"
    # verify it actually works (BOARD_FAKE_SITEINFO: test/offline seam)
    local info; info=${BOARD_FAKE_SITEINFO:-$(curl -s "$BASE?wstoken=$TOKEN&moodlewsrestformat=json&wsfunction=core_webservice_get_site_info")}
    MUID=$(printf '%s' "$info" | grep -oE '"userid":[0-9]+' | grep -oE '[0-9]+' | head -1)
    [ -n "$MUID" ] && { echo "  ✓ token works (user $MUID)"; return 0; }
    if printf '%s' "$info" | grep -q 'invalidtoken'; then
      echo "  ✗ Moodle says this token is INVALID. get a fresh one and paste again."
    else
      echo "  ! couldn't verify (offline / wrong domain?) — using the token anyway."; return 0  # don't block on network
    fi
    [ -n "${BOARD_NO_TUI:-}" ] && return 1
  done
}

# ---- write the EXAMS region of full.liquid from $EXAMRAW (sorted) ------------
write_exams() {
  local f; f=$(mktemp)
  if [ -s "$EXAMRAW" ]; then
    printf '      {%% assign exams = "%s" | split: "," %%}\n' "$(sort -n "$EXAMRAW" | paste -sd, -)" > "$f"
  else
    printf '      {%% assign exams = "" | split: "," %%}\n' > "$f"
  fi
  splice src/full.liquid '<!-- EXAMS -->' '<!-- /EXAMS -->' "$f"; rm -f "$f"
}

# ---- language: set LANGCODE to en|de (default English) -----------------------
pick_lang() {
  if ui; then
    dlg --no-tags --title "Moodle Board" --menu "Board language · Sprache des Boards" 0 0 0 \
        en "English (default)" de "Deutsch" || { LANGCODE=en; return; }
    LANGCODE=$(cat "$DLGOUT"); [ -z "$LANGCODE" ] && LANGCODE=en; return; fi
  local ans; read -rp "Board language — type 'de' for Deutsch, anything else = English [en]: " ans
  case "$(printf '%s' "$ans" | tr 'A-Z' 'a-z')" in de|german|deutsch) LANGCODE=de;; *) LANGCODE=en;; esac
}

# ---- write the I18N region (12 label vars) of all four views for LANGCODE -----
write_i18n() {
  local ne na ex as du ds dy noe noa noas ti th
  if [ "${LANGCODE:-en}" = de ]; then
    ne="Nächste Klausur"; na="Nächste Übung"; ex="Klausuren"; as="Abgaben"; du="Fällig"
    ds="Tage"; dy="Tag"; noe="keine Klausur"; noa="keine Übung"; noas="keine Abgaben"
    ti="Token ungültig"; th="./setup.sh neu starten"
  else
    ne="Next exam"; na="Next assignment"; ex="Exams"; as="Assignments"; du="Due"
    ds="Days"; dy="Day"; noe="no exam"; noa="no assignment"; noas="no assignments"
    ti="Token invalid"; th="restart ./setup.sh"
  fi
  local f v; f=$(mktemp)
  printf '{%% assign l_next_exam = "%s" %%}{%% assign l_next_assignment = "%s" %%}{%% assign l_exams = "%s" %%}{%% assign l_assignments = "%s" %%}{%% assign l_due = "%s" %%}{%% assign l_days = "%s" %%}{%% assign l_day = "%s" %%}{%% assign l_no_exam = "%s" %%}{%% assign l_no_assignment = "%s" %%}{%% assign l_no_assignments = "%s" %%}{%% assign l_token_invalid = "%s" %%}{%% assign l_token_hint = "%s" %%}\n' \
    "$ne" "$na" "$ex" "$as" "$du" "$ds" "$dy" "$noe" "$noa" "$noas" "$ti" "$th" > "$f"
  for v in full half_horizontal half_vertical quadrant; do
    splice "src/$v.liquid" '<!-- I18N -->' '<!-- /I18N -->' "$f"
  done
  rm -f "$f"
}

# ---- update exams only: reuse existing course labels from COURSEMAP ----------
update_exams() {
  local labels=() lbl
  while IFS= read -r lbl; do [ -n "$lbl" ] && labels+=("$lbl"); done < <(
    grep -oE '\{% assign clabel = "[^"]*" %\}' src/full.liquid | sed -E 's/.*"([^"]*)".*/\1/')
  [ "${#labels[@]}" -gt 0 ] || { echo "  no existing courses found — run a full setup."; exit 1; }
  echo; echo "UPDATE EXAM DATES — this replaces all exams. Skip a course to drop its exam."
  EXAMRAW=$(mktemp)
  for lbl in "${labels[@]}"; do echo "  · $lbl"; exam_pick "$lbl"; done
  write_exams; rm -f "$EXAMRAW" ${DLGOUT:+"$DLGOUT"}
  echo; echo "✓ exam dates updated in src/full.liquid. Re-deploy / refresh to see them."
}

# already configured if full.liquid has at least one baked course mapping
configured() { grep -Eq '\{% when [0-9]+ %\}' src/full.liquid 2>/dev/null; }

# ---------------------------------------------------------------------------
# offer `dialog` for the nice calendar/checklists; typed prompts work without it.
if [ -z "$DIALOG" ] && [ -z "${BOARD_NO_TUI:-}" ] && [ -t 0 ] && [ -t 1 ]; then
  if   command -v brew    >/dev/null 2>&1; then inst="brew install dialog"
  elif command -v apt-get >/dev/null 2>&1; then inst="sudo apt-get install -y dialog"
  elif command -v dnf     >/dev/null 2>&1; then inst="sudo dnf install -y dialog"
  elif command -v pacman  >/dev/null 2>&1; then inst="sudo pacman -S --noconfirm dialog"
  else inst=""; fi
  if [ -n "$inst" ]; then
    echo "tip: install 'dialog' for a real calendar + checklists (else you'll just type)."
    read -rp "  run '$inst' now? [Y/n] " yn
    case "$yn" in [Nn]*) ;; *) eval "$inst" && DIALOG=$(command -v dialog 2>/dev/null || true);; esac
    echo
  fi
fi

# what to run? a flag wins; otherwise a menu when it's already been set up before.
MODE=""
case "${1:-}" in --token) MODE=token;; --exams) MODE=exams;; --lang) MODE=lang;; --full) MODE=full;; esac
if [ -z "$MODE" ]; then
  if configured; then
    MODE=$(menu "You've set this board up before — what do you want to do?" \
      exams "Update exam dates  (keep your courses + token)" \
      token "Get / fix the Moodle token  (verify it works)" \
      lang  "Change board language  (English / Deutsch)" \
      full  "Full setup from scratch  (re-pick courses)")
    [ -z "$MODE" ] && { echo "  (cancelled)"; exit 0; }
  else MODE=full; fi
fi

# exams-only path needs no token/network — reuse the baked course labels and leave.
[ "$MODE" = exams ] && { update_exams; exit 0; }

# language-only path: no token/network — flip all four views' I18N region and leave.
[ "$MODE" = lang ] && { pick_lang; write_i18n; rm -f ${DLGOUT:+"$DLGOUT"}
  echo; echo "✓ board language set to $LANGCODE in all views. Re-deploy / refresh to see it."; exit 0; }

get_token || { echo "  aborted — no working token."; exit 1; }

# token-only path: token is verified + printed; courses/exams stay as they are.
[ "$MODE" = token ] && { cat <<EOF

✓ token verified. Paste it into the BYOS plugin's "Moodle Token" field; for local preview:
    export MOODLE_TOKEN=$TOKEN && trmnlp serve
(courses + exams left unchanged.)
EOF
  exit 0; }

# --- full setup: fetch + parse the course list ---
RESP=${BOARD_FAKE_RESP:-$(curl -s "$BASE?wstoken=$TOKEN&moodlewsrestformat=json&wsfunction=core_enrol_get_users_courses&userid=${MUID:-0}")}  # BOARD_FAKE_RESP: test/offline seam
CID=(); CSHORT=(); ITEM=(); CHECK=(); STARTS=(); N=0
while read -r s; do STARTS+=("$s"); done < <(printf '%s' "$RESP" | grep -oE '"startdate":[0-9]+' | grep -oE '[0-9]+')
CUT=$(( $(date +%s) - 160*86400 ))
j=0
while IFS='|' read -r cid cshort cfull; do
  [ -z "$cid" ] && continue
  N=$((N+1)); CID[$N]=$cid; CSHORT[$N]=$cshort; ITEM[$N]="$cshort — $cfull"
  st=${STARTS[$j]:-0}; j=$((j+1))
  if [ "${#STARTS[@]}" -ne 0 ] && [ "$st" -ge "$CUT" ]; then CHECK[$N]=1; else CHECK[$N]=0; fi
done < <(printf '%s' "$RESP" | grep -oE '"id":[0-9]+,"shortname":"[^"]*","fullname":"[^"]*"' \
         | sed -E 's/"id":([0-9]+),"shortname":"([^"]*)","fullname":"([^"]*)"/\1|\2|\3/')

CIDS=""; idx=0; MAPFILE=$(mktemp); EXAMRAW=$(mktemp)
if [ "$N" -gt 0 ]; then
  echo; echo "PICK YOUR COURSES (this semester pre-checked):"; checklist
  echo "(per course: a short screen label, then its exam day)"
  for ((k=1;k<=N;k++)); do
    [ "${CHECK[$k]:-0}" = 1 ] || continue
    read -rp "  ${CSHORT[$k]} → label [${CSHORT[$k]}]: " ab
    ab=$(printf '%s' "${ab:-${CSHORT[$k]}}" | tr -d '"|,')
    CIDS="${CIDS}&courseids[$idx]=${CID[$k]}"; idx=$((idx+1))
    printf '      {%% when %s %%}{%% assign clabel = "%s" %%}\n' "${CID[$k]}" "$ab" >> "$MAPFILE"
    exam_pick "$ab"
  done
else
  echo "  (couldn't auto-list courses — token issue? enter IDs manually)"
  read -rp "  course IDs, comma-separated: " IDS; IFS=','
  for id in $IDS; do id=$(printf '%s' "$id" | tr -cd '0-9'); [ -n "$id" ] && CIDS="${CIDS}&courseids[$idx]=$id" && idx=$((idx+1)); done; unset IFS
fi

cat > src/settings.yml <<EOF
---
strategy: polling
name: Moodle Board
polling_verb: get
polling_url: $BASE?wstoken={{ moodle_token }}&moodlewsrestformat=json&wsfunction=mod_assign_get_assignments${CIDS}
polling_headers: ''
no_screen_padding: 'no'
dark_mode: 'no'
refresh_interval: 60
custom_fields:
- keyname: moodle_token
  field_type: string
  name: Moodle Token
  description: your Moodle wstoken — run ./setup.sh to get it
EOF

splice src/full.liquid '<!-- COURSEMAP -->' '<!-- /COURSEMAP -->' "$MAPFILE"
write_exams
pick_lang; write_i18n   # board language (defaults to English)
rm -f "$MAPFILE" "$EXAMRAW" ${DLGOUT:+"$DLGOUT"}

cat <<EOF

✓ src/settings.yml ($idx course(s)) + src/full.liquid (labels + exams) written.

PREVIEW:   export MOODLE_TOKEN=$TOKEN && trmnlp serve     # http://localhost:4567
ON DEVICE: import the plugin into byos_laravel, paste the token into "Moodle Token".

LATER:     ./setup.sh again shows a menu — or ./setup.sh --token / --exams to jump straight in.
EOF
