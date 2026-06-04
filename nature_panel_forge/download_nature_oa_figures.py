#!/usr/bin/env python3
"""Download metadata and figures for recent open-access Nature-family papers.

The script uses NCBI E-utilities and the PMC Open Access package service.
It writes paper metadata to Papers/ and five main article figures per paper
to Figures/<paper-id>/.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parents[1]
PAPERS_DIR = BASE_DIR / os.environ.get("PAPERS_DIR", "Papers")
FIGURES_DIR = BASE_DIR / os.environ.get("FIGURES_DIR", "Figures")
USER_AGENT = "SciFigureHub/1.0 (local research download)"
YEARS = {item.strip() for item in os.environ.get("PMC_YEARS", "2025,2026").split(",") if item.strip()}
TARGET_PAPERS = int(os.environ.get("TARGET_PAPERS", "10"))
FIGURES_PER_PAPER = int(os.environ.get("FIGURES_PER_PAPER", "5"))
ESEARCH_RETMAX = int(os.environ.get("PMC_ESEARCH_RETMAX", "50"))
ESEARCH_SORT = os.environ.get("PMC_SEARCH_SORT", "pub date")
INITIAL_RETSTART = int(os.environ.get("PMC_RETSTART", "0"))
ALLOW_PARTIAL_DOWNLOAD = os.environ.get("ALLOW_PARTIAL_DOWNLOAD", "1").strip().lower() in {"1", "true", "yes", "y"}
SEARCH_TERM = os.environ.get(
    "PMC_SEARCH_TERM",
    'Nature*[Journal] AND (2025[pdat] OR 2026[pdat]) AND open access[filter]',
)
EXCLUDE_DOIS_FILE = os.environ.get("EXCLUDE_DOIS_FILE", "")
EXCLUDE_PMCIDS_FILE = os.environ.get("EXCLUDE_PMCIDS_FILE", "")
DOWNLOAD_CURSOR_FILE = os.environ.get("DOWNLOAD_CURSOR_FILE", "")
PREFERRED_IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif"]
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


@dataclass
class Candidate:
    pmcid: str
    oa_package_url: str
    license: str
    citation: str


@dataclass
class FigureRecord:
    index: int
    label: str
    caption: str
    original_member: str
    output_file: str


def http_get(url: str, *, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def load_identifier_file(path_value: str) -> set[str]:
    if not path_value:
        return set()
    path = Path(path_value)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        return set()
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return {str(item).strip() for item in payload if str(item).strip()}
        if isinstance(payload, dict):
            values: set[str] = set()
            for key in ["dois", "pmcids", "processed_dois", "processed_pmcids"]:
                items = payload.get(key)
                if isinstance(items, list):
                    values.update(str(item).strip() for item in items if str(item).strip())
            return values
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}


EXCLUDE_DOIS = load_identifier_file(EXCLUDE_DOIS_FILE)
EXCLUDE_PMCIDS = load_identifier_file(EXCLUDE_PMCIDS_FILE)


def text_content(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join(" ".join(element.itertext()).split())


def first_text(root: ET.Element, path: str) -> str:
    return text_content(root.find(path))


def safe_slug(value: str, fallback: str, max_len: int = 72) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    if not slug:
        slug = fallback.lower()
    return slug[:max_len].strip("-") or fallback.lower()


def esearch_ids(retstart: int, retmax: int = ESEARCH_RETMAX) -> list[str]:
    params = {
        "db": "pmc",
        "term": SEARCH_TERM,
        "retstart": str(retstart),
        "retmax": str(retmax),
        "retmode": "json",
    }
    if ESEARCH_SORT:
        params["sort"] = ESEARCH_SORT
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(params)
    payload = json.loads(http_get(url).decode("utf-8"))
    return [f"PMC{pmc_id}" for pmc_id in payload["esearchresult"]["idlist"]]


def get_oa_candidate(pmcid: str) -> Candidate | None:
    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={urllib.parse.quote(pmcid)}"
    root = ET.fromstring(http_get(url).decode("utf-8"))
    record = root.find(".//record")
    if record is None or record.attrib.get("retracted", "no").lower() == "yes":
        return None

    tgz_link = None
    for link in record.findall("./link"):
        if link.attrib.get("format") == "tgz":
            tgz_link = link.attrib.get("href")
            break
    if not tgz_link:
        return None

    package_url = normalize_oa_package_url(tgz_link)
    return Candidate(
        pmcid=pmcid,
        oa_package_url=package_url,
        license=record.attrib.get("license", ""),
        citation=record.attrib.get("citation", ""),
    )


def normalize_oa_package_url(url: str) -> str:
    """Map PMC OA package FTP URLs to currently reachable HTTPS URLs."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    if path.startswith("/pub/pmc/oa_package/"):
        path = path.replace("/pub/pmc/oa_package/", "/pub/pmc/deprecated/oa_package/", 1)
    return urllib.parse.urlunparse(("https", "ftp.ncbi.nlm.nih.gov", path, "", "", ""))


