"""Download 10-K filings from SEC EDGAR and write the local corpus manifest."""

import json
import time

import httpx

from app.config import get_settings

CIKS = {"NVDA": 1045810, "AMD": 2488, "INTC": 50863, "MU": 723125}
FILING_YEARS = range(2020, 2025)  # filingDate years 2020-2024 (about five per company)
USER_AGENT = "filing-rag research dev@sungyongcho.com"  # SEC requires contact details
CORPUS = get_settings().corpus_dir


def _pick_10k(block: dict) -> list[dict]:
    """Extract target-year 10-K records from one SEC submissions payload.

    Parameters
    ----------
    block
        SEC submissions `recent` or `files` entry containing filing arrays.

    Returns
    -------
    list[dict]
        10-K filing entries for configured target years.
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
    """Download filing list for one CIK and filter target 10-K years.

    Parameters
    ----------
    client
        Authenticated HTTP client.
    cik
        SEC Central Index Key.

    Returns
    -------
    list[dict]
        Filtered filing records.
    """
    r = client.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    r.raise_for_status()
    filings = r.json()["filings"]
    result = _pick_10k(filings["recent"])
    # Older filings live in separate files; fetch each file that overlaps the target years.
    for extra in filings.get("files", []):
        if int(extra["filingFrom"][:4]) <= max(FILING_YEARS):  # overlaps the target period
            time.sleep(0.2)
            er = client.get(f"https://data.sec.gov/submissions/{extra['name']}")
            er.raise_for_status()
            result += _pick_10k(er.json())
    return result


def download(client: httpx.Client, ticker: str, cik: int, filing: dict) -> dict:
    """Download one 10-K filing to local corpus and return manifest metadata.

    Parameters
    ----------
    client
        HTTP client to use for fetch.
    ticker
        Company ticker symbol.
    cik
        SEC Central Index Key.
    filing
        Filtered filing metadata from SEC submissions.

    Returns
    -------
    dict
        Updated manifest item including local file path and source URL.
    """
    acc = filing["accession"].replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{filing['primary_doc']}"
    dest = CORPUS / ticker
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{filing['filing_date']}_{filing['accession']}.html"
    if not path.exists():  # idempotent: do not download an existing snapshot again
        r = client.get(url)
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    return {"ticker": ticker, "cik": cik, **filing, "file": str(path), "url": url}


def main() -> None:
    """Fetch target filings for configured tickers and write `manifest.json`.

    Returns
    -------
    None
    """
    CORPUS.mkdir(parents=True, exist_ok=True)
    manifest = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0) as client:
        for ticker, cik in CIKS.items():
            filings = fetch_10k_list(client, cik)
            print(f"{ticker}: {len(filings)}개 10-K")
            for filing in filings:
                manifest.append(download(client, ticker, cik, filing))
                time.sleep(0.2)  # respect the SEC rate guidance (at most 10 requests/s)
    (CORPUS / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"총 {len(manifest)}개 filing → {CORPUS}")


if __name__ == "__main__":
    main()
