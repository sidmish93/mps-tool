"""Pull NSE public shareholding, listing dates, and closes, then apply the rules.

Shareholding comes from the filings table on
nseindia.com/companies-listing/corporate-filings-shareholding-pattern.
The share count and the public-sector flag come from the filing's own XBRL.
The close comes from the NSE cash bhavcopy.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

from rules import assess

HOME = "https://www.nseindia.com/"
ARCHIVE = "https://nsearchives.nseindia.com/"
SHP = HOME + "api/corporate-share-holdings-master"
INDEX = HOME + "api/NextApi/apiClient/marketWatchApi"
EQUITY_LIST = ARCHIVE + "content/equities/EQUITY_L.csv"
HDR = {
    "Accept": "application/json, text/plain, */*",
    "Referer": HOME + "companies-listing/corporate-filings-shareholding-pattern",
}
PSU_INDEXES = ("NIFTY PSE", "NIFTY CPSE", "NIFTY PSU BANK")
PRICE_SERIES = ("EQ", "BE", "BZ", "SM")
HISTORY_START = date(2023, 1, 1)
CACHE_PATH = Path(__file__).resolve().parent / "output" / "xbrl_cache.json"

_MONTHS = {name: i for i, name in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


class Cancelled(Exception):
    pass


def parse_nse_date(value):
    if not value:
        return None
    token = str(value).strip().split()[0]
    parts = token.split("-")
    if len(parts) != 3:
        return None
    month = _MONTHS.get(parts[1].upper()[:3])
    if month is None:
        return None
    try:
        return date(int(parts[2]), month, int(parts[0]))
    except ValueError:
        return None


def _num(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in ("", "-", "NA", "None"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _check(cancel):
    if cancel and cancel():
        raise Cancelled()


class Nse:
    def __init__(self):
        self.session = None

    def _open(self):
        from curl_cffi import requests as chrome
        self.session = chrome.Session(impersonate="chrome")
        self.session.get(HOME, timeout=40)

    def get(self, url, params=None, headers=None, timeout=90, accept_status=()):
        last = None
        for _ in range(3):
            try:
                if self.session is None:
                    self._open()
                response = self.session.get(
                    url, params=params, headers=headers or HDR, timeout=timeout)
            except Exception as exc:
                self.session = None
                last = exc
                continue
            if response.status_code in (401, 403, 429):
                self.session = None
                last = RuntimeError(f"NSE returned {response.status_code} for {url}")
                continue
            if response.status_code in accept_status:
                return response
            try:
                response.raise_for_status()
            except Exception as exc:
                last = exc
                self.session = None
                continue
            return response
        raise last


def _chunks(start: date, end: date, days: int = 120):
    cursor = start
    while cursor <= end:
        stop = min(end, cursor + timedelta(days=days - 1))
        yield cursor, stop
        cursor = stop + timedelta(days=1)


def _dmy(day: date) -> str:
    return day.strftime("%d-%m-%Y")


def fetch_filings(nse: Nse, today: date, progress, cancel):
    """Latest submitted row per symbol and as-of date, for the main board."""
    kept = {}
    for start, stop in _chunks(HISTORY_START, today):
        _check(cancel)
        progress(f"Reading shareholding filings {_dmy(start)} to {_dmy(stop)}.")
        response = nse.get(SHP, params={
            "index": "equities",
            "from_date": _dmy(start),
            "to_date": _dmy(stop),
        }, timeout=180)
        rows = response.json()
        if not isinstance(rows, list):
            raise RuntimeError("NSE did not return a shareholding list.")
        for row in rows:
            symbol = (row.get("symbol") or "").strip().upper()
            as_of = parse_nse_date(row.get("date"))
            public = _num(row.get("public_val"))
            submitted = parse_nse_date(row.get("submissionDate"))
            if not symbol or as_of is None or public is None or submitted is None:
                continue
            slot = kept.setdefault(symbol, {})
            try:
                record = int(row.get("recordId") or 0)
            except (TypeError, ValueError):
                record = 0
            current = slot.get(as_of)
            # A revised filing has a later submission date. recordId breaks a tie.
            if current and (current["_submitted"], current["_record"]) >= (submitted, record):
                continue
            slot[as_of] = {
                "_submitted": submitted,
                "_record": record,
                "as_of": as_of,
                "public": public,
                "promoter": _num(row.get("pr_and_prgrp")),
                "employee": _num(row.get("employeeTrusts")),
                "name": (row.get("name") or symbol).strip(),
                "isin": (row.get("isin") or "").strip(),
                "xbrl": row.get("xbrl") or "",
            }
    return kept


def fetch_listings(nse: Nse):
    response = nse.get(EQUITY_LIST, headers={"Accept": "text/csv,*/*"}, timeout=60)
    text = response.content.decode("utf-8-sig", "replace")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames:
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
    found = {}
    for row in reader:
        symbol = (row.get("SYMBOL") or "").strip().upper()
        series = (row.get("SERIES") or "").strip().upper()
        listed = parse_nse_date(row.get("DATE OF LISTING"))
        if not symbol or listed is None:
            continue
        if symbol in found and found[symbol]["series"] == "EQ":
            continue
        if series == "EQ" or symbol not in found:
            found[symbol] = {"listing": listed, "series": series}
    return found


def fetch_psu_and_freefloat(nse: Nse, progress, cancel):
    psu = set()
    freefloat = {}
    headers = {"Accept": "application/json", "Referer": HOME + "market-data/live-equity-market"}
    for name in PSU_INDEXES:
        _check(cancel)
        progress(f"Reading {name} for public-sector names.")
        payload = nse.get(INDEX, params={"functionName": "getIndicesData", "symbol": name},
                          headers=headers).json()
        for row in ((payload.get("data") or {}).get("data") or []):
            if row.get("series") and row.get("symbol"):
                psu.add(row["symbol"].strip().upper())
    _check(cancel)
    progress("Reading free-float market caps.")
    payload = nse.get(
        INDEX, params={"functionName": "getIndicesData", "symbol": "NIFTY TOTAL MKT"},
        headers=headers, timeout=120).json()
    for row in ((payload.get("data") or {}).get("data") or []):
        symbol = (row.get("symbol") or "").strip().upper()
        ffmc = _num(row.get("ffmc"))
        if row.get("series") and symbol and ffmc and ffmc > 0:
            freefloat[symbol] = ffmc
    return psu, freefloat


def fetch_prices(nse: Nse, today: date, progress, cancel):
    """Newest close per symbol, walking back across recent cash bhavcopies."""
    chosen = {}
    newest = None
    for offset in range(0, 8):
        _check(cancel)
        day = today - timedelta(days=offset)
        url = (ARCHIVE + "content/cm/BhavCopy_NSE_CM_0_0_0_"
               + day.strftime("%Y%m%d") + "_F_0000.csv.zip")
        response = nse.get(url, headers={"Accept": "*/*"}, timeout=60,
                           accept_status=(404,))
        if response.status_code == 404:
            continue
        if newest is None:
            newest = day
        progress(f"Reading the {day.isoformat()} close.")
        try:
            archive = zipfile.ZipFile(io.BytesIO(response.content))
            name = archive.namelist()[0]
            text = archive.read(name).decode("utf-8-sig", "replace")
        except (zipfile.BadZipFile, IndexError, KeyError):
            continue
        for row in csv.DictReader(io.StringIO(text)):
            if (row.get("FinInstrmTp") or "").upper() != "STK":
                continue
            series = (row.get("SctySrs") or "").upper()
            if series not in PRICE_SERIES:
                continue
            symbol = (row.get("TckrSymb") or "").strip().upper()
            price = _num(row.get("ClsPric"))
            if not symbol or not price or price <= 0:
                continue
            rank = PRICE_SERIES.index(series)
            held = chosen.get(symbol)
            if held is None or rank < held[0]:
                chosen[symbol] = (rank, price, day)
    return {symbol: (price, day) for symbol, (_rank, price, day) in chosen.items()}, newest


def _local(tag):
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def parse_xbrl(payload: bytes):
    """Share count of the SCRR total, and the public-sector flag, from one filing."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(payload)
    members = {}
    for element in root.iter():
        if _local(element.tag) != "context":
            continue
        member = ""
        for child in element.iter():
            if _local(child.tag) == "explicitMember" and child.text:
                member = child.text.strip()
                break
        members[element.attrib.get("id")] = member
    shares = None
    psu = None
    for element in root.iter():
        name = _local(element.tag)
        if name == "WhetherTheListedEntityIsPublicSectorUndertaking" and element.text:
            psu = element.text.strip().lower() in ("true", "yes", "1")
        elif name == "NumberOfShares":
            context = element.attrib.get("contextRef") or ""
            if not context.endswith("_ContextI"):
                continue
            if not members.get(context, "").endswith("ShareholdingPatternMember"):
                continue
            parsed = _num(element.text)
            if parsed and parsed > 0:
                shares = int(parsed)
    return shares, psu