def find_article_xml(tf: tarfile.TarFile) -> str | None:
    xml_members = [
        member.name
        for member in tf.getmembers()
        if member.isfile() and member.name.lower().endswith((".nxml", ".xml"))
    ]
    for name in xml_members:
        extracted = tf.extractfile(name)
        if extracted and b"<article" in extracted.read(1024):
            return name
    return xml_members[0] if xml_members else None


def publication_date(root: ET.Element) -> tuple[str, str]:
    dates = root.findall(".//article-meta/pub-date")
    preferred_types = ["epub", "ppub", "collection", "pmc-release"]
    for preferred in preferred_types:
        for pub_date in dates:
            if pub_date.attrib.get("pub-type") == preferred:
                parsed = date_from_element(pub_date)
                if parsed[0]:
                    return parsed
    for pub_date in dates:
        parsed = date_from_element(pub_date)
        if parsed[0]:
            return parsed
    return "", ""


def date_from_element(pub_date: ET.Element) -> tuple[str, str]:
    year = text_content(pub_date.find("year"))
    month = text_content(pub_date.find("month")).zfill(2)
    day = text_content(pub_date.find("day")).zfill(2)
    if not year:
        return "", ""
    if month and day:
        return year, f"{year}-{month}-{day}"
    if month:
        return year, f"{year}-{month}"
    return year, year


