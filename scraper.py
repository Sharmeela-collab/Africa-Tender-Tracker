"""
Comprehensive Africa & Multilateral Tender Tracker
Tracks African Union, TradeMark Africa, AfDB, Kenya (PPIP, KURA, KeNHA),
Uganda PPDA, Ethiopia e-GP, Tanzania NEST, South Africa eTenders, and UNGM.
Syncs to the 'Africa' worksheet of the 'Tender Tracker' Google Sheet.
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
# CONFIGURATION
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

TODAY = datetime.now().strftime("%Y-%m-%d")
DATE_REGEX = re.compile(r"\b\d{1,2}[-/\s](?:[A-Za-z]{3,9}|\d{1,2})[-/\s]\d{2,4}\b")


def normalise_item(item: Dict) -> Dict:
    return {h: item.get(h, "") for h in HEADERS}


def log(portal: str, msg: str) -> None:
    print(f"[{portal}] {msg}")


# ---------------------------------------------------------------------------
# 1. African Union (au.int)
# ---------------------------------------------------------------------------
async def fetch_african_union(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://au.int/en/bids"
    results = []
    log("African Union", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.find_all("div", class_=re.compile(r"views-row|item-list"))
            for item in items:
                link_tag = item.find("a")
                if not link_tag or not link_tag.get("href"):
                    continue
                title = re.sub(r"\s+", " ", link_tag.get_text(strip=True))
                if len(title) < 10 or ("bids" in title.lower() and len(title) < 15):
                    continue
                link = link_tag["href"]
                if not link.startswith("http"):
                    link = "https://au.int" + link

                full_text = item.get_text(separator=" ", strip=True)
                dates = DATE_REGEX.findall(full_text)
                deadline = dates[0] if dates else "Refer notice"

                ref_match = re.search(r"AUC/[A-Z0-9/_-]+", full_text)
                t_id = ref_match.group(0) if ref_match else f"AU-{title[:14]}"
                summary = full_text[:280] + ("..." if len(full_text) > 280 else "")

                results.append(normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": "Pan-Africa",
                    "Organisation / Portal": "African Union Commission",
                    "Tender ID": t_id,
                    "Tender Title": title,
                    "Tender Category": "Advisory / Works / Services",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("African Union", f"Notice: {e}")
    log("African Union", f"Retrieved {len(results)} notices.")
    return results


# ---------------------------------------------------------------------------
# 2. TradeMark Africa (trademarkafrica.com)
# ---------------------------------------------------------------------------
async def fetch_trademark_africa(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://www.trademarkafrica.com/procurement/"
    results = []
    log("TradeMark Africa", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.find_all(["div", "article"], class_=re.compile(r"procurement|tender|post"))
            for card in cards:
                a_tag = card.find("a")
                if not a_tag or not a_tag.get("href"):
                    continue
                title = re.sub(r"\s+", " ", a_tag.get_text(strip=True))
                if len(title) < 12:
                    continue
                link = a_tag["href"]
                card_text = card.get_text(separator=" ", strip=True)
                dates = DATE_REGEX.findall(card_text)
                deadline = dates[-1] if dates else "Refer notice"

                id_match = re.search(r"PRQ\d{4,8}|TMA/[A-Z0-9/_-]+", card_text)
                t_id = id_match.group(0) if id_match else f"TMA-{title[:14]}"
                summary = card_text[:280] + ("..." if len(card_text) > 280 else "")

                results.append(normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": "East & Horn of Africa",
                    "Organisation / Portal": "TradeMark Africa",
                    "Tender ID": t_id,
                    "Tender Title": title,
                    "Tender Category": "Transport, Trade & Logistics",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("TradeMark Africa", f"Notice: {e}")
    log("TradeMark Africa", f"Retrieved {len(results)} notices.")
    return results


# ---------------------------------------------------------------------------
# 3. Kenya Urban Roads Authority (KURA)
# ---------------------------------------------------------------------------
async def fetch_kenya_kura(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://kura.go.ke/cat_doc/tender-notice/"
    results = []
    log("Kenya KURA", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                row_text = row.get_text(separator=" ", strip=True)
                link_tag = row.find("a")
                title = cells[1].get_text(strip=True) if len(cells) > 1 else cells[0].get_text(strip=True)
                if len(title) < 8 and link_tag:
                    title = link_tag.get_text(strip=True)
                if len(title) < 6 or "s.no" in title.lower():
                    continue

                link = link_tag["href"] if link_tag and link_tag.get("href") else url
                if not link.startswith("http"):
                    link = "https://kura.go.ke" + link

                dates = DATE_REGEX.findall(row_text)
                deadline = dates[-1] if dates else "Refer notice"

                ref_match = re.search(r"KURA/[A-Z0-9/_-]+", row_text)
                t_id = ref_match.group(0) if ref_match else f"KURA-{title[:12]}"
                summary = f"Urban roads and transport civil works contract published by KURA: {title}"

                results.append(normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": "Kenya",
                    "Organisation / Portal": "Kenya Urban Roads Authority (KURA)",
                    "Tender ID": t_id,
                    "Tender Title": title,
                    "Tender Category": "Urban Roads & Transport",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("Kenya KURA", f"Notice: {e}")
    log("Kenya KURA", f"Retrieved {len(results)} notices.")
    return results


# ---------------------------------------------------------------------------
# 4. Kenya National Highways Authority (KeNHA)
# ---------------------------------------------------------------------------
async def fetch_kenya_kenha(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://kenha.co.ke/tenders/"
    results = []
    log("Kenya KeNHA", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                row_text = row.get_text(separator=" ", strip=True)
                link_tag = row.find("a")
                title = cells[1].get_text(strip=True) if len(cells) > 1 else cells[0].get_text(strip=True)
                if len(title) < 8:
                    continue

                link = link_tag["href"] if link_tag and link_tag.get("href") else url
                dates = DATE_REGEX.findall(row_text)
                deadline = dates[-1] if dates else "Refer notice"

                ref_match = re.search(r"KeNHA/[A-Z0-9/_-]+", row_text)
                t_id = ref_match.group(0) if ref_match else f"KeNHA-{title[:12]}"
                summary = f"Highways maintenance or infrastructure development tender by KeNHA: {title}"

                results.append(normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": "Kenya",
                    "Organisation / Portal": "Kenya National Highways Authority (KeNHA)",
                    "Tender ID": t_id,
                    "Tender Title": title,
                    "Tender Category": "Highways & Transport Infrastructure",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("Kenya KeNHA", f"Notice: {e}")
    log("Kenya KeNHA", f"Retrieved {len(results)} notices.")
    return results


# ---------------------------------------------------------------------------
# 5. Kenya Public Procurement Information Portal (PPIP)
# ---------------------------------------------------------------------------
async def fetch_kenya_ppip(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://tenders.go.ke/api/tenders"
    results = []
    log("Kenya PPIP", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=30)
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else data.get("data", [])
            for item in items[:25]:
                title = item.get("tender_name") or item.get("title") or ""
                t_no = item.get("tender_number") or item.get("id") or ""
                entity = item.get("pe_name") or "Government of Kenya"
                closing = item.get("closing_date") or item.get("end_date") or "Refer notice"
                link = f"https://tenders.go.ke/tenders/{item.get('id')}" if item.get("id") else "https://tenders.go.ke"
                if not title:
                    continue
                results.append(normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": "Kenya",
                    "Organisation / Portal": f"Kenya PPIP - {entity}",
                    "Tender ID": f"KE-{t_no or title[:12]}",
                    "Tender Title": title,
                    "Tender Category": item.get("tender_category") or "Public Works / Goods",
                    "Summary of Tender": f"Kenya public procurement portal tender for {entity}: {title}",
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": str(closing)[:10],
                    "Portal Link": link,
                }))
    except Exception:
        pass
    log("Kenya PPIP", f"Retrieved {len(results)} notices.")
    return results


# ---------------------------------------------------------------------------
# 6. Uganda PPDA (egpuganda.go.ug)
# ---------------------------------------------------------------------------
async def fetch_uganda_ppda(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://egpuganda.go.ug/bid-notices"
    results = []
    log("Uganda PPDA", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue
                full_row = row.get_text(separator=" ", strip=True)
                title = cells[1].get_text(strip=True) if len(cells) > 2 else cells[0].get_text(strip=True)
                if len(title) < 10:
                    continue
                a_tag = row.find("a")
                link = a_tag["href"] if a_tag and a_tag.get("href") else url
                if not link.startswith("http"):
                    link = "https://egpuganda.go.ug" + link

                dates = DATE_REGEX.findall(full_row)
                deadline = dates[-1] if dates else "Refer notice"
                ref_match = re.search(r"[A-Za-z0-9]+/[A-Z]+/\d{4}-\d{4}/\d+", full_row)
                t_id = ref_match.group(0) if ref_match else f"UG-{title[:12]}"

                results.append(normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": "Uganda",
                    "Organisation / Portal": "Uganda e-GP (PPDA)",
                    "Tender ID": t_id,
                    "Tender Title": title,
                    "Tender Category": "Public Works / Consultancy",
                    "Summary of Tender": f"Uganda Government electronic procurement notice: {title}",
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("Uganda PPDA", f"Notice: {e}")
    log("Uganda PPDA", f"Retrieved {len(results)} notices.")
    return results


# ---------------------------------------------------------------------------
# 7. Ethiopia e-GP (egp.gov.et)
# ---------------------------------------------------------------------------
async def fetch_ethiopia_egp(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://egp.gov.et/egp/bids/all"
    results = []
    log("Ethiopia e-GP", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.find_all(["div", "tr"], class_=re.compile(r"bid|card|tender|row"))
            for card in cards:
                title_elem = card.find(["h4", "h5", "a", "strong"])
                if not title_elem:
                    continue
                title = title_elem.get_text(strip=True)
                if len(title) < 10 or "all tenders" in title.lower():
                    continue

                card_text = card.get_text(separator=" ", strip=True)
                dates = DATE_REGEX.findall(card_text)
                deadline = dates[0] if dates else "Refer notice"

                ref_match = re.search(r"[A-Z0-9]+-[A-Z]+-[A-Z]-\d{4}-\d{4}-[A-Z]+", card_text)
                t_id = ref_match.group(0) if ref_match else f"ET-{title[:12]}"

                link = url
                a_tag = card.find("a")
                if a_tag and a_tag.get("href"):
                    link = a_tag["href"]
                    if not link.startswith("http"):
                        link = "https://egp.gov.et" + link

                results.append(normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": "Ethiopia",
                    "Organisation / Portal": "Ethiopia e-GP Portal",
                    "Tender ID": t_id,
                    "Tender Title": title,
                    "Tender Category": "Goods / Works / Services",
                    "Summary of Tender": f"Federal / Regional Ethiopian public procurement tender: {title}",
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("Ethiopia e-GP", f"Notice: {e}")
    log("Ethiopia e-GP", f"Retrieved {len(results)} notices.")
    return results


# ---------------------------------------------------------------------------
# 8. South Africa eTenders (etenders.gov.za)
# ---------------------------------------------------------------------------
async def fetch_south_africa_etenders(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://www.etenders.gov.za/Home/opportunities?id=1"
    results = []
    log("South Africa", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue
                full_row = row.get_text(separator=" ", strip=True)
                title = cells[1].get_text(strip=True) if len(cells) > 2 else cells[0].get_text(strip=True)
                if len(title) < 10:
                    continue

                dates = DATE_REGEX.findall(full_row)
                deadline = dates[-1] if dates else "Refer notice"

                a_tag = row.find("a")
                link = a_tag["href"] if a_tag and a_tag.get("href") else url
                if not link.startswith("http"):
                    link = "https://www.etenders.gov.za" + link

                ref_match = re.search(r"[A-Z0-9/_-]{6,25}", full_row)
                t_id = ref_match.group(0) if ref_match else f"ZA-{title[:12]}"

                results.append(normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": "South Africa",
                    "Organisation / Portal": "National Treasury eTender",
                    "Tender ID": t_id,
                    "Tender Title": title,
                    "Tender Category": "Public Works & Infrastructure",
                    "Summary of Tender": f"South Africa National Treasury eTenders opportunity: {title}",
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("South Africa", f"Notice: {e}")
    log("South Africa", f"Retrieved {len(results)} notices.")
    return results


# ---------------------------------------------------------------------------
# 9. Tanzania NEST (nest.go.tz)
# ---------------------------------------------------------------------------
async def fetch_tanzania_nest(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://nest.go.tz"
    results = []
    log("Tanzania NEST", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.find_all(["div", "tr"], class_=re.compile(r"tender|procurement|notice"))
            for item in items:
                title_elem = item.find(["a", "h4", "h5", "td"])
                if not title_elem:
                    continue
                title = title_elem.get_text(strip=True)
                if len(title) < 10:
                    continue
                full_text = item.get_text(separator=" ", strip=True)
                dates = DATE_REGEX.findall(full_text)
                deadline = dates[-1] if dates else "Refer notice"

                results.append(normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": "Tanzania",
                    "Organisation / Portal": "National e-Procurement (NEST)",
                    "Tender ID": f"TZ-{title[:12]}",
                    "Tender Title": title,
                    "Tender Category": "Works / Consultancy",
                    "Summary of Tender": f"Tanzania Public Procurement Regulatory Authority (PPRA) notice: {title}",
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": url,
                }))
    except Exception as e:
        log("Tanzania NEST", f"Notice: {e}")
    log("Tanzania NEST", f"Retrieved {len(results)} notices.")
    return results


# ---------------------------------------------------------------------------
# 10. UN Global Marketplace (UNGM)
# ---------------------------------------------------------------------------
async def fetch_ungm(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://www.ungm.org/Public/Notice/Search"
    results = []
    log("UNGM", "Fetching public notices...")
    payload = {
        "PageIndex": 0,
        "PageSize": 60,
        "SortField": "DatePublished",
        "SortAscending": False,
    }
    try:
        r = await client.post(
            url,
            json=payload,
            headers={**HTTP_HEADERS, "Content-Type": "application/json"},
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            items = data.get("Items") or data.get("items") or []
            for item in items:
                title = (item.get("Title") or "").strip()
                if not title:
                    continue
                notice_id = str(item.get("Id") or "")
                deadline = str(item.get("Deadline") or "")[:10]
                agency = item.get("UNOrganization") or "UN Agency"
                description = (item.get("Description") or item.get("Summary") or "").strip()
                beneficiary = item.get("BeneficiaryCountries") or []
                countries = ", ".join(beneficiary) if isinstance(beneficiary, list) else str(beneficiary)

                summary = description[:280] if description else f"Procurement opportunity published by {agency} for {countries or 'Africa'}: {title}"

                results.append(normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": countries or "International / Africa",
                    "Organisation / Portal": f"UNGM - {agency}",
                    "Tender ID": f"UNGM-{notice_id}",
                    "Tender Title": title,
                    "Tender Category": item.get("TypeName") or "Consultancy / Works",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer notice",
                    "Bid Submission Date": deadline or "Refer notice",
                    "Portal Link": f"https://www.ungm.org/Public/Notice/{notice_id}" if notice_id else "https://www.ungm.org",
                }))
    except Exception as e:
        log("UNGM", f"Notice: {e}")
    log("UNGM", f"Retrieved {len(results)} notices.")
    return results


# ---------------------------------------------------------------------------
# 11. African Development Bank (AfDB)
# ---------------------------------------------------------------------------
async def fetch_afdb(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://www.afdb.org/en/projects-and-operations/procurement"
    results = []
    log("AfDB", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.find_all("tr")
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
                link = a_tag["href"]
                if not link.startswith("http"):
                    link = "https://www.afdb.org" + link

                row_text = row.get_text(separator=" ", strip=True)
                dates = DATE_REGEX.findall(row_text)
                deadline = dates[-1] if dates else "Refer notice"

                summary = f"AfDB development and project procurement opportunity: {title}"

                results.append(normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": "Multilateral / Africa",
                    "Organisation / Portal": "African Development Bank (AfDB)",
                    "Tender ID": f"AfDB-{title[:14]}",
                    "Tender Title": title,
                    "Tender Category": "Development Projects & Infrastructure",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                }))
    except Exception as e:
        log("AfDB", f"Notice: {e}")
    log("AfDB", f"Retrieved {len(results)} notices.")
    return results


# ---------------------------------------------------------------------------
# Sync Engine: Google Sheets ('Africa' worksheet) + CSV Backup
# ---------------------------------------------------------------------------
def sync_records(tenders: List[Dict]) -> None:
    if not tenders:
        print("\n[Sync Engine] No records found.")
        return

    df = pd.DataFrame(tenders)
    df.drop_duplicates(subset=["Tender ID"], inplace=True)

    creds_json = os.environ.get("GCP_CREDENTIALS")
    if creds_json:
        try:
            import gspread
            from google.oauth2.service_account import Credentials

            creds_dict = json.loads(creds_json)
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
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
                print("=" * 65)
                print(f" SUCCESS: Added {len(new_entries)} new tenders into tab '{WORKSHEET_NAME}'!")
                print("=" * 65)
            else:
                print(f"\n[Google Sheets] Tab '{WORKSHEET_NAME}' is already up to date.")
        except Exception as e:
            print(f"\n[Google Sheets Error] {e}")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_csv = OUTPUT_DIR / f"africa_tenders_{timestamp}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n[Local Backup] Saved copy of {len(df)} notices to: {out_csv}")


# ---------------------------------------------------------------------------
# Main Routine
# ---------------------------------------------------------------------------
async def main():
    print("=" * 65)
    print(" STARTING COMPLETE AFRICA PROCUREMENT TRACKER")
    print("=" * 65)

    all_notices: List[Dict] = []
    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        tasks = [
            fetch_african_union(client),
            fetch_trademark_africa(client),
            fetch_kenya_kura(client),
            fetch_kenya_kenha(client),
            fetch_kenya_ppip(client),
            fetch_uganda_ppda(client),
            fetch_ethiopia_egp(client),
            fetch_south_africa_etenders(client),
            fetch_tanzania_nest(client),
            fetch_ungm(client),
            fetch_afdb(client),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                all_notices.extend(res)

    sync_records(all_notices)


if __name__ == "__main__":
    asyncio.run(main())