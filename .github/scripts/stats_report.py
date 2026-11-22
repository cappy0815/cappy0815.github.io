#!/usr/bin/env python3
"""Wochenbericht aus stats/data/history.json als HTML-Mail.

Zeitraum: die letzten 7 vollen Tage (UTC) bis gestern, Vergleich mit den 7 Tagen davor.
Versand über Gmail-SMTP mit SMTP_USER / SMTP_PASS (Google-App-Passwort).
Mit --dry-run DATEI wird nur die HTML-Datei geschrieben.
"""
import datetime as dt
import html
import json
import os
import re
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
cfg = json.load(open(os.path.join(ROOT, "stats", "config.json"), encoding="utf-8"))
hist = json.load(open(os.path.join(ROOT, "stats", "data", "history.json"), encoding="utf-8"))

# Gulf-Farben wie auf der Projektseite
BG, BOARD, INK, MUTED, LINE, BLUE, ORANGE = "#0B0D10", "#14181C", "#F4F6F7", "#A2ADB6", "#252B31", "#8FC9E8", "#F2722B"


def days_back(end, n):
    return [(end - dt.timedelta(days=i)).isoformat() for i in range(n)]


def ssum(series, days):
    return sum(series.get(d, 0) for d in days)


def split_file(name):
    """'Player-v0.10.3.apk' -> ('Player', '0.10.3'); 'EHV_NRW_LiveTicker_v3.5.exe' -> ('EHV NRW LiveTicker', '3.5')"""
    m = re.match(r"^(.*?)[-_ ]v(\d[\w.]*?)(\.(apk|exe|zip|msi))?$", name, re.I)
    if not m:
        return name, "–"
    app = m.group(1).replace("_", " ").replace("-", " ")
    ext = (m.group(4) or "").lower()
    if ext:
        app += " (Android)" if ext == "apk" else " (Windows)"
    return app, m.group(2)


def delta(now, prev):
    if now == prev:
        return f'<span style="color:{MUTED}">±0</span>'
    col = BLUE if now > prev else ORANGE
    return f'<span style="color:{col}">{"+" if now > prev else "−"}{abs(now - prev)}</span>'