def member_index(tf: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    return {member.name: member for member in tf.getmembers() if member.isfile()}


def choose_image_member(members: dict[str, tarfile.TarInfo], href: str) -> str | None:
    href_base = Path(href).name
    by_stem: dict[str, list[str]] = {}
    for name in members:
        path = Path(name)
        ext = path.suffix.lower()
        if ext not in PREFERRED_IMAGE_EXTS:
            continue
        by_stem.setdefault(path.stem, []).append(name)

    matches = by_stem.get(href_base, [])
    if not matches:
        matches = [
            name
            for name in members
            if Path(name).suffix.lower() in PREFERRED_IMAGE_EXTS
            and Path(name).stem.startswith(href_base)
        ]
    if not matches:
        return None

    def score(name: str) -> tuple[int, str]:
        ext = Path(name).suffix.lower()
        try:
            rank = PREFERRED_IMAGE_EXTS.index(ext)
        except ValueError:
            rank = len(PREFERRED_IMAGE_EXTS)
        return rank, name

    return sorted(matches, key=score)[0]


def iter_figures(root: ET.Element) -> Iterable[ET.Element]:
    body = root.find(".//body")
    if body is not None:
        yield from body.findall(".//fig")
        return
    yield from root.findall(".//fig")


def extract_figures(
    tf: tarfile.TarFile,
    root: ET.Element,
    paper_dir: Path,
    *,
    count: int,
) -> list[FigureRecord]:
    members = member_index(tf)
    records: list[FigureRecord] = []
    used_members: set[str] = set()

    for fig in iter_figures(root):
        graphic = fig.find(".//graphic")
        if graphic is None:
            continue
        href = graphic.attrib.get(XLINK_HREF) or graphic.attrib.get("href")
        if not href:
            continue
        image_member = choose_image_member(members, href)
        if not image_member or image_member in used_members:
            continue

        source = tf.extractfile(image_member)
        if source is None:
            continue

        figure_index = len(records) + 1
        ext = Path(image_member).suffix.lower()
        output_name = f"fig{figure_index:02d}{ext}"
        output_path = paper_dir / output_name
        with output_path.open("wb") as handle:
            shutil.copyfileobj(source, handle)

        records.append(
            FigureRecord(
                index=figure_index,
                label=text_content(fig.find("label")),
                caption=text_content(fig.find("caption")),
                original_member=image_member,
                output_file=str(output_path.relative_to(BASE_DIR)),
            )
        )
        used_members.add(image_member)
        if len(records) >= count:
            break

    return records


def process_candidate(candidate: Candidate) -> dict | None:
    archive = http_get(candidate.oa_package_url, timeout=120)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        xml_name = find_article_xml(tf)
        if not xml_name:
            return None
        xml_file = tf.extractfile(xml_name)
        if xml_file is None:
            return None
        root = ET.fromstring(xml_file.read())

        journal = first_text(root, ".//journal-title")
        if not journal.lower().startswith("nature"):
            return None

        year, pub_date = publication_date(root)
        if year not in YEARS:
            return None

        doi = first_text(root, ".//article-id[@pub-id-type='doi']")
        title = first_text(root, ".//article-title")
        abstract = first_text(root, ".//article-meta/abstract")
        if not doi or not title or not abstract:
            return None
        if doi in EXCLUDE_DOIS:
            return None
        if not doi.startswith("10.1038/"):
            return None
        if journal.lower() == "nature and science of sleep":
            return None

        article_id = safe_slug(doi.replace("/", "-"), candidate.pmcid)
        paper_dir = FIGURES_DIR / article_id
        if paper_dir.exists():
            shutil.rmtree(paper_dir)
        paper_dir.mkdir(parents=True, exist_ok=True)

        figures = extract_figures(tf, root, paper_dir, count=FIGURES_PER_PAPER)
        if len(figures) < FIGURES_PER_PAPER:
            shutil.rmtree(paper_dir, ignore_errors=True)
            return None

        metadata = {
            "paper_id": article_id,
            "pmcid": candidate.pmcid,
            "doi": doi,
            "doi_url": f"https://doi.org/{doi}",
            "journal": journal,
            "publication_date": pub_date,
            "year": year,
            "title": title,
            "abstract": abstract,
            "license": candidate.license,
            "citation": candidate.citation,
            "pmc_url": f"https://pmc.ncbi.nlm.nih.gov/articles/{candidate.pmcid}/",
            "oa_package_url": candidate.oa_package_url,
            "figures": [record.__dict__ for record in figures],
        }

        paper_json = PAPERS_DIR / f"{article_id}.json"
        paper_md = PAPERS_DIR / f"{article_id}.md"
        paper_json.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paper_md.write_text(render_markdown(metadata), encoding="utf-8")
        (paper_dir / "captions.json").write_text(
            json.dumps(metadata["figures"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return metadata


def render_markdown(metadata: dict) -> str:
    return (
        f"# {metadata['title']}\n\n"
        f"- DOI: {metadata['doi']}\n"
        f"- Journal: {metadata['journal']}\n"
        f"- Publication date: {metadata['publication_date']}\n"
        f"- PMCID: {metadata['pmcid']}\n"
        f"- License: {metadata['license']}\n"
        f"- DOI URL: {metadata['doi_url']}\n"
        f"- PMC URL: {metadata['pmc_url']}\n\n"
        "## Abstract\n\n"
        f"{metadata['abstract']}\n"
    )


def write_indexes(records: list[dict], *, initial_retstart: int, final_retstart: int, seen_pmcids: set[str]) -> None:
    papers_csv = PAPERS_DIR / "papers.csv"
    with papers_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "paper_id",
                "pmcid",
                "doi",
                "doi_url",
                "journal",
                "publication_date",
                "year",
                "title",
                "abstract",
                "license",
                "pmc_url",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in writer.fieldnames})

    figures_csv = FIGURES_DIR / "figures.csv"
    with figures_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "paper_id",
                "doi",
                "pmcid",
                "figure_index",
                "label",
                "output_file",
                "caption",
                "original_member",
            ],
        )
        writer.writeheader()
        for record in records:
            for figure in record["figures"]:
                writer.writerow(
                    {
                        "paper_id": record["paper_id"],
                        "doi": record["doi"],
                        "pmcid": record["pmcid"],
                        "figure_index": figure["index"],
                        "label": figure["label"],
                        "output_file": figure["output_file"],
                        "caption": figure["caption"],
                        "original_member": figure["original_member"],
                    }
                )

    manifest = {
        "source": "NCBI PubMed Central Open Access package service",
        "query": SEARCH_TERM,
        "search_sort": ESEARCH_SORT,
        "years": sorted(YEARS),
        "initial_retstart": initial_retstart,
        "final_retstart": final_retstart,
        "seen_pmcids": sorted(seen_pmcids),
        "excluded_dois": len(EXCLUDE_DOIS),
        "excluded_pmcids": len(EXCLUDE_PMCIDS),
        "target_papers": TARGET_PAPERS,
        "figures_per_paper": FIGURES_PER_PAPER,
        "records": records,
    }
    (PAPERS_DIR / "papers.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_name = os.environ.get("DOWNLOAD_MANIFEST", "download_manifest.json")
    (BASE_DIR / manifest_name).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if DOWNLOAD_CURSOR_FILE:
        cursor_path = Path(DOWNLOAD_CURSOR_FILE)
        if not cursor_path.is_absolute():
            cursor_path = BASE_DIR / cursor_path
        cursor_path.parent.mkdir(parents=True, exist_ok=True)
        cursor_path.write_text(
            json.dumps(
                {
                    "query": SEARCH_TERM,
                    "search_sort": ESEARCH_SORT,
                    "initial_retstart": initial_retstart,
                    "final_retstart": final_retstart,
                    "downloaded_papers": len(records),
                    "seen_pmcids": sorted(seen_pmcids),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def main() -> None:
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    seen: set[str] = set()
    retstart = INITIAL_RETSTART
    initial_retstart = retstart

    while len(records) < TARGET_PAPERS:
        ids = esearch_ids(retstart)
        if not ids:
            break
        retstart += len(ids)

        for pmcid in ids:
            if pmcid in EXCLUDE_PMCIDS:
                continue
            if pmcid in seen:
                continue
            seen.add(pmcid)
            if len(records) >= TARGET_PAPERS:
                break

            try:
                candidate = get_oa_candidate(pmcid)
                time.sleep(0.35)
                if candidate is None:
                    continue
                record = process_candidate(candidate)
            except (urllib.error.URLError, urllib.error.HTTPError, ET.ParseError, tarfile.TarError) as exc:
                print(f"skip {pmcid}: {exc}")
                continue

            if record is None:
                print(f"skip {pmcid}: missing required metadata or figures")
                continue

            digest = hashlib.sha1(record["doi"].encode("utf-8")).hexdigest()[:8]
            print(
                f"saved {len(records) + 1:02d}/{TARGET_PAPERS}: "
                f"{record['journal']} {record['publication_date']} {record['doi']} {digest}"
            )
            records.append(record)

    if len(records) < TARGET_PAPERS:
        message = f"Only downloaded {len(records)} papers; expected {TARGET_PAPERS}"
        if not records or not ALLOW_PARTIAL_DOWNLOAD:
            raise SystemExit(message)
        print(f"{message}; writing partial batch because ALLOW_PARTIAL_DOWNLOAD=1")

    write_indexes(records, initial_retstart=initial_retstart, final_retstart=retstart, seen_pmcids=seen)
    print(f"done: {len(records)} papers, {len(records) * FIGURES_PER_PAPER} figures")


if __name__ == "__main__":
    main()