def _load_cache():
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")


def _xbrl_facts(nse: Nse, url: str, cache: dict):
    if url in cache:
        hit = cache[url]
        return hit.get("shares"), hit.get("psu")
    response = nse.get(url, headers={"Accept": "application/xml,text/xml,*/*"}, timeout=40)
    shares, psu = parse_xbrl(response.content)
    if shares is not None or psu is not None:
        cache[url] = {"shares": shares, "psu": psu}
    return shares, psu


def run(progress, cancel=None):
    today = date.today()
    nse = Nse()
    filings = fetch_filings(nse, today, progress, cancel)
    _check(cancel)
    progress("Reading listing dates.")
    listings = fetch_listings(nse)
    progress(f"Listing dates for {len(listings)} symbols.")
    _check(cancel)
    psu_index, freefloat = fetch_psu_and_freefloat(nse, progress, cancel)
    _check(cancel)
    prices, newest_price = fetch_prices(nse, today, progress, cancel)
    progress(f"Closes for {len(prices)} symbols.")

    short = []
    for symbol, by_date in filings.items():
        latest = max(by_date)
        if by_date[latest]["public"] < 25:
            short.append(symbol)
    short.sort()
    progress(f"{len(short)} companies have public shareholding below 25%.")

    cache = _load_cache()
    facts = {}
    for index, symbol in enumerate(short, start=1):
        _check(cancel)
        latest = filings[symbol][max(filings[symbol])]
        url = latest.get("xbrl") or ""
        if index == 1 or index % 10 == 0 or index == len(short):
            progress(f"Reading share counts {index} of {len(short)}.",
                     current=index, total=len(short))
        if not url.startswith("https://") or "nseindia.com" not in url:
            facts[symbol] = (None, None)
            continue
        try:
            facts[symbol] = _xbrl_facts(nse, url, cache)
        except Exception:
            facts[symbol] = (None, None)
        if index % 20 == 0:
            _save_cache(cache)
    _save_cache(cache)

    results = []
    for symbol in short:
        _check(cancel)
        by_date = filings[symbol]
        latest_day = max(by_date)
        latest = by_date[latest_day]
        history = [(day, row["public"]) for day, row in by_date.items()]
        shares, psu_flag = facts.get(symbol, (None, None))
        if psu_flag is None:
            psu = symbol in psu_index
        else:
            psu = bool(psu_flag)
        price_row = prices.get(symbol)
        price = price_row[0] if price_row else None
        price_date = price_row[1] if price_row else None
        mcap = None
        mcap_note = ""
        if shares and price:
            mcap = shares * price / 1e7
        elif latest["public"] >= 1 and freefloat.get(symbol):
            mcap = (freefloat[symbol] / 1e7) / (latest["public"] / 100.0)
            mcap_note = (
                " Market cap is the free-float market cap divided by the public "
                "percentage, because the share count could not be read."
            )
        listing = (listings.get(symbol) or {}).get("listing")
        decision = assess(symbol, listing, mcap, psu, history, today)
        if mcap_note:
            decision["basis"] += mcap_note
        end = decision["end_date"]
        results.append({
            "symbol": symbol,
            "name": latest["name"],
            "isin": latest["isin"],
            "as_of": latest_day.isoformat(),
            "promoter": latest["promoter"],
            "public": latest["public"],
            "employee": latest["employee"],
            "psu": psu,
            "listing": listing.isoformat() if listing else None,
            "mcap_cr": round(mcap, 2) if mcap is not None else None,
            "price": price,
            "price_date": price_date.isoformat() if price_date else None,
            "shares": shares,
            "target": decision["target"],
            "gap": decision["gap"],
            "sale_cr": decision["sale_cr"],
            "sale_25_cr": decision["sale_25_cr"],
            "end_date": end.isoformat() if end else None,
            "status": decision["status"],
            "days": (end - today).days if end else None,
            "basis": decision["basis"],
            "slab": decision["slab"],
            "stale": (today - latest_day).days > 200,
            "xbrl": latest["xbrl"] if str(latest["xbrl"]).startswith("https://") else "",
        })

    rank = {"Overdue": 0, "Cure period": 1, "Within time": 2, "Date unknown": 3}
    results.sort(key=lambda row: (
        rank.get(row["status"], 9),
        row["end_date"] or "9999-99-99",
        -(row["sale_cr"] or 0),
        row["symbol"],
    ))
    progress(
        f"Done. {sum(1 for row in results if row['status'] == 'Overdue')} overdue, "
        f"{sum(1 for row in results if row['status'] == 'Cure period')} in a cure period, "
        f"{sum(1 for row in results if row['status'] == 'Within time')} within time."
    )
    if newest_price is None:
        progress("No cash bhavcopy was available, so sale sizes that need a close are blank.")
    return results, today.isoformat()
