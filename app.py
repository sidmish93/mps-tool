"""Web view of companies below the minimum public shareholding.

Run:  python app.py
Then open http://127.0.0.1:5050
"""

from __future__ import annotations

import io
import threading
import traceback
from datetime import date, datetime

from flask import Flask, jsonify, render_template, send_file
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from nse import Cancelled, run
from rules import NOTES

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

_gate = threading.Lock()
_cancel = threading.Event()
_job = {}


def _reset():
    _job.clear()
    _job.update(running=False, log=[], current=0, total=0, finished=False,
                error=None, cancelled=False, results=None, today=None)


_reset()


def _progress(message, current=None, total=None):
    stamp = datetime.now().strftime("%H:%M:%S")
    _job["log"].append(f"[{stamp}] {message}")
    if len(_job["log"]) > 500:
        del _job["log"][:-500]
    if current is not None:
        _job["current"] = current
    if total is not None:
        _job["total"] = total
    print(message, flush=True)


def _worker():
    try:
        results, today = run(_progress, cancel=_cancel.is_set)
        _job["results"] = results
        _job["today"] = today
    except Cancelled:
        _job["cancelled"] = True
        _progress("Cancelled.")
    except Exception as exc:
        _job["error"] = str(exc)
        _progress("ERROR: " + _job["error"])
        traceback.print_exc()
    finally:
        _job["finished"] = True
        _job["running"] = False
        _gate.release()


@app.route("/")
def index():
    return render_template("index.html", notes=NOTES)


@app.post("/start")
def start():
    if not _gate.acquire(blocking=False):
        return jsonify(ok=False, error="A fetch is already running."), 409
    _reset()
    _cancel.clear()
    _job["running"] = True
    threading.Thread(target=_worker, daemon=True).start()
    return jsonify(ok=True)


@app.post("/cancel")
def cancel():
    _cancel.set()
    return jsonify(ok=True)


@app.get("/status")
def status():
    payload = {
        "running": _job["running"],
        "finished": _job["finished"],
        "cancelled": _job["cancelled"],
        "error": _job["error"],
        "log": _job["log"][-80:],
        "current": _job["current"],
        "total": _job["total"],
        "today": _job["today"],
        "count": len(_job["results"]) if _job["results"] else 0,
    }
    if _job["finished"] and not _job["running"] and _job["results"] is not None:
        payload["results"] = _job["results"]
    return jsonify(payload)


def _workbook(results, today):
    book = Workbook()
    sheet = book.active
    sheet.title = "Below 25%"
    headers = [
        "Company", "Symbol", "ISIN", "Quarter", "Promoter %", "Public %",
        "Employee trust %", "Public sector", "Listing date", "Market cap (Rs cr)",
        "Price (Rs)", "Price date", "Shares", "Target %", "Gap (percentage points)",
        "Sale to target (Rs cr)", "Sale to 25% (Rs cr)", "End date", "Status",
        "Days", "Size band", "How the date was set", "Filing",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in results:
        sheet.append([
            row["name"], row["symbol"], row["isin"],
            date.fromisoformat(row["as_of"]),
            row["promoter"], row["public"], row["employee"],
            "Yes" if row["psu"] else "No",
            date.fromisoformat(row["listing"]) if row["listing"] else None,
            row["mcap_cr"], row["price"],
            date.fromisoformat(row["price_date"]) if row["price_date"] else None,
            row["shares"], row["target"], row["gap"],
            row["sale_cr"], row["sale_25_cr"],
            date.fromisoformat(row["end_date"]) if row["end_date"] else None,
            row["status"], row["days"], row["slab"], row["basis"], row["xbrl"],
        ])
    for index, width in enumerate(
            [42, 14, 16, 14, 12, 12, 16, 14, 14, 20, 12, 14, 16, 12, 18,
             22, 20, 14, 16, 10, 32, 80, 40], 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    notes = book.create_sheet("Notes")
    notes.append(["Screened on", today])
    notes.append([])
    for line in NOTES:
        notes.append([line])
    notes.column_dimensions["A"].width = 120
    return book


@app.get("/download.xlsx")
def download():
    if _job["running"]:
        return jsonify(ok=False, error="The fetch is still running."), 409
    if not _job["results"]:
        return jsonify(ok=False, error="Fetch the list first."), 400
    book = _workbook(_job["results"], _job["today"])
    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    name = f"MPS_shortfall_{_job['today']}.xlsx"
    return send_file(buffer, as_attachment=True, download_name=name,
                     mimetype=("application/vnd.openxmlformats-officedocument."
                               "spreadsheetml.sheet"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
