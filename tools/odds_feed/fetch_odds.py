#!/usr/bin/env python3
"""Fetches real games and odds from a licensed odds API (The Odds API, https://the-odds-api.com/liveapi/guides/v4/) and writes the small JSON file the game reads.

Why an API and not scraping: a bookmaker's pages are theirs and change without notice, scraping them breaks their terms, and a key put in a web page is public to every
visitor. So this runs on a schedule (GitHub Actions) with the key as a secret, and the game only ever reads the finished file. No key, no file: the game shows its simulated slate.

usage: ODDS_API_KEY=... fetch_odds.py [--config odds_feed_config.json] [--out odds.json]
       fetch_odds.py --self-test      runs the checks against canned API responses (no network)
Output schema mke.odds_feed.v1: {generated_utc, source, events: [{id, league, sport, home, away, start_real, status: upcoming|live|final, odds: {home, away},
home_score, away_score, winner: home|away|tie|null}]}. Odds are decimal, the median across bookmakers for each side. In-game money only; nothing here is betting advice.
"""
import argparse, json, os, statistics, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

API = "https://api.the-odds-api.com/v4"

def parse_time(s):
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())

def get(path, params, opener=urllib.request.urlopen):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    with opener(url, timeout=30) as r:
        body = json.loads(r.read().decode("utf-8")); hdr = r.headers
        return body, {"remaining": hdr.get("x-requests-remaining"), "used": hdr.get("x-requests-used")}

def median_odds(event):
    """Median decimal price per side across bookmakers' head-to-head markets; None if there is no usable market."""
    prices = {event["home_team"]: [], event["away_team"]: []}
    for bm in event.get("bookmakers", []):
        for m in bm.get("markets", []):
            if m.get("key") != "h2h":
                continue
            for o in m.get("outcomes", []):
                if o.get("name") in prices and isinstance(o.get("price"), (int, float)) and o["price"] >= 1.01:
                    prices[o["name"]].append(float(o["price"]))
    h, a = prices[event["home_team"]], prices[event["away_team"]]
    if not h or not a:
        return None
    return {"home": round(statistics.median(h), 2), "away": round(statistics.median(a), 2)}

def build(cfg, fetch, now):
    """fetch(path, params) -> (body, usage). Returns (document, usage_log)."""
    watch = set(cfg["watch"]); events = {}; usage = []
    active, _ = fetch("/sports/", {"apiKey": KEY[0]})   # free: tells which sports are in season
    in_season = {s["key"] for s in active if s.get("active")}
    for key, meta in cfg["sports"].items():
        if key not in in_season:
            continue
        odds, u = fetch(f"/sports/{key}/odds/", {"apiKey": KEY[0], "regions": cfg["regions"], "markets": "h2h", "oddsFormat": "decimal"}); usage.append((key, "odds", u))
        for e in odds:
            if e["home_team"] not in watch and e["away_team"] not in watch:
                continue
            o = median_odds(e)
            start = parse_time(e["commence_time"])
            events[e["id"]] = {"id": "feed:" + e["id"], "league": meta["league"], "sport": meta["sport"], "home": e["home_team"], "away": e["away_team"], "start_real": start,
                               "status": "live" if start <= now else "upcoming", "odds": o, "home_score": 0, "away_score": 0, "winner": None}
        scores, u = fetch(f"/sports/{key}/scores/", {"apiKey": KEY[0], "daysFrom": cfg["scores_days_from"]}); usage.append((key, "scores", u))
        for s in scores:
            if s["home_team"] not in watch and s["away_team"] not in watch:
                continue
            start = parse_time(s["commence_time"]); sc = {x["name"]: x.get("score") for x in (s.get("scores") or [])}
            hs = int(sc.get(s["home_team"]) or 0); as_ = int(sc.get(s["away_team"]) or 0)
            ev = events.setdefault(s["id"], {"id": "feed:" + s["id"], "league": meta["league"], "sport": meta["sport"], "home": s["home_team"], "away": s["away_team"], "start_real": start,
                                             "status": "upcoming", "odds": None, "home_score": 0, "away_score": 0, "winner": None})
            if s.get("scores"):
                ev["home_score"], ev["away_score"] = hs, as_
            if s.get("completed"):
                ev["status"] = "final"; ev["winner"] = "home" if hs > as_ else "away" if as_ > hs else "tie"
            elif start <= now:
                ev["status"] = "live"
    # a game with no odds cannot be bet on; keep it only if it is final (so bets on it can settle)
    out = [e for e in events.values() if e["odds"] or e["status"] == "final"]
    out.sort(key=lambda e: (e["status"] == "final", e["start_real"]))
    return {"schema": "mke.odds_feed.v1", "generated_utc": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "the-odds-api.com", "stale_after_hours": cfg["stale_after_hours"],
            "events": out[: cfg["max_events"]]}, usage

