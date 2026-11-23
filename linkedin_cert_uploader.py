"""Reads certificate PDFs from a folder, works out the details, and adds each one
to your LinkedIn profile (with the PDF attached as media), one after another.

WARNING: LinkedIn's User Agreement forbids automating its website. Accounts
that are detected can be restricted. This script goes slowly and you sign in
yourself, but use it at your own risk.

Setup (once):
    python -m pip install playwright pypdf python-dateutil
    python -m playwright install chromium      (only needed if you don't use Edge)

Usage:
    # 1. See what it reads from each PDF -- nothing is sent to LinkedIn
    python linkedin_cert_uploader.py "C:\\path\\to\\certs" --dry-run

    # 2. Upload them, stopping before each Save so you can check the form
    python linkedin_cert_uploader.py "C:\\path\\to\\certs" --confirm

    # 3. Upload them all, unattended
    python linkedin_cert_uploader.py "C:\\path\\to\\certs"

Useful options:
    --issuer RELX
        Issuer to use when the PDF only shows it as a logo (image), which is
        the case for RELX certificates -- there is no text to read.
    --group-name "Agile Scrum Certifications"
        File every certificate under ONE LinkedIn certification name and use the
        course title as the media title (this is what your video does). Without
        it, each course gets its own certification entry.

The first run opens a browser window: sign in to LinkedIn there, then press
Enter in the terminal. The sign-in is kept in ./linkedin-profile for next time
(treat that folder like a password -- it holds your session).

Certificates already uploaded are recorded in uploaded.json next to the PDFs
and skipped on later runs, so you can stop and resume at any time.

Tip: if the script can't find a certificate's name in the PDF, it uses the file
name -- so naming files "AWS Certified Developer - Associate.pdf" works well.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from dateutil import parser as dateparser
from pypdf import PdfReader

# ---------------------------------------------------------------------------
# 1. Reading the PDF
# ---------------------------------------------------------------------------

# Issuer keywords -> the name LinkedIn knows the organisation by.
ISSUERS = [
    (r"\bRELX\b", "RELX"),
    (r"\bAWS\b|Amazon Web Services", "Amazon Web Services (AWS)"),
    (r"Microsoft|Azure", "Microsoft"),
    (r"Google Cloud", "Google Cloud"),
    (r"\bGoogle\b", "Google"),
    (r"Coursera", "Coursera"),
    (r"Udemy", "Udemy"),
    (r"edX\b", "edX"),
    (r"LinkedIn Learning", "LinkedIn"),
    (r"Pluralsight", "Pluralsight"),
    (r"Cisco|CCNA|CCNP", "Cisco"),
    (r"CompTIA", "CompTIA"),
    (r"Oracle", "Oracle"),
    (r"Scrum\.org|Professional Scrum", "Scrum.org"),
    (r"Scrum Alliance|Certified ScrumMaster", "Scrum Alliance"),
    (r"Project Management Institute|\bPMI\b|\bPMP\b", "Project Management Institute"),
    (r"\bISC2\b|\(ISC\)", "ISC2"),
    (r"ISACA", "ISACA"),
    (r"Linux Foundation|\bCNCF\b|Kubernetes", "The Linux Foundation"),
    (r"HashiCorp|Terraform", "HashiCorp"),
    (r"Salesforce", "Salesforce"),
    (r"\bIBM\b", "IBM"),
    (r"Red Hat", "Red Hat"),
    (r"Databricks", "Databricks"),
    (r"Snowflake", "Snowflake"),
    (r"MongoDB", "MongoDB"),
    (r"PeopleCert|AXELOS|ITIL|PRINCE2", "PeopleCert"),
    (r"freeCodeCamp", "freeCodeCamp"),
    (r"HubSpot", "HubSpot"),
    (r"GitHub", "GitHub"),
    (r"Atlassian", "Atlassian"),
]

# Phrases that usually come right before the certification's title. The title
# may be on the same line ("has completed X") or on the next line, which is how
# RELX certificates are laid out ("for successfully completing" / <title>).
TITLE_LEADS = [
    r"has successfully completed(?: the)?",
    r"has completed(?: the)?",
    r"successfully completed(?: the)?",
    r"has earned(?: the)?",
    r"has achieved(?: the)?",
    r"has been awarded(?: the)?",
    r"is hereby (?:awarded|certified as)",
    r"for (?:successfully )?completing(?: the)?",
    r"in recognition of(?: completing)?(?: the)?",
    r"certification(?: name)?\s*:",
    r"course\s*:",
]

# Lines that look like a title.
TITLE_WORDS = re.compile(
    r"Certified|Certification|Certificate (?:in|of)|Associate|Professional|"
    r"Specialist|Practitioner|Fundamentals|Expert|Foundations?",
    re.I,
)
# Lines that are boilerplate, never the title.
NOT_TITLE = re.compile(
    r"^(certi[a-z]*ate of (completion|achievement)|certificate number|certificate no|"
    r"this is to certify|this certifies|presented to|awarded to|awarded|verify|validation|"
    r"credential|issued|date|expir|duration|signature|c ?o ?u ?r ?s ?e$|https?://|www\.)",
    re.I,
)

URL_RE = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.I)
PREFERRED_URL = re.compile(
    r"credly|learn\.microsoft|coursera\.org/(?:verify|account/accomplishments)|"
    r"udemy\.com/certificate|credentials?\.|verify|validation|certmetrics|"
    r"youracclaim|accredible|badgr|cert",
    re.I,
)
CRED_ID_RE = re.compile(
    r"(?:credential|certificate|certification|verification|validation|license|licence|cert)"
    r"\s*(?:id|no\.?|number|#|code)\s*[:#.-]?\s*([A-Z0-9][A-Z0-9\-]{3,})",
    re.I,
)

MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RE = re.compile(
    rf"\b{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b"  # March 3, 2025
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTHS},?\s+\d{{4}}\b"  # 3 March 2025
    rf"|\b{MONTHS}\s+\d{{4}}\b"  # March 2025
    r"|\b\d{4}-\d{2}-\d{2}\b"  # 2025-03-03
    r"|\b\d{1,2}/\d{1,2}/\d{4}\b",  # 03/03/2025
    re.I,
)
ISSUE_KEY = re.compile(r"issue|award|earn|complet|achiev|date|granted|certified on", re.I)
EXPIRY_KEY = re.compile(r"expir|valid (?:until|through|thru|till)|renew", re.I)


@dataclass
class Cert:
    pdf: str
    name: str = ""
    organization: str = ""
    issue: date | None = None
    expiry: date | None = None
    cert_url: str = ""
    cert_id: str = ""
    media_title: str = ""  # title shown under the PDF on your profile
    notes: list[str] = field(default_factory=list)


def pdf_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        # Link annotations often hold the verification URL even when it's not printed.
        for page in reader.pages:
            for annot in page.get("/Annots") or []:
                uri = (annot.get_object().get("/A") or {}).get("/URI")
                if uri:
                    text += f"\n{uri}"
        return text
    except Exception as exc:  # noqa: BLE001 - a bad PDF shouldn't stop the batch
        return f"__ERROR__ {exc}"


def parse_date(s: str) -> date | None:
    try:
        return dateparser.parse(s, default=dateparser.parse("2000-01-01"), dayfirst=False).date()
    except (ValueError, OverflowError):
        return None


def find_dates(lines: list[str]) -> tuple[date | None, date | None]:
    issue = expiry = None
    loose: list[date] = []
    for i, line in enumerate(lines):
        for m in DATE_RE.finditer(line):
            d = parse_date(m.group(0))
            if not d or not (1990 <= d.year <= date.today().year + 10):
                continue
            # The label is usually on the same line or the line above.
            context = line[: m.start()] + " " + (lines[i - 1] if i else "")
            if EXPIRY_KEY.search(context) and not expiry:
                expiry = d
            elif ISSUE_KEY.search(context) and not issue:
                issue = d
            else:
                loose.append(d)
    if not issue and loose:
        past = [d for d in loose if d <= date.today()]
        issue = min(past) if past else None
    if not expiry:
        later = [d for d in loose if issue and d > issue]
        expiry = max(later) if later else None
    return issue, expiry


FRAGMENT_END = re.compile(r"\b(?:a|an|the|as|of|to|for|in|and|be)$", re.I)


def score_title(t: str, issuer: str) -> int:
    """Higher = more likely to be the real certification title."""
    if not (4 <= len(t) <= 120) or NOT_TITLE.search(t) or FRAGMENT_END.search(t):
        return -1
    if re.fullmatch(r"(?:certificate|certification|certified)(?: of \w+)?", t, re.I):
        return -1
    words = len(t.split())
    s = 0
    s += 3 if TITLE_WORDS.search(t) else 0
    s += 2 if 3 <= words <= 12 else 0
    s += 1 if issuer and issuer.split()[0].lower() in t.lower() else 0
    s -= 3 if re.search(r"\b(?:has|have|successfully|requirements|recogni[sz]ed|this)\b", t, re.I) else 0
    s += 1 if t[:1].isupper() else 0
    return s


def find_name(lines: list[str], issuer: str, filename_title: str) -> str:
    # (score, priority, -position, title). Position breaks ties in favour of the
    # line that comes first after the lead phrase (the real title comes before
    # "Date of completion", "Duration", etc.).
    cands: list[tuple[int, int, int, str]] = []

    def add(t: str, priority: int, pos: int) -> None:
        t = t.strip(" .:\"-'")
        sc = score_title(t, issuer)
        if sc >= 0:
            cands.append((sc, priority, -pos, t))

    # Text right after "has successfully completed ..." etc. If the lead phrase
    # is alone on its line, the title is on the line(s) below it.
    for i, line in enumerate(lines):
        for lead in TITLE_LEADS:
            m = re.search(lead + r"\s*(.*)$", line, re.I)
            if not m:
                continue
            if m.group(1).strip():
                add(m.group(1), 3, i)
            for k, nxt in enumerate(lines[i + 1 : i + 3], 1):
                add(nxt, 3 if not m.group(1).strip() else 2, i + k)
            break
    # Any line that reads like a title.
    for i, line in enumerate(lines):
        if TITLE_WORDS.search(line):
            add(line, 1, i)
    # A descriptive file name ("AWS Certified Developer - Associate.pdf").
    if TITLE_WORDS.search(filename_title) and len(filename_title.split()) >= 3:
        add(filename_title, 1, 999)

    if not cands:
        return ""
    return max(cands, key=lambda c: c[:3])[3]


def name_from_filename(path: Path) -> str:
    stem = re.sub(r"[_]+", " ", path.stem)
    stem = re.sub(r"\b(certificate|cert|final|copy|\(\d+\))\b", "", stem, flags=re.I)
    return re.sub(r"\s{2,}", " ", stem).strip(" -")


def extract(path: Path, default_issuer: str = "", group_name: str = "") -> Cert:
    cert = Cert(pdf=str(path))
    text = pdf_text(path)
    if text.startswith("__ERROR__"):
        cert.notes.append(f"couldn't read PDF ({text[10:]})")
        text = ""
    if len(text.strip()) < 20:
        cert.notes.append("no text in PDF (scanned image?) -- using the file name")

    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    full = " ".join(lines) + " " + path.stem

    for pattern, org in ISSUERS:
        if re.search(pattern, full, re.I):
            cert.organization = org
            break
    if not cert.organization and default_issuer:
        cert.organization = default_issuer  # issuer is probably a logo, not text

    course = find_name(lines, cert.organization, name_from_filename(path))
    if not course:
        course = name_from_filename(path)
        cert.notes.append("title not found in PDF -- used the file name")

    cert.media_title = course[:200]
    cert.name = (group_name or course)[:100]  # LinkedIn caps the name at 100 characters

    cert.issue, cert.expiry = find_dates(lines)

    urls = [u.rstrip(".,;)") for u in URL_RE.findall(text)]
    urls = [u if u.lower().startswith("http") else "https://" + u for u in urls]
    preferred = [u for u in urls if PREFERRED_URL.search(u)]
    cert.cert_url = (preferred or urls or [""])[0]

    m = CRED_ID_RE.search(text)
    if m:
        cert.cert_id = m.group(1)

    if not cert.organization:
        cert.notes.append("issuer not found -- pass --issuer \"Name\" or add it to ISSUERS")
    if not cert.issue:
        cert.notes.append("no issue date found -- LinkedIn will leave it blank")
    return cert


# ---------------------------------------------------------------------------
# 2. Driving LinkedIn
# ---------------------------------------------------------------------------


def add_to_profile_url(c: Cert) -> str:
    q: dict[str, str | int] = {"startTask": "CERTIFICATION_NAME", "name": c.name}
    if c.organization:
        q["organizationName"] = c.organization
    if c.issue:
        q["issueYear"], q["issueMonth"] = c.issue.year, c.issue.month
    if c.expiry:
        q["expirationYear"], q["expirationMonth"] = c.expiry.year, c.expiry.month
    if c.cert_url:
        q["certUrl"] = c.cert_url
    if c.cert_id:
        q["certId"] = c.cert_id
    return "https://www.linkedin.com/profile/add?" + urlencode(q)


def human_pause(lo: float = 1.0, hi: float = 2.5) -> None:
    time.sleep(random.uniform(lo, hi))


def top_dialog(page):
    return page.get_by_role("dialog").last


def cert_form(page):
    """The 'Add license or certification' dialog (not the media sub-dialog)."""
    return page.get_by_role("dialog").filter(has_text=re.compile(r"license or certification", re.I)).last


def click_save(dialog, timeout: int = 90000) -> None:
    """Wait for Save to be visible and enabled (LinkedIn disables it while a PDF is still
    processing), then click it."""
    from playwright.sync_api import expect

    btn = dialog.get_by_role("button", name=re.compile(r"^save$", re.I)).last
    btn.wait_for(state="visible", timeout=timeout)
    expect(btn).to_be_enabled(timeout=timeout)
    btn.scroll_into_view_if_needed()
    try:
        btn.click(timeout=timeout)
    except Exception:  # noqa: BLE001 - something overlapping the button; click it directly
        btn.evaluate("el => el.click()")


def fill_if_empty(locator, value: str) -> None:
    """Type into a field only if LinkedIn didn't already pre-fill it."""
    try:
        if locator.count() and not locator.first.input_value().strip():
            locator.first.fill(value)
    except Exception:  # noqa: BLE001 - pre-fill via the URL is the main path
        pass


