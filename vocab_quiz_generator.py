"""
Vocabulary + comprehension-quiz generation for the daily gospel email.

Wires into gospel_scraper.py's build_daily_exercise() output: takes the
German gospel text only (vocab/quiz are generated from German, since
that's the target language) and produces:
  - 3-5 B1/B2-level vocabulary items, with modern-equivalent notes for
    any word that's liturgical/archaic register
  - 3-5 multiple-choice comprehension questions on the text's content

build_daily_email() then combines this with the SK+DE gospel text from
gospel_scraper into one final compact payload - the actual content for
one day's email.
"""

import json
import os
import requests
from typing import Callable

EXTRACTION_PROMPT = """You are preparing a daily German-learning exercise for a Slovak \
native speaker at CEFR level A1/A2 aiming for B1/B2, built around today's Catholic \
gospel reading. You will be given the German gospel text for the day.

Produce STRICT JSON (no markdown, no commentary) with this shape:
{{
  "vocabulary": [
    {{
      "word": "<word or short phrase as it appears/inflects in the text>",
      "meaning_sk": "<Slovak translation of the word/phrase - this is the primary meaning cue for an A1/A2 learner>",
      "meaning_de": "<short plain-German definition, A2/B1-level German, as a secondary/reinforcing explanation>",
      "example": "<one short original example sentence using the word, NOT quoted from the gospel text>",
      "register_note": "<null, or a brief note + modern equivalent if this word is liturgical/archaic register>"
    }}
  ],
  "quiz": [
    {{
      "question": "<question in German about the text's content, not just vocabulary recall>",
      "options": ["<option A>", "<option B>", "<option C>", "<option D>"],
      "correct_index": <0-3>
    }}
  ]
}}

Rules:
- Choose 3 to 5 vocabulary items: prioritize words a B1/B2 learner would actually
  reuse in daily German, not just words unique to this passage.
- The learner is a Slovak native speaker at A1/A2 reaching for B1/B2 - always give
  the Slovak translation (meaning_sk) as the primary, immediately usable meaning cue;
  the German definition (meaning_de) is a secondary reinforcement, not the only aid.
- If a word is essentially never used outside liturgical/biblical register,
  include it only if central to understanding the passage, and always give a
  register_note with the everyday equivalent.
- Write 3 to 5 quiz questions that test understanding of what happened in the
  text (events, reasons, who/what/why), not just spotting a word.
- Do not quote more than a few words verbatim from the gospel text in any
  example sentence or question - paraphrase in your own words.

Gospel text:
{gospel_text}
"""


def build_prompt(gospel_text: str) -> str:
    return EXTRACTION_PROMPT.format(gospel_text=gospel_text.strip())


def call_llm_anthropic(prompt: str, api_key: str | None = None) -> str:
    """Real call_llm implementation against the Anthropic API. Reads the
    key from the ANTHROPIC_API_KEY env var if not passed explicitly.
    Confirmed reachable from this environment (returns 401 without a key,
    not a network/connectivity error) - just needs a real key to run live."""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Set ANTHROPIC_API_KEY (or pass api_key=) to call the live API.")
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(block["text"] for block in data["content"] if block["type"] == "text")


def generate_vocab_and_quiz(gospel_text: str, call_llm: Callable[[str], str]) -> dict:
    """call_llm: a function taking a prompt string and returning the raw
    model response text (JSON string). Use call_llm_anthropic for the real
    API, or any stand-in for testing."""
    prompt = build_prompt(gospel_text)
    raw = call_llm(prompt)
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(cleaned)


def build_daily_email(exercise: dict, call_llm: Callable[[str], str]) -> dict:
    """Combine gospel_scraper.build_daily_exercise() output with generated
    vocab + quiz into the final, compact daily-email payload: both gospel
    texts (SK+DE), vocabulary, and quiz - nothing else.

    Passes feast_sk through from exercise (build_daily_exercise() already
    includes it) rather than dropping it - callers used to have to patch
    it back on manually after calling this function, which is fragile and
    easy to forget (as vocab_quiz_generator.py's own __main__ block below
    originally did)."""
    vq = generate_vocab_and_quiz(exercise["de_text"], call_llm)
    return {
        "date": exercise["date"],
        "feast_sk": exercise.get("feast_sk"),
        "citation_sk": exercise["citation_sk"],
        "citation_de": exercise["citation_de"],
        "sk_text": exercise["sk_text"],
        "de_text": exercise["de_text"],
        "vocabulary": vq["vocabulary"],
        "quiz": vq["quiz"],
    }


if __name__ == "__main__":
    # Live run - requires ANTHROPIC_API_KEY set, and network access to both
    # svatepismo.sk/vaticannews.va (for the scraper) and api.anthropic.com.
    from datetime import date
    from gospel_scraper import fetch_sk, fetch_de, build_daily_exercise

    d = date.today()
    exercise = build_daily_exercise(fetch_sk(d), fetch_de(d))
    email = build_daily_email(exercise, call_llm_anthropic)
    print(json.dumps(email, indent=2, ensure_ascii=False))
