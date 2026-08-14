"""
Daily deploy wiring: runs the full pipeline for a given date and publishes
the rendered quiz page as a static file at a per-day path.

    gospel_scraper.fetch_sk/fetch_de -> build_daily_exercise
        -> vocab_quiz_generator.build_daily_email (LLM call)
        -> render into quiz_template.html
        -> write to <output_dir>/<date>.html
        -> write/update <output_dir>/latest.html (convenience alias)

Intended to run once per day via a scheduler (e.g. GitHub Actions on a
cron schedule) against a static-hosting output directory such as a
GitHub Pages `docs/` folder. This script only writes local files - the
publish step (git commit + push, or upload to a host) is the scheduler's
job, not this script's; see daily-quiz-workflow.yml for the GitHub
Actions wiring that does that part.
"""

import json
import sys
from datetime import date
from pathlib import Path
from typing import Callable

from gospel_scraper import fetch_sk, fetch_de, build_daily_exercise
from vocab_quiz_generator import build_daily_email, call_llm_anthropic

TEMPLATE_PATH = Path(__file__).parent / "quiz_page" / "quiz_template.html"
PLACEHOLDER = "/*__DAY_JSON__*/"


def render_quiz_html(day_data: dict, template_path: Path = TEMPLATE_PATH) -> str:
    """Render the quiz page template with one day's data. Uses a plain
    string-replace on a placeholder token rather than regex-matching
    balanced braces in the old hardcoded block - much less fragile."""
    template = template_path.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise ValueError(f"Template at {template_path} is missing the {PLACEHOLDER} placeholder")
    day_json = json.dumps(day_data, ensure_ascii=False, indent=2)
    return template.replace(PLACEHOLDER, day_json)


def build_and_render(d: date, call_llm: Callable[[str], str] = call_llm_anthropic) -> tuple[dict, str]:
    """Run the full pipeline for one date and return (day_data, rendered_html).
    call_llm is injectable so this can be tested/run without a live API key."""
    sk = fetch_sk(d)
    de = fetch_de(d)
    exercise = build_daily_exercise(sk, de)
    if not exercise["citations_match"]:
        print(
            f"WARNING: {d.isoformat()} - SK citation ({exercise['citation_sk']}) and "
            f"DE citation ({exercise['citation_de']}) do not match. Proceeding with "
            f"same-day DE text anyway; see gospel_scraper.py's fetch_pair() docstring "
            f"for the citation-lookup fallback this needs once it's built.",
            file=sys.stderr,
        )
    email = build_daily_email(exercise, call_llm)
    html = render_quiz_html(email)
    return email, html


def write_quiz_files(d: date, html: str, output_dir: Path) -> Path:
    """Write the rendered page for one date, plus a 'latest.html' alias.
    Takes already-rendered html rather than re-running the pipeline, so
    callers that also need day_data (e.g. to send the matching email)
    don't pay for a second LLM call for the same day."""
    output_dir.mkdir(parents=True, exist_ok=True)
    dated_path = output_dir / f"{d.isoformat()}.html"
    dated_path.write_text(html, encoding="utf-8")
    latest_path = output_dir / "latest.html"
    latest_path.write_text(html, encoding="utf-8")
    return dated_path


def publish(d: date, output_dir: Path) -> Path:
    """Convenience wrapper: run the pipeline AND write the files, for
    standalone use (quiz page only, no email). See run_daily.py for the
    combined quiz-page + email flow that shares a single pipeline run."""
    _, html = build_and_render(d)
    return write_quiz_files(d, html, output_dir)


if __name__ == "__main__":
    # Live run - requires ANTHROPIC_API_KEY set and network access to
    # svatepismo.sk, vaticannews.va, and api.anthropic.com. This sandbox
    # can reach api.anthropic.com but not the two scraper sources (see
    # gospel_scraper.py's docstring) - run this on a machine/CI runner
    # with normal internet access.
    target_date = date.today()
    out_dir = Path("docs") / "quiz"
    path = publish(target_date, out_dir)
    print(f"Published {target_date.isoformat()} -> {path}")
