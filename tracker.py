"""
TikTok Link Tracker - versione per Render.com
"""
import os
import csv
import json
import string
import random
import urllib.request
from datetime import datetime
from flask import Flask, request, redirect, render_template, url_for, jsonify
from user_agents import parse

app = Flask(__name__)

# ============ CONFIGURAZIONE ============
# Su Render, PUBLIC_URL si imposta come Environment Variable.
# In locale puoi lasciarlo vuoto o mettere http://localhost:8080
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip()

# File di dati (ATTENZIONE: su Render sono effimeri, vedi README)
LOG_FILE   = "clicks_tiktok.csv"
LINKS_FILE = "links.json"

# Header del CSV
HEADERS = [
    "timestamp", "short_code", "ip", "paese", "citta",
    "browser", "os", "device", "referrer",
    "utm_source", "utm_medium", "utm_campaign", "utm_content",
    "user_agent_raw"
]
# ========================================


def init_files():
    """Crea i file di dati se non esistono."""
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HEADERS)
    if not os.path.exists(LINKS_FILE):
        with open(LINKS_FILE, "w") as f:
            json.dump({}, f)


init_files()


def genera_codice():
    caratteri = string.ascii_letters + string.digits
    with open(LINKS_FILE) as f:
        esistenti = json.load(f)
    while True:
        codice = ''.join(random.choices(caratteri, k=6))
        if codice not in esistenti:
            return codice


def url_corto(codice):
    """Costruisce il link pulito, senza porta."""
    if PUBLIC_URL:
        return PUBLIC_URL.rstrip("/") + "/" + codice
    return f"{request.scheme}://{request.host}/{codice}"


def geolocalizza_ip(ip):
    """Usa ip-api.com per paese/città. Restituisce n/d se fallisce."""
    try:
        if ip in ("127.0.0.1", "localhost") or ip.startswith("10.") or ip.startswith("192.168."):
            return {"country": "Interno", "city": "-"}
        with urllib.request.urlopen(f"http://ip-api.com/json/{ip}?lang=it", timeout=3) as r:
            data = json.loads(r.read())
            if data.get("status") == "success":
                return {"country": data.get("country", "n/d"), "city": data.get("city", "n/d")}
    except Exception:
        pass
    return {"country": "n/d", "city": "n/d"}


@app.route("/")
def dashboard():
    rows = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        for row in reader:
            rows.append(dict(zip(headers, row)))

    stats = {"totale_click": len(rows), "paesi": {}, "dispositivi": {}, "fonti": {}}
    for r in rows:
        stats["paesi"][r["paese"]] = stats["paesi"].get(r["paese"], 0) + 1
        stats["dispositivi"][r["device"]] = stats["dispositivi"].get(r["device"], 0) + 1
        fonte = r["utm_source"] or "diretto"
        stats["fonti"][fonte] = stats["fonti"].get(fonte, 0) + 1

    top_paesi       = sorted(stats["paesi"].items(),       key=lambda x: x[1], reverse=True)[:3]
    top_dispositivi = sorted(stats["dispositivi"].items(), key=lambda x: x[1], reverse=True)[:3]
    top_fonti       = sorted(stats["fonti"].items(),       key=lambda x: x[1], reverse=True)[:3]
    ultime_righe    = rows[::-1][:50]

    with open(LINKS_FILE) as f:
        my_links = json.load(f)
    links_view = []
    for code, info in my_links.items():
        links_view.append({
            "code": code,
            "short": url_corto(code),
            "url": info["url"],
            "campaign": info.get("utm_campaign", ""),
            "created": info.get("created", "")[:16],
        })

    return render_template(
        "dashboard.html",
        rows=ultime_righe,
        stats=stats,
        top_paesi=top_paesi,
        top_dispositivi=top_dispositivi,
        top_fonti=top_fonti,
        links_view=links_view
    )


@app.route("/crea", methods=["POST"])
def crea_link():
    url_destinazione = request.form.get("url")
    utm_campaign = request.form.get("campaign", "tiktok_generale")
    utm_content  = request.form.get("content", "")

    codice = genera_codice()
    with open(LINKS_FILE) as f:
        links = json.load(f)
    links[codice] = {
        "url": url_destinazione,
        "created": datetime.now().isoformat(),
        "utm_campaign": utm_campaign,
        "utm_content": utm_content,
    }
    with open(LINKS_FILE, "w") as f:
        json.dump(links, f)

    return redirect(url_for("dashboard"))


@app.route("/<codice>")
def redirect_link(codice):
    with open(LINKS_FILE) as f:
        links = json.load(f)
    if codice not in links:
        return "Link non trovato", 404
    link_info = links[codice]

    # IP reale anche dietro proxy (X-Forwarded-For viene da Render/Cloudflare)
    ip_raw = request.headers.get("X-Forwarded-For", request.remote_addr)
    # X-Forwarded-For può contenere più IP: prendi il primo (quello del client)
    ip = ip_raw.split(",")[0].strip() if ip_raw else request.remote_addr

    ua  = parse(request.headers.get("User-Agent", ""))
    geo = geolocalizza_ip(ip)

    utm_source   = request.args.get("utm_source", "tiktok")
    utm_medium   = request.args.get("utm_medium", "social")
    utm_campaign = request.args.get("utm_campaign", link_info["utm_campaign"])
    utm_content  = request.args.get("utm_content", link_info["utm_content"])

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            datetime.now().isoformat(), codice, ip,
            geo["country"], geo["city"],
            f"{ua.browser.family} {ua.browser.version_string}",
            f"{ua.os.family} {ua.os.version_string}",
            ua.device.family,
            request.referrer or "diretto",
            utm_source, utm_medium, utm_campaign, utm_content,
            request.headers.get("User-Agent", ""),
        ])

    return redirect(link_info["url"])


@app.route("/api/stats")
def api_stats():
    rows = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        for row in reader:
            rows.append(dict(zip(headers, row)))
    return jsonify(rows[::-1])


if __name__ == "__main__":
    # Render assegna la porta via $PORT. In locale usa 8080.
    port = int(os.environ.get("PORT", 8080))
    print("=" * 50)
    print("  TIKTOK LINK TRACKER - AVVIO")
    print(f"  Porta: {port}")
    if PUBLIC_URL:
        print(f"  Link pubblici tipo: {PUBLIC_URL}/abcd12")
    print("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=False)