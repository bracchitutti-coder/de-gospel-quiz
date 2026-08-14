"""
Daily gospel email: renders the HTML + plain-text version of the morning
email from the same day_data payload used by deploy_daily_quiz.py, and
links to that day's published quiz page.

Email-specific constraints this respects (different from the quiz page,
which runs in a real browser):
  - No <script>, no CSS custom properties, no @import web fonts, no
    <details>/<summary> - email clients strip or don't support these
    reliably. Everything here is inline-styled, table-based layout,
    web-safe font stacks only.
  - No gradients relied upon for legibility - a solid bgcolor fallback
    is always set alongside any gradient, since many clients (notably
    Outlook desktop) ignore CSS gradients entirely.
  - Both a text/html and text/plain part are produced - always send both
    (multipart/alternative) for deliverability and accessibility.
"""

import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

DAWN_BLUE = "#4A5B82"
INK = "#1B2333"
PAPER = "#F2EEE3"
GOLD = "#C9A24B"


def build_quiz_url(d: date, base_url: str) -> str:
    """base_url e.g. 'https://yourusername.github.io/gospel-quiz/docs/quiz'"""
    return f"{base_url.rstrip('/')}/{d.isoformat()}.html"


def _vocab_html_rows(vocabulary: list[dict]) -> str:
    rows = []
    for v in vocabulary:
        note = (
            f'<br><span style="font-size:12px;color:#A6483A;">{escape(v["register_note"])}</span>'
            if v.get("register_note")
            else ""
        )
        sk_part = f' <span style="color:#4A5B82;">({escape(v["meaning_sk"])})</span>' if v.get("meaning_sk") else ""
        rows.append(
            f'<tr><td style="padding:6px 0;font-family:Georgia,\'Times New Roman\',serif;'
            f'font-size:14px;color:{INK};line-height:1.5;">'
            f'<strong>{escape(v["word"])}</strong>{sk_part} — {escape(v["meaning_de"])}{note}'
            f"</td></tr>"
        )
    return "\n".join(rows)


def render_email_html(day_data: dict, quiz_url: str) -> str:
    d = day_data["date"]
    feast = escape(day_data.get("feast_sk") or "")
    citation_sk = escape(day_data["citation_sk"])
    citation_de = escape(day_data["citation_de"])
    sk_text = escape(day_data["sk_text"]).replace("\n", "<br>")
    de_text = escape(day_data["de_text"]).replace("\n", "<br>")
    vocab_rows = _vocab_html_rows(day_data["vocabulary"])

    return f"""\
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Evanjelium dňa · {escape(d)}</title>
</head>
<body style="margin:0;padding:0;background-color:{PAPER};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{PAPER};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
       style="width:600px;max-width:100%;background-color:#FAF8F2;border-radius:10px;overflow:hidden;">

  <!-- Header band -->
  <tr>
    <td bgcolor="{DAWN_BLUE}" style="background-color:{DAWN_BLUE};padding:28px 28px 22px;">
      <p style="margin:0;font-family:Helvetica,Arial,sans-serif;font-size:11px;font-weight:bold;
                letter-spacing:1.5px;text-transform:uppercase;color:{GOLD};">
        {escape(d)}
      </p>
      <p style="margin:6px 0 0;font-family:Georgia,'Times New Roman',serif;font-size:20px;
                color:#FAF8F2;line-height:1.3;">
        {feast}
      </p>
      <p style="margin:4px 0 0;font-family:Helvetica,Arial,sans-serif;font-size:12px;color:#C7CEE0;">
        {citation_sk} &nbsp;·&nbsp; {citation_de}
      </p>
    </td>
  </tr>

  <!-- Slovak text -->
  <tr>
    <td style="padding:24px 28px 4px;">
      <p style="margin:0 0 8px;font-family:Helvetica,Arial,sans-serif;font-size:11px;font-weight:bold;
                letter-spacing:1px;text-transform:uppercase;color:{GOLD};">Slovensky</p>
      <p style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:16px;line-height:1.6;color:{INK};">
        {sk_text}
      </p>
    </td>
  </tr>

  <!-- German text -->
  <tr>
    <td style="padding:20px 28px 4px;">
      <p style="margin:0 0 8px;font-family:Helvetica,Arial,sans-serif;font-size:11px;font-weight:bold;
                letter-spacing:1px;text-transform:uppercase;color:{GOLD};">Deutsch</p>
      <p style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:16px;line-height:1.6;color:{INK};">
        {de_text}
      </p>
    </td>
  </tr>

  <!-- Vocabulary -->
  <tr>
    <td style="padding:22px 28px 4px;border-top:1px solid #E4DECF;">
      <p style="margin:0 0 6px;font-family:Helvetica,Arial,sans-serif;font-size:11px;font-weight:bold;
                letter-spacing:1px;text-transform:uppercase;color:{GOLD};">Slová dňa · Wörter des Tages</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        {vocab_rows}
      </table>
    </td>
  </tr>

  <!-- CTA -->
  <tr>
    <td align="center" style="padding:26px 28px 30px;">
      <table role="presentation" cellpadding="0" cellspacing="0">
        <tr>
          <td align="center" bgcolor="{INK}" style="background-color:{INK};border-radius:8px;">
            <a href="{escape(quiz_url)}"
               style="display:inline-block;padding:13px 26px;font-family:Helvetica,Arial,sans-serif;
                      font-size:14px;font-weight:bold;color:{PAPER};text-decoration:none;">
              Dnešný kvíz · Heutiges Quiz
            </a>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <tr>
    <td style="padding:0 28px 22px;text-align:center;">
      <p style="margin:0;font-family:Helvetica,Arial,sans-serif;font-size:11px;color:{DAWN_BLUE};opacity:0.75;">
        Denné cvičenie nemčiny · Tägliche Deutschübung
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>
"""


