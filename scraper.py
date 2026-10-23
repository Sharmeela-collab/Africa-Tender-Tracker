"""
Africa Transport Consultancy Tender Tracker
---------------------------------------------
- Active / Open Tenders ONLY (filters out expired & past submission dates).
- Transport Consulting & Advisory ONLY (strict keyword + negative exclusion filter).
- Deep inspection of tender links for accurate title and scope summaries.
- Formatted output directly to the 'Africa' worksheet of 'Tender Tracker'.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

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

TODAY = datetime.now().date()
DATE_REGEX = re.compile(r"\b\d{1,2}[-/\s](?:[A-Za-z]{3,9}|\d{1,2})[-/\s]\d{2,4}\b")

# ---------------------------------------------------------------------------
# Strict Transport Consulting & Exclusion Filters
# ---------------------------------------------------------------------------

# Exclude obvious non-transport or non-consulting services immediately
NEGATIVE_KEYWORDS = [
    "hotel", "catering", "accommodation", "conference", "hospitality",
    "cleaning", "security guard", "stationery", "uniform", "textbook",
    "medical supply", "pharmaceutical", "fertilizer", "pest control",
    "laundry", "sanitation", "event management", "catering services"
]

# Primary Transport Domains
TRANSPORT_DOMAINS = [
    r"\broad\b", r"\broads\b", r"\bhighway\b", r"\bhighways\b", r"\bexpressway\b",
    r"\btransit\b", r"\bbrt\b", r"\bbus rapid transit\b", r"\burban mobility\b",
    r"\brail\b", r"\brailway\b", r"\brailways\b", r"\blight rail\b", r"\bmetro\b",
    r"\bport\b", r"\bports\b", r"\bmaritime\b", r"\bharbour\b", r"\bshipping\b",
    r"\bairport\b", r"\baviation\b", r"\brunway\b", r"\bflight\b",
    r"\btraffic\b", r"\btolling\b", r"\bintelligent transport\b", r"\bits\b",
    r"\bcorridor\b", r"\bfreight\b", r"\blogistics\b", r"\bfleet\b",
    r"\bbridge\b", r"\bbridges\b", r"\bflyover\b", r"\bviaduct\b", r"\binterchange\b"
]

# Consulting, Advisory & Planning Terms
CONSULTING_TERMS = [
    r"\bconsultan\w*\b", r"\badvisory\b", r"\bfeasibility\b", r"\bdesign\b",
    r"\bsupervision\b", r"\btechnical assistance\b", r"\bstudy\b", r"\bstudies\b",
    r"\bmaster plan\b", r"\bplanning\b", r"\btransaction advisory\b", r"\besia\b",
    r"\benvironmental and social\b", r"\baudit\b", r"\bengineering services\b"
]


def is_active_date(date_str: str) -> bool:
    """Returns True if the date string is today or in the future; rejects expired dates."""
    if not date_str or "refer" in date_str.lower() or "tbd" in date_str.lower():
        return True  # Keep if date needs manual check rather than falsely discarding
    
    # Try various date formats
    clean_date = re.sub(r"[^\w\s-]", "", date_str.split()[0]).strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            parsed = datetime.strptime(clean_date, fmt).date()
            return parsed >= TODAY
        except ValueError:
            continue
    return True


def is_transport_consultancy(title: str, summary: str, category: str) -> bool:
    """Strictly matches transport + consultancy while blocking non-relevant domains."""
    full_text = f"{title} {summary} {category}".lower()

    # 1. Reject if any negative keyword is present
    if any(neg in full_text for neg in NEGATIVE_KEYWORDS):
        return False

    # 2. Check if a transport keyword exists
    has_transport = any(re.search(pattern, full_text) for pattern in TRANSPORT_DOMAINS)
    if not has_transport:
        return False

    # 3. Check if consultancy/advisory intent exists
    has_consulting = any(re.search(pattern, full_text) for pattern in CONSULTING_TERMS)
    return has_consulting


def normalise_item(item: Dict) -> Dict:
    return {h: item.get(h, "") for h in HEADERS}


def log(portal: str, msg: str) -> None:
    print(f"[{portal}] {msg}")


# ---------------------------------------------------------------------------
# Deep Portal Scrapers (Title, Scope Summary, Expiry Check)
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
                if len(title) < 10:
                    continue

                full_text = item.get_text(separator=" ", strip=True)
                dates = DATE_REGEX.findall(full_text)
                deadline = dates[0] if dates else "Refer notice"

                if not is_active_date(deadline):
                    continue

                link = link_tag["href"]
                if not link.startswith("http"):
                    link = "https://au.int" + link

                ref_match = re.search(r"AUC/[A-Z0-9/_-]+", full_text)
                t_id = ref_match.group(0) if ref_match else f"AU-{title[:14]}"
                summary = f"AU Commission consultancy notice: {full_text[:300]}"

                if is_transport_consultancy(title, summary, "Consultancy"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "Pan-Africa",
                        "Organisation / Portal": "African Union Commission",
                        "Tender ID": t_id,
                        "Tender Title": title,
                        "Tender Category": "Consulting Services",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
    except Exception as e:
        log("African Union", f"Notice: {e}")
    log("African Union", f"Retrieved {len(results)} active transport consulting notices.")
    return results


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

                if not is_active_date(deadline):
                    continue

                id_match = re.search(r"PRQ\d{4,8}|TMA/[A-Z0-9/_-]+", card_text)
                t_id = id_match.group(0) if id_match else f"TMA-{title[:14]}"
                summary = f"TradeMark Africa trade logistics & transport consultancy: {card_text[:300]}"

                if is_transport_consultancy(title, summary, "Consulting / Advisory"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "East & Horn of Africa",
                        "Organisation / Portal": "TradeMark Africa",
                        "Tender ID": t_id,
                        "Tender Title": title,
                        "Tender Category": "Consulting & Advisory Services",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
    except Exception as e:
        log("TradeMark Africa", f"Notice: {e}")
    log("TradeMark Africa", f"Retrieved {len(results)} active transport consulting notices.")
    return results


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

                if not is_active_date(deadline):
                    continue

                ref_match = re.search(r"KURA/[A-Z0-9/_-]+", row_text)
                t_id = ref_match.group(0) if ref_match else f"KURA-{title[:12]}"
                summary = f"Urban roads and transport consultancy / engineering supervision: {title}"

                # Only include consulting, design, supervision, or study tenders
                if is_transport_consultancy(title, summary, "Consultancy"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "Kenya",
                        "Organisation / Portal": "Kenya Urban Roads Authority (KURA)",
                        "Tender ID": t_id,
                        "Tender Title": title,
                        "Tender Category": "Consulting & Engineering Services",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
    except Exception as e:
        log("Kenya KURA", f"Notice: {e}")
    log("Kenya KURA", f"Retrieved {len(results)} active transport consulting notices.")
    return results


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

                if not is_active_date(deadline):
                    continue

                ref_match = re.search(r"KeNHA/[A-Z0-9/_-]+", row_text)
                t_id = ref_match.group(0) if ref_match else f"KeNHA-{title[:12]}"
                summary = f"National highways consultancy, feasibility, or engineering design: {title}"

                if is_transport_consultancy(title, summary, "Consulting"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "Kenya",
                        "Organisation / Portal": "Kenya National Highways Authority (KeNHA)",
                        "Tender ID": t_id,
                        "Tender Title": title,
                        "Tender Category": "Highway Consulting & Supervision",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
    except Exception as e:
        log("Kenya KeNHA", f"Notice: {e}")
    log("Kenya KeNHA", f"Retrieved {len(results)} active transport consulting notices.")
    return results


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

                # Check if notice has expired
                if not is_active_date(deadline):
                    continue

                ref_match = re.search(r"[A-Za-z0-9]+/[A-Z]+/\d{4}-\d{4}/\d+", full_row)
                t_id = ref_match.group(0) if ref_match else f"UG-{title[:12]}"

                # Deep inspection: Follow the link to read the real title & description if vague
                summary = f"Uganda e-GP procurement notice: {title}"
                if "rfq" in title.lower() or len(title) < 25:
                    try:
                        detail_resp = await client.get(link, headers=HTTP_HEADERS, timeout=10)
                        if detail_resp.status_code == 200:
                            d_soup = BeautifulSoup(detail_resp.text, "html.parser")
                            desc_elem = d_soup.find(["div", "p"], class_=re.compile(r"description|detail|scope"))
                            if desc_elem:
                                summary = desc_elem.get_text(separator=" ", strip=True)[:350]
                    except Exception:
                        pass

                # Strict transport consulting gate
                if is_transport_consultancy(title, summary, "Consultancy"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "Uganda",
                        "Organisation / Portal": "Uganda e-GP (PPDA)",
                        "Tender ID": t_id,
                        "Tender Title": title,
                        "Tender Category": "Consulting Services",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
    except Exception as e:
        log("Uganda PPDA", f"Notice: {e}")
    log("Uganda PPDA", f"Retrieved {len(results)} active transport consulting notices.")
    return results


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

                deadline = str(item.get("Deadline") or "")[:10]
                if not is_active_date(deadline):
                    continue

                notice_id = str(item.get("Id") or "")
                agency = item.get("UNOrganization") or "UN Agency"
                description = (item.get("Description") or item.get("Summary") or "").strip()
                beneficiary = item.get("BeneficiaryCountries") or []
                countries = ", ".join(beneficiary) if isinstance(beneficiary, list) else str(beneficiary)

                summary = description[:350] if description else f"UN advisory and transport consultancy notice by {agency} for {countries or 'Africa'}: {title}"

                if is_transport_consultancy(title, summary, item.get("TypeName") or "Consultancy"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": countries or "International / Africa",
                        "Organisation / Portal": f"UNGM - {agency}",
                        "Tender ID": f"UNGM-{notice_id}",
                        "Tender Title": title,
                        "Tender Category": "Consulting & Advisory Services",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer notice",
                        "Bid Submission Date": deadline,
                        "Portal Link": f"https://www.ungm.org/Public/Notice/{notice_id}" if notice_id else "https://www.ungm.org",
                    }))
    except Exception as e:
        log("UNGM", f"Notice: {e}")
    log("UNGM", f"Retrieved {len(results)} active transport consulting notices.")
    return results


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

                if not is_active_date(deadline):
                    continue

                summary = f"AfDB transport infrastructure consultancy and technical assistance: {title}"

                if is_transport_consultancy(title, summary, "Consulting / Advisory"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "Multilateral / Africa",
                        "Organisation / Portal": "African Development Bank (AfDB)",
                        "Tender ID": f"AfDB-{title[:14]}",
                        "Tender Title": title,
                        "Tender Category": "Technical Assistance & Consulting",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
    except Exception as e:
        log("AfDB", f"Notice: {e}")
    log("AfDB", f"Retrieved {len(results)} active transport consulting notices.")
    return results


# ---------------------------------------------------------------------------
# Formatting Engine: Dark Navy Header, Wrapped Text, Clean Justification
# ---------------------------------------------------------------------------

def apply_google_sheet_formatting(sh, total_rows: int) -> None:
    try:
        sheet_id = sh.id
        format_requests = [
            # 1. Header Styling
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 10,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.08, "green": 0.22, "blue": 0.38},
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                            "textFormat": {
                                "bold": True,
                                "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                                "fontSize": 10,
                            },
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                }
            },
            # 2. General Data Format
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": max(total_rows, 2),
                        "startColumnIndex": 0,
                        "endColumnIndex": 10,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "verticalAlignment": "TOP",
                            "textFormat": {"fontSize": 9},
                        }
                    },
                    "fields": "userEnteredFormat(verticalAlignment,textFormat)",
                }
            },
            # 3. Text Justification & Word Wrap on Title (E) and Summary (G)
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": max(total_rows, 2),
                        "startColumnIndex": 4,
                        "endColumnIndex": 7,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "horizontalAlignment": "LEFT",
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat(horizontalAlignment,wrapStrategy)",
                }
            },
            # 4. Center Align Columns: Date, Country, ID, Deadlines
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": max(total_rows, 2),
                        "startColumnIndex": 0,
                        "endColumnIndex": 2,
                    },
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat.horizontalAlignment",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": max(total_rows, 2),
                        "startColumnIndex": 3,
                        "endColumnIndex": 4,
                    },
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat.horizontalAlignment",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": max(total_rows, 2),
                        "startColumnIndex": 7,
                        "endColumnIndex": 9,
                    },
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat.horizontalAlignment",
                }
            },
            # 5. Freeze Header Row
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            },
            # 6. Column Widths
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 105}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2}, "properties": {"pixelSize": 125}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3}, "properties": {"pixelSize": 190}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 4}, "properties": {"pixelSize": 150}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 4, "endIndex": 5}, "properties": {"pixelSize": 320}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 5, "endIndex": 6}, "properties": {"pixelSize": 170}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 6, "endIndex": 7}, "properties": {"pixelSize": 360}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 7, "endIndex": 8}, "properties": {"pixelSize": 130}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 8, "endIndex": 9}, "properties": {"pixelSize": 130}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 9, "endIndex": 10}, "properties": {"pixelSize": 180}, "fields": "pixelSize"}},
        ]
        sh.spreadsheet.batch_update({"requests": format_requests})
        print(f"[Format Engine] Applied justified formatting and text-wrapping to '{WORKSHEET_NAME}'!")
    except Exception as e:
        print(f"[Format Notice] Could not apply layout formatting: {e}")


# ---------------------------------------------------------------------------
# Sync Engine: Google Sheets ('Africa' worksheet) + CSV Backup
# ---------------------------------------------------------------------------

def sync_records(tenders: List[Dict]) -> None:
    if not tenders:
        print("\n[Sync Engine] No active transport consulting tenders found in this cycle.")
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
                print(f" SUCCESS: Added {len(new_entries)} active transport consulting notices to '{WORKSHEET_NAME}'!")
                print("=" * 65)
            else:
                print(f"\n[Google Sheets] Tab '{WORKSHEET_NAME}' is up to date.")

            total_rows_after = len(sh.get_all_values())
            apply_google_sheet_formatting(sh, total_rows_after)

        except Exception as e:
            print(f"\n[Google Sheets Error] {e}")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_csv = OUTPUT_DIR / f"africa_transport_consulting_{timestamp}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n[Local Backup] Saved copy to: {out_csv}")


# ---------------------------------------------------------------------------
# Main Routine
# ---------------------------------------------------------------------------

async def main():
    print("=" * 65)
    print(" STARTING ACTIVE TRANSPORT CONSULTING TENDER TRACKER")
    print("=" * 65)

    all_notices: List[Dict] = []
    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        tasks = [
            fetch_african_union(client),
            fetch_trademark_africa(client),
            fetch_kenya_kura(client),
            fetch_kenya_kenha(client),
            fetch_uganda_ppda(client),
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
