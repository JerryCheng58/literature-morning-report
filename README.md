# Literature Morning Report

Personalized daily literature reports for researchers. Configure your research direction once, then generate a traceable morning report with source links, deduplication, bilingual summaries, research ideas, and citation exports for EndNote, Zotero, and NoteExpress.

This repository is a reusable Codex Skill plus a standalone Python CLI. It was extracted from a real PhD literature-monitoring workflow and generalized for researchers in different disciplines.

## What It Does

- Builds database queries from your own `research_profile.yml`.
- Searches open scholarly sources and credential-gated databases when API keys are available.
- Deduplicates papers by PMID, DOI, and normalized title.
- Generates UTF-8 text and HTML reports.
- Summarizes abstracts instead of copying long copyrighted abstracts.
- Exports citations as RIS, BibTeX, ENW, and CSL-JSON.
- Sends email through SMTP or Resend.
- Records skipped databases, so users can audit whether Web of Science, Scopus, Embase, or IEEE Xplore were actually queried.

## Supported Sources

Open or low-barrier sources:

- PubMed / MEDLINE
- Europe PMC
- Semantic Scholar
- OpenAlex
- Crossref
- arXiv

Credential-gated sources:

- Web of Science
- Scopus
- Embase
- IEEE Xplore

Web of Science, Scopus, Embase, and IEEE Xplore require API credentials and/or institutional entitlements. The workflow does not scrape restricted web interfaces.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
Copy-Item assets\research_profile.template.yml research_profile.yml
```

Edit `research_profile.yml`, then run:

```powershell
python scripts\literature_morning_report.py `
  --profile research_profile.yml `
  --history sent_history.tsv `
  --journal-metrics assets\journal_metrics.template.tsv `
  --output-dir reports `
  --dry-run
```

For a no-network demo:

```powershell
python scripts\literature_morning_report.py `
  --profile assets\research_profile.template.yml `
  --history reports\sent_history.tsv `
  --journal-metrics assets\journal_metrics.template.tsv `
  --output-dir reports `
  --offline-sample `
  --dry-run `
  --date 2026-06-14
```

## Configure Your Research Profile

The required profile fields are:

- `discipline`
- `research_direction`
- `core_keywords`
- `must_include_logic`
- `exclude_keywords`
- `preferred_databases`
- `journal_threshold`
- `report_language`
- `delivery_email`
- `delivery_time`
- `export_formats`

See `references/profile_schema.md` for details.

## Email Delivery

Use SMTP:

```powershell
$env:SMTP_HOST="smtp.example.com"
$env:SMTP_PORT="465"
$env:SMTP_USER="user@example.com"
$env:SMTP_PASS="app-password"
$env:SMTP_FROM="Literature Report <user@example.com>"
```

Or use Resend:

```powershell
$env:RESEND_API_KEY="re_xxx"
$env:RESEND_FROM="Literature Report <reports@your-domain.com>"
```

Run without `--dry-run` to send.

## Citation Export

The CLI writes citation files next to the report:

- `.ris` for EndNote, Zotero, and NoteExpress
- `.enw` for EndNote
- `.bib` for Zotero and BibTeX workflows
- `.csl.json` for CSL-compatible tools

## Commercial Boundary

This open-source version is self-hosted and requires users to supply their own API keys and email credentials.

A paid hosted service can provide:

- no-code setup
- stable daily scheduling
- verified sending domain
- personal paper favorites
- one-click export
- team accounts
- curated templates
- support

Do not promise manual expert review unless a human review workflow is actually staffed. The default claim should be: automated, configurable, traceable literature monitoring.

## Disclaimer

This tool is for research productivity. It does not provide medical, clinical, legal, or publication-quality expert advice. Always verify original sources before citing or making research decisions.

## License

MIT License. See `LICENSE`.
