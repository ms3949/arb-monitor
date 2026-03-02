import asyncio
import websockets
import json
import csv
import os
import time
import base64
import hmac
import hashlib
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# --- Configuration ---
# User should fill these in .env
BOLT_KEY = os.getenv("BOLT_KEY")
KALSHI_KEY_ID = os.getenv("KALSHI_KEY_ID")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH") 
POLY_HOST = "wss://ws-poly.polymarket.com"


# --- Game Configuration ---
# CONFIGURATION FOR TONIGHT
# Optional: use kalshi_url + poly_url instead of ticker/slug; run: python url_to_ticker.py -k URL -p URL -c
CONFIG = {
    # Sam Houston vs Kennesaw State - resolved from URLs via url_to_ticker
    "SMHO_VS_KENN": {
        "kalshi_url": "https://kalshi.com/markets/kxncaambgame/mens-college-basketball-mens-game/kxncaambgame-26feb14shsukenn",
        "poly_url": "https://polymarket.com/sports/cbb/games/week/1/cbb-smho-kenest-2026-02-14",
        "kalshi_team_ticker": "SHSU",  # Sam Houston
        "kalshi_target_outcome": "Sam Houston Bearkats",
        "poly_outcome_index": 0,
    }
}


# Runtime resolved IDs
RESOLVED_IDS = {
    "poly_asset_ids": {}  # condition_id -> asset_id
}


def _bolt_team_match(home_feed, away_feed, home_target, away_target, cfg):
    """True if feed (home_feed, away_feed) matches CONFIG (home_target, away_target), including aliases."""
    def names_match(a, b):
        if not a or not b:
            return False
        a, b = a.strip(), b.strip()
        if a in b or b in a:
            return True
        return False

    def target_matches_feed(tgt, feed_side):
        if names_match(tgt, feed_side):
            return True
        aliases = cfg.get("bolt_home_aliases" if tgt == home_target else "bolt_away_aliases") or []
        return any(names_match(alt, feed_side) for alt in aliases)

    return (target_matches_feed(home_target, home_feed) and target_matches_feed(away_target, away_feed)) or \
           (target_matches_feed(home_target, away_feed) and target_matches_feed(away_target, home_feed))

import requests

def resolve_poly_ids():
    """Resolve poly_condition_id to CLOB asset_id via Gamma API."""
    print("Resolving Polymarket IDs...")
    for game, cfg in CONFIG.items():
        cond_id = (cfg.get("poly_condition_id") or "").strip()
        idx = cfg.get("poly_outcome_index", 0)
        if not cond_id:
            continue
        cond_id_norm = cond_id.lower()
        if not cond_id_norm.startswith("0x"):
            cond_id_norm = "0x" + cond_id_norm
        try:
            # Prefer slug when set (Gamma condition_id param often returns unrelated list)
            slug = cfg.get("poly_slug")
            if slug:
                try:
                    r = requests.get(f"https://gamma-api.polymarket.com/markets?slug={slug}", timeout=10)
                    if r.status_code == 200:
                        data_s = r.json()
                        ms = data_s if isinstance(data_s, list) else [data_s]
                        if ms:
                            m = ms[0]
                            raw = m.get("clobTokenIds")
                            if raw is not None:
                                clob_ids = json.loads(raw) if isinstance(raw, str) else raw
                                if clob_ids:
                                    # Subscribe to BOTH outcome tokens so we get price updates for the full market
                                    asset_ids = [str(aid) for aid in clob_ids]
                                    RESOLVED_IDS["poly_asset_ids"][cond_id] = asset_ids
                                    print(f"  {game}: Resolved via slug -> {len(asset_ids)} asset(s)")
                                    continue
                except Exception as e:
                    print(f"  {game}: Slug resolve error: {e}")

            # Fallback: try condition_id / conditionId params
            for param in ("condition_id", "conditionId"):
                url = f"https://gamma-api.polymarket.com/markets?{param}={cond_id}"
                resp = requests.get(url, timeout=10)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if not data:
                    continue
                markets = data if isinstance(data, list) else [data]
                market = None
                for m in markets:
                    cid = (m.get("conditionId") or m.get("condition_id") or "").strip().lower()
                    if cid and (cid == cond_id_norm or cid == cond_id.lower()):
                        market = m
                        break
                if not market and markets:
                    market = markets[0]
                if not market:
                    continue
                raw = market.get("clobTokenIds")
                if raw is None:
                    continue
                clob_ids = json.loads(raw) if isinstance(raw, str) else raw
                if not clob_ids:
                    print(f"  {game}: No clobTokenIds.")
                    continue
                asset_ids = [str(aid) for aid in clob_ids]
                RESOLVED_IDS["poly_asset_ids"][cond_id] = asset_ids
                print(f"  {game}: Resolved {cond_id[:10]}... -> {len(asset_ids)} asset(s)")
                break
            if cond_id not in RESOLVED_IDS["poly_asset_ids"]:
                # Fallback: resolve by slug (Gamma condition_id param often returns unrelated list)
                slug = cfg.get("poly_slug")
                if slug:
                    try:
                        url_slug = f"https://gamma-api.polymarket.com/markets?slug={slug}"
                        resp_s = requests.get(url_slug, timeout=10)
                        if resp_s.status_code == 200:
                            data_s = resp_s.json()
                            markets_s = data_s if isinstance(data_s, list) else [data_s]
                            if markets_s:
                                m = markets_s[0]
                                raw = m.get("clobTokenIds")
                                if raw is not None:
                                    clob_ids = json.loads(raw) if isinstance(raw, str) else raw
                                    if clob_ids:
                                        asset_ids = [str(aid) for aid in clob_ids]
                                        RESOLVED_IDS["poly_asset_ids"][cond_id] = asset_ids
                                        print(f"  {game}: Resolved via slug {slug[:40]}... -> {len(asset_ids)} asset(s)")
                    except Exception as e:
                        print(f"  {game}: Slug fallback error: {e}")
                if cond_id not in RESOLVED_IDS["poly_asset_ids"]:
                    print(f"  {game}: No market found for condition_id {cond_id[:16]}... (check poly_slug or Gamma)")
        except requests.RequestException as e:
            print(f"  {game}: Request error resolving Polymarket ID: {e}")
        except Exception as e:
            print(f"  {game}: Error resolving Polymarket ID: {e}")


