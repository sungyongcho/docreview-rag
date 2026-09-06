import json
from pathlib import Path
import time

import httpx

CIKS = {"NVDA": 1045810, "AMD": 2488, "INTC": 50863, "MU": 723125}
FILING_YEARS = range(2020, 2025)  # filingDate years 2020-2024, about five per company
USER_AGENT = "filing-rag research dev@sungyongcho.com"  # SEC requires a contact address
CORPUS = Path("data/corpus")


def _pick_10k(block: dict) -> list[dict]:
    """Return only the target-year 10-K filings in one submissions block.

    SEC returns a filing list as **parallel arrays**: the same index means the same
    filing. ``strict=True`` matters. If the lengths disagree, a plain ``zip`` stops
    **silently** at the shorter one and drops every filing after it. A document
    missing from the corpus would then raise nothing at all, and a crash is better
    than a silent loss. (Measured: all eight recent and older responses across four
    companies had equal lengths.)
    """
    rows = zip(
        block["form"],
        block["accessionNumber"],
        block["filingDate"],
        block["reportDate"],
        block["primaryDocument"],
        strict=True,
    )
    return [
        {"accession": acc, "filing_date": fd, "report_date": rd, "primary_doc": doc}
        for form, acc, fd, rd, doc in rows
        if form == "10-K" and int(fd[:4]) in FILING_YEARS
    ]


def fetch_10k_list(client: httpx.Client, cik: int) -> list[dict]:
    """Return every target 10-K across the recent and older submissions files."""
    r = client.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    r.raise_for_status()
    filings = r.json()["filings"]
    result = _pick_10k(filings["recent"])
    # Older filings live in separate files[] entries; fetch one when its range overlaps.
    for extra in filings.get("files", []):
        if int(extra["filingFrom"][:4]) <= max(FILING_YEARS):  # overlaps the target range
            time.sleep(0.2)
            er = client.get(f"https://data.sec.gov/submissions/{extra['name']}")
            er.raise_for_status()
            result += _pick_10k(er.json())
    return result


def download(client: httpx.Client, ticker: str, cik: int, filing: dict) -> dict:
    acc = filing["accession"].replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{filing['primary_doc']}"
    dest = CORPUS / ticker
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{filing['filing_date']}_{filing['accession']}.html"
    if not path.exists():  # idempotent: never re-download a snapshot already on disk
        r = client.get(url)
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    return {"ticker": ticker, "cik": cik, **filing, "file": str(path), "url": url}


def main() -> None:
    CORPUS.mkdir(parents=True, exist_ok=True)
    manifest = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0) as client:
        for ticker, cik in CIKS.items():
            filings = fetch_10k_list(client, cik)
            print(f"{ticker}: {len(filings)} 10-K filings")
            for filing in filings:
                manifest.append(download(client, ticker, cik, filing))
                time.sleep(0.2)  # stay polite to SEC, at most 10 requests per second
    (CORPUS / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"{len(manifest)} filings total -> {CORPUS}")


if __name__ == "__main__":
    main()
