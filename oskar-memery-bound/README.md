# Memery Bound

A TRMNL plugin that displays the "Meme of the Week" — the most-reacted image
posted to a Telegram chat over a configurable lookback window.

## How it works

- `image.py` is a long-running HTTP server that logs into Telegram as a **user**
  (not a bot — bots can't read chat history or reaction counts), scans the
  configured chat for the image with the most reactions in the last `days`, and
  serves it at `GET /meme?days=X`.
- The TRMNL plugin polls that server directly (`polling_url` in
  `src/settings.yml`) and renders the returned `url` / `message` across all four
  layouts.

## Running the meme server

1. Copy `.env.example` to `.env` and fill in your Telegram API credentials
   (get `API_ID` / `API_HASH` at https://my.telegram.org) and the chat to scan.
2. First run is interactive so you can log in:
   ```
   docker compose run --service-ports meme
   ```
   The session is written to `./data` and reused non-interactively afterwards.
3. Subsequent runs: `docker compose up`.

Point `polling_url` in `src/settings.yml` at your deployed server (defaults to
`https://meme.hpi.church/meme`).

## Custom fields

- **Lookback Window (days)** — how many days back to search for the most-reacted
  image (default `7`).
