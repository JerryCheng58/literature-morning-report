# Quality Policy

## Hard Rules

- Never fabricate PMID, DOI, journal metrics, quartile, CAS zone, abstract content, or experimental conclusions.
- A paper is source-verified when it has a PMID, DOI, OpenAlex ID, Crossref metadata, or publisher/source URL.
- Impact factor, JCR quartile, and CAS zone are verified only when supplied through `journal_metrics.tsv` or another explicit source. Otherwise state `unverified`.
- PubMed abstracts may be protected by copyright. Summarize instead of reproducing long text.
- If no new eligible paper exists, generate and optionally send a short no-new-literature report.

## Ranking

Rank candidates by:

1. Fit to `must_include_logic` and `research_direction`.
2. Fit to important mechanisms and user-defined keywords.
3. Reliable identifiers and source links.
4. Journal metric evidence.
5. Recency.
6. Actionability for experiments, methods, or topic selection.

## Adjacent Inspiration

Use adjacent inspiration only when a paper is methodologically useful but fails a strict journal metric or direct disease-match rule. Label it clearly and do not use it to inflate the strict main list.
