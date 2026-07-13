"""
Mensa Griebnitzsee Scraper.

Aus einem Discord-Bot umgebaut zu einem reinen Scraper mit einem
einzigen Einstiegspunkt:

    run(input) -> JSON-String mit dem Speiseplan der aktuellen Woche.

Es wird ausschliesslich die Python-Standardbibliothek benutzt
(urllib, html.parser, difflib, json) -- kein `requests`, kein
`beautifulsoup4`.
"""

import ssl
import urllib.error
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser

BASE_URL = "https://www.imensa.de/potsdam/mensa-griebnitzsee/{day}.html"

# Reihenfolge bestimmt die Reihenfolge in der Ausgabe.
DAYS = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag"]

DAY_LABELS = {
    "montag": "Montag",
    "dienstag": "Dienstag",
    "mittwoch": "Mittwoch",
    "donnerstag": "Donnerstag",
    "freitag": "Freitag",
}

# HTML-Void-Elemente haben kein schliessendes Tag -> bei der
# Verschachtelungstiefe nicht mitzaehlen.
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

# Ab dieser Aehnlichkeit gelten zwei Beschreibungen als dasselbe Gericht.
_DUPLICATE_THRESHOLD = 0.75

# Der Runner hat keine CA-Zertifikate -> Zertifikatspruefung deaktivieren.
# (Tradeoff: kein Schutz vor MITM; fuer einen oeffentlichen Speiseplan ok.)
_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE


class _MealParser(HTMLParser):
    """Zieht (Kategorie, Beschreibung, Preis) aus dem HTML eines Tages.

    Die imensa-Struktur sieht in etwa so aus:

        <div class="aw-meal-category">
            <h3 class="aw-meal-category-name">Vegan</h3>
            <p  class="aw-meal-description">Gemuesecurry ...</p>
            <div class="aw-meal-price">1,50 &euro;</div>
        </div>
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meals = []  # gesammelte {'category','description','price'}
        self._depth = 0
        self._meal = None  # aktuell befuelltes Gericht
        self._meal_depth = None  # Tiefe, in der das Kategorie-div geoeffnet wurde
        self._field = None  # 'category' | 'description' | 'price'
        self._field_depth = None

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            return
        self._depth += 1
        classes = dict(attrs).get("class", "").split()

        if "aw-meal-category" in classes and self._meal is None:
            self._meal = {"category": "", "description": "", "price": ""}
            self._meal_depth = self._depth

        if self._meal is not None and self._field is None:
            if "aw-meal-category-name" in classes:
                self._field, self._field_depth = "category", self._depth
            elif "aw-meal-description" in classes:
                self._field, self._field_depth = "description", self._depth
            elif "aw-meal-price" in classes:
                self._field, self._field_depth = "price", self._depth

    def handle_data(self, data):
        if self._field is not None and self._meal is not None:
            self._meal[self._field] += data

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        # Feld beenden, sobald sein eigenes Tag schliesst.
        if self._field is not None and self._depth <= self._field_depth:
            self._field = None
            self._field_depth = None
        # Gericht abschliessen und speichern, sobald das Kategorie-div schliesst.
        if self._meal is not None and self._depth <= self._meal_depth:
            self.meals.append(self._meal)
            self._meal = None
            self._meal_depth = None
            self._field = None
            self._field_depth = None
        self._depth -= 1


def _parse_price(price_text, category):
    """Liefert die drei Preisstufen (float oder None) aus dem Roh-Preistext."""
    prices = {"student": None, "employee": None, "guest": None}
    if not price_text or "€" not in price_text:
        return prices
    try:
        student = float(price_text.replace("€", "").replace(",", ".").strip())
    except ValueError:
        return prices
    # Feste Aufschlaege des Studierendenwerks Potsdam.
    if "Dessert" in category:
        employee = guest = student + 0.50
    else:
        employee = student + 2.55
        guest = student + 3.55
    return {
        "student": round(student, 2),
        "employee": round(employee, 2),
        "guest": round(guest, 2),
    }


def parse_day(html):
    """Parst das HTML eines Tages zu einer Liste von Gerichten (gefiltert + dedupliziert)."""
    parser = _MealParser()
    parser.feed(html)

    meals = []
    seen = []
    for raw in parser.meals:
        category = raw["category"].strip()
        description = " ".join(raw["description"].split())
        price_text = raw["price"].strip()

        if not category or not description:
            continue
        # Abend-Angebot und Theke ueberspringen.
        if "Abend" in category or "theke" in category.lower():
            continue
        # Fast identische Gerichte (gleiche Speise unter zwei Labels) verwerfen.
        if any(
            SequenceMatcher(None, description.lower(), s).ratio() > _DUPLICATE_THRESHOLD
            for s in seen
        ):
            continue
        seen.append(description.lower())

        meals.append(
            {
                "category": category,
                "description": description,
                "prices": _parse_price(price_text, category),
            }
        )
    return meals


def _fetch(url):
    """Laedt eine Seite via urllib und gibt den dekodierten HTML-Text zurueck."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (mensa-scraper)"}
    )
    with urllib.request.urlopen(req, timeout=15, context=_SSL_CONTEXT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def scrape_week():
    """Laedt und parst jeden Wochentag der aktuellen Woche."""
    week = {}
    # for day in DAYS:
    now = datetime.now()
    _, _, iso_day = now.isocalendar()
    for day_nr in range(iso_day - 1, iso_day + 1):
        day = DAYS[day_nr]
        try:
            html = _fetch(BASE_URL.format(day=day))
            meals = parse_day(html)
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            ValueError,
        ) as e:
            meals = []
            print(f"Fehler beim Laden von {day}: {e}")
        week[day] = {"label": DAY_LABELS[day], "meals": meals}
    return week


def run(input=None):
    """Einstiegspunkt.

    `input` darf das rohe HTML einer einzelnen Seite enthalten. Es wird der
    Kompatibilitaet halber akzeptiert, aber nicht benoetigt: die aktuelle
    Woche wird direkt per urllib von imensa geladen.

    Rueckgabe: dict mit dem Speiseplan der aktuellen Woche. Der Runner
    serialisiert das Ergebnis selbst zu JSON. Falls ein JSON-*String*
    gebraucht wird, stattdessen `return json.dumps(result, ensure_ascii=False)`.
    """
    now = datetime.now()
    iso_year, iso_week, _ = now.isocalendar()

    result = {
        "mensa_name": "Griebnitzsee",
        "location": "Potsdam",
        "week": f"{iso_week:02d}",
        "scraped_at": now.isoformat(timespec="seconds"),
        "days": scrape_week(),
    }
    return result


if __name__ == "__main__":
    now = datetime.now()
    iso_year, iso_week, iso_day = now.isocalendar()
    print(iso_day)