def ensure_organization(page, form, org: str) -> None:
    """The URL usually pre-fills the issuer. If not, type it and pick the suggestion
    (as in the video: 'RELX' typed, then LinkedIn links it to the company)."""
    if not org:
        return
    box = form.get_by_label(re.compile(r"issuing organi[sz]ation", re.I)).first
    try:
        if box.input_value().strip().lower() == org.lower():
            return
        box.click()
        box.fill("")
        box.press_sequentially(org, delay=90)
        human_pause(1.5, 2.5)
        option = page.get_by_role("option", name=re.compile(rf"^\s*{re.escape(org)}", re.I))
        if option.count():
            option.first.click()  # links the profile entry to the company page + logo
        else:
            # Keep it as plain text. Click the heading to close the dropdown --
            # NOT Escape, which can close the whole dialog.
            form.get_by_role("heading").first.click()
        human_pause()
    except Exception:  # noqa: BLE001
        pass


def ensure_dates(form, c: Cert) -> None:
    """Pick month/year from the dropdowns if the URL didn't pre-fill them."""
    selects = form.locator("select")
    try:
        if selects.count() < 2 or not c.issue:
            return
        pairs = [(0, c.issue)]
        if c.expiry and selects.count() >= 4:
            pairs.append((2, c.expiry))
        for idx, d in pairs:
            month, year = selects.nth(idx), selects.nth(idx + 1)
            if not month.input_value():
                for label in (d.strftime("%B"), d.strftime("%b"), str(d.month)):
                    try:
                        month.select_option(label=label, timeout=2000)
                        break
                    except Exception:  # noqa: BLE001
                        continue
            if not year.input_value():
                year.select_option(label=str(d.year), timeout=2000)
    except Exception:  # noqa: BLE001
        pass