def build(today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    end = today - dt.timedelta(days=1)
    week = days_back(end, 7)
    prev = days_back(end - dt.timedelta(days=7), 7)
    period = f"{dt.date.fromisoformat(week[-1]):%d.%m.} – {end:%d.%m.%Y}"

    site = hist.get("site", {"pages": {}, "events": {}})
    names = cfg.get("page_names", {})

    # --- Seiten
    rows = []
    for path, series in site.get("pages", {}).items():
        w, p, t = ssum(series, week), ssum(series, prev), sum(series.values())
        rows.append((names.get(path, path), w, p, t))
    rows.sort(key=lambda r: (-r[1], -r[3]))
    tot_w = sum(r[1] for r in rows)
    tot_p = sum(r[2] for r in rows)

    # --- Downloads (Klicks auf der Projektseite)
    apps = {}
    for ev, series in site.get("events", {}).items():
        if not ev.startswith("download/"):
            continue
        app, ver = split_file(ev.split("/", 1)[1])
        a = apps.setdefault(app, {"w": 0, "p": 0, "t": 0, "ver": []})
        w, p, t = ssum(series, week), ssum(series, prev), sum(series.values())
        a["w"] += w; a["p"] += p; a["t"] += t
        a["ver"].append((ver, w, t))
    dl_w = sum(a["w"] for a in apps.values())
    dl_p = sum(a["p"] for a in apps.values())

    # --- Release-Downloads (falls Dateien als GitHub-Release hochgeladen sind)
    rel_rows = []
    for repo, assets in hist.get("releases", {}).items():
        for name, e in assets.items():
            snaps = e["snap"]
            if not snaps:
                continue
            last_day = max(snaps)
            older = [d for d in snaps if d <= prev[0]]
            base = snaps[max(older)] if older else 0
            rel_rows.append((repo, name, e["tag"], snaps[last_day] - base, snaps[last_day]))

    # --- GitHub-Repos
    repo_rows = []
    for repo, t in hist.get("traffic", {}).items():
        v = {d: x[0] for d, x in t.get("views", {}).items()}
        u = {d: x[1] for d, x in t.get("views", {}).items()}
        c = {d: x[0] for d, x in t.get("clones", {}).items()}
        repo_rows.append((repo, ssum(v, week), ssum(u, week), ssum(c, week), ssum(v, prev)))
    repo_rows.sort(key=lambda r: -r[1])

    # ---------- HTML
    th = f'style="text-align:left;padding:6px 10px;color:{MUTED};font-weight:500;font-size:12px;border-bottom:1px solid {LINE}"'
    thr = th.replace("text-align:left", "text-align:right")
    td = f'style="padding:6px 10px;border-bottom:1px solid {LINE}"'
    tdr = f'style="padding:6px 10px;border-bottom:1px solid {LINE};text-align:right;font-family:Consolas,monospace"'
    esc = html.escape

    def table(head, body):
        return (f'<table cellspacing="0" cellpadding="0" style="width:100%;border-collapse:collapse;font-size:14px;color:{INK}">'
                f"<tr>{head}</tr>{body}</table>")

    def h2(t):
        return f'<h2 style="font-size:16px;margin:28px 0 8px;color:{BLUE};font-weight:600">{t}</h2>'

    def kpi(label, val, prevval):
        return (f'<td style="background:{BOARD};padding:14px 16px;border-top:3px solid {BLUE};width:33%">'
                f'<div style="font-size:12px;color:{MUTED}">{label}</div>'
                f'<div style="font-size:26px;font-weight:700;color:{INK}">{val}</div>'
                f'<div style="font-size:12px">{delta(val, prevval)} zur Vorwoche</div></td>')

    nev_w = sum(ssum(s, week) for pth, s in site.get("pages", {}).items() if "nev-daily" in pth.lower())
    nev_p = sum(ssum(s, prev) for pth, s in site.get("pages", {}).items() if "nev-daily" in pth.lower())

    out = [f'<div style="background:{BG};color:{INK};font-family:Segoe UI,Roboto,Arial,sans-serif;padding:24px">',
           f'<div style="max-width:680px;margin:0 auto">',
           f'<div style="height:6px;background:linear-gradient(90deg,{BLUE} 0 70%,{ORANGE} 70% 100%)"></div>',
           f'<h1 style="font-size:22px;margin:18px 0 2px">Wochenstatistik cappy0815</h1>',
           f'<div style="color:{MUTED};font-size:13px">{period}</div>',
           f'<table cellspacing="8" style="width:100%;margin-top:14px"><tr>',
           kpi("Besuche gesamt", tot_w, tot_p), kpi("davon NEV-Daily", nev_w, nev_p), kpi("Downloads", dl_w, dl_p),
           "</tr></table>"]

    out.append(h2("Webseiten"))
    if rows:
        body = "".join(f"<tr><td {td}>{esc(n)}</td><td {tdr}>{w}</td><td {tdr}>{delta(w, p)}</td><td {tdr}>{t}</td></tr>" for n, w, p, t in rows)
        out.append(table(f"<th {th}>Seite</th><th {thr}>Woche</th><th {thr}>Δ</th><th {thr}>gesamt</th>", body))
    else:
        out.append(f'<p style="color:{MUTED}">Noch keine Daten von GoatCounter.</p>')

    out.append(h2("Downloads je App und Version"))
    if apps:
        body = ""
        for app, a in sorted(apps.items(), key=lambda x: (-x[1]["w"], -x[1]["t"])):
            body += f'<tr><td {td}><b>{esc(app)}</b></td><td {tdr}><b>{a["w"]}</b></td><td {tdr}>{delta(a["w"], a["p"])}</td><td {tdr}><b>{a["t"]}</b></td></tr>'
            for ver, w, t in sorted(a["ver"], key=lambda v: [int(x) if x.isdigit() else 0 for x in re.split(r"\D+", v[0]) if x], reverse=True):
                body += f'<tr><td {td}><span style="color:{MUTED};padding-left:14px">v{esc(ver)}</span></td><td {tdr}>{w}</td><td {tdr}></td><td {tdr}>{t}</td></tr>'
        out.append(table(f"<th {th}>App</th><th {thr}>Woche</th><th {thr}>Δ</th><th {thr}>gesamt</th>", body))
    else:
        out.append(f'<p style="color:{MUTED}">Noch keine Downloads gezählt.</p>')

    if rel_rows:
        out.append(h2("GitHub-Releases"))
        body = "".join(f"<tr><td {td}>{esc(r)}</td><td {td}>{esc(n)}</td><td {tdr}>{w}</td><td {tdr}>{t}</td></tr>" for r, n, tag, w, t in sorted(rel_rows, key=lambda x: -x[4]))
        out.append(table(f"<th {th}>Repo</th><th {th}>Datei</th><th {thr}>Woche</th><th {thr}>gesamt</th>", body))

    out.append(h2("GitHub-Repos"))
    if repo_rows:
        body = "".join(f"<tr><td {td}>{esc(r)}</td><td {tdr}>{v}</td><td {tdr}>{delta(v, pv)}</td><td {tdr}>{u}</td><td {tdr}>{c}</td></tr>" for r, v, u, c, pv in repo_rows)
        out.append(table(f"<th {th}>Repo</th><th {thr}>Aufrufe</th><th {thr}>Δ</th><th {thr}>Besucher*</th><th {thr}>Klone</th>", body))
    else:
        out.append(f'<p style="color:{MUTED}">Noch keine Traffic-Daten (STATS_TOKEN gesetzt?).</p>')

    out.append(f'<p style="font-size:12px;color:{MUTED};margin-top:24px;line-height:1.5">'
               f"Besuche: GoatCounter zählt je Seite einen Besuch pro Besucher und 8 Stunden, anonym und ohne Cookies. "
               f"Downloads: Klicks auf die Download-Knöpfe der Projektseite; Updates direkt aus den Apps werden nicht gezählt. "
               f"*Besucher: Tageswerte von GitHub addiert, wer an mehreren Tagen kommt, zählt mehrfach.</p>")
    out.append(f'<p style="margin-top:18px"><a href="{cfg["stats_url"]}" style="color:{BLUE}">Zur Statistik-Seite →</a></p>')
    out.append("</div></div>")
    subject = f"Wochenstatistik {period}: {tot_w} Besuche, {dl_w} Downloads"
    return subject, "".join(out)


def main():
    subject, body = build()
    if "--dry-run" in sys.argv:
        path = sys.argv[sys.argv.index("--dry-run") + 1]
        open(path, "w", encoding="utf-8").write(f"<!doctype html><meta charset=utf-8><title>{html.escape(subject)}</title><body style='margin:0'>{body}")
        print(subject); print("geschrieben:", path)
        return
    user, pw = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
    if not (user and pw):
        sys.exit("SMTP_USER / SMTP_PASS fehlen – keine Mail verschickt")
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, f"cappy0815 Statistik <{user}>", cfg["mail_to"]
    msg.attach(MIMEText(f"{subject}\n\n{cfg['stats_url']}", "plain", "utf-8"))
    msg.attach(MIMEText(body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, pw)
        s.sendmail(user, [cfg["mail_to"]], msg.as_string())
    print("Mail verschickt:", subject)


if __name__ == "__main__":
    main()
