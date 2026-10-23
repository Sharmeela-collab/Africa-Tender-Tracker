"""
Africa & Multilateral Procurement Portal Tracker (Transport Industry Only)
Filters specifically for roads, transit, highways, ports, railways, logistics,
traffic, fleet, and mobility-related projects.
Syncs matching notices to the 'Africa' tab of 'Tender Tracker'.
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

# ---------------------------------------------------------------------------
# TRANSPORT INDUSTRY FILTER
# ---------------------------------------------------------------------------

TRANSPORT_KEYWORDS = [
    # Roadways & Pavements
    "road", "roads", "highway", "highways", "pavement", "asphalt", "bitumen",
    "dual carriageway", "expressway", "feeder road", "culvert", "drainage",
    
    # Structures & Crossings
    "bridge", "bridges", "flyover", "viaduct", "interchange", "tunnel",
    
    # Public & Urban Mobility
    "transport", "transportation", "transit", "bus", "buses", "brt", 
    "mass rapid transit", "metro", "light rail", "tram", "mobility",
    
    # Rail & Freight
    "rail", "railway", "railroad", "locomotive", "track", "rolling stock",
    
    # Maritime & Aviation
    "port", "ports", "harbour", "harbor", "maritime", "dock", "jetty",
    "airport", "runway", "airfield", "aviation",
    
    # Traffic, Vehicles & Logistics
    "traffic", "its", "toll", "tolling", "fleet", "vehicle", "vehicles",
    "corridor", "logistics", "freight", "cargo", "signalling", "pedestrian"
]

def is_transport_related(item: Dict) -> bool:
    """Checks if any transport-related term is present in Title, Summary, or Category."""
    search_text = f"{item.get('Tender Title', '')} {item.get('Summary of Tender', '')} {item.get('Tender Category', '')}".lower()
    for kw in TRANSPORT_KEYWORDS:
        # Use regex boundary matching so 'port' matches 'sea port' but not 'opportunity'
        if re.search(rf"\b{re.escape(kw)}\b", search_text):
            return True
    return False

def normalise_item(item: Dict) -> Dict:
    return {h: item.get(h, "") for h in HEADERS}

def log(portal: str, msg: str) -> None:
    print(f"[{portal}] {msg}")


# ---------------------------------------------------------------------------
# PORTAL FETCHERS
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

                entry = normalise_item({
                    "Date Found": TODAY,
                    "Country / Region": "Pan-Africa",
                    "Organisation / Portal": "African Union Commission",
                    "Tender ID": t_id,
                    "Tender Title": title,
                    "Tender Category": "Advisory / Infrastructure / Transport",
                    "Summary of Tender": summary,
                    "Pre-bid Meeting Date": "Refer document",
                    "Bid Submission Date": deadline,
                    "Portal Link": link,
                })
                if is_transport_related(entry):
                    results.append(entry)
    except Exception as e:
        log("African Union", f"Notice: {e}")
    log("African Union", f"Retrieved {len(results)} transport notices.")
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

                id_match = re.search(r"PRQ\d{4,8}|TMA/[A-Z0-9/_-]+", card_text)
                t_id = id_match.group(0) if id_match else f"TMA-{title[:14]}"
                summary = card_text[:280] + ("..." if len(card_text) > 280 else "")

                entry = normalise_item({
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
                })
                if is_transport_related(entry):
                    results.append(entry)
    except Exception as e:
        log("TradeMark Africa", f"Notice: {e}")
    log("TradeMark Africa", f"Retrieved {len(results)} transport notices.")
    return results


async def fetch_kenya_kura(client: httpx.AsyncClient) -> List[Dict]:
    """KURA tenders are inherently transport/road focused."""
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