def attach_pdf(page, pdf: Path, title: str) -> None:
    """Add media > pick the PDF > give it the required title > Save (as in the video)."""
    form = cert_form(page)
    add_btn = form.get_by_role("button", name=re.compile(r"add (media|a document|document)", re.I)).first
    add_btn.scroll_into_view_if_needed()
    human_pause(0.5, 1.2)

    # Menu entries LinkedIn may show after "Add media" (wording varies by account/layout).
    menu_text = re.compile(r"^\s*(add a document|add document|document|upload( a)? (file|document)|add a file)\s*$", re.I)

    def pick_from_menu() -> bool:
        for finder in (
            lambda: page.get_by_role("menuitem", name=menu_text),
            lambda: page.get_by_role("button", name=menu_text),
            lambda: page.get_by_role("link", name=menu_text),
            lambda: page.get_by_role("option", name=menu_text),
            lambda: page.get_by_text(menu_text),
        ):
            item = finder()
            if item.count():
                with page.expect_file_chooser(timeout=8000) as fc:
                    item.first.click()
                fc.value.set_files(str(pdf))
                return True
        return False

    try:
        # In the video, "Add media" opens the file picker straight away.
        with page.expect_file_chooser(timeout=5000) as fc:
            add_btn.click()
        fc.value.set_files(str(pdf))
    except Exception:  # noqa: BLE001 - a menu ("Add a document") opened instead, or a hidden input is used
        human_pause(0.8, 1.5)
        try:
            ok = pick_from_menu()
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            page.locator("input[type=file]").last.set_input_files(str(pdf))

    # An "Add media" dialog opens once the upload finishes. Title* is REQUIRED.
    title_re = re.compile(r"^title", re.I)
    title_box = page.get_by_role("textbox", name=title_re).last
    title_box.wait_for(timeout=120000)
    human_pause(1, 2)
    title_box.fill(title)
    human_pause(0.8, 1.5)
    media_dialog = page.get_by_role("dialog").filter(has=page.get_by_role("textbox", name=title_re)).last
    click_save(media_dialog)
    title_box.wait_for(state="hidden", timeout=90000)
    human_pause()