def render_email_text(day_data: dict, quiz_url: str) -> str:
    vocab_lines = "\n".join(
        f"- {v['word']}"
        + (f" ({v['meaning_sk']})" if v.get("meaning_sk") else "")
        + f" — {v['meaning_de']}"
        + (f" [{v['register_note']}]" if v.get("register_note") else "")
        for v in day_data["vocabulary"]
    )
    return f"""\
{day_data['date']} · {day_data.get('feast_sk') or ''}
{day_data['citation_sk']} / {day_data['citation_de']}

SLOVENSKY
{day_data['sk_text']}

DEUTSCH
{day_data['de_text']}

SLOVA DNA / WORTER DES TAGES
{vocab_lines}

Dnesny kviz / Heutiges Quiz:
{quiz_url}
"""


def send_email(day_data: dict, quiz_url: str) -> None:
    """Sends via SMTP using credentials from environment variables:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO.
    Not run automatically - call explicitly once credentials are set up."""
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    from_addr = os.environ.get("EMAIL_FROM", user)
    to_addr = os.environ["EMAIL_TO"]

    msg = MIMEMultipart("alternative")
    feast = day_data.get("feast_sk") or ""
    msg["Subject"] = f"Evanjelium dňa · {day_data['date']} · {feast}"
    msg["From"] = from_addr
    msg["To"] = to_addr

    msg.attach(MIMEText(render_email_text(day_data, quiz_url), "plain", "utf-8"))
    msg.attach(MIMEText(render_email_html(day_data, quiz_url), "html", "utf-8"))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())


if __name__ == "__main__":
    # Live run - requires ANTHROPIC_API_KEY, network access to the scraper
    # sources, and SMTP_* env vars set for actual sending.
    from deploy_daily_quiz import build_and_render

    QUIZ_BASE_URL = os.environ.get(
        "QUIZ_BASE_URL", "https://yourusername.github.io/gospel-quiz/docs/quiz"
    )

    d = date.today()
    day_data, _ = build_and_render(d)
    quiz_url = build_quiz_url(d, QUIZ_BASE_URL)

    html = render_email_html(day_data, quiz_url)
    print(html[:500], "...\n[truncated]")

    if os.environ.get("SMTP_HOST"):
        send_email(day_data, quiz_url)
        print("Email sent.")
    else:
        print("SMTP_HOST not set - skipping actual send (dry run only).")