def resolve_from_urls():
    """If CONFIG has kalshi_url + poly_url, resolve to ticker/slug/condition_id via url_to_ticker."""
    try:
        from url_to_ticker import validate_pair
    except ImportError:
        return
    for game, cfg in list(CONFIG.items()):
        k_url = cfg.get("kalshi_url")
        p_url = cfg.get("poly_url")
        if not k_url or not p_url:
            continue
        result = validate_pair(kalshi_url=k_url, poly_url=p_url)
        team = cfg.get("kalshi_team_ticker")
        snippet = result.to_config_snippet(team_ticker=team, bolt_key=BOLT_KEY)
        if snippet:
            CONFIG[game].update(snippet)
            print(f"  {game}: Resolved from URLs -> kalshi={snippet.get('kalshi_market_ticker')} poly_slug={snippet.get('poly_slug')}")

# --- Shared State ---
# Key: Game Name (e.g., "SUPER_BOWL")
# Value: { "Bolt_Home_Prob", "Bolt_Away_Prob", "Bolt_Home_Book", "Bolt_Away_Book", "Kalshi_Prob", "Poly_Prob", "updated_at" }
# Value: { "Bolt_Home_Prob", "Bolt_Away_Prob", "Bolt_Home_Book", "Bolt_Away_Book", "Kalshi_Prob", "Poly_Prob", "updated_at" }
LATEST_PRICES = {}

# Kalshi Local Order Books
# ticker -> { "bids": {price: size}, "asks": {price: size} }
KALSHI_BOOKS = {}

# Phase 1: Only log when |Bolt_Prob - Kalshi_Price| (or Poly) > this threshold (used when LOG_ALL_EVENTS is False)
DEVIATION_THRESHOLD = 0.05

# Log all event updates (Bolt, Kalshi, Poly) for robust analysis / Super Bowl; set False to log only >5% deviation
LOG_ALL_EVENTS = True

def initialize_shared_state():
    for game in CONFIG:
        LATEST_PRICES[game] = {
            "Bolt_Home_Prob": None,
            "Bolt_Away_Prob": None,
            "Bolt_Home_Book": None,
            "Bolt_Away_Book": None,
            "Kalshi_Prob": None,
            "Kalshi_Bid": None, "Kalshi_Bid_Size": None,
            "Kalshi_Ask": None, "Kalshi_Ask_Size": None,
            "Poly_Prob": None,
            "Poly_Bid": None, "Poly_Bid_Size": None,
            "Poly_Ask": None, "Poly_Ask_Size": None,
            "updated_at": 0
        }

# --- Helpers ---

def american_to_implied(odds):
    """
    Converts American Odds to Implied Probability (0.0 to 1.0).
    """
    try:
        odds = float(odds)
        if odds > 0:
            return 100 / (odds + 100)
        else:
            return (-odds) / (-odds + 100)
    except (ValueError, TypeError):
        return None


CSV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fsu_vt_live.csv")


