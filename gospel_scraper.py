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
"""

import re
import requests
from datetime import date
from dataclasses import dataclass
from typing import Optional


SK_URL_TEMPLATE = "https://svatepismo.sk/liturgicke-citanie-na-den/{y:04d}-{m:02d}-{d:02d}"
DE_URL_TEMPLATE = "https://www.vaticannews.va/de/tagesevangelium-und-tagesliturgie/{y}/{m:02d}/{d:02d}.html"

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


def _extract_markdown_sections(md_text: str, heading_level: str = "##") -> list[dict]:
    """Split markdown-ish text into sections at a given heading level.
    Returns [{'heading': str, 'body': str}] in document order."""
    pattern = re.compile(rf"^{re.escape(heading_level)}\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(md_text))
    sections = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        sections.append({"heading": m.group(1).strip(), "body": md_text[start:end].strip()})
    return sections


def parse_sk_page(md_text: str, d: date, url: str) -> GospelText:
    """Parse a svatepismo.sk page (markdown-rendered).

    The feast/day name (e.g. "5. nedeľa v Cezročnom období" or "Svätého
    Maximiliána Máriu Kolbeho, kňaza a mučeníka") lives in the page's H1,
    separate from the "## Nedeľa 08. 02. 2026" day-of-week/date heading -
    take the H1, not the H2, or you get the date label instead of the
    actual feast name.

    IMPORTANT: some days carry more than one Mass formulary - e.g. a weekday
    memorial PLUS a vigil Mass for the next day's solemnity (confirmed on a
    real page: 14 Aug 2026 has both the weekday memorial for St Maximilian
    Kolbe AND the Assumption vigil, each with their own '### Evanjelium...'
    section and their own H1 feast heading). The FIRST H1 and FIRST
    '### Evanjelium...' section on the page are always the primary/normal
    day's feast and Gospel; later ones are vigil/optional-memorial variants.
    Do NOT take the last '###' section - that grabs the wrong Gospel on
    these multi-formulary days."""
    h1_sections = _extract_markdown_sections(md_text, "#")
    feast = h1_sections[0]["heading"] if h1_sections else None

    subsections = _extract_markdown_sections(md_text, "###")
    gospel_section = None
    for s in subsections:
        if s["heading"].lower().startswith("evanjelium"):
            gospel_section = s
            break
    if gospel_section is None:
        return GospelText("sk", d.isoformat(), url, feast, None, None, None, None)

    heading = gospel_section["heading"]
    citation = None
    m = CITATION_RE.search(heading)
    if m:
        citation = m.group(0).strip()

    body_lines = [ln for ln in gospel_section["body"].splitlines()]
    body_lines = [ln for ln in body_lines if ln.strip() not in ("", "---")]
    body_lines = [ln for ln in body_lines if not ln.strip().startswith("*Alelujový verš")]
    # Being the last section on the page, this can also pick up the site's
    # trailing attribution note ("Liturgické čítania sú použité z webu...")
    # and any nav link after it - cut everything from that line onward.
    cut_idx = None
    for i, ln in enumerate(body_lines):
        if (
            "použité z webu" in ln
            or ln.strip().startswith("[Nasledujúci")
            or ln.strip().startswith("#### ")  # "Dnešný deň obsahuje tieto varianty" marker
        ):
            cut_idx = i
            break
    if cut_idx is not None:
        body_lines = body_lines[:cut_idx]
    text = "\n".join(body_lines).strip()

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


def parse_de_page(md_text: str, d: date, url: str) -> GospelText:
    """Parse a Vatican News DE page. Gospel section is '## Evangelium vom Tag',
    found positionally by matching 'evangelium' in the heading (case-
    insensitive), which is stable regardless of exact heading punctuation."""
    sections = _extract_markdown_sections(md_text, "##")

    gospel_section = None
    for s in sections:
        if "evangelium" in s["heading"].lower():
            gospel_section = s

    feast = None
    fm = re.search(r"Datum\d{2}/\d{2}/\d{4}\s*\n\s*(.+)", md_text)
    if fm:
        feast = fm.group(1).strip()

    if gospel_section is None:
        return GospelText("de", d.isoformat(), url, feast, None, None, None, None)

    heading = gospel_section["heading"]
    body = gospel_section["body"].strip()
    lines = [ln for ln in body.splitlines() if ln.strip()]
    citation = None
    if len(lines) >= 2:
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
