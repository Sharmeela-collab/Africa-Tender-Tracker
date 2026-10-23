"""
Diagnostic Transport Tender Tracker
Africa + South Asia + Multilaterals
Prints raw counts and detailed match/skip logs for total transparency.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import httpx
from bs4 import BeautifulSoup
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SHEET_NAME = "Tender Tracker"
WORKSHEET_NAME = "Africa"

OUTPUT_DIR = Path("./output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = [
    "Date Found",
    "Country / Region",
    "Organisation / Portal",
    "Tender ID",
    "Tender Title",
    "Tender Category",
    "Summary of Tender",      # Column G
    "Pre-bid Meeting Date",  # Column H
    "Bid Submission Date",   # Column I
    "Portal Link",           # Column J
]

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

TODAY_STR = datetime.now().strftime("%Y-%m-%d")
DATE_REGEX = re.compile(r"\b\d{1,2}[-/\s](?:[A-Za-z]{3,9}|\d{1,2})[-/\s]\d{2,4}\b")

# Non-transport exclusions
EXCLUSIONS = [
    "avocado", "packhouse", "packing line", "grading line", "agro", "agriculture",
    "fisheries", "fishery", "fish", "livestock", "horticulture", "hotel", "catering",
    "accommodation", "cleaning", "security guard", "stationery", "medical",
    "pharmaceutical", "fertilizer", "uniform"
]

TRANSPORT_KEYWORDS = [
    "road", "highway", "expressway", "pavement", "bridge", "flyover", "viaduct",
    "interchange", "tunnel", "transit", "brt", "bus", "transport", "mobility",
    "rail", "railway", "train", "locomotive", "port", "harbour", "maritime",
    "jetty", "airport", "runway", "aviation", "traffic", "feeder road", "corridor"
]


def log(portal: str, msg: str) -> None:
    print(f"[{portal}] {msg}")


def check_transport_qualification(title: str, summary: str, is_transport_agency: bool = False) -> tuple[bool, str]:
    """Inspects text and returns (is_qualified, reason)."""
    text = f"{title} {summary}".lower()

    for exc in EXCLUSIONS:
        if exc in text:
            return False, f"Matched exclusion term '{exc}'"

    if is_transport_agency:
        return True, "Published by dedicated Transport Authority"

    for kw in TRANSPORT_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", text):
            return True, f"Matched transport keyword '{kw}'"

    return False, "No transport domain keyword matched"


def clean_summary_text(raw_text: str, fallback_title: str) -> str:
    clean = re.sub(r"\s+", " ", raw_text).strip()
    clean = re.sub(r"(Tender Notice|Advert|Description|Scope of Work|Overview)[:\s]*", "", clean, flags=re.IGNORECASE)
    if len(clean) > 40:
        return f"Scope of Assignment: {clean[:340]}..."
    return f"Scope of Assignment: Transport infrastructure / consulting services for {fallback_title}."


def normalise_item(item: Dict) -> Dict:
    return {h: item.get(h, "") for h in HEADERS}


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

async def fetch_african_union(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://au.int/en/bids"
    results = []
    log("African Union", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=25)
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.find_all("div", class_=re.compile(r"views-row|item-list"))
        log("African Union", f"Raw rows found on page: {len(items)}")

        for item in items:
            link_tag = item.find("a")
            if not link_tag or not link_tag.get("href"):
                continue
            title = re.sub(r"\s+", " ", link_tag.get_text(strip=True))
            if len(title) < 10:
                continue

            full_text = item.get_text(separator=" ", strip=True)
            dates = DATE_REGEX.findall(full_text)
            deadline = dates[0] if dates else "Refer notice"

            link = link_tag["href"]
            if not link.startswith("http"):
                link = "https://au.int" + link

            summary = clean_summary_text(full_text, title)
            ok, reason = check_transport_qualification(title, summary)
            if ok:
                log("African Union", f"-> MATCH: {title[:60]}")
                results.append(normalise_item({
                    "Date Found": TODAY_STR,
                    "Country / Region": "Pan-Africa",
                    "Organisation / Portal": "African Union Commission",
                    "Tender ID": f"AU-{title[:14]}",
                    "Tender Title": title,
                    "Tender Category": "Transport / Infrastructure",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer notice",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("African Union", f"Notice: {e}")
    log("African Union", f"Retrieved {len(results)} qualifying notices.")
    return results


async def fetch_trademark_africa(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://www.trademarkafrica.com/procurement/"
    results = []
    log("TradeMark Africa", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=25)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.find_all(["div", "article"], class_=re.compile(r"procurement|tender|post"))
        log("TradeMark Africa", f"Raw rows found on page: {len(cards)}")

        for card in cards:
            a_tag = card.find("a")
            if not a_tag or not a_tag.get("href"):
                continue
            title = re.sub(r"\s+", " ", a_tag.get_text(strip=True))
            if len(title) < 12:
                continue

            card_text = card.get_text(separator=" ", strip=True)
            dates = DATE_REGEX.findall(card_text)
            deadline = dates[-1] if dates else "Refer notice"
            link = a_tag["href"]

            summary = clean_summary_text(card_text, title)
            ok, reason = check_transport_qualification(title, summary)
            if ok:
                log("TradeMark Africa", f"-> MATCH: {title[:60]}")
                results.append(normalise_item({
                    "Date Found": TODAY_STR,
                    "Country / Region": "East & Horn of Africa",
                    "Organisation / Portal": "TradeMark Africa",
                    "Tender ID": f"TMA-{title[:14]}",
                    "Tender Title": title,
                    "Tender Category": "Transport / Logistics",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer notice",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("TradeMark Africa", f"Notice: {e}")
    log("TradeMark Africa", f"Retrieved {len(results)} qualifying notices.")
    return results


async def fetch_kenya_roads(client: httpx.AsyncClient) -> List[Dict]:
    sources = [
        ("https://kura.go.ke/cat_doc/tender-notice/", "Kenya Urban Roads Authority (KURA)", "Urban Roads & Transport"),
        ("https://kenha.co.ke/tenders/", "Kenya National Highways Authority (KeNHA)", "Highways Infrastructure")
    ]
    results = []
    for url, org, cat in sources:
        log(org, "Connecting...")
        try:
            r = await client.get(url, headers=HTTP_HEADERS, timeout=25)
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.find_all("tr")
            log(org, f"Raw table rows found: {len(rows)}")

            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                row_text = row.get_text(separator=" ", strip=True)
                link_tag = row.find("a")
                title = cells[1].get_text(strip=True) if len(cells) > 1 else cells[0].get_text(strip=True)
                if len(title) < 8 or "s.no" in title.lower():
                    continue

                dates = DATE_REGEX.findall(row_text)
                deadline = dates[-1] if dates else "Refer notice"

                link = link_tag["href"] if link_tag and link_tag.get("href") else url
                if not link.startswith("http"):
                    link = ("https://kura.go.ke" if "kura" in url else "https://kenha.co.ke") + link

                summary = clean_summary_text(row_text, title)
                ok, reason = check_transport_qualification(title, summary, is_transport_agency=True)
                if ok:
                    log(org, f"-> MATCH: {title[:60]}")
                    results.append(normalise_item({
                        "Date Found": TODAY_STR,
                        "Country / Region": "Kenya",
                        "Organisation / Portal": org,
                        "Tender ID": f"KE-{title[:12]}",
                        "Tender Title": title,
                        "Tender Category": cat,
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
        except Exception as e:
            log(org, f"Notice: {e}")
        log(org, f"Retrieved {len(results)} qualifying notices.")
    return results


async def fetch_afdb(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://www.afdb.org/en/projects-and-operations/procurement"
    results = []
    log("AfDB", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=25)
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.find_all("tr")
        log("AfDB", f"Raw rows found: {len(rows)}")

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            a_tag = row.find("a")
            if not a_tag or not a_tag.get("href"):
                continue
            title = re.sub(r"\s+", " ", a_tag.get_text(strip=True))
            if len(title) < 8:
                continue

            row_text = row.get_text(separator=" ", strip=True)
            dates = DATE_REGEX.findall(row_text)
            deadline = dates[-1] if dates else "Refer notice"

            link = a_tag["href"]
            if not link.startswith("http"):
                link = "https://www.afdb.org" + link

            summary = clean_summary_text(row_text, title)
            ok, reason = check_transport_qualification(title, summary)
            if ok:
                log("AfDB", f"-> MATCH: {title[:60]}")
                results.append(normalise_item({
                    "Date Found": TODAY_STR,
                    "Country / Region": "Multilateral / Africa",
                    "Organisation / Portal": "African Development Bank (AfDB)",
                    "Tender ID": f"AfDB-{title[:14]}",
                    "Tender Title": title,
                    "Tender Category": "Transport / Infrastructure",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("AfDB", f"Notice: {e}")
    log("AfDB", f"Retrieved {len(results)} qualifying notices.")
    return results


async def fetch_ungm(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://www.ungm.org/Public/Notice/Search"
    results = []
    log("UNGM", "Fetching public notices...")
    payload = {"PageIndex": 0, "PageSize": 60, "SortField": "DatePublished", "SortAscending": False}
    try:
        r = await client.post(url, json=payload, headers={**HTTP_HEADERS, "Content-Type": "application/json"}, timeout=25)
        data = r.json()
        items = data.get("Items") or []
        log("UNGM", f"Raw items received: {len(items)}")

        for item in items:
            title = (item.get("Title") or "").strip()
            if not title:
                continue

            deadline = str(item.get("Deadline") or "")[:10]
            agency = item.get("UNOrganization") or "UN Agency"
            desc = (item.get("Description") or item.get("Summary") or "").strip()
            countries = ", ".join(item.get("BeneficiaryCountries") or []) or "International / Africa"

            summary = clean_summary_text(desc if desc else title, title)
            ok, reason = check_transport_qualification(title, summary)
            if ok:
                log("UNGM", f"-> MATCH: {title[:60]}")
                notice_id = str(item.get("Id") or "")
                results.append(normalise_item({
                    "Date Found": TODAY_STR,
                    "Country / Region": countries,
                    "Organisation / Portal": f"UNGM - {agency}",
                    "Tender ID": f"UNGM-{notice_id}",
                    "Tender Title": title,
                    "Tender Category": item.get("TypeName") or "Transport / Advisory",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer notice",
                    "Bid Submission Date": deadline or "Refer notice",
                    "Portal Link": f"https://www.ungm.org/Public/Notice/{notice_id}" if notice_id else "https://www.ungm.org",
                }))
    except Exception as e:
        log("UNGM", f"Notice: {e}")
    log("UNGM", f"Retrieved {len(results)} qualifying notices.")
    return results


async def fetch_adb(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://www.adb.org/projects/tenders"
    results = []
    log("ADB", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=25)
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.find_all(["div", "li"], class_=re.compile(r"item|views-row|search-result"))
        log("ADB", f"Raw tender blocks found: {len(items)}")

        for item in items:
            a_tag = item.find("a")
            if not a_tag or not a_tag.get("href"):
                continue
            title = re.sub(r"\s+", " ", a_tag.get_text(strip=True))
            if len(title) < 10:
                continue

            item_text = item.get_text(separator=" ", strip=True)
            dates = DATE_REGEX.findall(item_text)
            deadline = dates[-1] if dates else "Refer notice"

            link = a_tag["href"]
            if not link.startswith("http"):
                link = "https://www.adb.org" + link

            summary = clean_summary_text(item_text, title)
            ok, reason = check_transport_qualification(title, summary)
            if ok:
                log("ADB", f"-> MATCH: {title[:60]}")
                results.append(normalise_item({
                    "Date Found": TODAY_STR,
                    "Country / Region": "Asia-Pacific",
                    "Organisation / Portal": "Asian Development Bank (ADB)",
                    "Tender ID": f"ADB-{title[:12]}",
                    "Tender Title": title,
                    "Tender Category": "Transport / Infrastructure",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer CSRN portal",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("ADB", f"Notice: {e}")
    log("ADB", f"Retrieved {len(results)} qualifying notices.")
    return results


async def fetch_giz_kfw(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://ausschreibungen.giz.de/buyer/ausschreibungen.html"
    results = []
    log("GIZ / KfW", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.find_all(["tr", "div"], class_=re.compile(r"project|tender|row"))
        log("GIZ / KfW", f"Raw rows found: {len(rows)}")

        for item in rows:
            row_text = item.get_text(separator=" ", strip=True)
            a_tag = item.find("a")
            title = a_tag.get_text(strip=True) if a_tag else ""
            if len(title) < 10:
                continue

            dates = DATE_REGEX.findall(row_text)
            deadline = dates[-1] if dates else "Refer notice"

            link = a_tag["href"] if a_tag and a_tag.get("href") else url
            if not link.startswith("http"):
                link = "https://ausschreibungen.giz.de" + link

            summary = clean_summary_text(row_text, title)
            ok, reason = check_transport_qualification(title, summary)
            if ok:
                log("GIZ / KfW", f"-> MATCH: {title[:60]}")
                results.append(normalise_item({
                    "Date Found": TODAY_STR,
                    "Country / Region": "Global / South Asia",
                    "Organisation / Portal": "GIZ International Services",
                    "Tender ID": f"GIZ-{title[:12]}",
                    "Tender Title": title,
                    "Tender Category": "Sustainable Transport",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("GIZ / KfW", f"Notice: {e}")
    log("GIZ / KfW", f"Retrieved {len(results)} qualifying notices.")
    return results


async def fetch_south_asia_and_islands(client: httpx.AsyncClient) -> List[Dict]:
    portals = [
        ("https://eproc.publicprocurement.govmu.org", "Mauritius", "Mauritius e-Procurement"),
        ("https://bolpatra.gov.np/egp/", "Nepal", "Nepal PPMO"),
        ("https://www.egp.gov.bt", "Bhutan", "Bhutan e-GP"),
        ("https://promise.lk", "Sri Lanka", "Sri Lanka PROMISE"),
    ]
    results = []
    for url, country, org in portals:
        log(org, f"Connecting to {country} portal...")
        try:
            r = await client.get(url, headers=HTTP_HEADERS, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.find_all(["tr", "div"], class_=re.compile(r"row|tender|item"))
            log(org, f"Raw rows found: {len(rows)}")

            for row in rows:
                row_text = row.get_text(separator=" ", strip=True)
                a_tag = row.find("a")
                title = a_tag.get_text(strip=True) if a_tag else ""
                if len(title) < 10:
                    continue

                dates = DATE_REGEX.findall(row_text)
                deadline = dates[-1] if dates else "Refer notice"

                link = a_tag["href"] if a_tag and a_tag.get("href") else url
                if not link.startswith("http"):
                    link = url.rstrip("/") + "/" + link.lstrip("/")

                summary = clean_summary_text(row_text, title)
                ok, reason = check_transport_qualification(title, summary)
                if ok:
                    log(org, f"-> MATCH: {title[:60]}")
                    results.append(normalise_item({
                        "Date Found": TODAY_STR,
                        "Country / Region": country,
                        "Organisation / Portal": org,
                        "Tender ID": f"{country[:2].upper()}-{title[:12]}",
                        "Tender Title": title,
                        "Tender Category": "Transport Infrastructure",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
        except Exception as e:
            log(org, f"Notice: {e}")
        log(org, f"Retrieved {len(results)} qualifying notices.")
    return results


# ---------------------------------------------------------------------------
# Sync Engine
# ---------------------------------------------------------------------------

def sync_records(tenders: List[Dict]) -> None:
    print("\n" + "=" * 65)
    print(f" TOTAL QUALIFYING NOTICES DISCOVERED: {len(tenders)}")
    print("=" * 65)

    if not tenders:
        print("[Sync Engine] No qualifying notices found across portals.")
        return

    df = pd.DataFrame(tenders)
    df.drop_duplicates(subset=["Tender ID"], inplace=True)

    creds_json = os.environ.get("GCP_CREDENTIALS")
    if creds_json:
        try:
            import gspread
            from google.oauth2.service_account import Credentials

            creds_dict = json.loads(creds_json)
            scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            gc = gspread.authorize(creds)

            spreadsheet = gc.open(SHEET_NAME)
            try:
                sh = spreadsheet.worksheet(WORKSHEET_NAME)
            except gspread.exceptions.WorksheetNotFound:
                sh = spreadsheet.add_worksheet(title=WORKSHEET_NAME, rows="1000", cols="20")

            rows = sh.get_all_values()
            if len(rows) == 0:
                sh.append_row(HEADERS)
                existing_ids = set()
            else:
                existing_ids = {r[3].strip() for r in rows[1:] if len(r) > 3}

            new_entries = []
            for item in df.to_dict(orient="records"):
                if item["Tender ID"] not in existing_ids:
                    existing_ids.add(item["Tender ID"])
                    new_entries.append([item[h] for h in HEADERS])

            if new_entries:
                sh.append_rows(new_entries)
                print(f"[Google Sheets] Appended {len(new_entries)} new tenders into tab '{WORKSHEET_NAME}'!")
            else:
                print(f"[Google Sheets] Tab '{WORKSHEET_NAME}' already contains all discovered tenders.")
        except Exception as e:
            print(f"[Google Sheets Error] {e}")

    out_csv = OUTPUT_DIR / f"transport_tenders_{TODAY_STR}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"[CSV Backup] Saved copy to {out_csv}")


async def main():
    print("=" * 65)
    print(" STARTING DIAGNOSTIC TRANSPORT TENDER TRACKER")
    print("=" * 65)

    all_notices = []
    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        tasks = [
            fetch_african_union(client),
            fetch_trademark_africa(client),
            fetch_kenya_roads(client),
            fetch_afdb(client),
            fetch_ungm(client),
            fetch_adb(client),
            fetch_giz_kfw(client),
            fetch_south_asia_and_islands(client),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                all_notices.extend(res)

    sync_records(all_notices)


if __name__ == "__main__":
    asyncio.run(main())