def log_dislocation(game, trigger_source, team, bolt_implied_prob, bolt_sportsbook_source, kalshi_price, poly_price, spread_delta):
    """
    Phase 1: Log one row per dislocation event.
    Columns: timestamp, trigger_source, team, bolt_implied_prob, bolt_sportsbook_source, kalshi_price, poly_price, spread_delta
    """
    try:
        file_exists = os.path.isfile(CSV_FILE)
        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "timestamp", "trigger_source", "team", "bolt_implied_prob",
                    "bolt_sportsbook_source", "kalshi_price", "poly_price", "spread_delta",
                    "kalshi_bid", "kalshi_bid_size", "kalshi_ask", "kalshi_ask_size",
                    "poly_bid", "poly_bid_size", "poly_ask", "poly_ask_size"
                ])
            
            # Extract extended fields from LATEST_PRICES
            # (Note: This function is called with specific arguments, but we need the full snapshot 
            # for the extra fields. We will fetch them from LATEST_PRICES using 'game')
            
            prices = LATEST_PRICES.get(game, {})
            
            writer.writerow([
                datetime.now().isoformat(),
                trigger_source,
                team or "",
                bolt_implied_prob if bolt_implied_prob is not None else "",
                bolt_sportsbook_source or "",
                kalshi_price if kalshi_price is not None else "",
                poly_price if poly_price is not None else "",
                spread_delta,
                prices.get("Kalshi_Bid") or "", prices.get("Kalshi_Bid_Size") or "",
                prices.get("Kalshi_Ask") or "", prices.get("Kalshi_Ask_Size") or "",
                prices.get("Poly_Bid") or "", prices.get("Poly_Bid_Size") or "",
                prices.get("Poly_Ask") or "", prices.get("Poly_Ask_Size") or ""
            ])
            f.flush()
            os.fsync(f.fileno())
        b = f"{bolt_implied_prob:.3f}" if bolt_implied_prob is not None else "N/A"
        print(f"[ARB] Logged: {game} {team} | Bolt={b} Kalshi={kalshi_price} Poly={poly_price} spread={spread_delta:.3f}")
    except Exception as e:
        print(f"CSV write error: {e}")


def check_arbitrage(game, trigger_source):
    """
    When LOG_ALL_EVENTS: log every update (Bolt, Kalshi, Poly) for full timeline analysis.
    When False: log only on Bolt_Update when |Bolt_Prob - Kalshi/Poly| > DEVIATION_THRESHOLD.
    One row per event with kalshi_price and poly_price for comparison.
    """
    prices = LATEST_PRICES.get(game)
    if not prices:
        return

    cfg = CONFIG[game]
    k_prob = prices.get("Kalshi_Prob")
    p_prob = prices.get("Poly_Prob")

    # Kalshi target outcome (e.g. away team) -> we compare Bolt side for that team
    kalshi_target = cfg.get("kalshi_target_outcome")
    bolt_prob_k = None
    bolt_book_k = None
    team_k = None
    if kalshi_target == cfg.get("bolt_home"):
        bolt_prob_k = prices.get("Bolt_Home_Prob")
        bolt_book_k = prices.get("Bolt_Home_Book")
        team_k = cfg.get("bolt_home")
    elif kalshi_target == cfg.get("bolt_away"):
        bolt_prob_k = prices.get("Bolt_Away_Prob")
        bolt_book_k = prices.get("Bolt_Away_Book")
        team_k = cfg.get("bolt_away")

    # Spread vs Kalshi; spread vs Poly (Poly market is same side as Kalshi target, e.g. Seattle)
    spread_vs_kalshi = (bolt_prob_k - k_prob) if (bolt_prob_k is not None and k_prob is not None) else None
    bolt_prob_p = bolt_prob_k
    bolt_book_p = bolt_book_k
    spread_vs_poly = (bolt_prob_p - p_prob) if (bolt_prob_p is not None and p_prob is not None) else None

    # Pick representative spread_delta and side for this row (prefer Kalshi side)
    spread_delta = 0.0
    bolt_prob = bolt_prob_k
    bolt_book = bolt_book_k
    team = team_k or cfg.get("bolt_home") or ""
    if spread_vs_kalshi is not None:
        spread_delta = spread_vs_kalshi
    elif spread_vs_poly is not None:
        spread_delta = spread_vs_poly

    if LOG_ALL_EVENTS:
        # Log every event (Bolt, Kalshi, Poly) for full timeline and robust analysis
        log_dislocation(
            game,
            trigger_source,
            team,
            bolt_prob,
            bolt_book,
            k_prob,
            p_prob,
            spread_delta,
        )
        return

    # Log only when Bolt_Update and deviation > 5%
    if trigger_source != "Bolt_Update":
        return
    should_log = False
    if spread_vs_kalshi is not None and abs(spread_vs_kalshi) > DEVIATION_THRESHOLD:
        should_log = True
        spread_delta = spread_vs_kalshi
        bolt_prob, bolt_book, team = bolt_prob_k, bolt_book_k, team_k
    if spread_vs_poly is not None and abs(spread_vs_poly) > DEVIATION_THRESHOLD:
        if not should_log or abs(spread_vs_poly) > abs(spread_delta):
            should_log = True
            spread_delta = spread_vs_poly
            bolt_prob, bolt_book, team = bolt_prob_p, bolt_book_p, (cfg.get("bolt_home") or "")
    if should_log:
        log_dislocation(
            game,
            trigger_source,
            team,
            bolt_prob,
            bolt_book,
            k_prob,
            p_prob,
            spread_delta,
        )

