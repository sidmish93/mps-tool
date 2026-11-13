"""Minimum public shareholding deadlines and sale sizes.

The size bands and the years-from-listing timelines are Rule 19(2)(b) of the
Securities Contracts (Regulation) Rules, 1957, as substituted by G.S.R. 184(E)
on 13 March 2026. A fall after a company has already reached 25% is Rule 19A:
12 months to restore, or 24 months for a public-sector company. The government
exemption for public-sector companies ran until 1 August 2026.

The clock is the listing date. The March 2026 proviso makes those timelines
available to companies that were already listed. It does not restart them on
13 March 2026.

The size band in the rule is post-issue capital at the offer price. Callers
pass today's market cap, and the basis text says so.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

MPS = 25.0
INTERIM = 15.0
PSU_EXEMPTION_END = date(2026, 8, 1)
LIC_SYMBOL = "LICI"
LIC_10_DUE = date(2027, 5, 16)
LIC_25_DUE = date(2032, 5, 16)
LISTING_WINDOW_DAYS = 200

_MON = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

NOTES = [
    "Public shareholding is the Public (B) percentage NSE publishes, calculated under the SCRR on (A+B+C2). Shares held by an employee trust are outside that percentage.",
    "The sale size is the value, at the latest NSE close, of shares that would have to move to the public to reach the target. The number of shares stays the same.",
    "The size band uses today's market cap in place of post-issue capital at the offer price, which is the figure in Rule 19(2)(b). A company that has grown or shrunk a lot since listing can fall in a different band.",
    "Timelines run from the listing date. The 13 March 2026 amendment makes those timelines available to companies already listed. It does not start the clock again on 13 March 2026.",
    "When a later filing is below 25% after one that was at or above 25%, the end date is 12 months from the day after the last filing that was still at or above 25%. For a public-sector company that period is 24 months.",
    "The day the holding actually crossed 25% can be earlier than the next filing, so this restoration date can be later than the legal deadline.",
    "Public-sector companies that were still below 25% were exempt until 1 August 2026. That date has passed.",
    "Life Insurance Corporation follows its own exemption: 10% by 16 May 2027 and 25% by 16 May 2032.",
    "A company whose public shareholding fell under an insolvency resolution plan can have a different clock. Those cases are not identified.",
    "This is a reading of the published rules and NSE filings, for screening. It is not a compliance opinion.",
]


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def pretty(day: date) -> str:
    return f"{day.day} {_MON[day.month - 1]} {day.year}"


def _cr(amount: float) -> str:
    if amount >= 100:
        return f"{amount:,.0f}"
    return f"{amount:,.2f}"


def _sale(mcap_cr: float | None, public: float, target: float) -> float | None:
    if mcap_cr is None or public >= target:
        return 0.0 if mcap_cr is not None and public >= target else None
    return round(mcap_cr * (target - public) / 100.0, 2)


def _band(mcap_cr: float) -> str:
    if mcap_cr <= 1600:
        return "upto_1600"
    if mcap_cr <= 4000:
        return "to_4000"
    if mcap_cr <= 50000:
        return "to_50000"
    if mcap_cr <= 100000:
        return "to_1l"
    if mcap_cr <= 500000:
        return "to_5l"
    return "above_5l"


def _band_label(band: str) -> str:
    return {
        "upto_1600": "up to ₹1,600 cr",
        "to_4000": "above ₹1,600 cr to ₹4,000 cr",
        "to_50000": "above ₹4,000 cr to ₹50,000 cr",
        "to_1l": "above ₹50,000 cr to ₹1 lakh cr",
        "to_5l": "above ₹1 lakh cr to ₹5 lakh cr",
        "above_5l": "above ₹5 lakh cr",
    }[band]


def _status(end: date | None, today: date, kind: str) -> str:
    if end is None:
        return "Date unknown"
    if today > end:
        return "Overdue"
    if kind == "cure":
        return "Cure period"
    return "Within time"


def _row(public, target, mcap_cr, end, today, status, basis, slab, kind) -> dict:
    gap = round(target - public, 4)
    return {
        "target": target,
        "gap": gap,
        "sale_cr": _sale(mcap_cr, public, target),
        "sale_25_cr": _sale(mcap_cr, public, MPS),
        "end_date": end,
        "status": status,
        "basis": basis,
        "slab": slab,
        "kind": kind,
    }


def _public_at_listing(listing: date, history: list[tuple[date, float]]) -> float | None:
    window_end = listing + timedelta(days=LISTING_WINDOW_DAYS)
    near = [item for item in history if listing <= item[0] <= window_end]
    if not near:
        return None
    near.sort(key=lambda item: item[0])
    return near[0][1]


def _milestones(listing: date, mcap_cr: float, public: float,
                public_at_listing: float | None):
    """Return (milestones, listing_note). Milestones are (target %, due date)."""
    band = _band(mcap_cr)
    if band == "upto_1600":
        return [(MPS, listing)], ""
    if band in ("to_4000", "to_50000"):
        return [(MPS, add_months(listing, 36))], ""
    if band == "to_1l":
        return [(MPS, add_months(listing, 60))], ""
    # Above ₹1 lakh crore: 15% in 5 years and 25% in 10, if listing was below 15.
    if public_at_listing is None:
        if public < INTERIM:
            note = (
                "No filing in this pull falls in the first 200 days after listing, "
                "so the public percentage at listing is unknown. The next date used "
                "is 15% at five years from listing, and 25% at ten years."
            )
            return [
                (INTERIM, add_months(listing, 60)),
                (MPS, add_months(listing, 120)),
            ], note
        note = (
            "No filing in this pull falls in the first 200 days after listing, "
            "so the public percentage at listing is unknown. Public is already "
            "15% or more, so the date used is 25% five years from listing. A company "
            "that listed below 15% would have until ten years for 25%."
        )
        return [(MPS, add_months(listing, 60))], note
    if public_at_listing < INTERIM:
        return [
            (INTERIM, add_months(listing, 60)),
            (MPS, add_months(listing, 120)),
        ], ""
    return [(MPS, add_months(listing, 60))], ""


def assess(symbol: str, listing: date | None, mcap_cr: float | None,
           psu: bool, history: list[tuple[date, float]], today: date) -> dict:
    """Decide the next target, the sale, and the end date for one company.

    `history` is (as-of date, public %) for every filing we have, including
    the latest. Public % is NSE's published number.
    """
    if not history:
        raise ValueError("history is empty")
    series = sorted(history, key=lambda item: item[0])
    as_of, public = series[-1]
    slab = _band_label(_band(mcap_cr)) if mcap_cr is not None else None

    if public >= MPS:
        return _row(public, MPS, mcap_cr, None, today, "Meets MPS",
                    "Public shareholding is at least 25%.", slab, "meets")

    if (symbol or "").upper() == LIC_SYMBOL:
        return _lic(public, mcap_cr, today, slab)

    last_ok = None
    for day, level in series:
        if level >= MPS:
            last_ok = day
    if last_ok is not None and last_ok < as_of:
        return _cure(public, mcap_cr, psu, last_ok, today, slab)

    if listing is None:
        return _row(
            public, MPS, mcap_cr, None, today, "Date unknown",
            "Listing date is not on the NSE equity list, so the end date cannot be set.",
            slab, "unknown")
    if mcap_cr is None:
        return _row(
            public, MPS, mcap_cr, None, today, "Date unknown",
            "Market cap is missing, so the size band and the sale cannot be set.",
            None, "unknown")
    return _glide(public, listing, mcap_cr, psu, series, today, slab)


def _lic(public, mcap_cr, today, slab) -> dict:
    if public < 10:
        target, end = 10.0, LIC_10_DUE
        basis = (
            "Life Insurance Corporation has a specific exemption: 10% by "
            f"{pretty(LIC_10_DUE)} and 25% by {pretty(LIC_25_DUE)}."
        )
    else:
        target, end = MPS, LIC_25_DUE
        basis = (
            "Life Insurance Corporation has a specific exemption. "
            f"The 10% milestone is already met. 25% is due by {pretty(LIC_25_DUE)}."
        )
    return _row(public, target, mcap_cr, end, today,
                _status(end, today, "exemption"), basis, slab, "exemption")


def _cure(public, mcap_cr, psu, last_ok, today, slab) -> dict:
    fall_on = last_ok + timedelta(days=1)
    months = 24 if psu else 12
    end = add_months(fall_on, months)
    who = "A public-sector company gets 24 months" if psu else "Rule 19A gives 12 months"
    basis = (
        f"Public shareholding was at least 25% in the {pretty(last_ok)} filing "
        f"and is below 25% after that. {who} from {pretty(fall_on)}."
    )
    if psu and end < PSU_EXEMPTION_END:
        end = PSU_EXEMPTION_END
        basis += " The public-sector exemption runs to 1 Aug 2026, which is later."
    if mcap_cr is None:
        basis += " Market cap is missing, so the sale size is blank."
    return _row(public, MPS, mcap_cr, end, today,
                _status(end, today, "cure"), basis, slab, "cure")


def _glide(public, listing, mcap_cr, psu, series, today, slab) -> dict:
    at_listing = _public_at_listing(listing, series)
    milestones, note = _milestones(listing, mcap_cr, public, at_listing)
    unmet = [(target, due) for target, due in milestones if public < target]
    target, raw_end = unmet[0]
    end = raw_end
    due_25 = next(due for level, due in milestones if level == MPS)
    band = _band(mcap_cr)
    if band == "upto_1600":
        basis = (
            f"Today's market cap of ₹{_cr(mcap_cr)} cr is in the band that had to "
            f"list with 25% public shareholding ({pretty(listing)})."
        )
    elif target == INTERIM:
        basis = (
            f"Today's market cap of ₹{_cr(mcap_cr)} cr is used as the size band ({slab}). "
            f"The next milestone is 15% on {pretty(raw_end)}. "
            f"25% is due on {pretty(due_25)}."
        )
    else:
        years = (raw_end.year - listing.year)
        basis = (
            f"Today's market cap of ₹{_cr(mcap_cr)} cr is used as the size band ({slab}). "
            f"25% is due on {pretty(raw_end)}, {years} years from listing on {pretty(listing)}."
        )
    if note:
        basis = basis + " " + note
    if psu and end < PSU_EXEMPTION_END:
        end = PSU_EXEMPTION_END
        basis = (
            "Public-sector company still below 25%. The exemption to reach 25% "
            f"ran to 1 Aug 2026. The size-band date from listing would have been "
            f"{pretty(raw_end)}."
        )
    return _row(public, target, mcap_cr, end, today,
                _status(end, today, "glide"), basis, slab, "glide")
