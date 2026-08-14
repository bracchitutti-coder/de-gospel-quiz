"""
Daily gospel fetcher: Slovak (primary) + German (paired) for the German-learning
gospel-email project.

Sources:
  SK: svatepismo.sk/liturgicke-citanie-na-den/YYYY-MM-DD
      Full Slovak liturgical readings, republished from lc.kbs.sk (the
      Slovak Bishops' Conference calendar) with the full text included -
      lc.kbs.sk itself only publishes citations, not full text, so
      svatepismo.sk is used as the full-text SK source. Slovak day/calendar
      always takes precedence, per design decision.
  DE: vaticannews.va/de/tagesevangelium-und-tagesliturgie/YYYY/MM/DD.html
      Full German liturgical readings (Einheitsübersetzung 2016). NOTE:
      this is NOT the same URL family as the English "word-of-the-day"
      pages - the German section uses a different path.

Pairing logic:
  1. Always fetch the SK page for the requested date - this is authoritative.
  2. Fetch the DE page for the same date.
  3. Compare the Gospel citations (e.g. "Mt 5, 13-16" vs "Mt 14, 13-21").
     If they match (same book + chapter + verses), the same-day DE text is
     used directly - cleanest case, same pericope same day.
  4. If they don't match (calendars diverged - national/local feast days
     etc.), same_day_de is still returned for reference, but callers should
     source the German text for the SK citation from a citation-lookup
     Bible source instead (not implemented here - see NOTE at bottom).

IMPORTANT PARSING NOTE: this module parses the REAL HTML the sites return
(via BeautifulSoup) - not a Markdown-converted representation. An earlier
version of this file was built and tested against Markdown text obtained
through a browsing tool that auto-converts pages before they're ever seen,
which does NOT match what Python's `requests` actually receives (raw HTML
with <h1>/<h2>/<h3> tags, not '#'/'##'/'###' text). That mismatch was never
exercised until this ran for real against live pages - see the git history
/ conversation for how that surfaced. This version has NOT been verified
against a real live fetch either (this development sandbox cannot reach
these domains), only against hand-built HTML fixtures approximating the
structure seen via the browsing tool - so some iteration after a real run
is still expected. The ValueError raised when no matching section is found
includes the actual heading tags/text found, specifically to make that
next round of debugging fast rather than another blind guess.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import date
from dataclasses import dataclass
from typing import Optional


SK_URL_TEMPLATE = "https://svatepismo.sk/liturgicke-citanie-na-den/{y:04d}-{m:02d}-{d:02d}"
DE_URL_TEMPLATE = "https://www.vaticannews.va/de/tagesevangelium-und-tagesliturgie/{y}/{m:02d}/{d:02d}.html"

HEADING_TAGS = ("h1", "h2", "h3", "h4")

# Text fragments that mark the end of real content and the start of
# site boilerplate (nav links, attribution, cookie/copyright text) - used
# as a hard stop when collecting paragraph text, since boilerplate isn't
# always separated from content by its own heading tag.
SK_BOILERPLATE_MARKERS = ("použité z webu", "Nasledujúci deň", "Predošlý deň")
DE_BOILERPLATE_MARKERS = (
    "Einheitsübersetzung der Heiligen Schrift",
    "Dein Beitrag zu einer großen Mission",
    "Copyright ©",
)

# Citation book-abbreviation differences between languages worth normalizing.
# Matthew/Mark/Luke abbreviations are shared (Mt, Mk, Lk); John differs
# (SK: Jn, DE: Joh). Extend this table if other mismatches turn up in testing.
BOOK_ABBR_SK_TO_DE = {"Jn": "Joh"}
BOOK_ABBR_DE_TO_SK = {v: k for k, v in BOOK_ABBR_SK_TO_DE.items()}

CITATION_RE = re.compile(r"([A-ZÁ-Ža-zá-ž]{2,4})\s*(\d+)\s*,\s*([\d.,\u2013\-–\s]+)")


@dataclass
class GospelText:
    lang: str
    date: str
    url: str
    feast: Optional[str]
    citation: Optional[str]
    citation_normalized: Optional[str]
    heading: Optional[str]
    text: Optional[str]


def _normalize_citation(raw: str, lang: str) -> Optional[str]:
    """Normalize a citation string to 'BOOK CHAPTER:VERSES' with digits only
    for verses (dashes/commas stripped to a comparable core), so SK and DE
    citations for the same pericope compare equal regardless of punctuation
    style (en-dash vs hyphen, comma vs period)."""
    m = CITATION_RE.search(raw)
    if not m:
        return None
    book, chapter, verses = m.groups()
    book = book.strip()
    if lang == "de" and book in BOOK_ABBR_DE_TO_SK:
        book = BOOK_ABBR_DE_TO_SK[book]
    verses_digits = re.sub(r"[^\d,]", "", verses.replace(".", ","))
    return f"{book}{chapter}:{verses_digits}"


def _find_heading_and_paragraphs(
    soup: BeautifulSoup, keyword: str, boilerplate_markers: tuple[str, ...]
) -> tuple[Optional[str], Optional[list[str]], list[tuple[str, str]]]:
    """Find the first heading tag (checked across HEADING_TAGS, in document
    order) whose text STARTS WITH `keyword` (case-insensitive, not just
    "contains" - a page's generic nav/title heading can legitimately
    contain the word "evanjelium"/"evangelium" as part of a longer phrase
    without being the actual Gospel section; anchoring to the start avoids
    matching those). Returns
    (heading_text, paragraph_texts, all_headings_found) where
    all_headings_found is [(tag_name, text), ...] for every heading on the
    page - always returned so callers can build a useful error message
    whether or not the target was found.

    Paragraph collection stops at whichever comes first: the next heading
    tag (any level in HEADING_TAGS), or a paragraph matching one of
    boilerplate_markers (attribution/nav text that isn't always under its
    own heading)."""
    all_headings = soup.find_all(HEADING_TAGS)
    all_headings_found = [(h.name, h.get_text(" ", strip=True)) for h in all_headings]

    target = None
    for h in all_headings:
        if h.get_text(" ", strip=True).lower().startswith(keyword.lower()):
            target = h
            break

    if target is None:
        return None, None, all_headings_found

    heading_text = target.get_text(" ", strip=True)
    paragraphs: list[str] = []
    for elem in target.find_all_next():
        if elem in all_headings:
            break
        if getattr(elem, "name", None) == "p":
            text = elem.get_text(" ", strip=True)
            if not text:
                continue
            if any(marker in text for marker in boilerplate_markers):
                break
            paragraphs.append(text)

    return heading_text, paragraphs, all_headings_found


def parse_sk_page(html: str, d: date, url: str) -> GospelText:
    """Parse a svatepismo.sk page's real HTML.

    The feast/day name (e.g. "5. nedeľa v Cezročnom období" or "Svätého
    Maximiliána Máriu Kolbeho, kňaza a mučeníka") is the page's <h1> -
    separate from a "Nedeľa 08. 02. 2026" day-of-week/date label elsewhere
    on the page.

    IMPORTANT: some days carry more than one Mass formulary - e.g. a weekday
    memorial PLUS a vigil Mass for the next day's solemnity (confirmed on a
    real page: 14 Aug 2026 has both the weekday memorial for St Maximilian
    Kolbe AND the Assumption vigil, each with their own Evanjelium heading).
    Taking the FIRST matching heading on the page is what makes this pick
    the primary/normal day's Gospel rather than a vigil/optional variant.

    Raises ValueError (with every heading found on the page, for diagnosis)
    if no Evanjelium heading is found at all."""
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    feast = h1.get_text(" ", strip=True) if h1 else None

    heading, paragraphs, all_headings = _find_heading_and_paragraphs(
        soup, "evanjelium", SK_BOILERPLATE_MARKERS
    )
    if heading is None:
        raise ValueError(
            f"parse_sk_page: no heading starting with 'evanjelium' found for {d.isoformat()} "
            f"at {url}. Headings found on page: {all_headings!r}. The page structure may "
            f"have changed, or this date's content may not be published yet - try again "
            f"later or inspect the URL directly."
        )

    citation = None
    m = CITATION_RE.search(heading)
    if m:
        citation = m.group(0).strip()

    # Drop the alleluia verse line (present as the first paragraph before
    # the pericope title) - it's a liturgical acclamation, not part of the
    # Gospel text itself.
    paragraphs = [p for p in paragraphs if not p.lower().startswith("alelujový verš")]
    text = "\n".join(paragraphs).strip()

    return GospelText(
        lang="sk",
        date=d.isoformat(),
        url=url,
        feast=feast,
        citation=citation,
        citation_normalized=_normalize_citation(citation, "sk") if citation else None,
        heading=heading,
        text=text,
    )


def parse_de_page(html: str, d: date, url: str) -> GospelText:
    """Parse a Vatican News DE page's real HTML. Gospel section is the
    heading containing 'evangelium' (case-insensitive) - e.g. 'Evangelium
    vom Tag'.

    Raises ValueError (with every heading found on the page, for diagnosis)
    if no matching heading is found at all - e.g. if a major solemnity is
    formatted differently, or the date's content isn't published yet."""
    soup = BeautifulSoup(html, "html.parser")

    feast = None
    date_marker = soup.find(string=re.compile(r"Datum\d{2}/\d{2}/\d{4}"))
    if date_marker is not None:
        # The feast/day name is the next non-empty text node after the
        # "DatumDD/MM/YYYY" marker in the page's text flow. Call find_next
        # on the string node itself (not its parent tag) - calling it on
        # the parent can return the marker's own text again instead of
        # advancing past it.
        nxt = date_marker.find_next(string=True)
        while nxt is not None and not nxt.strip():
            nxt = nxt.find_next(string=True)
        if nxt:
            feast = nxt.strip()

    heading, paragraphs, all_headings = _find_heading_and_paragraphs(
        soup, "evangelium", DE_BOILERPLATE_MARKERS
    )
    if heading is None:
        raise ValueError(
            f"parse_de_page: no heading starting with 'evangelium' found for {d.isoformat()} "
            f"at {url}. Headings found on page: {all_headings!r}. The page structure may "
            f"have changed for this date (e.g. a major solemnity formatted differently), "
            f"or this date's content may not be published yet - try again later or "
            f"inspect the URL directly."
        )

    citation = None
    lines = list(paragraphs)
    if lines:
        m = CITATION_RE.search(lines[0])
        if m:
            citation = m.group(0).strip()
            lines = lines[1:]
        elif len(lines) >= 2:
            m = CITATION_RE.search(lines[1])
            if m:
                citation = m.group(0).strip()
                lines = lines[2:]

    text = "\n".join(lines).strip()

    return GospelText(
        lang="de",
        date=d.isoformat(),
        url=url,
        feast=feast,
        citation=citation,
        citation_normalized=_normalize_citation(citation, "de") if citation else None,
        heading=heading,
        text=text,
    )


def fetch_sk(d: date) -> GospelText:
    url = SK_URL_TEMPLATE.format(y=d.year, m=d.month, d=d.day)
    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return parse_sk_page(resp.text, d, url)


def fetch_de(d: date) -> GospelText:
    url = DE_URL_TEMPLATE.format(y=d.year, m=d.month, d=d.day)
    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return parse_de_page(resp.text, d, url)


def fetch_pair(d: date) -> dict:
    """Slovak always wins for the day. German is fetched for the same date;
    citation match/mismatch tells the caller whether it's safe to pair
    directly or whether a citation-lookup fallback is needed for German."""
    sk = fetch_sk(d)
    de = fetch_de(d)
    same_citation = (
        sk.citation_normalized is not None
        and sk.citation_normalized == de.citation_normalized
    )
    return {
        "date": d.isoformat(),
        "sk": sk,
        "de_same_day": de,
        "citations_match": same_citation,
        # NOTE: when citations_match is False, `de_same_day` is NOT the
        # right pairing - a citation-lookup fallback (e.g. die-bibel.de or
        # a Bible API queried by sk.citation) is needed to fetch the correct
        # German text for sk.citation. Not implemented in this module yet.
    }


def build_daily_exercise(sk: GospelText, de: GospelText) -> dict:
    """Build the actual compact daily-exercise payload: Gospel text only,
    both languages, nothing else (no Tageslesung/first reading, no Psalm,
    no second reading, no papal commentary) - kept minimal on purpose so
    the daily email/exercise stays short and efficient."""
    return {
        "date": sk.date,
        "citation_sk": sk.citation,
        "citation_de": de.citation,
        "citations_match": sk.citation_normalized == de.citation_normalized,
        "feast_sk": sk.feast,
        "sk_text": sk.text,
        "de_text": de.text,
    }


if __name__ == "__main__":
    # Live run (needs network access to svatepismo.sk and vaticannews.va -
    # this sandbox's egress allowlist blocks both; run this on a machine
    # with normal internet access).
    result = fetch_pair(date.today())
    print(result)
