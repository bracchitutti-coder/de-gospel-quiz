"""
Daily orchestration: the ONE script the scheduler actually runs each morning.

Runs the full pipeline exactly once (one LLM call), then:
  1. writes the quiz page to docs/quiz/<date>.html (+ latest.html alias)
  2. sends the matching email with a link to that same page

Calling deploy_daily_quiz.py and build_email.py as separate scripts would
each independently re-run the pipeline (and re-pay for the LLM call) for
the same day's data - this script builds once and reuses the result for
both outputs.
"""

import os
import sys
from datetime import date
from pathlib import Path

from deploy_daily_quiz import build_and_render, write_quiz_files
from build_email import build_quiz_url, send_email


def run(d: date, output_dir: Path, quiz_base_url: str, do_send_email: bool = True) -> None:
    day_data, html = build_and_render(d)
    dated_path = write_quiz_files(d, html, output_dir)
    print(f"Wrote {dated_path}")

    quiz_url = build_quiz_url(d, quiz_base_url)

    if do_send_email:
        send_email(day_data, quiz_url)
        print(f"Sent email linking to {quiz_url}")
    else:
        print(f"Skipping email send (SMTP not configured); quiz page linked at {quiz_url}")


if __name__ == "__main__":
    target_date = date.today()
    out_dir = Path("docs") / "quiz"

    # In GitHub Actions this is set from repo context (owner + repo name)
    # so it doesn't need to be hardcoded per fork - see daily-quiz-workflow.yml.
    quiz_base_url = os.environ.get(
        "QUIZ_BASE_URL", "https://yourusername.github.io/gospel-quiz/quiz"
    )

    have_smtp = bool(os.environ.get("SMTP_HOST"))
    if not have_smtp:
        print("SMTP_HOST not set - will publish the quiz page but skip sending email.", file=sys.stderr)

    run(target_date, out_dir, quiz_base_url, do_send_email=have_smtp)
