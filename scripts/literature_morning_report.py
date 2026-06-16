from __future__ import annotations

import argparse
import ast
import datetime as dt
import html
import json
import os
import re
import smtplib
import ssl
import sys
import textwrap
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REQUIRED_PROFILE_FIELDS = {
    "discipline",
    "research_direction",
    "core_keywords",
    "must_include_logic",
    "exclude_keywords",
    "preferred_databases",
    "journal_threshold",
    "report_language",
    "delivery_email",
    "delivery_time",
    "export_formats",
}


DATABASE_ALIASES = {
    "pubmed": {"pubmed", "medline", "ncbi"},
    "europepmc": {"europepmc", "europe-pmc", "europe pmc", "pmc"},
    "semantic_scholar": {"semantic_scholar", "semantic-scholar", "semantic scholar", "s2"},
    "openalex": {"openalex", "open alex"},
    "crossref": {"crossref", "cross ref"},
    "arxiv": {"arxiv", "arxiv.org"},
    "web_of_science": {"web_of_science", "web-of-science", "web of science", "wos", "clarivate"},
    "scopus": {"scopus", "elsevier scopus"},
    "embase": {"embase", "elsevier embase"},
    "ieee_xplore": {"ieee_xplore", "ieee-xplore", "ieee xplore", "ieee"},
}

RESTRICTED_DATABASES = {
    "web_of_science": "Requires CLARIVATE_API_KEY for Web of Science Starter API.",
    "scopus": "Requires ELSEVIER_API_KEY and, for full access, institutional Scopus entitlement.",
    "embase": "Requires ELSEVIER_API_KEY and Embase entitlement; not available through the public Scopus endpoint.",
    "ieee_xplore": "Requires IEEE_API_KEY from IEEE Xplore API registration.",
}


@dataclass
class Paper:
    source: str
    title_en: str
    journal: str = ""
    year: str = ""
    pmid: str = ""
    doi: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    source_urls: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    quality_evidence: str = "unverified"
    score: int = 0
    category: str = "main"

    @property
    def key(self) -> str:
        if self.doi:
            return self.doi.lower()
        if self.pmid:
            return f"pmid:{self.pmid.lower()}"
        return normalize_title(self.title_en)


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        try:
            return ast.literal_eval(value)
        except Exception:
            return [part.strip().strip("\"'") for part in value[1:-1].split(",") if part.strip()]
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1].replace("''", "'")
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def load_simple_yaml(path: Path) -> dict[str, Any]:
    """Small one-level YAML reader used when PyYAML is unavailable."""
    root: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if not raw_line.startswith(" "):
            key, _, value = raw_line.partition(":")
            current_key = key.strip()
            value = value.strip()
            root[current_key] = parse_scalar(value) if value else []
            continue
        if current_key is None:
            continue
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            if not isinstance(root.get(current_key), list):
                root[current_key] = []
            root[current_key].append(parse_scalar(stripped[2:].strip()))
            continue
        subkey, _, value = stripped.partition(":")
        if not isinstance(root.get(current_key), dict):
            root[current_key] = {}
        root[current_key][subkey.strip()] = parse_scalar(value.strip())
    return root


