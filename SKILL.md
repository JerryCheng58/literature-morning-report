---
name: literature-morning-report
description: Generate a personalized research literature morning report from a user-provided research_profile.yml, with PubMed, Europe PMC, Semantic Scholar, OpenAlex, Crossref, arXiv, Web of Science, Scopus, Embase, and IEEE Xplore retrieval where credentials permit, plus deduplication, bilingual summaries, email delivery, and RIS/BibTeX/ENW/CSL-JSON export.
---

# Literature Morning Report

Use this skill when a researcher wants a daily, personalized literature report, literature alert, paper digest, reference export, or research inspiration workflow based on their own discipline and research direction.

## Quick Start

1. Copy `assets/research_profile.template.yml` to `research_profile.yml`.
2. Fill in the user's research direction, keywords, exclusion rules, journal threshold, email, schedule, and export formats.
3. Run:

```bash
python literature-morning-report/scripts/literature_morning_report.py \
  --profile research_profile.yml \
  --history sent_history.tsv \
  --output-dir reports \
  --max-papers 5
```

4. For a dry run, add `--dry-run`. For email delivery, configure either SMTP environment variables or Resend environment variables.

## Required Profile Fields

The profile must include:

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

See `references/profile_schema.md` for field meanings and examples.

## Workflow

1. Validate the profile.
2. Build database-specific queries from `core_keywords`, `must_include_logic`, and `exclude_keywords`.
3. Search the configured databases. Open sources run directly; Web of Science, Scopus, Embase, and IEEE Xplore run only when valid API credentials/entitlements are present.
4. Fetch paper metadata and abstracts, then deduplicate by PMID, DOI, and normalized title against the history file.
5. Rank papers by research fit, recency, DOI/PMID reliability, journal evidence, and mechanism/actionability.
6. Generate a UTF-8 text report and HTML report. Summarize abstracts; do not reproduce long copyrighted abstracts.
7. Export selected papers as RIS, BibTeX, ENW, and/or CSL-JSON for EndNote, Zotero, and NoteExpress.
8. Send the report if email credentials are configured and the run is not dry-run.
9. Append successfully sent papers to the history file.

## Quality Rules

Follow `references/quality_policy.md`.

Key constraints:

- Do not invent DOI, PMID, journal impact factor, JCR quartile, CAS zone, or conclusions.
- If journal metrics cannot be verified locally, label the metric as unverified instead of presenting it as fact.
- Abstracts must be summarized, not copied at length.
- If no new eligible papers are found, still generate a short no-new-literature report.

## Email Configuration

SMTP:

```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USER=user@example.com
SMTP_PASS=app-password
SMTP_FROM="Literature Report <user@example.com>"
```

Resend:

```bash
RESEND_API_KEY=re_xxx
RESEND_FROM="Literature Report <reports@your-domain.com>"
```

## Export Targets

- EndNote: prefer RIS or ENW.
- Zotero: prefer BibTeX, RIS, CSL-JSON, or Zotero API integration.
- NoteExpress: prefer RIS or BibTeX.

Use `references/export_formats.md` when adding new citation formats or reference-manager integrations.

## Database Sources

Read `references/database_sources.md` before changing database coverage. Supported names in `preferred_databases`:

- Open/low-barrier: `pubmed`, `europepmc`, `semantic_scholar`, `openalex`, `crossref`, `arxiv`.
- Credential-gated: `web_of_science`, `scopus`, `embase`, `ieee_xplore`.

Credential-gated databases must be reported as skipped when credentials are missing. Do not scrape restricted web interfaces.