def dismiss_follow_ups(page) -> None:
    """After saving, LinkedIn offers to share the update ('Skip' / 'Next'). Skip it."""
    btn = page.get_by_role("button", name=re.compile(r"^(skip|no thanks|not now|dismiss)$", re.I))
    try:
        btn.first.wait_for(timeout=6000)
        btn.first.click(timeout=3000)
    except Exception:  # noqa: BLE001 - not every save shows the prompt
        pass
    human_pause(1, 2)


def form_errors(page) -> str:
    try:
        msgs = page.locator("[role=alert], .artdeco-inline-feedback--error").all_inner_texts()
        return "; ".join(m.strip() for m in msgs if m.strip())
    except Exception:  # noqa: BLE001
        return ""


def upload_one(page, c: Cert, confirm: bool) -> None:
    goto_safely(page, add_to_profile_url(c))
    form = cert_form(page)
    form.wait_for(timeout=60000)
    human_pause(2, 4)

    # The URL pre-fills most fields; double-check each and fix any that are empty.
    fill_if_empty(form.get_by_label(re.compile(r"^name", re.I)), c.name)
    ensure_organization(page, form, c.organization)
    ensure_dates(form, c)

    attach_pdf(page, Path(c.pdf), c.media_title or c.name)

    if confirm:
        input("  Check the form in the browser, then press Enter to Save...")

    form = cert_form(page)
    click_save(form)
    try:
        # Saved once the form dialog goes away.
        form.wait_for(state="hidden", timeout=90000)
    except Exception as exc:  # noqa: BLE001
        err = form_errors(page)
        raise RuntimeError(f"LinkedIn didn't accept the form{': ' + err if err else ''}") from exc
    human_pause(2, 4)
    dismiss_follow_ups(page)