def load_profile(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except Exception:
        data = load_simple_yaml(path)
    if not isinstance(data, dict):
        raise SystemExit(f"Profile is not a mapping: {path}")
    missing = sorted(REQUIRED_PROFILE_FIELDS - set(data))
    if missing:
        raise SystemExit(f"Profile missing required fields: {', '.join(missing)}")
    return data


def load_history(path: Path) -> tuple[set[str], set[str], set[str]]:
    pmids: set[str] = set()
    dois: set[str] = set()
    titles: set[str] = set()
    if not path.exists():
        return pmids, dois, titles
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.startswith("date_sent"):
            continue
        parts = line.split("\t")
        if len(parts) > 1 and parts[1].strip():
            pmids.add(parts[1].strip().lower())
        if len(parts) > 2 and parts[2].strip():
            dois.add(parts[2].strip().lower())
        if len(parts) > 4 and parts[4].strip():
            titles.add(normalize_title(parts[4]))
    return pmids, dois, titles


def read_journal_metrics(path: Path | None) -> dict[str, dict[str, str]]:
    if not path or not path.exists():
        return {}
    rows = path.read_text(encoding="utf-8-sig").splitlines()
    if not rows:
        return {}
    header = [h.strip().lower() for h in rows[0].split("\t")]
    metrics: dict[str, dict[str, str]] = {}
    for line in rows[1:]:
        if not line.strip():
            continue
        values = line.split("\t")
        row = {header[i]: values[i].strip() for i in range(min(len(header), len(values)))}
        journal = normalize_title(row.get("journal", ""))
        if journal:
            metrics[journal] = row
    return metrics


def http_get(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "literature-morning-report/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def http_json(url: str, timeout: int = 30) -> dict[str, Any]:
    return json.loads(http_get(url, timeout=timeout).decode("utf-8"))


def build_queries(profile: dict[str, Any]) -> list[str]:
    clauses = [str(item).strip() for item in profile.get("must_include_logic", []) if str(item).strip()]
    if not clauses:
        keywords = [str(item).strip() for item in profile.get("core_keywords", []) if str(item).strip()]
        clauses = [" OR ".join(keywords)] if keywords else [str(profile["research_direction"])]
    excludes = [str(item).strip() for item in profile.get("exclude_keywords", []) if str(item).strip()]
    if excludes:
        exclude_clause = " OR ".join(excludes)
        clauses = [f"({clause}) NOT ({exclude_clause})" for clause in clauses]
    return clauses


def canonical_databases(profile: dict[str, Any]) -> set[str]:
    requested: set[str] = set()
    for raw_name in profile.get("preferred_databases", []):
        name = str(raw_name).strip().lower().replace(" ", "_").replace("-", "_")
        matched = False
        for canonical, aliases in DATABASE_ALIASES.items():
            normalized_aliases = {alias.replace(" ", "_").replace("-", "_") for alias in aliases}
            if name in normalized_aliases:
                requested.add(canonical)
                matched = True
                break
        if not matched and name:
            requested.add(name)
    return requested


def first_present(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def pubmed_search(query: str, lookback_days: int, retmax: int) -> list[str]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "xml",
        "retmax": str(retmax),
        "sort": "pub date",
        "datetype": "pdat",
        "reldate": str(lookback_days),
        "tool": os.environ.get("NCBI_TOOL", "literature_morning_report"),
        "email": os.environ.get("NCBI_EMAIL", "developer@example.com"),
    }
    if os.environ.get("NCBI_API_KEY"):
        params["api_key"] = os.environ["NCBI_API_KEY"]
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(params)
    root = ET.fromstring(http_get(url))
    return [node.text for node in root.findall(".//Id") if node.text]


def pubmed_fetch(pmids: list[str]) -> list[Paper]:
    if not pmids:
        return []
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urllib.parse.urlencode(params)
    root = ET.fromstring(http_get(url, timeout=60))
    papers: list[Paper] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext("./MedlineCitation/PMID") or ""
        title_el = article.find("./MedlineCitation/Article/ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        journal = article.findtext("./MedlineCitation/Article/Journal/Title") or ""
        year = (
            article.findtext("./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year")
            or article.findtext("./MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate")
            or ""
        )
        ids = {
            item.attrib.get("IdType"): (item.text or "")
            for item in article.findall("./PubmedData/ArticleIdList/ArticleId")
        }
        authors = []
        for author in article.findall("./MedlineCitation/Article/AuthorList/Author"):
            last = author.findtext("LastName") or ""
            fore = author.findtext("ForeName") or ""
            collective = author.findtext("CollectiveName") or ""
            name = collective or " ".join(part for part in [fore, last] if part)
            if name:
                authors.append(name)
        abstract_parts = []
        for abstract in article.findall("./MedlineCitation/Article/Abstract/AbstractText"):
            label = abstract.attrib.get("Label")
            text = "".join(abstract.itertext()).strip()
            if text:
                abstract_parts.append((label + ": " if label else "") + text)
        doi = ids.get("doi", "")
        urls = [f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"] if pmid else []
        if doi:
            urls.append(f"https://doi.org/{doi}")
        if title:
            papers.append(
                Paper(
                    source="pubmed",
                    pmid=pmid,
                    doi=doi,
                    title_en=title,
                    journal=journal,
                    year=year[:4],
                    authors=authors,
                    abstract=" ".join(abstract_parts),
                    source_urls=urls,
                )
            )
    return papers


def openalex_search(query: str, lookback_days: int, per_page: int) -> list[Paper]:
    start_date = (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()
    params = {
        "search": query,
        "filter": f"from_publication_date:{start_date}",
        "per-page": str(per_page),
    }
    if os.environ.get("OPENALEX_EMAIL"):
        params["mailto"] = os.environ["OPENALEX_EMAIL"]
    if os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = http_json(url, timeout=30)
    papers: list[Paper] = []
    for item in data.get("results", []):
        title = item.get("title") or ""
        doi = (item.get("doi") or "").replace("https://doi.org/", "")
        journal = ((item.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        authors = [
            ((auth.get("author") or {}).get("display_name") or "")
            for auth in item.get("authorships", [])
            if (auth.get("author") or {}).get("display_name")
        ]
        abstract = abstract_from_inverted_index(item.get("abstract_inverted_index") or {})
        urls = [item.get("id")] if item.get("id") else []
        if doi:
            urls.append(f"https://doi.org/{doi}")
        if title:
            papers.append(
                Paper(
                    source="openalex",
                    doi=doi,
                    title_en=title,
                    journal=journal,
                    year=str(item.get("publication_year") or ""),
                    authors=authors,
                    abstract=abstract,
                    source_urls=urls,
                )
            )
    return papers


def abstract_from_inverted_index(index: dict[str, list[int]]) -> str:
    if not index:
        return ""
    positions: dict[int, str] = {}
    for word, slots in index.items():
        for slot in slots:
            positions[int(slot)] = word
    return " ".join(positions[idx] for idx in sorted(positions))


def crossref_search(query: str, lookback_days: int, rows: int) -> list[Paper]:
    start_date = (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()
    params = {
        "query.bibliographic": query,
        "filter": f"from-pub-date:{start_date}",
        "rows": str(rows),
    }
    if os.environ.get("CROSSREF_EMAIL"):
        params["mailto"] = os.environ["CROSSREF_EMAIL"]
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    data = http_json(url, timeout=30)
    papers: list[Paper] = []
    for item in data.get("message", {}).get("items", []):
        title = " ".join(item.get("title") or []).strip()
        journal = " ".join(item.get("container-title") or []).strip()
        year = ""
        date_parts = item.get("published-print") or item.get("published-online") or item.get("created") or {}
        if date_parts.get("date-parts"):
            year = str(date_parts["date-parts"][0][0])
        authors = []
        for author in item.get("author", []):
            name = " ".join(part for part in [author.get("given", ""), author.get("family", "")] if part)
            if name:
                authors.append(name)
        doi = item.get("DOI") or ""
        abstract = re.sub("<[^>]+>", "", item.get("abstract") or "")
        urls = [item.get("URL")] if item.get("URL") else []
        if title:
            papers.append(
                Paper(
                    source="crossref",
                    doi=doi,
                    title_en=title,
                    journal=journal,
                    year=year,
                    authors=authors,
                    abstract=abstract,
                    source_urls=urls,
                )
            )
    return papers


def europepmc_search(query: str, lookback_days: int, page_size: int) -> list[Paper]:
    start_date = (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()
    full_query = f"({query}) AND FIRST_PDATE:[{start_date} TO {dt.date.today().isoformat()}]"
    params = {"query": full_query, "format": "json", "pageSize": str(page_size), "sort": "FIRST_PDATE_D desc"}
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params)
    data = http_json(url, timeout=30)
    papers: list[Paper] = []
    for item in data.get("resultList", {}).get("result", []):
        title = item.get("title") or ""
        doi = item.get("doi") or ""
        pmid = item.get("pmid") or ""
        journal = item.get("journalTitle") or ""
        year = str(item.get("pubYear") or "")
        authors = [name.strip() for name in (item.get("authorString") or "").split(",") if name.strip()]
        urls = []
        if pmid:
            urls.append(f"https://europepmc.org/article/MED/{pmid}")
        elif item.get("id"):
            urls.append(f"https://europepmc.org/article/{item.get('source')}/{item.get('id')}")
        if doi:
            urls.append(f"https://doi.org/{doi}")
        if title:
            papers.append(
                Paper(
                    source="europepmc",
                    pmid=pmid,
                    doi=doi,
                    title_en=title,
                    journal=journal,
                    year=year,
                    authors=authors,
                    abstract=item.get("abstractText") or "",
                    source_urls=urls,
                )
            )
    return papers


def semantic_scholar_search(query: str, lookback_days: int, limit: int) -> list[Paper]:
    fields = "title,authors,year,abstract,venue,externalIds,url,publicationDate"
    params = {"query": query, "limit": str(min(limit, 100)), "fields": fields}
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": "literature-morning-report/0.1"}
    if os.environ.get("SEMANTIC_SCHOLAR_API_KEY"):
        headers["x-api-key"] = os.environ["SEMANTIC_SCHOLAR_API_KEY"]
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    cutoff = dt.date.today() - dt.timedelta(days=lookback_days)
    papers: list[Paper] = []
    for item in data.get("data", []):
        year = str(item.get("year") or "")
        publication_date = item.get("publicationDate") or ""
        if publication_date:
            try:
                if dt.date.fromisoformat(publication_date[:10]) < cutoff:
                    continue
            except ValueError:
                pass
        title = item.get("title") or ""
        external = item.get("externalIds") or {}
        doi = external.get("DOI") or ""
        pmid = str(external.get("PubMed") or "")
        authors = [(author.get("name") or "") for author in item.get("authors", []) if author.get("name")]
        urls = [item.get("url")] if item.get("url") else []
        if doi:
            urls.append(f"https://doi.org/{doi}")
        if title:
            papers.append(
                Paper(
                    source="semantic_scholar",
                    pmid=pmid,
                    doi=doi,
                    title_en=title,
                    journal=item.get("venue") or "",
                    year=year,
                    authors=authors,
                    abstract=item.get("abstract") or "",
                    source_urls=urls,
                )
            )
    return papers


def arxiv_search(query: str, lookback_days: int, max_results: int) -> list[Paper]:
    params = {
        "search_query": f'all:"{query}"',
        "start": "0",
        "max_results": str(min(max_results, 100)),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    root = ET.fromstring(http_get(url, timeout=30))
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ns):
        published = entry.findtext("atom:published", default="", namespaces=ns)
        if published:
            try:
                published_dt = dt.datetime.fromisoformat(published.replace("Z", "+00:00"))
                if published_dt < cutoff:
                    continue
            except ValueError:
                pass
        title = re.sub(r"\s+", " ", entry.findtext("atom:title", default="", namespaces=ns)).strip()
        summary = re.sub(r"\s+", " ", entry.findtext("atom:summary", default="", namespaces=ns)).strip()
        authors = [author.findtext("atom:name", default="", namespaces=ns) for author in entry.findall("atom:author", ns)]
        entry_id = entry.findtext("atom:id", default="", namespaces=ns)
        doi = entry.findtext("arxiv:doi", default="", namespaces=ns)
        year = published[:4] if published else ""
        if title:
            papers.append(
                Paper(
                    source="arxiv",
                    doi=doi,
                    title_en=title,
                    journal="arXiv",
                    year=year,
                    authors=[author for author in authors if author],
                    abstract=summary,
                    source_urls=[entry_id] if entry_id else [],
                )
            )
    return papers


def web_of_science_search(query: str, lookback_days: int, limit: int) -> list[Paper]:
    api_key = first_present("CLARIVATE_API_KEY", "WOS_API_KEY")
    if not api_key:
        raise RuntimeError(RESTRICTED_DATABASES["web_of_science"])
    current_year = dt.date.today().year
    start_year = (dt.date.today() - dt.timedelta(days=lookback_days)).year
    wos_query = query if re.search(r"\b[A-Z]{2}=", query) else f"TS=({query}) AND PY=({start_year}-{current_year})"
    params = {"q": wos_query, "db": os.environ.get("WOS_DATABASE", "WOS"), "limit": str(min(limit, 50)), "page": "1"}
    url = "https://api.clarivate.com/apis/wos-starter/v1/documents?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"X-ApiKey": api_key, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    rows = data.get("hits") or data.get("documents") or data.get("records") or []
    papers: list[Paper] = []
    for item in rows:
        title = first_string(item, "title", "Title") or first_nested_string(item, ["names", "title"])
        doi = first_string(item, "doi", "DOI")
        pmid = first_string(item, "pmid", "pubmedId", "PubMedID")
        journal = first_string(item, "source", "sourceTitle", "journal", "Source")
        year = str(first_string(item, "year", "publishedYear", "publicationYear") or "")
        authors = to_string_list(item.get("authors") or item.get("Authors") or [])
        url_value = first_string(item, "wosUrl", "url", "links")
        if title:
            papers.append(
                Paper(
                    source="web_of_science",
                    pmid=pmid,
                    doi=doi,
                    title_en=title,
                    journal=journal,
                    year=year,
                    authors=authors,
                    abstract=first_string(item, "abstract", "Abstract") or "",
                    source_urls=[url_value] if url_value else [],
                )
            )
    return papers


def scopus_search(query: str, lookback_days: int, count: int) -> list[Paper]:
    api_key = first_present("ELSEVIER_API_KEY", "SCOPUS_API_KEY")
    if not api_key:
        raise RuntimeError(RESTRICTED_DATABASES["scopus"])
    start_year = (dt.date.today() - dt.timedelta(days=lookback_days)).year
    params = {
        "query": f"TITLE-ABS-KEY({query}) AND PUBYEAR > {start_year - 1}",
        "count": str(min(count, 25)),
        "sort": "-coverDate",
    }
    url = "https://api.elsevier.com/content/search/scopus?" + urllib.parse.urlencode(params)
    headers = {"X-ELS-APIKey": api_key, "Accept": "application/json"}
    if os.environ.get("SCOPUS_INST_TOKEN"):
        headers["X-ELS-Insttoken"] = os.environ["SCOPUS_INST_TOKEN"]
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    papers: list[Paper] = []
    for item in data.get("search-results", {}).get("entry", []):
        title = item.get("dc:title") or ""
        doi = item.get("prism:doi") or ""
        journal = item.get("prism:publicationName") or ""
        cover_date = item.get("prism:coverDate") or ""
        links = [link.get("@href") for link in item.get("link", []) if link.get("@href")]
        if title:
            papers.append(
                Paper(
                    source="scopus",
                    doi=doi,
                    title_en=title,
                    journal=journal,
                    year=cover_date[:4],
                    authors=[item.get("dc:creator")] if item.get("dc:creator") else [],
                    abstract=item.get("dc:description") or "",
                    source_urls=links,
                )
            )
    return papers


def ieee_xplore_search(query: str, lookback_days: int, max_records: int) -> list[Paper]:
    api_key = first_present("IEEE_API_KEY", "IEEE_XPLORE_API_KEY")
    if not api_key:
        raise RuntimeError(RESTRICTED_DATABASES["ieee_xplore"])
    params = {
        "apikey": api_key,
        "format": "json",
        "querytext": query,
        "max_records": str(min(max_records, 25)),
        "start_record": "1",
        "sort_order": "desc",
        "sort_field": "publication_year",
    }
    url = "https://ieeexploreapi.ieee.org/api/v1/search/articles?" + urllib.parse.urlencode(params)
    data = http_json(url, timeout=30)
    cutoff_year = (dt.date.today() - dt.timedelta(days=lookback_days)).year
    papers: list[Paper] = []
    for item in data.get("articles", []):
        year = str(item.get("publication_year") or "")
        if year.isdigit() and int(year) < cutoff_year:
            continue
        title = item.get("title") or ""
        doi = item.get("doi") or ""
        authors = []
        for author in (item.get("authors") or {}).get("authors", []):
            name = author.get("full_name") or author.get("authorUrl") or ""
            if name:
                authors.append(name)
        if title:
            papers.append(
                Paper(
                    source="ieee_xplore",
                    doi=doi,
                    title_en=re.sub("<[^>]+>", "", title),
                    journal=item.get("publication_title") or "",
                    year=year,
                    authors=authors,
                    abstract=re.sub("<[^>]+>", "", item.get("abstract") or ""),
                    source_urls=[item.get("html_url")] if item.get("html_url") else [],
                )
            )
    return papers


def first_string(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                nested = first_string(first, "value", "text", "title", "name")
                if nested:
                    return nested
        if isinstance(value, dict):
            nested = first_string(value, "value", "text", "title", "name", "url")
            if nested:
                return nested
    return ""


def first_nested_string(item: dict[str, Any], path: list[str]) -> str:
    value: Any = item
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    if isinstance(value, str):
        return value
    return ""


def to_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                name = first_string(item, "name", "displayName", "fullName", "value")
                if name:
                    result.append(name)
        return result
    if isinstance(value, str):
        return [value]
    return []


def today_for_profile(profile: dict[str, Any]) -> dt.date:
    timezone_name = str(profile.get("timezone") or "UTC")
    try:
        return dt.datetime.now(ZoneInfo(timezone_name)).date()
    except Exception:
        return dt.date.today()


def sample_papers() -> list[Paper]:
    return [
        Paper(
            source="sample",
            pmid="00000001",
            doi="10.0000/sample.1",
            title_en="Gut microbiome signatures predict response to immune checkpoint inhibitors in solid tumors.",
            journal="Sample Journal",
            year=str(dt.date.today().year),
            authors=["Sample Author"],
            abstract=(
                "This sample paper evaluates gut microbiome features associated with response to immune "
                "checkpoint inhibitors in a solid tumor cohort and reports links between microbial diversity, "
                "immune infiltration, and treatment resistance."
            ),
            source_urls=["https://example.com/sample"],
        )
    ]


def collect_papers(profile: dict[str, Any], args: argparse.Namespace) -> tuple[list[Paper], int, list[str]]:
    if args.offline_sample:
        return sample_papers(), 1, ["sample: 1 candidate"]
    queries = build_queries(profile)
    databases = canonical_databases(profile)
    all_papers: list[Paper] = []
    raw_candidate_count = 0
    database_status: list[str] = []
    retmax = max(args.max_papers * 8, 20)
    for query in queries:
        if "pubmed" in databases:
            try:
                ids = pubmed_search(query, args.lookback_days, retmax)
                raw_candidate_count += len(ids)
                all_papers.extend(pubmed_fetch(ids[:retmax]))
                database_status.append(f"pubmed: {len(ids)} ids")
                time.sleep(0.34)
            except Exception as exc:
                message = f"pubmed skipped/failed: {exc}"
                database_status.append(message)
                print(message, file=sys.stderr)
        if "europepmc" in databases:
            try:
                papers = europepmc_search(query, args.lookback_days, min(retmax, 50))
                raw_candidate_count += len(papers)
                all_papers.extend(papers)
                database_status.append(f"europepmc: {len(papers)} records")
            except Exception as exc:
                message = f"europepmc skipped/failed: {exc}"
                database_status.append(message)
                print(message, file=sys.stderr)
        if "semantic_scholar" in databases:
            try:
                papers = semantic_scholar_search(query, args.lookback_days, min(retmax, 100))
                raw_candidate_count += len(papers)
                all_papers.extend(papers)
                database_status.append(f"semantic_scholar: {len(papers)} records")
            except Exception as exc:
                message = f"semantic_scholar skipped/failed: {exc}"
                database_status.append(message)
                print(message, file=sys.stderr)
        if "openalex" in databases:
            try:
                papers = openalex_search(query, args.lookback_days, min(retmax, 50))
                raw_candidate_count += len(papers)
                all_papers.extend(papers)
                database_status.append(f"openalex: {len(papers)} records")
            except Exception as exc:
                message = f"openalex skipped/failed: {exc}"
                database_status.append(message)
                print(message, file=sys.stderr)
        if "crossref" in databases:
            try:
                papers = crossref_search(query, args.lookback_days, min(retmax, 50))
                raw_candidate_count += len(papers)
                all_papers.extend(papers)
                database_status.append(f"crossref: {len(papers)} records")
            except Exception as exc:
                message = f"crossref skipped/failed: {exc}"
                database_status.append(message)
                print(message, file=sys.stderr)
        if "arxiv" in databases:
            try:
                papers = arxiv_search(query, args.lookback_days, min(retmax, 50))
                raw_candidate_count += len(papers)
                all_papers.extend(papers)
                database_status.append(f"arxiv: {len(papers)} records")
            except Exception as exc:
                message = f"arxiv skipped/failed: {exc}"
                database_status.append(message)
                print(message, file=sys.stderr)
        if "web_of_science" in databases:
            try:
                papers = web_of_science_search(query, args.lookback_days, min(retmax, 50))
                raw_candidate_count += len(papers)
                all_papers.extend(papers)
                database_status.append(f"web_of_science: {len(papers)} records")
            except Exception as exc:
                message = f"web_of_science skipped/failed: {exc}"
                database_status.append(message)
                print(message, file=sys.stderr)
        if "scopus" in databases:
            try:
                papers = scopus_search(query, args.lookback_days, min(retmax, 25))
                raw_candidate_count += len(papers)
                all_papers.extend(papers)
                database_status.append(f"scopus: {len(papers)} records")
            except Exception as exc:
                message = f"scopus skipped/failed: {exc}"
                database_status.append(message)
                print(message, file=sys.stderr)
        if "embase" in databases:
            message = f"embase skipped: {RESTRICTED_DATABASES['embase']}"
            database_status.append(message)
            print(message, file=sys.stderr)
        if "ieee_xplore" in databases:
            try:
                papers = ieee_xplore_search(query, args.lookback_days, min(retmax, 25))
                raw_candidate_count += len(papers)
                all_papers.extend(papers)
                database_status.append(f"ieee_xplore: {len(papers)} records")
            except Exception as exc:
                message = f"ieee_xplore skipped/failed: {exc}"
                database_status.append(message)
                print(message, file=sys.stderr)
    return all_papers, raw_candidate_count, database_status


def dedupe_and_filter(
    papers: list[Paper],
    profile: dict[str, Any],
    history_path: Path,
    journal_metrics: dict[str, dict[str, str]],
) -> list[Paper]:
    old_pmids, old_dois, old_titles = load_history(history_path)
    seen: set[str] = set()
    selected: list[Paper] = []
    excludes = [str(item).lower() for item in profile.get("exclude_keywords", []) if str(item).strip()]
    for paper in papers:
        title_norm = normalize_title(paper.title_en)
        if not title_norm:
            continue
        if paper.pmid.lower() in old_pmids or paper.doi.lower() in old_dois or title_norm in old_titles:
            continue
        if paper.key in seen or title_norm in seen:
            continue
        haystack = f"{paper.title_en} {paper.abstract}".lower()
        if any(term.lower() in haystack for term in excludes):
            continue
        seen.add(paper.key)
        seen.add(title_norm)
        apply_quality_evidence(paper, profile, journal_metrics)
        paper.score = score_paper(paper, profile)
        selected.append(paper)
    selected.sort(key=lambda item: (item.category != "main", -item.score, item.year), reverse=False)
    return selected


def apply_quality_evidence(
    paper: Paper,
    profile: dict[str, Any],
    journal_metrics: dict[str, dict[str, str]],
) -> None:
    metrics = journal_metrics.get(normalize_title(paper.journal))
    threshold = profile.get("journal_threshold") or {}
    min_if = float(threshold.get("min_impact_factor", 0) or 0)
    allowed_quartiles = {str(q).upper() for q in threshold.get("allowed_quartiles", [])}
    if not metrics:
        paper.quality_evidence = "Journal metric unverified locally; keep as source-verified candidate only."
        if threshold.get("allow_unverified_as_adjacent", True):
            paper.category = "adjacent"
        return
    impact_factor = float(metrics.get("impact_factor") or 0)
    quartile = str(metrics.get("quartile") or "").upper()
    cas_zone = str(metrics.get("cas_zone") or "")
    evidence_url = metrics.get("evidence_url") or ""
    paper.quality_evidence = (
        f"IF {impact_factor:g}; quartile {quartile or 'unverified'}; CAS zone {cas_zone or 'unverified'}"
        + (f"; evidence: {evidence_url}" if evidence_url else "")
    )
    if impact_factor < min_if or (allowed_quartiles and quartile not in allowed_quartiles):
        paper.category = "adjacent"


def score_paper(paper: Paper, profile: dict[str, Any]) -> int:
    keywords = [str(item).lower() for item in profile.get("core_keywords", []) if str(item).strip()]
    haystack = f"{paper.title_en} {paper.abstract}".lower()
    score = 0
    score += 8 if paper.pmid else 0
    score += 8 if paper.doi else 0
    score += 2 * sum(1 for keyword in keywords if keyword.lower() in haystack)
    score += 6 if paper.abstract else 0
    score += 4 if str(dt.date.today().year) in paper.year else 0
    score += 4 if paper.category == "main" else 0
    return score


def summarize_english(text: str, max_chars: int = 720) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return "No abstract available from the source metadata. Use the source link for manual review."
    if len(clean) <= max_chars:
        return clean
    cut = clean[:max_chars].rsplit(" ", 1)[0]
    return cut + "..."


def chinese_summary_stub(paper: Paper, profile: dict[str, Any]) -> str:
    matched = [
        keyword
        for keyword in profile.get("core_keywords", [])
        if str(keyword).lower() in f"{paper.title_en} {paper.abstract}".lower()
    ][:6]
    if matched:
        focus = "、".join(str(item) for item in matched)
    else:
        focus = profile.get("research_direction", "该研究方向")
    return (
        f"该文献与 {focus} 相关。系统已根据题名、摘要和来源链接生成英文摘要概述；"
        "中文精译建议由 AI 助手或人工在发送前复核，以避免误译专业术语。"
    )


def paper_to_csl(paper: Paper) -> dict[str, Any]:
    return {
        "type": "article-journal",
        "id": paper.doi or paper.pmid or normalize_title(paper.title_en).replace(" ", "-"),
        "title": paper.title_en,
        "container-title": paper.journal,
        "issued": {"date-parts": [[int(paper.year)]]} if paper.year.isdigit() else {},
        "DOI": paper.doi,
        "PMID": paper.pmid,
        "URL": paper.source_urls[0] if paper.source_urls else "",
        "author": [{"literal": author} for author in paper.authors],
        "abstract": summarize_english(paper.abstract, 1200),
    }


def citation_key(paper: Paper) -> str:
    first_author = paper.authors[0].split()[-1] if paper.authors else "paper"
    year = paper.year or "nd"
    token = re.sub(r"[^A-Za-z0-9]+", "", first_author) or "paper"
    return f"{token}{year}"


def export_ris(papers: list[Paper]) -> str:
    blocks = []
    for paper in papers:
        lines = ["TY  - JOUR", f"TI  - {paper.title_en}"]
        lines.extend(f"AU  - {author}" for author in paper.authors)
        if paper.journal:
            lines.append(f"JO  - {paper.journal}")
        if paper.year:
            lines.append(f"PY  - {paper.year}")
        if paper.doi:
            lines.append(f"DO  - {paper.doi}")
        if paper.pmid:
            lines.append(f"M1  - PMID:{paper.pmid}")
        if paper.source_urls:
            lines.append(f"UR  - {paper.source_urls[0]}")
        if paper.abstract:
            lines.append(f"N2  - {summarize_english(paper.abstract, 1200)}")
        lines.append("ER  -")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def export_bibtex(papers: list[Paper]) -> str:
    entries = []
    for paper in papers:
        fields = {
            "title": paper.title_en,
            "author": " and ".join(paper.authors),
            "journal": paper.journal,
            "year": paper.year,
            "doi": paper.doi,
            "url": paper.source_urls[0] if paper.source_urls else "",
            "abstract": summarize_english(paper.abstract, 1200),
        }
        body = ",\n".join(
            f"  {key} = {{{value}}}" for key, value in fields.items() if value
        )
        entries.append(f"@article{{{citation_key(paper)},\n{body}\n}}")
    return "\n\n".join(entries) + "\n"


def export_enw(papers: list[Paper]) -> str:
    blocks = []
    for paper in papers:
        lines = ["%0 Journal Article", f"%T {paper.title_en}"]
        lines.extend(f"%A {author}" for author in paper.authors)
        if paper.journal:
            lines.append(f"%J {paper.journal}")
        if paper.year:
            lines.append(f"%D {paper.year}")
        if paper.doi:
            lines.append(f"%R {paper.doi}")
        if paper.source_urls:
            lines.append(f"%U {paper.source_urls[0]}")
        if paper.abstract:
            lines.append(f"%X {summarize_english(paper.abstract, 1200)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def render_reports(
    profile: dict[str, Any],
    papers: list[Paper],
    raw_candidate_count: int,
    database_status: list[str],
    output_dir: Path,
    date_value: dt.date,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_date = date_value.isoformat()
    title = f"{profile.get('discipline')} 文献晨报"
    if not papers:
        text = (
            f"{title}\n"
            f"Date: {report_date}\n"
            f"Research direction: {profile.get('research_direction')}\n"
            f"Database status: {'; '.join(database_status)}\n"
            f"今日未检索到符合标准且未推送过的新文献。\n"
            f"Raw candidate count: {raw_candidate_count}\n"
        )
        html_text = (
            "<!doctype html><html><head><meta charset=\"utf-8\"></head><body>"
            f"<h1>{html.escape(title)}</h1><p>Date: {report_date}</p>"
            f"<p>Database status: {html.escape('; '.join(database_status))}</p>"
            "<p>今日未检索到符合标准且未推送过的新文献。</p>"
            f"<p>Raw candidate count: {raw_candidate_count}</p></body></html>"
        )
    else:
        text_parts = [
            title,
            f"Date: {report_date}",
            f"Research direction: {profile.get('research_direction')}",
            f"Database status: {'; '.join(database_status)}",
            f"Raw candidate count: {raw_candidate_count}; selected: {len(papers)}",
            "",
            "一、文献列表",
        ]
        html_parts = [
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
            f"<title>{html.escape(title)} {report_date}</title>",
            "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;line-height:1.6;max-width:920px;margin:24px auto;color:#1f2933}.paper{border-top:1px solid #ddd;padding:18px 0}.label{font-weight:700}</style>",
            "</head><body>",
            f"<h1>{html.escape(title)}</h1>",
            f"<p>Date: {report_date}</p>",
            f"<p><b>Research direction:</b> {html.escape(str(profile.get('research_direction')))}</p>",
            f"<p><b>Database status:</b> {html.escape('; '.join(database_status))}</p>",
            f"<p><b>Raw candidate count:</b> {raw_candidate_count}; <b>selected:</b> {len(papers)}</p>",
        ]
        for idx, paper in enumerate(papers, 1):
            en_summary = summarize_english(paper.abstract)
            zh_summary = chinese_summary_stub(paper, profile)
            relevance = relevance_sentence(paper, profile)
            mechanisms = mechanisms_sentence(paper, profile)
            hypothesis = hypothesis_sentence(paper, profile)
            urls = "; ".join(paper.source_urls)
            text_parts.extend(
                [
                    "",
                    f"{idx}. {paper.title_en}",
                    f"中文题名：待 AI/人工翻译 - {paper.title_en}",
                    f"期刊：{paper.journal}",
                    f"年份：{paper.year}",
                    f"PMID：{paper.pmid or 'N/A'}",
                    f"DOI：{paper.doi or 'N/A'}",
                    f"来源：{urls}",
                    f"分区/影响因子依据：{paper.quality_evidence}",
                    "Abstract content:",
                    en_summary,
                    "中文摘要内容：",
                    zh_summary,
                    f"与课题相关性：{relevance}",
                    f"关键机制：{mechanisms}",
                    f"可转化课题假设：{hypothesis}",
                ]
            )
            html_parts.extend(
                [
                    "<section class=\"paper\">",
                    f"<h2>{idx}. {html.escape(paper.title_en)}</h2>",
                    f"<p><span class=\"label\">中文题名：</span>待 AI/人工翻译 - {html.escape(paper.title_en)}</p>",
                    f"<p><span class=\"label\">期刊/年份：</span>{html.escape(paper.journal)} / {html.escape(paper.year)}</p>",
                    f"<p><span class=\"label\">PMID：</span>{html.escape(paper.pmid or 'N/A')}<br><span class=\"label\">DOI：</span>{html.escape(paper.doi or 'N/A')}</p>",
                    f"<p><span class=\"label\">来源：</span>{html.escape(urls)}</p>",
                    f"<p><span class=\"label\">分区/影响因子依据：</span>{html.escape(paper.quality_evidence)}</p>",
                    f"<p><span class=\"label\">Abstract content:</span><br>{html.escape(en_summary)}</p>",
                    f"<p><span class=\"label\">中文摘要内容：</span><br>{html.escape(zh_summary)}</p>",
                    f"<p><span class=\"label\">与课题相关性：</span>{html.escape(relevance)}</p>",
                    f"<p><span class=\"label\">关键机制：</span>{html.escape(mechanisms)}</p>",
                    f"<p><span class=\"label\">可转化课题假设：</span>{html.escape(hypothesis)}</p>",
                    "</section>",
                ]
            )
        ideas = ideas_section(profile, papers)
        text_parts.extend(["", "二、实验/选题灵感", ideas])
        html_parts.extend([f"<h2>实验/选题灵感</h2><p>{html.escape(ideas)}</p>", "</body></html>"])
        text = "\n".join(text_parts) + "\n"
        html_text = "\n".join(html_parts)
    text_path = output_dir / f"morning_report_{report_date}.txt"
    html_path = output_dir / f"morning_report_{report_date}.html"
    text_path.write_text(text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    return text_path, html_path


def relevance_sentence(paper: Paper, profile: dict[str, Any]) -> str:
    matches = [
        keyword
        for keyword in profile.get("core_keywords", [])
        if str(keyword).lower() in f"{paper.title_en} {paper.abstract}".lower()
    ][:5]
    if matches:
        return "Matches profile terms: " + ", ".join(str(item) for item in matches) + "."
    return "Selected by database query and source metadata; review source link for final fit."


def mechanisms_sentence(paper: Paper, profile: dict[str, Any]) -> str:
    mechanism_terms = [
        "inflammation",
        "oxidative stress",
        "Nrf2",
        "AMPK",
        "SIRT1",
        "PI3K",
        "immune response",
        "tumor microenvironment",
        "biomarker",
        "microbiome",
        "single-cell",
        "transcriptomics",
        "metabolism",
        "drug resistance",
        "ferroptosis",
        "mitophagy",
        "autophagy",
        "mitochondrial",
        "organoid",
    ]
    haystack = f"{paper.title_en} {paper.abstract}".lower()
    matches = [term for term in mechanism_terms if term.lower() in haystack]
    return ", ".join(matches[:8]) if matches else "Mechanism not explicit in available metadata."


def hypothesis_sentence(paper: Paper, profile: dict[str, Any]) -> str:
    direction = str(profile.get("research_direction", "the user's research direction"))
    return (
        f"Use this paper to refine a testable hypothesis for {direction}, focusing on the matched "
        "mechanism terms, source model, and measurable outcomes reported in the abstract."
    )


def ideas_section(profile: dict[str, Any], papers: list[Paper]) -> str:
    direction = str(profile.get("research_direction", "the user's research direction"))
    mechanisms = sorted({mechanisms_sentence(p, profile) for p in papers if p.abstract})[:3]
    return (
        f"1. Convert the strongest mechanism into one measurable experiment for {direction}. "
        f"2. Build a small comparison table across the selected papers using model, intervention, endpoint, and pathway. "
        f"3. Prioritize mechanisms for follow-up: {'; '.join(mechanisms) if mechanisms else 'review source abstracts'}."
    )


def export_files(papers: list[Paper], formats: list[str], output_dir: Path, date_value: dt.date) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    prefix = output_dir / f"citations_{date_value.isoformat()}"
    for fmt in {str(item).lower() for item in formats}:
        if fmt == "ris":
            path = prefix.with_suffix(".ris")
            path.write_text(export_ris(papers), encoding="utf-8")
        elif fmt == "bibtex":
            path = prefix.with_suffix(".bib")
            path.write_text(export_bibtex(papers), encoding="utf-8")
        elif fmt == "enw":
            path = prefix.with_suffix(".enw")
            path.write_text(export_enw(papers), encoding="utf-8")
        elif fmt == "csl-json":
            path = prefix.with_suffix(".csl.json")
            path.write_text(json.dumps([paper_to_csl(p) for p in papers], ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            continue
        written.append(path)
    return written


def send_email(profile: dict[str, Any], subject: str, text_path: Path, html_path: Path) -> bool:
    recipient = str(profile.get("delivery_email") or "").strip()
    if not recipient:
        raise RuntimeError("delivery_email is empty")
    if os.environ.get("RESEND_API_KEY") and os.environ.get("RESEND_FROM"):
        payload = {
            "from": os.environ["RESEND_FROM"],
            "to": [recipient],
            "subject": subject,
            "html": html_path.read_text(encoding="utf-8"),
            "text": text_path.read_text(encoding="utf-8"),
        }
        request = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
        return True
    if os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS"):
        host = os.environ.get("SMTP_HOST", "smtp.qq.com")
        port = int(os.environ.get("SMTP_PORT", "465"))
        sender = os.environ.get("SMTP_FROM", os.environ["SMTP_USER"])
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(text_path.read_text(encoding="utf-8"), subtype="plain", charset="utf-8", cte="base64")
        message.add_alternative(html_path.read_text(encoding="utf-8"), subtype="html", charset="utf-8", cte="base64")
        context = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
                smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
                smtp.send_message(message)
        return True
    raise RuntimeError("No email provider configured. Set Resend or SMTP environment variables.")


def append_history(history_path: Path, papers: list[Paper], date_value: dt.date) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    exists = history_path.exists() and history_path.stat().st_size > 0
    with history_path.open("a", encoding="utf-8", newline="") as handle:
        if not exists:
            handle.write("date_sent\tpmid\tdoi\tcategory\tnote\n")
        for paper in papers:
            note = f"{paper.journal}; {paper.title_en}"
            handle.write(
                f"{date_value.isoformat()}\t{paper.pmid}\t{paper.doi}\t{paper.category}\t{note}\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a personalized literature morning report.")
    parser.add_argument("--profile", required=True, help="Path to research_profile.yml")
    parser.add_argument("--history", default="sent_history.tsv", help="TSV history file for deduplication")
    parser.add_argument("--journal-metrics", help="Optional TSV journal metric file")
    parser.add_argument("--output-dir", default="reports", help="Output directory")
    parser.add_argument("--max-papers", type=int, default=None, help="Maximum selected papers")
    parser.add_argument("--lookback-days", type=int, default=None, help="Search lookback window")
    parser.add_argument("--dry-run", action="store_true", help="Generate outputs without sending email or writing history")
    parser.add_argument("--offline-sample", action="store_true", help="Use a local sample paper instead of network APIs")
    parser.add_argument("--date", help="Report date in YYYY-MM-DD; defaults to the profile timezone date")
    args = parser.parse_args()

    profile = load_profile(Path(args.profile))
    args.max_papers = args.max_papers or int(profile.get("max_papers") or 5)
    args.lookback_days = args.lookback_days or int(profile.get("lookback_days") or 7)
    today = dt.date.fromisoformat(args.date) if args.date else today_for_profile(profile)
    history_path = Path(args.history)
    metrics_path = Path(args.journal_metrics) if args.journal_metrics else None
    journal_metrics = read_journal_metrics(metrics_path)

    papers, raw_count, database_status = collect_papers(profile, args)
    candidates = dedupe_and_filter(papers, profile, history_path, journal_metrics)
    selected = candidates[: args.max_papers]
    output_dir = Path(args.output_dir)
    text_path, html_path = render_reports(profile, selected, raw_count, database_status, output_dir, today)
    exports = export_files(selected, profile.get("export_formats", []), output_dir, today)

    subject_prefix = ((profile.get("email") or {}).get("subject_prefix") if isinstance(profile.get("email"), dict) else None) or "文献晨报"
    subject = f"{subject_prefix}-{today.isoformat()}"
    if args.dry_run:
        print(f"DRY RUN: generated {text_path} and {html_path}")
    else:
        send_email(profile, subject, text_path, html_path)
        append_history(history_path, selected, today)
        print(f"SENT: {subject} -> {profile.get('delivery_email')}")
    if exports:
        print("EXPORTS:", ", ".join(str(path) for path in exports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