# --- Clients ---


async def run_bolt_client():
    if not BOLT_KEY:
        print("Bolt WARNING: BOLT_KEY not set. Bolt client will not connect. Set BOLT_KEY in .env")
        while True:
            await asyncio.sleep(60)
    uri = f"wss://spro.agency/api?key={BOLT_KEY}"
    print(f"Connecting to Bolt: {uri.split('?')[0]}...")

    bolt_no_match_log_interval = 0  # log "no game matched" at most every 30 sec
    backoff = 1
    while True:
        try:
            async with websockets.connect(uri, max_size=None) as websocket:
                print("Bolt Connected.")
                ack = await websocket.recv()
                ack_str = ack.decode("utf-8") if isinstance(ack, bytes) else ack
                bolt_ack_error = False
                try:
                    ack_data = json.loads(ack_str)
                    for item in (ack_data if isinstance(ack_data, list) else [ack_data]):
                        if isinstance(item, dict) and item.get("action") == "error":
                            msg = item.get("message", "")
                            print(f"Bolt API error: {msg}")
                            if "concurrent connections" in msg.lower() or "max" in msg.lower():
                                print("  -> Close other Bolt connections (max 3 per account). Waiting 60s...")
                                await asyncio.sleep(60)
                            bolt_ack_error = True
                            break
                except (json.JSONDecodeError, TypeError):
                    pass
                if bolt_ack_error:
                    continue

                # Subscription - NFL; use exact format from GET get_info / get_markets (BoltOdds docs)
                sub_msg = {
                    "action": "subscribe",
                    "filters": {
                        "sports": ["NCAAB", "Basketball", "NCAA Basketball"],
                        "sportsbooks": ["draftkings", "pinnacle"],
                        "markets": ["Moneyline"]
                    }
                }
                await websocket.send(json.dumps(sub_msg))
                print("Bolt subscribed (NFL Moneyline, draftkings, pinnacle).")

                while True:
                    msg_txt = await websocket.recv()
                    now = time.time()
                    if bolt_no_match_log_interval > 0 and now - bolt_no_match_log_interval < 30:
                        pass  # skip verbose bolt msg when we're not matching
                    else:
                        print(f"Bolt msg: {msg_txt[:200]}...")
                    try:
                        raw_msg = json.loads(msg_txt)
                    except json.JSONDecodeError:
                        continue
                    
                    # Bolt sends list of messages or single dict; message has "action" and "data" (BoltOdds API)
                    messages = raw_msg if isinstance(raw_msg, list) else [raw_msg]
                    for msg in messages:
                        if not isinstance(msg, dict):
                            continue
                        if msg.get("action") == "ping":
                            continue
                        action = msg.get("action") or msg.get("type")
                        data = msg.get("data", {})
                        if action not in ("initial_state", "game_update", "line_update"):
                            continue
                        # Bolt data is one game: { home_team, away_team, outcomes, sportsbook, ... }
                        if isinstance(data, dict) and ("home_team" in data or "away_team" in data):
                            games = [data]
                        elif isinstance(data, list):
                            games = data
                        elif data.get("games"):
                            games = data["games"]
                        elif data.get("game"):
                            games = [data["game"]]
                        else:
                            games = []
                        if not games:
                            continue

                        # Log once per 30s if Bolt sends games but none match CONFIG (so user can align team names)
                        matched_any = False
                        for g in games:
                            home = g.get("home_team", "") or g.get("home_team_name", "")
                            away = g.get("away_team", "") or g.get("away_team_name", "")
                            for _gn, cfg in CONFIG.items():
                                if _bolt_team_match(home, away, cfg.get("bolt_home"), cfg.get("bolt_away"), cfg):
                                    matched_any = True
                                    break
                            if matched_any:
                                break
                        if not matched_any and games:
                            if bolt_no_match_log_interval == 0 or now - bolt_no_match_log_interval >= 30:
                                bolt_no_match_log_interval = now
                                g0 = games[0]
                                h0 = g0.get("home_team", "") or g0.get("home_team_name", "?")
                                a0 = g0.get("away_team", "") or g0.get("away_team_name", "?")
                                # DEBUG:
                                print(f"Bolt Seen: {h0} vs {a0}")
                                print(f"Bolt: No game matched CONFIG. CONFIG expects e.g. bolt_home/bolt_away. Example from feed: home={h0!r} away={a0!r}")

                        # Iterate over our configured games to check if this update is relevant
                        for game_name, cfg in CONFIG.items():
                            home_target = cfg.get("bolt_home")
                            away_target = cfg.get("bolt_away")

                            for g in games:
                                home = g.get("home_team", "") or g.get("home_team_name", "")
                                away = g.get("away_team", "") or g.get("away_team_name", "")

                                if not _bolt_team_match(home, away, home_target, away_target, cfg):
                                    continue

                                outcomes = g.get("outcomes", [])
                                home_odds = None
                                away_odds = None
                                home_book = g.get("sportsbook") or g.get("book") or g.get("source")
                                away_book = home_book or ""

                                if isinstance(outcomes, dict):
                                    outcomes_list = list(outcomes.values())
                                elif isinstance(outcomes, list):
                                    outcomes_list = outcomes
                                else:
                                    outcomes_list = []

                                def _label_matches_target(label, target, aliases_key):
                                    if not label:
                                        return False
                                    if target and (target in label or label in target):
                                        return True
                                    for alt in (cfg.get(aliases_key) or []):
                                        if alt and (alt in label or label in alt):
                                            return True
                                    return False

                                for oc in outcomes_list:
                                    if not isinstance(oc, dict):
                                        continue
                                    label = (oc.get("label") or oc.get("outcome_target") or "").strip()
                                    odds_val = oc.get("odds")
                                    book = oc.get("sportsbook") or oc.get("book") or oc.get("source") or home_book
                                    if odds_val is None or odds_val == "":
                                        continue
                                    if _label_matches_target(label, home_target, "bolt_home_aliases"):
                                        home_odds = odds_val
                                        if book:
                                            home_book = book
                                    elif _label_matches_target(label, away_target, "bolt_away_aliases"):
                                        away_odds = odds_val
                                        if book:
                                            away_book = book
                                updated = False
                                if home_odds:
                                    prob = american_to_implied(home_odds)
                                    current = LATEST_PRICES[game_name]["Bolt_Home_Prob"]
                                    if prob and current != prob:
                                        LATEST_PRICES[game_name]["Bolt_Home_Prob"] = prob
                                        LATEST_PRICES[game_name]["Bolt_Home_Book"] = home_book
                                        print(f"Bolt [{game_name}] Home ({home_target}): {home_odds} -> {prob:.3f}")
                                        updated = True
                                if away_odds:
                                    prob = american_to_implied(away_odds)
                                    current = LATEST_PRICES[game_name]["Bolt_Away_Prob"]
                                    if prob and current != prob:
                                        LATEST_PRICES[game_name]["Bolt_Away_Prob"] = prob
                                        LATEST_PRICES[game_name]["Bolt_Away_Book"] = away_book
                                        print(f"Bolt [{game_name}] Away ({away_target}): {away_odds} -> {prob:.3f}")
                                        updated = True
                                if updated:
                                    LATEST_PRICES[game_name]["updated_at"] = time.time()
                                    check_arbitrage(game_name, "Bolt_Update")

        except Exception as e:
            print(f"Bolt Connection Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

# Cryptography for Kalshi
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

def load_private_key(path):
    with open(path, "rb") as key_file:
        return serialization.load_pem_private_key(
            key_file.read(),
            password=None
        )

def sign_pss_text(private_key, text):
    message = text.encode('utf-8')
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')


async def run_kalshi_client():
    # UPDATED URL
    host = "wss://api.elections.kalshi.com"
    path = "/trade-api/ws/v2"
    uri = host + path
    print(f"Connecting to Kalshi: {uri}...")
    
    try:
        private_key = load_private_key(KALSHI_PRIVATE_KEY_PATH)
    except Exception as e:
        print(f"Failed to load Kalshi Private Key: {e}")
        return 

    backoff = 1
    while True:
        try:
           # Generate Headers for Handshake
           timestamp = str(int(time.time() * 1000))
           msg_string = timestamp + "GET" + path
           signature = sign_pss_text(private_key, msg_string)
           
           headers = {
               "KALSHI-ACCESS-KEY": KALSHI_KEY_ID,
               "KALSHI-ACCESS-SIGNATURE": signature,
               "KALSHI-ACCESS-TIMESTAMP": timestamp
           }
           
           async with websockets.connect(uri, additional_headers=headers) as websocket:
                print("Kalshi Connected.")
                
                # Subscribe to all configured tickers - ORDERBOOK
                for game_name, cfg in CONFIG.items():
                    ticker = cfg.get("kalshi_market_ticker")
                    if ticker:
                        # Init local book
                        KALSHI_BOOKS[ticker] = {"bids": {}, "asks": {}}
                        
                        sub_msg = {
                            "id": 2, 
                            "cmd": "subscribe", 
                            "params": {"channels": ["orderbook_delta"], "market_ticker": ticker}
                        }
                        await websocket.send(json.dumps(sub_msg))
                        print(f"Kalshi Subscribed to Orderbook: {ticker}")


                while True:
                    msg_txt = await websocket.recv()
                    msg = json.loads(msg_txt)
                    # DEBUG: Print raw message type/ticker to verify subscription
                    m_type = msg.get("type")
                    if m_type != "ping":
                         # print(f"Kalshi/Raw: {str(msg)[:1000]}")
                         pass

                    # Handle Snapshot and Delta
                    # msg type: "orderbook_snapshot" or "orderbook_delta" (or generic "channel_data"?)
                    # Kalshi V2: type="orderbook_snapshot" / "orderbook_delta"
                    
                    m_type = msg.get("type")
                    if m_type in ("orderbook_snapshot", "orderbook_delta"):
                        data = msg.get("msg", {})
                        ticker = data.get("market_ticker")
                        if not ticker: continue
                        
                        # Data format V2: "yes": [[price, qty], ...], "no": ...
                        # Or "bids"/"asks" if using a different API, but raw msg showed "yes" and "no".
                        yes_orders = data.get("yes") or data.get("bids") or []
                        no_orders = data.get("no") or data.get("asks") or []
                        
                        # Initialize Book
                        if ticker not in KALSHI_BOOKS:
                            KALSHI_BOOKS[ticker] = {"bids": {}, "asks": {}} # Asks derived from NO bids
                        
                        book = KALSHI_BOOKS[ticker]
                        
                        # Process YES orders -> Bids for Yes
                        for p, q in yes_orders:
                            if q == 0:
                                book["bids"].pop(p, None)
                            else:
                                book["bids"][p] = q
                                
                        # Process NO orders -> Asks for Yes
                        # Buying NO at P is equivalent to Selling YES at 100-P
                        # So a BID for NO at P becomes an ASK for YES at 100-P
                        for p, q in no_orders:
                            yes_ask_price = 100 - p
                            if q == 0:
                                book["asks"].pop(yes_ask_price, None)
                            else:
                                book["asks"][yes_ask_price] = q
                                
                    elif m_type == "orderbook_delta":
                        data = msg.get("msg", {})
                        ticker = data.get("market_ticker")
                        if not ticker: continue
                        
                        side = data.get("side") # "yes" or "no"
                        price = data.get("price")
                        delta = data.get("delta")
                        
                        if ticker not in KALSHI_BOOKS:
                            KALSHI_BOOKS[ticker] = {"bids": {}, "asks": {}}
                        book = KALSHI_BOOKS[ticker]
                        
                        if side == "yes":
                            new_qty = book["bids"].get(price, 0) + delta
                            if new_qty <= 0:
                                book["bids"].pop(price, None)
                            else:
                                book["bids"][price] = new_qty
                        elif side == "no":
                            yes_ask_price = 100 - price
                            new_qty = book["asks"].get(yes_ask_price, 0) + delta
                            if new_qty <= 0:
                                book["asks"].pop(yes_ask_price, None)
                            else:
                                book["asks"][yes_ask_price] = new_qty

                    # Determine Best Bid/Ask
                    if ticker in KALSHI_BOOKS:
                        book = KALSHI_BOOKS[ticker]
                        best_bid = max(book["bids"].keys()) if book["bids"] else None
                        best_ask = min(book["asks"].keys()) if book["asks"] else None
                        
                        bb_size = book["bids"][best_bid] if best_bid else None
                        ba_size = book["asks"][best_ask] if best_ask else None
                        
                        # Calculate Probability (Midpoint or Last Trade approx)
                        # We use midpoint for general tracking, but for Arb we prefer Best Offer if buying?
                        # For "Kalshi Price" field, let's keep it as Midpoint or Ask?
                        # Original code used "price" from ticker. 
                        # Let's use Midpoint.
                        
                        prob = None
                        if best_bid and best_ask:
                            prob = ((best_bid + best_ask) / 2.0) / 100.0
                        elif best_bid:
                            prob = float(best_bid) / 100.0
                        elif best_ask:
                            prob = float(best_ask) / 100.0
                            
                        if prob is not None:
                             # Find which game this belongs to
                            for game_name, cfg in CONFIG.items():
                                if cfg.get("kalshi_market_ticker") == ticker:
                                    # Update Liquidity Fields
                                    LATEST_PRICES[game_name]["Kalshi_Bid"] = best_bid
                                    LATEST_PRICES[game_name]["Kalshi_Bid_Size"] = bb_size
                                    LATEST_PRICES[game_name]["Kalshi_Ask"] = best_ask
                                    LATEST_PRICES[game_name]["Kalshi_Ask_Size"] = ba_size
                                    
                                    old_prob = LATEST_PRICES[game_name]["Kalshi_Prob"]
                                    if old_prob != prob:
                                        LATEST_PRICES[game_name]["Kalshi_Prob"] = prob
                                        LATEST_PRICES[game_name]["updated_at"] = time.time()
                                        print(f"Kalshi [{game_name}] Book: {ticker} {prob:.2f} | B:{best_bid}({bb_size}) A:{best_ask}({ba_size})")
                                        check_arbitrage(game_name, "Kalshi_Update")

        except Exception as e:
            print(f"Kalshi Connection Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


def _apply_poly_update(target_game, price_to_log, bid=None, bid_size=None, ask=None, ask_size=None):
    """Update shared state and log Poly_Update if price changed."""
    
    # Update Liquidity Fields
    if bid is not None: LATEST_PRICES[target_game]["Poly_Bid"] = bid
    if bid_size is not None: LATEST_PRICES[target_game]["Poly_Bid_Size"] = bid_size
    if ask is not None: LATEST_PRICES[target_game]["Poly_Ask"] = ask
    if ask_size is not None: LATEST_PRICES[target_game]["Poly_Ask_Size"] = ask_size

    old_prob = LATEST_PRICES[target_game]["Poly_Prob"]
    
    # If price_to_log is None, we might still want to update if we have new Bid/Ask info
    # But for now, we follow original logic for triggering update on prob change,
    # OR if we have significant book change. 
    # Let's verify if price_to_log is provided.
    
    should_log = False
    if price_to_log is not None and old_prob != price_to_log:
        LATEST_PRICES[target_game]["Poly_Prob"] = price_to_log
        should_log = True
        
    if should_log:
        LATEST_PRICES[target_game]["updated_at"] = time.time()
        print(f"Poly [{target_game}]: {price_to_log:.3f} | B:{bid}({bid_size}) A:{ask}({ask_size})")
        check_arbitrage(target_game, "Poly_Update")


def _poly_asset_to_game(asset_id):
    """Resolve asset_id to CONFIG game name."""
    for c_id, a_ids in RESOLVED_IDS["poly_asset_ids"].items():
        ids = a_ids if isinstance(a_ids, list) else [a_ids]
        if asset_id in ids:
            for gn, gcfg in CONFIG.items():
                if gcfg.get("poly_condition_id") == c_id:
                    return gn
    return None


def _poly_best_bid_ask(update):
    """Extract best bid/ask AND sizes from Polymarket event. Returns (bid, bid_size, ask, ask_size)."""
    event_type = update.get("event_type")
    
    if event_type == "book":
        bids = update.get("bids", []) or update.get("buys", [])
        asks = update.get("asks", []) or update.get("sells", [])
        
        bb = float(bids[0]["price"]) if bids else None
        bbs = float(bids[0]["size"]) if bids else None
        
        ba = float(asks[0]["price"]) if asks else None
        bas = float(asks[0]["size"]) if asks else None
        
        return bb, bbs, ba, bas
        
    if event_type == "best_bid_ask":
        # Check standard fields
        b = update.get("best_bid")
        a = update.get("best_ask")
        
        # Determine if size is present (common keys: best_bid_amount, size, etc)
        # We'll check likely keys
        bbs = float(update.get("best_bid_amount")) if update.get("best_bid_amount") else None
        bas = float(update.get("best_ask_amount")) if update.get("best_ask_amount") else None
        
        return (float(b) if b is not None else None, bbs, float(a) if a is not None else None, bas)
        
    return None, None, None, None


def _poly_price_changes(update):
    """For price_change events, yield (asset_id, best_bid, best_ask) for each affected asset."""
    for pc in update.get("price_changes", []):
        asset_id = pc.get("asset_id")
        # price_change msg usually only sends PRICE if it changed. 
        # But looking at Clob docs, it sends 'best_bid', 'best_ask' which are strings.
        # It does NOT guaranteed send size. But let's check.
        # Actually it's safer to rely on "book" or "best_bid_ask" for size.
        # If "price_change" is just minimal updates, we might miss size.
        # However, checking schemas: price_change event usually has sizes too if they changed?
        # Actually, let's look for 'bid_size' or 'ask_size' properties if they exist?
        # Often it is best_bid_amount or similar.
        # Without doc access, I will assume simple presence or skip.
        
        b = pc.get("best_bid")
        a = pc.get("best_ask")
        
        # Try to find sizes if available? (optimistic)
        # Assuming keys might be standard if present.
        # If not present, we pass None and state keeps old value? 
        # No, State isn't stateful enough here (we only process raw msg).
        # We'll just extract what we can.
        
        if asset_id and (b is not None or a is not None):
            yield asset_id, (float(b) if b else None), (float(a) if a else None)


async def run_poly_client():
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    print(f"Connecting to Polymarket: {uri}...")

    assets_to_sub = []
    for game, cfg in CONFIG.items():
        cond_id = cfg.get("poly_condition_id")
        if cond_id and cond_id in RESOLVED_IDS["poly_asset_ids"]:
            a_ids = RESOLVED_IDS["poly_asset_ids"][cond_id]
            ids = a_ids if isinstance(a_ids, list) else [a_ids]
            assets_to_sub.extend(ids)

    if not assets_to_sub:
        print("Polymarket WARNING: No assets resolved (resolve_poly_ids failed or wrong condition_id). Poly updates will not be logged.")

    backoff = 1
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print("Polymarket Connected.")
                # CLOB docs: send type "market" and assets_ids on connect
                if assets_to_sub:
                    sub_msg = {"type": "market", "assets_ids": assets_to_sub}
                    await websocket.send(json.dumps(sub_msg))
                    print(f"Poly Subscribed to {len(assets_to_sub)} assets.")

                while True:
                    msgs_txt = await websocket.recv()
                    if isinstance(msgs_txt, bytes):
                        msgs_txt = msgs_txt.decode("utf-8")
                    try:
                        raw = json.loads(msgs_txt)
                    except json.JSONDecodeError:
                        continue
                    updates = raw if isinstance(raw, list) else [raw]

                    for update in updates:
                        if not isinstance(update, dict):
                            continue
                        event_type = update.get("event_type")
                        if event_type not in ("book", "price_change", "best_bid_ask"):
                            continue

                        if event_type == "price_change":
                            for asset_id, best_bid, best_ask in _poly_price_changes(update):
                                target_game = _poly_asset_to_game(asset_id)
                                if not target_game:
                                    continue
                                price_to_log = (best_bid + best_ask) / 2 if (best_bid is not None and best_ask is not None) else (best_ask or best_bid)
                                if price_to_log is not None:
                                    # price_change doesn't give us reliable size, so pass None
                                    _apply_poly_update(target_game, price_to_log, bid=best_bid, ask=best_ask)
                            continue

                        asset_id = update.get("asset_id")
                        if not asset_id:
                            continue
                        target_game = _poly_asset_to_game(asset_id)
                        if not target_game:
                            continue
                            
                        best_bid, best_bid_size, best_ask, best_ask_size = _poly_best_bid_ask(update)
                        
                        price_to_log = None
                        if best_bid is not None and best_ask is not None:
                            price_to_log = (best_bid + best_ask) / 2
                        elif best_ask is not None:
                            price_to_log = best_ask
                        elif best_bid is not None:
                            price_to_log = best_bid
                            
                        # Pass even if price_to_log is None, mainly to update state
                        _apply_poly_update(target_game, price_to_log, 
                                           bid=best_bid, bid_size=best_bid_size,
                                           ask=best_ask, ask_size=best_ask_size)

        except Exception as e:
            print(f"Poly Connection Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

async def main():
    print("Starting Latency Arbitrage Logger...")
    print(f"  BOLT_KEY: {'set' if BOLT_KEY else 'NOT SET'}")
    print(f"  Kalshi: key and key path configured" if (KALSHI_KEY_ID and KALSHI_PRIVATE_KEY_PATH) else "  Kalshi: missing KEY_ID or PRIVATE_KEY_PATH")

    # 1. Resolve from URLs (if kalshi_url + poly_url in CONFIG)
    resolve_from_urls()
    # 2. Resolve Poly asset IDs
    resolve_poly_ids()
    n_poly = len(RESOLVED_IDS["poly_asset_ids"])
    print(f"  Polymarket: {n_poly} asset(s) resolved for subscription" + (" (update poly_condition_id if 0)" if n_poly == 0 else ""))

    # 3. Init State
    initialize_shared_state()

    # 4. Start Clients
    await asyncio.gather(
        run_bolt_client(),
        run_kalshi_client(),
        run_poly_client()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopping...")