def goto_safely(page, url: str, tries: int = 3) -> None:
    """page.goto, tolerating 'interrupted by another navigation' (LinkedIn redirects a lot)."""
    for attempt in range(tries):
        try:
            page.goto(url, wait_until="domcontentloaded")
            return
        except Exception as exc:  # noqa: BLE001
            if "interrupted by another navigation" not in str(exc) or attempt == tries - 1:
                raise
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)


def is_signed_in(page) -> bool:
    url = page.url
    if re.search(r"/(login|checkpoint|authwall|uas|signup)", url) or "linkedin.com" not in url:
        return False
    return True


def ensure_signed_in(page) -> None:
    goto_safely(page, "https://www.linkedin.com/feed/")
    if not is_signed_in(page):
        input("\nSign in to LinkedIn in the browser window, then press Enter here...")
        # Let LinkedIn finish its own post-login redirect before we navigate again.
        try:
            page.wait_for_url(re.compile(r"linkedin\.com/(feed|in/|mynetwork|jobs|checkpoint)"), timeout=30000)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
        goto_safely(page, "https://www.linkedin.com/feed/")
        if not is_signed_in(page):
            raise SystemExit("Still not signed in (LinkedIn may be asking for a verification step). "
                             "Finish it in the browser, then run the script again.")


# ---------------------------------------------------------------------------
# 3. The queue
# ---------------------------------------------------------------------------


