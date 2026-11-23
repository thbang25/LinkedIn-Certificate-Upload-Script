# LinkedIn Certificate Uploader

A Python script that reads certificate PDFs from a folder, works out the details of each one (course name, issuer, dates, credential ID, verification URL), and adds it to your LinkedIn profile under **Licenses & certifications**, with the PDF attached as media.

It drives a real, visible browser window using [Playwright](https://playwright.dev/python/). You sign in to LinkedIn yourself, and the script fills in and saves the "Add license or certification" form for each PDF, one after another, with pauses in between.

> **Warning: use at your own risk.** LinkedIn's User Agreement prohibits automating its website, and accounts that are detected can be restricted. The script runs slowly, in a visible browser, and you sign in yourself, but that does not guarantee your account is safe. See [Staying on LinkedIn's good side](#staying-on-linkedins-good-side).

---

## Features

- Extracts the certification name, issuer, issue and expiry dates, credential ID and credential URL from each PDF.
- Handles titles that follow "for successfully completing" or "has completed", including titles on a separate line.
- Falls back to the file name when the PDF has no readable text.
- Fills the form through a LinkedIn link, then double-checks each field and fixes any that are empty.
- Attaches the PDF as media and fills the required media title.
- Skips the "share this update" popup after saving.
- Remembers what it has uploaded in `uploaded.json`, so you can stop and resume at any time.
- Dry-run mode shows what it read from each PDF without touching LinkedIn.
- Saves a screenshot when something goes wrong.

## Requirements

- Python 3.9 or newer
- Microsoft Edge (preinstalled on Windows), or Playwright's Chromium
- A LinkedIn account

## Installation

```bash
python -m pip install playwright pypdf python-dateutil
```

If you don't use Edge, also install Playwright's browser:

```bash
python -m playwright install chromium
```

The script tries Edge first and falls back to Chromium automatically.

## Quick start

```bash
# 1. See what it reads from each PDF. Nothing is sent to LinkedIn.
python linkedin_cert_uploader.py "C:\path\to\certs" --dry-run

# 2. Upload a couple, pausing before each Save so you can check the form.
python linkedin_cert_uploader.py "C:\path\to\certs" --confirm --limit 2

# 3. Upload the rest.
python linkedin_cert_uploader.py "C:\path\to\certs"
```

On the first run a browser window opens. Sign in to LinkedIn there, then press **Enter** in the terminal. Your session is kept in a `linkedin-profile` folder next to the script, so later runs usually don't ask you to sign in again.

## Command reference

```
python linkedin_cert_uploader.py FOLDER [options]
```

| Argument / option | Default | What it does |
|---|---|---|
| `FOLDER` | required | Folder containing the certificate PDFs. |
| `--dry-run` | off | Only print what was read from each PDF and the LinkedIn link it would use. Needs no browser and no sign-in. |
| `--confirm` | off | Pause before each Save so you can check the form in the browser. Press Enter to save. |
| `--issuer NAME` | none | Issuer to use when the PDF doesn't name one in text, for example when it is only a logo image. |
| `--group-name NAME` | none | File every certificate under one LinkedIn certification name. The course title becomes the media title shown under the PDF. |
| `--profile PATH` | `./linkedin-profile` | Browser profile folder that keeps you signed in. |
| `--min-gap SECONDS` | `30` | Minimum wait between certificates. |
| `--max-gap SECONDS` | `75` | Maximum wait between certificates. The actual wait is random between the two. |
| `--limit N` | `10` | Maximum number of certificates per run. |
| `-h`, `--help` | | Show the built-in help. |

### Example commands

Preview everything, with a fixed issuer:

```bash
python linkedin_cert_uploader.py "C:\certs" --dry-run --issuer RELX
```

First real run: two certificates, checking each one before it is saved:

```bash
python linkedin_cert_uploader.py "C:\certs" --issuer RELX --confirm --limit 2
```

Regular run: grouped under one name, slow and gentle:

```bash
python linkedin_cert_uploader.py "C:\certs" --issuer RELX --group-name "RELX Learning Certificates" --min-gap 120 --max-gap 300 --limit 10
```

Process everything in one go (higher risk, see below):

```bash
python linkedin_cert_uploader.py "C:\certs" --issuer RELX --group-name "RELX Learning Certificates" --min-gap 120 --max-gap 300 --limit 500
```

Use a separate browser profile, for example for a second account:

```bash
python linkedin_cert_uploader.py "C:\certs" --profile "C:\linkedin-profile-2"
```

## How it works

1. **Read the PDFs.** Text is extracted with `pypdf`. The script looks for a title after phrases such as "has completed" or "for successfully completing", an issuer from a built-in list, dates labelled as issued or expiring, a certificate or credential ID, and any verification URL.
2. **Build a LinkedIn link.** It opens `linkedin.com/profile/add?startTask=CERTIFICATION_NAME&...` with the details filled in.
3. **Check the form.** Any field the link didn't fill (name, issuer, issue date) is filled in by the script.
4. **Attach the PDF.** It clicks **Add media**, chooses the PDF, types the required media title, and saves the media dialog.
5. **Save and move on.** It saves the certificate, skips the share-update prompt, records the file in `uploaded.json`, waits a random gap, and continues.

## Files the script creates

| File | Where | Purpose |
|---|---|---|
| `uploaded.json` | inside your PDF folder | Log of uploaded PDFs. Delete an entry (or the file) to upload that PDF again. |
| `<name>.error.png` | inside your PDF folder | Screenshot taken when a certificate fails. |
| `linkedin-profile/` | next to the script | Browser profile holding your LinkedIn session. |

## When something goes wrong

If a certificate can't be completed, the script saves a screenshot and asks what to do:

- Type **`d`** if you finished it by hand and it saved. It is logged as done.
- Press **Enter** to skip it. It will be tried again on the next run.
- Type **`q`** to quit.

Common issues:

| Problem | What to try |
|---|---|
| `ModuleNotFoundError: No module named 'pypdf'` | Run the install command above. |
| "Issuer not found" / certificate skipped | Pass `--issuer "Name"`, or add the issuer to the `ISSUERS` list in the script. |
| Name is wrong or taken from the file name | Run `--dry-run` to see what was read. If the PDF has no readable text, rename the file to the certification name. |
| Timeouts | LinkedIn can be slow. The script already waits up to 90 seconds for key steps. Check your connection and run again. |
| Still asked to sign in | Finish any verification step LinkedIn shows in the browser, then run the script again. |
| Browser warning about a "sandbox" | Harmless. It comes from the automation browser, not from LinkedIn. |

## Customising

- **Add an issuer.** Edit the `ISSUERS` list near the top of the script. Each entry is a pattern to look for in the PDF and the exact name LinkedIn uses for that organisation.
- **Add title phrases.** Edit `TITLE_LEADS` for phrases that appear just before the title in your certificates.

## Staying on LinkedIn's good side

There is no setting that makes automation safe, but these habits lower the risk:

- Keep the browser **visible** (never headless).
- Use long gaps, for example `--min-gap 120 --max-gap 300`.
- Upload in small batches (`--limit 10`) and spread them over several days instead of one long run.
- Use `--group-name` so you add a few certification entries with many media items, rather than hundreds of separate entries.
- Check your profile after the first runs. If LinkedIn shows a verification prompt or any warning, stop and wait a few days.

## Limitations

- It depends on LinkedIn's current page layout. If LinkedIn changes the form, a step may need updating.
- PDFs that are scanned images have no text to read, so the file name is used instead.
- Issuer names embedded only in a logo can't be read. Use `--issuer`.
- It adds certificates only. It doesn't edit or delete existing ones.

## Keep secrets out of git

Add this to your `.gitignore` so you never publish your LinkedIn session or your personal certificates:

```
linkedin-profile/
uploaded.json
*.error.png
*.pdf
```

## Disclaimer

This project is not affiliated with or endorsed by LinkedIn. You are responsible for complying with LinkedIn's terms and for any consequences for your account.
