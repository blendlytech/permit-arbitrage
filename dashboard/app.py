"""
Permit Arbitrage — Outbound Dashboard API
Flask server that powers the campaign control UI.
"""

import csv
import json
import os
import re
import smtplib
import threading
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Flask, jsonify, render_template, request, send_from_directory

# Import v2 email templates
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from outbound.templates import render_subject_a, render_subject_b, render_body_a, render_body_b

# ── Load .env ─────────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_file = os.path.join(_ROOT, ".env")
if os.path.exists(_env_file):
    with open(_env_file, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ[_k.strip()] = _v.strip()

OUTPUT_DIR = os.path.join(_ROOT, "output")
SEND_LOG   = os.path.join(OUTPUT_DIR, "email_send_log.json")

# ── Shared send-state (thread-safe via simple dict + lock) ────────────────────
_send_state = {"status": "idle", "progress": [], "total": 0, "sent": 0, "failed": 0}
_state_lock = threading.Lock()

app = Flask(__name__, static_folder="static", template_folder="templates")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_JUNK_PATTERNS = [
    r"@sentry\.", r"@wixpress\.", r"\.gov$", r"@talgov\.com",
    r"noreply@", r"no-reply@", r"donotreply@", r"support@", r"info@example\.com",
]

def _is_valid_email(email: str) -> bool:
    if not email or not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        return False
    return not any(re.search(p, email, re.IGNORECASE) for p in _JUNK_PATTERNS)


def _load_send_log() -> list:
    if os.path.exists(SEND_LOG):
        with open(SEND_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_send_log(log: list):
    with open(SEND_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def _already_emailed(email: str) -> bool:
    return any(e.get("email", "").lower() == email.lower() for e in _load_send_log())


def _get_permit_count(county_keyword: str) -> int:
    total = 0
    kw = county_keyword.split()[0].replace(" ", "_")
    # Search both root and leads_archive
    search_dirs = [OUTPUT_DIR, os.path.join(OUTPUT_DIR, "leads_archive")]
    for d in search_dirs:
        if not os.path.exists(d): continue
        for fname in os.listdir(d):
            if fname.endswith(".csv") and ("_Leads_" in fname or "FRESH_LEADS_" in fname) and kw in fname:
                with open(os.path.join(d, fname), "r", encoding="utf-8") as f:
                    total += max(0, sum(1 for _ in f) - 1)
    return total if total > 0 else 132


def _list_prospect_files() -> list:
    files = []
    # Search both root and prospects_archive
    search_dirs = [OUTPUT_DIR, os.path.join(OUTPUT_DIR, "prospects_archive")]
    for d in search_dirs:
        if not os.path.exists(d): continue
        for fname in os.listdir(d):
            if fname.startswith("Prospects_List") and fname.endswith(".csv"):
                # Return relative path from output/ for easy loading
                if d == OUTPUT_DIR:
                    files.append(fname)
                else:
                    files.append(f"prospects_archive/{fname}")
    return sorted(files)


def _load_prospects(csv_path: str) -> list:
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    seen, deduped = set(), []
    for r in rows:
        em = r.get("Owner Email", "").strip().lower()
        if em and em not in seen and _is_valid_email(em):
            seen.add(em)
            deduped.append(r)
    return deduped


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Pages
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/inventory")
def api_inventory():
    inv_path = os.path.join(OUTPUT_DIR, "inventory.json")
    if os.path.exists(inv_path):
        with open(inv_path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"total_leads": 0, "counties": {}})


@app.route("/api/run_cleanup", methods=["POST"])
def api_run_cleanup():
    try:
        import organize_output
        organize_output.organize()
        return jsonify({"status": "success", "message": "Cleanup complete"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/info")
def landing():
    return render_template("landing.html")


# ─────────────────────────────────────────────────────────────────────────────
# Routes — API
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/prospect-files")
def api_prospect_files():
    return jsonify(_list_prospect_files())


@app.route("/api/prospects")
def api_prospects():
    fname = request.args.get("file")
    county = request.args.get("county", "Leon County")
    template = request.args.get("template", "B")
    sender = request.args.get("sender", "James")

    if not fname:
        files = _list_prospect_files()
        fname = files[0] if files else None
    if not fname:
        return jsonify({"error": "No prospect file found"}), 404

    csv_path = os.path.join(OUTPUT_DIR, fname)
    prospects = _load_prospects(csv_path)
    permit_count = _get_permit_count(county)

    result = []
    for p in prospects:
        fn = p.get("Owner First Name", "").strip() or "there"
        if template == "A":
            subject = render_subject_a(permit_count, p.get("Niche", "Residential"), county)
            body = render_body_a(
                first_name=fn,
                permit_count=permit_count,
                niche=p.get("Niche", "Residential"),
                county=county,
                sender_name=sender,
                landing_url=request.host_url + "info"
            )
        else:
            subject = render_subject_b(permit_count, county)
            body = render_body_b(
                first_name=fn,
                permit_count=permit_count,
                county=county,
                sender_name=sender,
                landing_url=request.host_url + "info"
            )
        result.append({
            "business":   p.get("Business Name", ""),
            "email":      p.get("Owner Email", "").strip(),
            "first_name": fn,
            "niche":      p.get("Niche", ""),
            "phone":      p.get("Phone", ""),
            "website":    p.get("Website", ""),
            "subject":    subject,
            "body":       body,
            "already_sent": _already_emailed(p.get("Owner Email", "").strip()),
        })

    return jsonify({
        "file": fname,
        "county": county,
        "permit_count": permit_count,
        "prospects": result,
    })


@app.route("/api/send-log")
def api_send_log():
    return jsonify(_load_send_log())


def _smtp_send(to_email, subject, body):
    smtp_host = os.environ.get("SMTP_HOST", "mail.spacemail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 465))
    sender_email = os.environ.get("SMTP_USER")
    sender_pass  = os.environ.get("SMTP_PASS")
    from_name    = os.environ.get("SMTP_FROM_NAME", "Clay Mills | PermitLeads")

    if not sender_pass:
        return False, "SMTP_PASS not configured"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{from_name} <{sender_email}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as srv:
            srv.login(sender_email, sender_pass)
            srv.send_message(msg)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def _run_send_batch(batch: list, delay: int):
    """Background thread: sends emails one by one with delay."""
    log = _load_send_log()
    with _state_lock:
        _send_state.update({"status": "running", "total": len(batch), "sent": 0, "failed": 0, "progress": []})

    for i, item in enumerate(batch):
        with _state_lock:
            if _send_state["status"] == "aborted":
                break

        success, msg = _smtp_send(item["email"], item["subject"], item["body"])
        entry = {
            "email":     item["email"],
            "business":  item["business"],
            "niche":     item["niche"],
            "subject":   item["subject"],
            "status":    "sent" if success else "failed",
            "error":     "" if success else msg,
            "timestamp": datetime.now().isoformat(),
        }
        log.append(entry)
        _save_send_log(log)

        with _state_lock:
            if success:
                _send_state["sent"] += 1
            else:
                _send_state["failed"] += 1
            _send_state["progress"].append(entry)

        if i < len(batch) - 1:
            time.sleep(delay)

    with _state_lock:
        if _send_state["status"] != "aborted":
            _send_state["status"] = "done"


@app.route("/api/send", methods=["POST"])
def api_send():
    data  = request.get_json(force=True)
    batch = data.get("batch", [])
    delay = int(data.get("delay", 45))

    with _state_lock:
        if _send_state["status"] == "running":
            return jsonify({"error": "Campaign already running"}), 409

    if not batch:
        return jsonify({"error": "Empty batch"}), 400

    # Filter already-sent
    to_send = [b for b in batch if not _already_emailed(b["email"])]
    if not to_send:
        return jsonify({"error": "All prospects have already been emailed"}), 400

    t = threading.Thread(target=_run_send_batch, args=(to_send, delay), daemon=True)
    t.start()
    return jsonify({"ok": True, "queued": len(to_send)})


@app.route("/api/send-status")
def api_send_status():
    with _state_lock:
        return jsonify(dict(_send_state))


@app.route("/api/abort", methods=["POST"])
def api_abort():
    with _state_lock:
        _send_state["status"] = "aborted"
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 60)
    print("  Permit Arbitrage — Outbound Dashboard")
    print("  http://localhost:5000")
    print("=" * 60)
    app.run(debug=False, host="0.0.0.0", port=5000)
