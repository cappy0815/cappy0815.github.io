#!/usr/bin/env python3
"""Sammelt täglich die Zugriffszahlen und schreibt sie nach stats/data/history.json.

Quellen
  - GitHub Traffic API: Aufrufe und Klone je Repo (GitHub hält nur 14 Tage vor,
    deshalb wird täglich gesichert). Braucht STATS_TOKEN mit "Administration: read".
  - GitHub Releases API: download_count je Release-Datei (nur Gesamtzähler,
    darum wird täglich ein Schnappschuss abgelegt).
  - GoatCounter API: Besuche je Seite und Download-Ereignisse je Tag.
    Braucht GOATCOUNTER_TOKEN.

Fehlt ein Token, wird die jeweilige Quelle übersprungen, der Rest läuft weiter.
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(ROOT, "stats", "config.json")
HISTORY = os.path.join(ROOT, "stats", "data", "history.json")


def http_json(url, token=None, scheme="Bearer"):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "cappy0815-stats"})
    if token:
        req.add_header("Authorization", f"{scheme} {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def collect_traffic(cfg, hist, token):
    owner = cfg["owner"]
    out = hist.setdefault("traffic", {})
    for repo in cfg["repos"]:
        r = out.setdefault(repo, {"views": {}, "clones": {}})
        for kind in ("views", "clones"):
            url = f"https://api.github.com/repos/{owner}/{repo}/traffic/{kind}?per=day"
            try:
                data = http_json(url, token)
            except urllib.error.HTTPError as e:
                print(f"  ! traffic {repo}/{kind}: HTTP {e.code}", file=sys.stderr)
                continue
            # GitHub liefert die letzten 14 Tage; vorhandene Tage werden überschrieben (Werte des laufenden Tags wachsen noch)
            for d in data.get(kind, []):
                r[kind][d["timestamp"][:10]] = [d["count"], d["uniques"]]


def collect_releases(cfg, hist, token, today):
    owner = cfg["owner"]
    out = hist.setdefault("releases", {})
    for repo in cfg["repos"]:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=100"
        try:
            rels = http_json(url, token)
        except urllib.error.HTTPError as e:
            print(f"  ! releases {repo}: HTTP {e.code}", file=sys.stderr)
            continue
        for rel in rels:
            for a in rel.get("assets", []):
                entry = out.setdefault(repo, {}).setdefault(a["name"], {"tag": rel["tag_name"], "snap": {}})
                entry["tag"] = rel["tag_name"]
                entry["snap"][today] = a["download_count"]


def collect_goatcounter(cfg, hist, token, today):
    code = cfg["goatcounter_code"]
    days = cfg.get("goatcounter_days_back", 10)
    start = (dt.datetime.combine(today_date(today), dt.time()) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:00:00Z")
    end = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")
    site = hist.setdefault("site", {"pages": {}, "events": {}})
    q = urllib.parse.urlencode({"start": start, "end": end, "limit": "100"})
    url = f"https://{code}.goatcounter.com/api/v0/stats/hits?{q}"
    try:
        data = http_json(url, token)
    except urllib.error.HTTPError as e:
        print(f"  ! goatcounter: HTTP {e.code}", file=sys.stderr)
        return
    for h in data.get("hits", []):
        bucket = site["events"] if h.get("event") else site["pages"]
        series = bucket.setdefault(h["path"], {})
        for s in h.get("stats") or []:
            if s.get("daily"):
                series[s["day"]] = s["daily"]
    if data.get("more"):
        print("  ! goatcounter: mehr als 100 Pfade, Rest nicht erfasst", file=sys.stderr)


def today_date(s):
    return dt.date.fromisoformat(s)


def main():
    cfg = load(CONFIG, None)
    hist = load(HISTORY, {})
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    gh = os.environ.get("STATS_TOKEN") or None
    gc = os.environ.get("GOATCOUNTER_TOKEN") or None

    if gh:
        print("GitHub Traffic …"); collect_traffic(cfg, hist, gh)
    else:
        print("STATS_TOKEN fehlt – GitHub Traffic übersprungen")
    print("GitHub Releases …"); collect_releases(cfg, hist, gh or os.environ.get("GITHUB_TOKEN"), today)
    if gc:
        print("GoatCounter …"); collect_goatcounter(cfg, hist, gc, today)
    else:
        print("GOATCOUNTER_TOKEN fehlt – GoatCounter übersprungen")

    hist["updated"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("gespeichert:", HISTORY)


if __name__ == "__main__":
    main()
