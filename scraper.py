"""
Global Transport Consulting Tender Tracker
Covers: Africa (AU, TMA, KeNHA, KURA, AfDB) + South Asia (Nepal, Bhutan, Sri Lanka)
        + Mauritius + Multilateral (ADB CSRN, UNGM, GIZ / KfW).
Outputs directly to the 'Africa' worksheet of the 'Tender Tracker' Google Sheet.
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
# Verification & Exclusions
# ---------------------------------------------------------------------------

STRICT_EXCLUSIONS = [
    "avocado", "packhouse", "packing line", "grading line", "agro", "agriculture",
    "fisheries", "fishery", "fish", "livestock", "horticulture", "farmer",
    "legal and regulatory review", "business process review", "customs process",
    "hotel", "catering", "accommodation", "cleaning", "security guard",
    "stationery", "medical", "pharmaceutical", "health sector", "laundry",
    "fertilizer", "seed supply", "irrigation system", "school supply", "uniform"
]

TRANSPORT_DOMAINS = [
    r"\broad\b", r"\broads\b", r"\bhighway\b", r"\bhighways\b", r"\bexpressway\b",
    r"\bdual carriageway\b", r"\bpavement\b", r"\bbridge\b", r"\bbridges\b",
    r"\bflyover\b", r"\bviaduct\b", r"\binterchange\b", r"\btunnel\b",
    r"\btransit\b", r"\bbrt\b", r"\bbus rapid transit\b", r"\burban mobility\b",
    r"\bbuses\b", r"\be-bus\b", r"\blight rail\b", r"\bmetro\b", r"\btram\b",
    r"\brail\b", r"\brailway\b", r"\brailways\b", r"\blocomotive\b", r"\brolling stock\b",
    r"\bport\b", r"\bports\b", r"\bmaritime\b", r"\bharbour\b", r"\bjetty\b",
    r"\bairport\b", r"\brunway\b", r"\baviation\b",
    r"\btraffic\b", r"\bits\b", r"\bintelligent transport\b", r"\btolling\b",
    r"\btransport planning\b", r"\bfeeder road\b"
]

CONSULTING_HINTS = [
    r"\bconsult\w*\b", r"\badvisory\b", r"\bfeasibility\b", r"\bdesign\b",
    r"\bsupervision\b", r"\btechnical assistance\b", r"\bstudy\b", r"\bmaster plan\b",
    r"\bplanning\b", r"\btransaction advisory\b", r"\besia\b", r"\baudit\b",
    r"\bengineering\b", r"\bassessment\b", r"\bsurvey\b"
]


def is_active_date(date_str: str) -> bool:
    """Accepts notices unless their date is explicitly in the past."""
    if not date_str or "refer" in date_str.lower() or "tbd" in date_str.lower():
        return True
    clean_date = re.sub(r"[^\w\s-]", "", date_str.split()[0]).strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            parsed = datetime.strptime(clean_date, fmt).date()
            return parsed >= TODAY
        except ValueError:
            continue
    return True


def is_transport_consultancy(title: str, summary: str, category: str, is_transport_org: bool = False) -> bool:
    """
    Evaluates whether a tender belongs to transport consulting.
    If issued by a transport authority (e.g., KeNHA, KURA), consultancy hints qualify it directly.
    """
    text_corpus = f"{title} {summary} {category}".lower()

    if any(ex in text_corpus for ex in STRICT_EXCLUSIONS):
        return False

    has_consulting = any(re.search(p, text_corpus) for p in CONSULTING_HINTS)
    if is_transport_org:
        return has_consulting or "works" in text_corpus or "tender" in text_corpus

    has_transport = any(re.search(p, text_corpus) for p in TRANSPORT_DOMAINS)
    return has_transport and has_consulting


def clean_summary_text(raw_text: str, fallback_title: str) -> str:
    clean = re.sub(r"\s+", " ", raw_text).strip()
    clean = re.sub(r"(Tender Notice|Advert|Description|Scope of Work|Overview)[:\s]*", "", clean, flags=re.IGNORECASE)
    if len(clean) > 40:
        return f"Scope of Assignment: {clean[:340]}..."
    return f"Scope of Assignment: Transport consulting, design, and advisory services for {fallback_title}."


def normalise_item(item: Dict) -> Dict:
    return {h: item.get(h, "") for h in HEADERS}


def log(portal: str, msg: str) -> None:
    print(f"[{portal}] {msg}")


# ---------------------------------------------------------------------------
# African Portals
# ---------------------------------------------------------------------------

async def fetch_african_union(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://au.int/en/bids"
    results = []
    log("African Union", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=25)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for item in soup.find_all("div", class_=re.compile(r"views-row|item-list")):
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
                summary = clean_summary_text(full_text, title)

                if is_transport_consultancy(title, summary, "Advisory"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "Pan-Africa",
                        "Organisation / Portal": "African Union Commission",
                        "Tender ID": t_id,
                        "Tender Title": title,
                        "Tender Category": "Transport Strategy & Advisory",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
    except Exception as e:
        log("African Union", f"Notice: {e}")
    log("African Union", f"Retrieved {len(results)} valid notices.")
    return results


async def fetch_trademark_africa(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://www.trademarkafrica.com/procurement/"
    results = []
    log("TradeMark Africa", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=25)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for card in soup.find_all(["div", "article"], class_=re.compile(r"procurement|tender|post")):
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
                summary = clean_summary_text(card_text, title)

                if is_transport_consultancy(title, summary, "Consulting"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "East & Horn of Africa",
                        "Organisation / Portal": "TradeMark Africa",
                        "Tender ID": t_id,
                        "Tender Title": title,
                        "Tender Category": "Transport & Logistics Consulting",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
    except Exception as e:
        log("TradeMark Africa", f"Notice: {e}")
    log("TradeMark Africa", f"Retrieved {len(results)} valid notices.")
    return results


async def fetch_kenya_roads(client: httpx.AsyncClient) -> List[Dict]:
    sources = [
        ("https://kura.go.ke/cat_doc/tender-notice/", "Kenya Urban Roads Authority (KURA)", "Urban Transport Consulting"),
        ("https://kenha.co.ke/tenders/", "Kenya National Highways Authority (KeNHA)", "Highway Engineering & Supervision")
    ]
    results = []
    for url, org, cat in sources:
        log(org, "Checking notices...")
        try:
            r = await client.get(url, headers=HTTP_HEADERS, timeout=25)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for row in soup.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) < 2:
                        continue
                    row_text = row.get_text(separator=" ", strip=True)
                    link_tag = row.find("a")
                    title = cells[1].get_text(strip=True) if len(cells) > 1 else cells[0].get_text(strip=True)
                    if len(title) < 10 or "s.no" in title.lower():
                        continue

                    dates = DATE_REGEX.findall(row_text)
                    deadline = dates[-1] if dates else "Refer notice"
                    if not is_active_date(deadline):
                        continue

                    link = link_tag["href"] if link_tag and link_tag.get("href") else url
                    if not link.startswith("http"):
                        link = ("https://kura.go.ke" if "kura" in url else "https://kenha.co.ke") + link

                    t_id_match = re.search(r"(KURA|KeNHA)/[A-Z0-9/_-]+", row_text)
                    t_id = t_id_match.group(0) if t_id_match else f"KE-{title[:12]}"
                    summary = clean_summary_text(row_text, title)

                    if is_transport_consultancy(title, summary, cat, is_transport_org=True):
                        results.append(normalise_item({
                            "Date Found": TODAY.strftime("%Y-%m-%d"),
                            "Country / Region": "Kenya",
                            "Organisation / Portal": org,
                            "Tender ID": t_id,
                            "Tender Title": title,
                            "Tender Category": cat,
                            "Summary of Tender": summary,
                            "Pre-bid Meeting Date": "Refer document",
                            "Bid Submission Date": deadline,
                            "Portal Link": link,
                        }))
        except Exception as e:
            log(org, f"Notice: {e}")
        log(org, f"Retrieved {len(results)} valid notices.")
    return results


async def fetch_afdb(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://www.afdb.org/en/projects-and-operations/procurement"
    results = []
    log("AfDB", "Connecting...")
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=25)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for row in soup.find_all("tr"):
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
                if not is_active_date(deadline):
                    continue

                link = a_tag["href"]
                if not link.startswith("http"):
                    link = "https://www.afdb.org" + link

                summary = clean_summary_text(row_text, title)

                if is_transport_consultancy(title, summary, "Technical Assistance"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "Multilateral / Africa",
                        "Organisation / Portal": "African Development Bank (AfDB)",
                        "Tender ID": f"AfDB-{title[:14]}",
                        "Tender Title": title,
                        "Tender Category": "Transport Sector Consulting",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
    except Exception as e:
        log("AfDB", f"Notice: {e}")
    log("AfDB", f"Retrieved {len(results)} valid notices.")
    return results


# ---------------------------------------------------------------------------
# Multilateral Portals: ADB, GIZ, KfW, UNGM
# ---------------------------------------------------------------------------

async def fetch_adb(client: httpx.AsyncClient) -> List[Dict]:
    """Asian Development Bank (CSRN & Projects API)"""
    log("ADB", "Fetching consulting opportunities...")
    results = []
    url = "https://www.adb.org/projects/tenders"
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=25)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for item in soup.find_all(["div", "li"], class_=re.compile(r"item|views-row|search-result")):
                a_tag = item.find("a")
                if not a_tag or not a_tag.get("href"):
                    continue
                title = re.sub(r"\s+", " ", a_tag.get_text(strip=True))
                if len(title) < 10:
                    continue

                item_text = item.get_text(separator=" ", strip=True)
                dates = DATE_REGEX.findall(item_text)
                deadline = dates[-1] if dates else "Refer notice"
                if not is_active_date(deadline):
                    continue

                link = a_tag["href"]
                if not link.startswith("http"):
                    link = "https://www.adb.org" + link

                summary = clean_summary_text(item_text, title)

                if is_transport_consultancy(title, summary, "Consulting Services"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "Asia-Pacific",
                        "Organisation / Portal": "Asian Development Bank (ADB)",
                        "Tender ID": f"ADB-{title[:12]}",
                        "Tender Title": title,
                        "Tender Category": "Transport Technical Assistance",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer CSRN portal",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
    except Exception as e:
        log("ADB", f"Notice: {e}")
    log("ADB", f"Retrieved {len(results)} valid notices.")
    return results


async def fetch_ungm(client: httpx.AsyncClient) -> List[Dict]:
    url = "https://www.ungm.org/Public/Notice/Search"
    results = []
    log("UNGM", "Fetching notices...")
    payload = {
        "PageIndex": 0,
        "PageSize": 60,
        "SortField": "DatePublished",
        "SortAscending": False,
    }
    try:
        r = await client.post(url, json=payload, headers={**HTTP_HEADERS, "Content-Type": "application/json"}, timeout=25)
        if r.status_code == 200:
            data = r.json()
            for item in (data.get("Items") or []):
                title = (item.get("Title") or "").strip()
                deadline = str(item.get("Deadline") or "")[:10]
                if not title or not is_active_date(deadline):
                    continue

                agency = item.get("UNOrganization") or "UN Agency"
                desc = (item.get("Description") or item.get("Summary") or "").strip()
                countries = ", ".join(item.get("BeneficiaryCountries") or []) or "International / Regional"
                summary = clean_summary_text(desc if desc else title, title)

                if is_transport_consultancy(title, summary, item.get("TypeName") or "Consultancy"):
                    notice_id = str(item.get("Id") or "")
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": countries,
                        "Organisation / Portal": f"UNGM - {agency}",
                        "Tender ID": f"UNGM-{notice_id}",
                        "Tender Title": title,
                        "Tender Category": "Transport Advisory / Consulting",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer notice",
                        "Bid Submission Date": deadline,
                        "Portal Link": f"https://www.ungm.org/Public/Notice/{notice_id}" if notice_id else "https://www.ungm.org",
                    }))
    except Exception as e:
        log("UNGM", f"Notice: {e}")
    log("UNGM", f"Retrieved {len(results)} valid notices.")
    return results


async def fetch_giz_kfw(client: httpx.AsyncClient) -> List[Dict]:
    log("GIZ / KfW", "Connecting to German Development Cooperation portals...")
    results = []
    giz_url = "https://ausschreibungen.giz.de/buyer/ausschreibungen.html"
    try:
        r = await client.get(giz_url, headers=HTTP_HEADERS, timeout=20)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for item in soup.find_all(["tr", "div"], class_=re.compile(r"project|tender|row")):
                row_text = item.get_text(separator=" ", strip=True)
                a_tag = item.find("a")
                title = a_tag.get_text(strip=True) if a_tag else ""
                if len(title) < 10:
                    continue

                dates = DATE_REGEX.findall(row_text)
                deadline = dates[-1] if dates else "Refer notice"
                if not is_active_date(deadline):
                    continue

                link = a_tag["href"] if a_tag and a_tag.get("href") else giz_url
                if not link.startswith("http"):
                    link = "https://ausschreibungen.giz.de" + link

                summary = clean_summary_text(row_text, title)
                if is_transport_consultancy(title, summary, "Advisory"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "Global / South Asia / Africa",
                        "Organisation / Portal": "GIZ International Services",
                        "Tender ID": f"GIZ-{title[:12]}",
                        "Tender Title": title,
                        "Tender Category": "Sustainable Transport Advisory",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": link,
                    }))
    except Exception as e:
        log("GIZ / KfW", f"Notice: {e}")
    log("GIZ / KfW", f"Retrieved {len(results)} valid notices.")
    return results


# ---------------------------------------------------------------------------
# Mauritius & South Asian Portals: Bhutan, Nepal, Sri Lanka
# ---------------------------------------------------------------------------

async def fetch_mauritius_eproc(client: httpx.AsyncClient) -> List[Dict]:
    log("Mauritius e-Procurement", "Connecting...")
    url = "https://eproc.publicprocurement.govmu.org"
    results = []
    try:
        r = await client.get(url, headers=HTTP_HEADERS, timeout=20)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for row in soup.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue
                row_text = row.get_text(separator=" ", strip=True)
                title = cells[1].get_text(strip=True) if len(cells) > 2 else ""
                dates = DATE_REGEX.findall(row_text)
                deadline = dates[-1] if dates else "Refer notice"
                if len(title) < 8 or not is_active_date(deadline):
                    continue

                summary = clean_summary_text(row_text, title)
                if is_transport_consultancy(title, summary, "Consulting"):
                    results.append(normalise_item({
                        "Date Found": TODAY.strftime("%Y-%m-%d"),
                        "Country / Region": "Mauritius",
                        "Organisation / Portal": "Mauritius e-Procurement Portal",
                        "Tender ID": f"MU-{title[:12]}",
                        "Tender Title": title,
                        "Tender Category": "Transport Consulting & Advisory",
                        "Summary of Tender": summary,
                        "Pre-bid Meeting Date": "Refer document",
                        "Bid Submission Date": deadline,
                        "Portal Link": url,
                    }))
    except Exception as e:
        log("Mauritius e-Procurement", f"Notice: {e}")
    log("Mauritius e-Procurement", f"Retrieved {len(results)} valid notices.")
    return results


async def fetch_south_asia_national(client: httpx.AsyncClient) -> List[Dict]:
    targets = [
        ("https://bolpatra.gov.np/egp/", "Nepal", "Nepal PPMO (Bolpatra)"),
        ("https://www.egp.gov.bt", "Bhutan", "Bhutan e-GP (GPPMD)"),
        ("https://promise.lk", "Sri Lanka", "Sri Lanka National Procurement (PROMISE)")
    ]
    results = []
    for url, country, org in targets:
        log(org, f"Connecting to {country} portal...")
        try:
            r = await client.get(url, headers=HTTP_HEADERS, timeout=20)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for row in soup.find_all(["tr", "div"], class_=re.compile(r"row|tender|item")):
                    row_text = row.get_text(separator=" ", strip=True)
                    a_tag = row.find("a")
                    title = a_tag.get_text(strip=True) if a_tag else ""
                    if len(title) < 10:
                        continue
                    dates = DATE_REGEX.findall(row_text)
                    deadline = dates[-1] if dates else "Refer notice"
                    if not is_active_date(deadline):
                        continue

                    link = a_tag["href"] if a_tag and a_tag.get("href") else url
                    if not link.startswith("http"):
                        link = url.rstrip("/") + "/" + link.lstrip("/")

                    summary = clean_summary_text(row_text, title)
                    if is_transport_consultancy(title, summary, "Consulting"):
                        results.append(normalise_item({
                            "Date Found": TODAY.strftime("%Y-%m-%d"),
                            "Country / Region": country,
                            "Organisation / Portal": org,
                            "Tender ID": f"{country[:2].upper()}-{title[:12]}",
                            "Tender Title": title,
                            "Tender Category": "Transport Planning & Engineering",
                            "Summary of Tender": summary,
                            "Pre-bid Meeting Date": "Refer document",
                            "Bid Submission Date": deadline,
                            "Portal Link": link,
                        }))
        except Exception as e:
            log(org, f"Notice: {e}")
        log(org, f"Retrieved {len(results)} valid notices.")
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
            # 3. Left Align & Wrap Text on Title (E) and Scope Summary (G)
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": max(total_rows, 2),
                        "startColumnIndex": 4,
                        "endColumnIndex": 5,
                    },
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT", "wrapStrategy": "WRAP"}},
                    "fields": "userEnteredFormat(horizontalAlignment,wrapStrategy)",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": max(total_rows, 2),
                        "startColumnIndex": 6,
                        "endColumnIndex": 7,
                    },
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT", "wrapStrategy": "WRAP"}},
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
            # 6. Proportional Column Sizing
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 105}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2}, "properties": {"pixelSize": 125}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3}, "properties": {"pixelSize": 190}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 4}, "properties": {"pixelSize": 140}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 4, "endIndex": 5}, "properties": {"pixelSize": 320}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 5, "endIndex": 6}, "properties": {"pixelSize": 170}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 6, "endIndex": 7}, "properties": {"pixelSize": 380}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 7, "endIndex": 8}, "properties": {"pixelSize": 130}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 8, "endIndex": 9}, "properties": {"pixelSize": 130}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 9, "endIndex": 10}, "properties": {"pixelSize": 180}, "fields": "pixelSize"}},
        ]
        sh.spreadsheet.batch_update({"requests": format_requests})
        print(f"[Format Engine] Applied formatting to '{WORKSHEET_NAME}'!")
    except Exception as e:
        print(f"[Format Notice] Layout formatting exception: {e}")


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
    out_csv = OUTPUT_DIR / f"transport_consulting_{timestamp}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n[Local Backup] Saved copy to: {out_csv}")


# ---------------------------------------------------------------------------
# Main Routine
# ---------------------------------------------------------------------------

async def main():
    print("=" * 65)
    print(" STARTING RIGOROUS TRANSPORT CONSULTING TENDER TRACKER")
    print("=" * 65)

    all_notices: List[Dict] = []
    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        tasks = [
            fetch_african_union(client),
            fetch_trademark_africa(client),
            fetch_kenya_roads(client),
            fetch_afdb(client),
            fetch_adb(client),
            fetch_ungm(client),
            fetch_giz_kfw(client),
            fetch_mauritius_eproc(client),
            fetch_south_asia_national(client),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                all_notices.extend(res)

    sync_records(all_notices)


if __name__ == "__main__":
    asyncio.run(main())