KEY = [os.environ.get("ODDS_API_KEY", "")]

def self_test():
    cfg = {"sports": {"baseball_mlb": {"league": "Baseball", "sport": "baseball"}, "icehockey_nhl": {"league": "Hockey", "sport": "hockey"}}, "watch": ["Milwaukee Brewers"], "regions": "us", "scores_days_from": 1, "max_events": 10, "stale_after_hours": 6}
    now = parse_time("2026-10-15T20:00:00Z")
    sample = {
        "/sports/": [{"key": "baseball_mlb", "active": True}, {"key": "icehockey_nhl", "active": False}],
        "/sports/baseball_mlb/odds/": [
            {"id": "g1", "commence_time": "2026-10-15T23:10:00Z", "home_team": "Milwaukee Brewers", "away_team": "Chicago Cubs", "bookmakers": [
                {"markets": [{"key": "h2h", "outcomes": [{"name": "Milwaukee Brewers", "price": 1.8}, {"name": "Chicago Cubs", "price": 2.1}]}]},
                {"markets": [{"key": "h2h", "outcomes": [{"name": "Milwaukee Brewers", "price": 1.9}, {"name": "Chicago Cubs", "price": 2.0}]}]},
                {"markets": [{"key": "h2h", "outcomes": [{"name": "Milwaukee Brewers", "price": 1.85}, {"name": "Chicago Cubs", "price": 2.05}]}]}]},
            {"id": "g2", "commence_time": "2026-10-15T23:10:00Z", "home_team": "Boston Red Sox", "away_team": "New York Yankees", "bookmakers": []}],
        "/sports/baseball_mlb/scores/": [
            {"id": "g0", "commence_time": "2026-10-14T23:10:00Z", "completed": True, "home_team": "Milwaukee Brewers", "away_team": "St. Louis Cardinals", "scores": [{"name": "Milwaukee Brewers", "score": "5"}, {"name": "St. Louis Cardinals", "score": "3"}]},
            {"id": "g1", "commence_time": "2026-10-15T23:10:00Z", "completed": False, "home_team": "Milwaukee Brewers", "away_team": "Chicago Cubs", "scores": None},
            {"id": "g3", "commence_time": "2026-10-15T18:00:00Z", "completed": False, "home_team": "Milwaukee Brewers", "away_team": "Pittsburgh Pirates", "scores": [{"name": "Milwaukee Brewers", "score": "2"}, {"name": "Pittsburgh Pirates", "score": "2"}]}]}
    calls = []
    def fake(path, params):
        calls.append(path); return sample[path], {"remaining": "400", "used": "1"}
    doc, usage = build(cfg, fake, now); ev = {e["id"]: e for e in doc["events"]}
    assert "/sports/icehockey_nhl/odds/" not in calls, "a sport out of season must cost nothing"
    assert set(ev) == {"feed:g0", "feed:g1"}, set(ev)       # g2 is not a watched team; g3 is live with no odds, so it cannot be bet on and is left out
    assert ev["feed:g1"]["odds"] == {"home": 1.85, "away": 2.05}, ev["feed:g1"]   # the median across three bookmakers
    assert ev["feed:g1"]["status"] == "upcoming"
    assert ev["feed:g0"]["status"] == "final" and ev["feed:g0"]["winner"] == "home" and ev["feed:g0"]["home_score"] == 5
    assert doc["schema"] == "mke.odds_feed.v1" and doc["generated_utc"] == "2026-10-15T20:00:00Z"
    print("self-test ok: median odds, in-season filter, final result, games without odds left out")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "odds_feed_config.json")); ap.add_argument("--out", default="odds.json"); ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not KEY[0]:
        print("ODDS_API_KEY is not set: nothing to fetch (the game will show its simulated slate)"); return 2
    cfg = json.load(open(a.config))
    try:
        doc, usage = build(cfg, get, int(time.time()))
    except Exception as e:   # leave the previous file in place: the game treats an old file as stale
        print("fetch failed:", repr(e)); return 1
    # events with no odds yet and not final are dropped inside build(); a live game with no odds is not bettable
    tmp = a.out + ".tmp"; json.dump(doc, open(tmp, "w"), indent=1); os.replace(tmp, a.out)
    last = [u for _, _, u in usage if u.get("remaining")][-1:] or [{}]
    print(f"wrote {a.out}: {len(doc['events'])} events; credits remaining {last[0].get('remaining')} (used {last[0].get('used')})")
    return 0

if __name__ == "__main__":
    sys.exit(main())