def describe(c: Cert) -> str:
    rows = [
        ("Name", c.name),
        ("Media title", c.media_title if c.media_title != c.name else "(same as name)"),
        ("Issuer", c.organization or "?"),
        ("Issued", c.issue.strftime("%b %Y") if c.issue else "-"),
        ("Expires", c.expiry.strftime("%b %Y") if c.expiry else "-"),
        ("Credential ID", c.cert_id or "-"),
        ("Credential URL", c.cert_url or "-"),
    ]
    out = "\n".join(f"  {k:<15}{v}" for k, v in rows)
    for n in c.notes:
        out += f"\n  ! {n}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="Folder containing the certificate PDFs")
    ap.add_argument("--dry-run", action="store_true", help="only show what was read from each PDF")
    ap.add_argument("--confirm", action="store_true", help="pause before each Save")
    ap.add_argument("--issuer", default="", help="issuer to use when the PDF doesn't name one in text (e.g. RELX)")
    ap.add_argument("--group-name", default="",
                    help="one LinkedIn certification name for every PDF; the course title becomes the media title")
    ap.add_argument("--profile", type=Path, default=Path(__file__).with_name("linkedin-profile"),
                    help="browser profile folder that keeps you signed in")
    ap.add_argument("--min-gap", type=int, default=30, help="min seconds between certificates (default 30)")
    ap.add_argument("--max-gap", type=int, default=75, help="max seconds between certificates (default 75)")
    ap.add_argument("--limit", type=int, default=10, help="max certificates per run (default 10)")
    args = ap.parse_args()

    pdfs = sorted(args.folder.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {args.folder}")
        return 1

    log_path = args.folder / "uploaded.json"
    done: dict = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    queue = [p for p in pdfs if p.name not in done]
    print(f"{len(pdfs)} PDFs, {len(pdfs) - len(queue)} already uploaded, {len(queue)} to go.")

    certs = [extract(p, args.issuer, args.group_name) for p in queue]

    # Same certificate number twice usually means the same PDF saved under two names.
    seen: dict[str, str] = {}
    for c in certs:
        if c.cert_id and c.cert_id in seen:
            c.notes.append(f"same certificate number as {seen[c.cert_id]} -- possible duplicate")
        elif c.cert_id:
            seen[c.cert_id] = Path(c.pdf).name

    if args.dry_run:
        for c in certs:
            print(f"\n{Path(c.pdf).name}\n{describe(c)}\n  -> {add_to_profile_url(c)}")
        return 0

    certs = certs[: args.limit]
    from playwright.sync_api import sync_playwright  # imported late so --dry-run needs no browser

    failed = []
    with sync_playwright() as pw:
        launch = dict(user_data_dir=str(args.profile), headless=False, viewport={"width": 1280, "height": 900})
        try:
            ctx = pw.chromium.launch_persistent_context(channel="msedge", **launch)
        except Exception:  # noqa: BLE001 - no Edge: use Playwright's Chromium
            ctx = pw.chromium.launch_persistent_context(**launch)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(60000)
        ensure_signed_in(page)

        for i, c in enumerate(certs, 1):
            name = Path(c.pdf).name
            print(f"\n[{i}/{len(certs)}] {name}\n{describe(c)}")
            if not c.organization:
                print("  Skipped: LinkedIn requires an issuer. Re-run with --issuer \"Name\".")
                failed.append(name)
                continue
            try:
                upload_one(page, c, args.confirm)
                done[name] = {**asdict(c), "issue": str(c.issue or ""), "expiry": str(c.expiry or ""),
                              "uploaded": time.strftime("%Y-%m-%d %H:%M")}
                log_path.write_text(json.dumps(done, indent=2), encoding="utf-8")
                print("  Saved.")
            except Exception as exc:  # noqa: BLE001
                shot = args.folder / f"{Path(name).stem}.error.png"
                try:
                    page.screenshot(path=str(shot))
                except Exception:  # noqa: BLE001
                    pass
                print(f"  Couldn't finish automatically: {str(exc).splitlines()[0]}")
                print(f"  Screenshot: {shot}")
                ans = input("  Finish it by hand in the browser and type 'd' if you saved it, "
                            "Enter to skip, or 'q' to quit: ").strip().lower()
                if ans == "d":
                    done[name] = {"uploaded": time.strftime("%Y-%m-%d %H:%M"), "manual": True}
                    log_path.write_text(json.dumps(done, indent=2), encoding="utf-8")
                elif ans == "q":
                    break
                else:
                    failed.append(name)

            if i < len(certs):
                gap = random.uniform(args.min_gap, args.max_gap)
                print(f"  Waiting {gap:.0f}s before the next one...")
                time.sleep(gap)

        ctx.close()

    if failed:
        print("\nNot uploaded:\n  " + "\n  ".join(failed))
    remaining = len(queue) - len(certs)
    if remaining > 0:
        print(f"\n{remaining} left -- run again later (limit {args.limit} per run).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
