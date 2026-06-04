#!/usr/bin/env python3
"""Build and audit AI+chemistry/biology/materials/physics/environment/electronics Nature-family search keywords."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]

AI_KEYWORDS = [
    '"artificial intelligence"',
    '"machine learning"',
    '"deep learning"',
    '"neural network"',
    '"foundation model"',
    '"large language model"',
    '"computer vision"',
    '"AI-guided"',
    '"AI-based"',
    '"self-supervised"',
    '"representation learning"',
]

BIO_KEYWORDS = [
    "biology",
    "biological",
    "biomedical",
    "bioinformatics",
    '"single-cell"',
    '"cell-free"',
    "cellular",
    "protein",
    "proteins",
    "antibody",
    "genome",
    "genomic",
    "genomics",
    "transcriptome",
    "transcriptomic",
    "gene",
    "genes",
    "disease",
    "cancer",
    "tumor",
    "patient",
    "clinical",
    "drug",
    "immune",
    "molecular",
]

CHEM_KEYWORDS = [
    "chemistry",
    "chemical",
    "molecular",
    "molecule",
    "molecules",
    "compound",
    "compounds",
    "reaction",
    "reactions",
    "synthesis",
    "catalyst",
    "catalysis",
    "materials",
    "polymer",
    '"drug discovery"',
    '"molecular design"',
    '"protein design"',
    '"structure prediction"',
    "AlphaFold",
    "docking",
    "retrosynthesis",
]

MATERIALS_KEYWORDS = [
    '"materials science"',
    "material",
    "materials",
    "crystal",
    "crystalline",
    "structure-property",
    '"materials discovery"',
    '"materials design"',
    '"property prediction"',
    "polymer",
    "polymers",
    "nanomaterial",
    "nanomaterials",
    "nanoparticle",
    "nanoparticles",
    "alloy",
    "alloys",
    "perovskite",
    "perovskites",
    "semiconductor",
    "semiconductors",
    "battery",
    "batteries",
    "electrode",
    "electrodes",
    "electrolyte",
    "electrolytes",
    "catalyst",
    "catalysts",
    "catalysis",
    '"metal-organic framework"',
    '"metal-organic frameworks"',
    "MOF",
    "MOFs",
    '"solid-state"',
    '"thin film"',
    '"thin films"',
    "photovoltaic",
    "photovoltaics",
    "superconductor",
    "superconductors",
    '"2D materials"',
]

PHYSICS_KEYWORDS = [
    "physics",
    "physical",
    "quantum",
    "photonics",
    "optics",
    "laser",
    "ultrafast",
    "superconductivity",
    "superconductor",
    "superconductors",
    "spintronics",
    "magnetism",
    "magnetic",
    "topological",
    '"condensed matter"',
    "plasma",
    "fluid",
    "mechanics",
    "simulation",
    '"molecular dynamics"',
    '"statistical physics"',
]

ENVIRONMENT_KEYWORDS = [
    "environment",
    "environmental",
    "climate",
    '"climate change"',
    "earth",
    "geoscience",
    "geospatial",
    "atmosphere",
    "atmospheric",
    "ocean",
    "hydrology",
    "ecosystem",
    "ecology",
    "biodiversity",
    "pollution",
    "emissions",
    "carbon",
    "aerosol",
    "drought",
    "flood",
    "wildfire",
    '"remote sensing"',
    '"land use"',
    "sustainability",
]

ELECTRONICS_KEYWORDS = [
    "electronics",
    "electronic",
    "semiconductor",
    "semiconductors",
    "chip",
    "chips",
    "device",
    "devices",
    "transistor",
    "transistors",
    "sensor",
    "sensors",
    "circuit",
    "circuits",
    "computing",
    "computer",
    "information",
    "communication",
    "wireless",
    "signal",
    "signals",
    '"edge computing"',
    '"internet of things"',
    "IoT",
    "neuromorphic",
    "microelectronics",
    "optoelectronic",
    "optoelectronics",
    "photonic",
    "photonics",
]

AI_REGEXES = [
    r"\bartificial intelligence\b",
    r"\bmachine[- ]learning\b",
    r"\bdeep[- ]learning\b",
    r"\bneural networks?\b",
    r"\bfoundation models?\b",
    r"\blarge language models?\b",
    r"\bcomputer vision\b",
    r"\bAI[- ]guided\b",
    r"\bAI[- ]based\b",
    r"\bself[- ]supervised\b",
    r"\brepresentation learning\b",
]

BIO_REGEXES = [
    r"\bbiolog(?:y|ical)\b",
    r"\bbiomedical\b",
    r"\bbioinformatics\b",
    r"\bsingle[- ]cell\b",
    r"\bcell[- ]free\b",
    r"\bcellular\b",
    r"\bproteins?\b",
    r"\bantibod(?:y|ies)\b",
    r"\bgenom(?:e|ic|ics)\b",
    r"\btranscriptom(?:e|ic|ics)\b",
    r"\bgenes?\b",
    r"\bdisease\b",
    r"\bcancers?\b",
    r"\btumou?rs?\b",
    r"\bpatients?\b",
    r"\bclinical\b",
    r"\bdrugs?\b",
    r"\bimmune\b",
    r"\bmolecular\b",
]

CHEM_REGEXES = [
    r"\bchemistr(?:y|ies)\b",
    r"\bchemical(?:s)?\b",
    r"\bmolecular\b",
    r"\bmolecules?\b",
    r"\bcompounds?\b",
    r"\breactions?\b",
    r"\bsynthes(?:is|es|ized|ised)\b",
    r"\bcatalysts?\b",
    r"\bcatalys(?:is|t|e|ed)\b",
    r"\bmaterials?\b",
    r"\bpolymers?\b",
    r"\bdrug discovery\b",
    r"\bmolecular design\b",
    r"\bprotein design\b",
    r"\bstructure prediction\b",
    r"\bAlphaFold\b",
    r"\bdocking\b",
    r"\bretrosynthesis\b",
]

MATERIALS_REGEXES = [
    r"\bmaterials science\b",
    r"\bmaterials?\b",
    r"\bcrystall?ine\b",
    r"\bcrystals?\b",
    r"\bstructure[- ]property\b",
    r"\bmaterials? discovery\b",
    r"\bmaterials? design\b",
    r"\bproperty prediction\b",
    r"\bpolymers?\b",
    r"\bnanomaterials?\b",
    r"\bnanoparticles?\b",
    r"\balloys?\b",
    r"\bperovskites?\b",
    r"\bsemiconductors?\b",
    r"\bbatter(?:y|ies)\b",
    r"\belectrodes?\b",
    r"\belectrolytes?\b",
    r"\bcatalysts?\b",
    r"\bcatalys(?:is|t|e|ed)\b",
    r"\bmetal[- ]organic frameworks?\b",
    r"\bMOFs?\b",
    r"\bsolid[- ]state\b",
    r"\bthin films?\b",
    r"\bphotovoltaics?\b",
    r"\bsuperconductors?\b",
    r"\b2D materials?\b",
]

PHYSICS_REGEXES = [
    r"\bphysics\b",
    r"\bphysical\b",
    r"\bquantum\b",
    r"\bphotonics?\b",
    r"\boptics?\b",
    r"\blasers?\b",
    r"\bultrafast\b",
    r"\bsuperconduct(?:ivity|ors?)\b",
    r"\bspintronics?\b",
    r"\bmagneti(?:c|sm)\b",
    r"\btopological\b",
    r"\bcondensed matter\b",
    r"\bplasma\b",
    r"\bfluid\b",
    r"\bmechanics\b",
    r"\bsimulations?\b",
    r"\bmolecular dynamics\b",
    r"\bstatistical physics\b",
]

ENVIRONMENT_REGEXES = [
    r"\benvironment(?:al)?\b",
    r"\bclimate\b",
    r"\bclimate change\b",
    r"\bearth\b",
    r"\bgeoscience\b",
    r"\bgeospatial\b",
    r"\batmospher(?:e|ic)\b",
    r"\bocean\b",
    r"\bhydrology\b",
    r"\becosystems?\b",
    r"\becology\b",
    r"\bbiodiversity\b",
    r"\bpollution\b",
    r"\bemissions?\b",
    r"\bcarbon\b",
    r"\baerosols?\b",
    r"\bdroughts?\b",
    r"\bfloods?\b",
    r"\bwildfires?\b",
    r"\bremote sensing\b",
    r"\bland use\b",
    r"\bsustainability\b",
]

ELECTRONICS_REGEXES = [
    r"\belectronics?\b",
    r"\bsemiconductors?\b",
    r"\bchips?\b",
    r"\bdevices?\b",
    r"\btransistors?\b",
    r"\bsensors?\b",
    r"\bcircuits?\b",
    r"\bcomput(?:ing|er)\b",
    r"\binformation\b",
    r"\bcommunication\b",
    r"\bwireless\b",
    r"\bsignals?\b",
    r"\bedge computing\b",
    r"\binternet of things\b",
    r"\bIoT\b",
    r"\bneuromorphic\b",
    r"\bmicroelectronics?\b",
    r"\boptoelectronics?\b",
    r"\bphotonics?\b",
]


def pmc_field(keyword: str) -> str:
    return f"{keyword}[Title/Abstract]"


def build_query(years: list[str], include_open_access: bool = True, domain: str = "both") -> str:
    year_clause = " OR ".join(f"{year}[pdat]" for year in years)
    clauses = ["Nature*[Journal]", f"({year_clause})"]
    if include_open_access:
        clauses.append("open access[filter]")
    clauses.append("(" + " OR ".join(pmc_field(item) for item in AI_KEYWORDS) + ")")
    if domain == "biology":
        domain_keywords = BIO_KEYWORDS
    elif domain == "chemistry":
        domain_keywords = CHEM_KEYWORDS
    elif domain == "materials":
        domain_keywords = MATERIALS_KEYWORDS
    elif domain == "materials_chemistry":
        domain_keywords = MATERIALS_KEYWORDS + CHEM_KEYWORDS
    elif domain == "physics":
        domain_keywords = PHYSICS_KEYWORDS
    elif domain == "environment":
        domain_keywords = ENVIRONMENT_KEYWORDS
    elif domain == "electronics":
        domain_keywords = ELECTRONICS_KEYWORDS
    elif domain == "both":
        domain_keywords = BIO_KEYWORDS + CHEM_KEYWORDS
    else:
        raise ValueError(f"unsupported domain: {domain}")
    clauses.append("(" + " OR ".join(pmc_field(item) for item in domain_keywords) + ")")
    return " AND ".join(clauses)


def regex_hits(text: str, patterns: list[str]) -> list[str]:
    return [pat for pat in patterns if re.search(pat, text, flags=re.I)]


def scan_papers(papers_json: Path, out_csv: Path | None = None) -> list[dict]:
    records = json.loads(papers_json.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for record in records:
        text = f"{record.get('title', '')}\n{record.get('abstract', '')}"
        ai_hits = regex_hits(text, AI_REGEXES)
        bio_hits = regex_hits(text, BIO_REGEXES)
        chem_hits = regex_hits(text, CHEM_REGEXES)
        materials_hits = regex_hits(text, MATERIALS_REGEXES)
        physics_hits = regex_hits(text, PHYSICS_REGEXES)
        environment_hits = regex_hits(text, ENVIRONMENT_REGEXES)
        electronics_hits = regex_hits(text, ELECTRONICS_REGEXES)
        rows.append(
            {
                "paper_id": record.get("paper_id", ""),
                "doi": record.get("doi", ""),
                "journal": record.get("journal", ""),
                "publication_date": record.get("publication_date", ""),
                "title": record.get("title", ""),
                "ai_regex_hits": "; ".join(ai_hits),
                "bio_regex_hits": "; ".join(bio_hits),
                "chem_regex_hits": "; ".join(chem_hits),
                "materials_regex_hits": "; ".join(materials_hits),
                "physics_regex_hits": "; ".join(physics_hits),
                "environment_regex_hits": "; ".join(environment_hits),
                "electronics_regex_hits": "; ".join(electronics_hits),
                "is_ai_bio": bool(ai_hits and bio_hits),
                "is_ai_chem": bool(ai_hits and chem_hits),
                "is_ai_materials": bool(ai_hits and materials_hits),
                "is_ai_physics": bool(ai_hits and physics_hits),
                "is_ai_environment": bool(ai_hits and environment_hits),
                "is_ai_electronics": bool(ai_hits and electronics_hits),
                "is_target": bool(
                    ai_hits
                    and (
                        bio_hits
                        or chem_hits
                        or materials_hits
                        or physics_hits
                        or environment_hits
                        or electronics_hits
                    )
                ),
            }
        )
    if out_csv is not None:
        write_csv(out_csv, rows)
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build/audit AI+chemistry/biology/materials/physics/environment/electronics PMC keywords")
    sub = parser.add_subparsers(dest="command", required=True)

    p_query = sub.add_parser("query")
    p_query.add_argument("--years", nargs="+", default=["2025", "2026"])
    p_query.add_argument(
        "--domain",
        choices=["biology", "chemistry", "materials", "materials_chemistry", "physics", "environment", "electronics", "both"],
        default="both",
    )
    p_query.add_argument("--no-open-access", action="store_true")

    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--papers-json", default="Papers/papers.json")
    p_scan.add_argument("--out-csv", default="PaperKeywords/paper_keywords.csv")

    args = parser.parse_args()
    if args.command == "query":
        print(build_query(args.years, include_open_access=not args.no_open_access, domain=args.domain))
    elif args.command == "scan":
        papers_json = Path(args.papers_json)
        if not papers_json.is_absolute():
            papers_json = BASE_DIR / papers_json
        out_csv = Path(args.out_csv)
        if not out_csv.is_absolute():
            out_csv = BASE_DIR / out_csv
        rows = scan_papers(papers_json, out_csv)
        print(
            json.dumps(
                {
                    "papers": len(rows),
                    "ai_bio": sum(bool(row["is_ai_bio"]) for row in rows),
                    "ai_chem": sum(bool(row["is_ai_chem"]) for row in rows),
                    "ai_materials": sum(bool(row["is_ai_materials"]) for row in rows),
                    "ai_physics": sum(bool(row["is_ai_physics"]) for row in rows),
                    "ai_environment": sum(bool(row["is_ai_environment"]) for row in rows),
                    "ai_electronics": sum(bool(row["is_ai_electronics"]) for row in rows),
                    "target": sum(bool(row["is_target"]) for row in rows),
                    "out_csv": str(out_csv),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
