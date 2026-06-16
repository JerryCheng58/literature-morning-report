# Profile Schema

Use `assets/research_profile.template.yml` as the editable template.

## Required Fields

- `discipline`: Broad field such as biomedical sciences, oncology, materials science, psychology, education, economics, or computer science.
- `research_direction`: One precise sentence describing the user's research direction.
- `core_keywords`: Terms used for relevance scoring and fallback broad search.
- `must_include_logic`: One or more Boolean database queries. Each item is searched separately and merged. Use this to enforce strict AND logic.
- `exclude_keywords`: Terms that should remove a paper when found in title or abstract.
- `preferred_databases`: any supported database names from `references/database_sources.md`.
- `journal_threshold`: Local filtering policy. Metrics are only trusted when they come from a supplied metrics file or a verifiable source.
- `report_language`: `zh-en`, `en`, or `zh`.
- `delivery_email`: Recipient email.
- `delivery_time`: Local daily delivery time, for example `10:00`.
- `export_formats`: Any of `ris`, `bibtex`, `enw`, `csl-json`.

## Query Guidance

- Biomedical profiles should include `pubmed` and `europepmc`.
- Cross-disciplinary profiles should include `openalex`, `crossref`, and optionally `semantic_scholar`.
- Engineering/computer science profiles should add `arxiv` and optionally `ieee_xplore` when an IEEE API key is available.
- Web of Science, Scopus, Embase, and IEEE Xplore require credentials or institutional entitlements. Include them only when the operator can provide the needed environment variables.
- For strict requirements, encode them in `must_include_logic`, not just `core_keywords`.
- For organoid workflows, write explicit AND logic such as:

```text
(organoid OR patient-derived organoid OR organoid-on-chip) AND (immunotherapy OR drug screening OR treatment response)
```

## History File

The history TSV should use:

```text
date_sent<TAB>pmid<TAB>doi<TAB>category<TAB>note
```

Papers are deduplicated by PMID, DOI, and normalized title.
