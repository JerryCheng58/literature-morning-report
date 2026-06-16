# Database Sources

This workflow supports two database classes: open/low-barrier sources and credential-gated commercial or society databases.

## Open / Low-Barrier Sources

- `pubmed`: NCBI E-utilities for PubMed/MEDLINE. Recommended for biomedical literature. Respect NCBI rate limits and provide `NCBI_TOOL`, `NCBI_EMAIL`, and optionally `NCBI_API_KEY`.
- `europepmc`: Europe PMC REST API. Useful biomedical supplement with PubMed/PMC/Europe PMC coverage.
- `semantic_scholar`: Semantic Scholar Graph API. Useful broad scholarly search and citation discovery. Optional `SEMANTIC_SCHOLAR_API_KEY`.
- `openalex`: OpenAlex Works API. Broad cross-disciplinary metadata. Optional `OPENALEX_EMAIL` and `OPENALEX_API_KEY`.
- `crossref`: Crossref Works API. DOI metadata supplement. Optional `CROSSREF_EMAIL`.
- `arxiv`: arXiv Atom API. Useful for computer science, physics, mathematics, quantitative biology, and preprints.

## Credential-Gated Sources

- `web_of_science`: Clarivate Web of Science Starter API. Requires `CLARIVATE_API_KEY` or `WOS_API_KEY`. The script uses the Starter `/documents` endpoint and `TS=(query)` when the query is not already a WoS field-tag query.
- `scopus`: Elsevier Scopus Search API. Requires `ELSEVIER_API_KEY` or `SCOPUS_API_KEY`; many use cases also require institutional entitlement or `SCOPUS_INST_TOKEN`.
- `embase`: Elsevier Embase access is entitlement-gated. The workflow records it as skipped unless a dedicated Embase connector is implemented for a licensed deployment.
- `ieee_xplore`: IEEE Xplore Metadata Search API. Requires `IEEE_API_KEY` or `IEEE_XPLORE_API_KEY`.

## Environment Variables

```bash
NCBI_TOOL=literature_morning_report
NCBI_EMAIL=developer@example.com
NCBI_API_KEY=
OPENALEX_EMAIL=developer@example.com
OPENALEX_API_KEY=
CROSSREF_EMAIL=developer@example.com
SEMANTIC_SCHOLAR_API_KEY=
CLARIVATE_API_KEY=
WOS_API_KEY=
WOS_DATABASE=WOS
ELSEVIER_API_KEY=
SCOPUS_API_KEY=
SCOPUS_INST_TOKEN=
IEEE_API_KEY=
IEEE_XPLORE_API_KEY=
```

## Product Policy

- Do not claim Web of Science, Scopus, Embase, or IEEE Xplore coverage unless the run status says those databases were actually queried.
- Do not scrape restricted search-result pages.
- Store database run status in every report so paying users can audit coverage.
- Deduplicate across databases by DOI, PMID, and normalized title.

## Official Documentation Links

- NCBI E-utilities: https://www.ncbi.nlm.nih.gov/books/NBK25497/
- Europe PMC REST API: https://europepmc.org/RestfulWebService
- Semantic Scholar API: https://www.semanticscholar.org/product/api
- OpenAlex API: https://developers.openalex.org/
- Crossref REST API: https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- arXiv API: https://info.arxiv.org/help/api/
- Web of Science APIs: https://developer.clarivate.com/apis
- Scopus APIs: https://dev.elsevier.com/
- IEEE Xplore API: https://developer.ieee.org/
