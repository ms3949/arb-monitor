"""
Fetch live sports markets from Kalshi and Polymarket APIs.
Used by the Streamlit dashboard for market browsing and match validation.
"""
import json
import re
import requests
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed


KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA_API = "https://gamma-api.polymarket.com"


# ---------- Kalshi ----------

def fetch_kalshi_markets() -> list[dict]:
    """
    Fetch all open NCAAB game markets from Kalshi.
    Returns list of dicts with: event_ticker, tickers, title, home, away, date, display
    """
    results = []
    cursor = None
    seen_events = set()
    all_markets = []

    while True:
        params = {"series_ticker": "KXNCAAMBGAME", "status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get(f"{KALSHI_API}/markets", params=params, timeout=15)
            if r.status_code != 200:
                break
            data = r.json()
            markets = data.get("markets", [])
            if not markets:
                break
            all_markets.extend(markets)
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception as e:
            print(f"Kalshi fetch error: {e}")
            break

    # Group by event
    for m in all_markets:
        event_ticker = m.get("event_ticker", "")
        if event_ticker in seen_events:
            continue
        seen_events.add(event_ticker)

        title = m.get("title", "")
        home, away = _parse_kalshi_title(title)
        date = _parse_date_from_ticker(event_ticker)

        # Collect all tickers for this event
        tickers = [m2.get("ticker", "") for m2 in all_markets if m2.get("event_ticker") == event_ticker]

        results.append({
            "event_ticker": event_ticker,
            "tickers": tickers,
            "title": title,
            "home": home or "?",
            "away": away or "?",
            "date": date or "?",
            "display": f"{away} @ {home} ({date})" if home and away and date else title,
        })

    results.sort(key=lambda x: x.get("date", ""))
    return results


def _parse_kalshi_title(title: str):
    """Parse 'Away at Home Winner?' -> (home, away)"""
    m = re.search(r"(.+?)\s+at\s+(.+?)(?:\s+Winner|\s*\?|\s*$)", title, re.IGNORECASE)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    return None, None


def _parse_date_from_ticker(ticker: str) -> Optional[str]:
    """
    Parse date from Kalshi event ticker.
    Format: KXNCAAMBGAME-26MAR03DUKEUNC  ->  26=year_suffix, MAR=month, 03=day
    Result: 2026-03-03
    """
    m = re.search(r"(\d{2})([A-Z]{3})(\d{2})", ticker, re.IGNORECASE)
    if m:
        yr, mon, day = m.group(1), m.group(2).upper(), m.group(3)
        months = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
                  "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"}
        mm = months.get(mon)
        if mm:
            return f"20{yr}-{mm}-{day}"
    return None


# ---------- Polymarket ----------

def fetch_poly_markets(kalshi_games: list[dict] | None = None, progress_cb=None) -> list[dict]:
    """
    Fetch active CBB markets from Polymarket.
    Uses ThreadPoolExecutor for concurrent slug lookups (~5-10s for 65 games).
    progress_cb: optional callable(current, total) for progress reporting.
    """
    results = []
    if not kalshi_games:
        return results

    def _try_game(kg):
        """Try slug candidates for one Kalshi game. Returns poly market dict or None."""
        home = kg.get("home", "")
        away = kg.get("away", "")
        date = kg.get("date", "")
        if not home or not away or not date or date == "?":
            return None
        for slug in _build_slug_candidates(away, home, date):
            market = _try_poly_slug(slug)
            if market:
                return _parse_poly_market(market, slug)
        return None

    # Parallelize across games (10 workers)
    total = len(kalshi_games)
    done = 0
    with ThreadPoolExecutor(max_workers=10) as pool:
        future_to_game = {pool.submit(_try_game, kg): kg for kg in kalshi_games}
        for future in as_completed(future_to_game):
            done += 1
            if progress_cb:
                progress_cb(done, total)
            result = future.result()
            if result:
                results.append(result)

    results.sort(key=lambda x: x.get("date", ""))
    return results


def _build_slug_candidates(away_name: str, home_name: str, date: str) -> list[str]:
    """Build possible Polymarket slug variations for a game."""
    away_parts = _slug_variations(away_name)
    home_parts = _slug_variations(home_name)

    slugs = []
    for a in away_parts:
        for h in home_parts:
            slugs.append(f"cbb-{a}-{h}-{date}")
    # Also try reversed (some slugs are home-away)
    for h in home_parts:
        for a in away_parts:
            slugs.append(f"cbb-{h}-{a}-{date}")
    return slugs[:12]  # Cap at 12 attempts per game


def _slug_variations(name: str) -> list[str]:
    """
    Generate Polymarket slug abbreviation candidates from a team name.
    'Utah St.' -> ['utahst', 'usu']
    'Nebraska' -> ['nebr', 'nebraska', 'neb']
    """
    if not name:
        return []

    s = name.lower().strip()
    variations = []

    # Full collapsed (remove spaces, dots, apostrophes)
    collapsed = re.sub(r"[\s\.'\-]+", "", s)
    if len(collapsed) <= 8:
        variations.append(collapsed)
    else:
        variations.append(collapsed[:8])

    # Handle "St." -> "st" suffix
    if re.search(r"\bst\.?\s*$", s, re.IGNORECASE):
        base = re.sub(r"\bst\.?\s*$", "", s, flags=re.IGNORECASE).strip()
        collapsed_st = re.sub(r"[\s\.'\-]+", "", base) + "st"
        variations.append(collapsed_st[:8])

    # First 4 chars of first word (if multi-word)
    words = s.replace(".", "").split()
    if len(words) >= 2:
        short = words[0][:4] + words[1][:2]
        variations.append(short)
        # First word only
        if len(words[0]) >= 3:
            variations.append(words[0])

    # Just the first word truncated to 4
    if words:
        variations.append(words[0][:4])

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for v in variations:
        v = v.lower()
        if v and v not in seen:
            seen.add(v)
            unique.append(v)
    return unique[:5]


def _try_poly_slug(slug: str) -> Optional[dict]:
    """Fetch a Polymarket market by exact slug. Filters out settled/near-settled markets."""
    try:
        r = requests.get(f"{GAMMA_API}/markets", params={"slug": slug}, timeout=4)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                m = data[0]
                if m.get("active", True) and not m.get("closed", False):
                    # Filter out settled markets (any outcome price > 0.95)
                    prices_raw = m.get("outcomePrices")
                    if prices_raw:
                        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                        if prices and any(float(p) > 0.95 for p in prices):
                            return None  # Game is effectively settled
                    return m
    except Exception:
        pass
    return None


def _parse_poly_market(m: dict, slug: str = "") -> dict:
    """Parse a Polymarket market dict into our standard format."""
    slug = slug or m.get("slug", "")
    question = m.get("question", "")
    condition_id = m.get("conditionId", "")
    outcomes_raw = m.get("outcomes")
    outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else (outcomes_raw or [])
    clob_raw = m.get("clobTokenIds")
    clob_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else (clob_raw or [])

    date_match = re.search(r"(\d{4}-\d{2}-\d{2})$", slug)
    date = date_match.group(1) if date_match else "?"

    teams = [o for o in outcomes if o not in ("Over", "Under", "Yes", "No", "Draw")]

    return {
        "slug": slug,
        "question": question,
        "condition_id": condition_id,
        "clob_token_ids": clob_ids,
        "outcomes": outcomes,
        "teams": teams,
        "date": date,
        "display": question if question else slug,
    }


def _common_matchup_slugs():
    """Return empty — this is a placeholder for manual overrides."""
    return []


# ---------- Match Validation ----------

def validate_match(kalshi_game: dict, poly_game: dict) -> dict:
    """
    Check if a Kalshi game and Poly game refer to the same event.
    Returns {matched: bool, confidence: str, details: str, config: dict}
    """
    k_home = (kalshi_game.get("home") or "").lower()
    k_away = (kalshi_game.get("away") or "").lower()
    k_date = kalshi_game.get("date", "")

    p_date = poly_game.get("date", "")
    p_teams = [t.lower() for t in poly_game.get("teams", [])]
    p_question = (poly_game.get("question") or "").lower()

    # Date check
    date_match = k_date == p_date and k_date != "?"

    # Team matching
    def fuzzy_match(kalshi_name, poly_list, poly_q):
        if not kalshi_name:
            return False
        k_words = _significant_words(kalshi_name)
        for pt in poly_list:
            p_words = _significant_words(pt)
            if k_words & p_words:
                return True
        for w in k_words:
            if w in poly_q:
                return True
        return False

    home_match = fuzzy_match(k_home, p_teams, p_question)
    away_match = fuzzy_match(k_away, p_teams, p_question)

    matched = date_match and home_match and away_match

    if matched:
        confidence = "HIGH"
        details = "✅ Both teams and date match!"
    elif date_match and (home_match or away_match):
        matched = True
        confidence = "MEDIUM"
        team_found = "home" if home_match else "away"
        details = f"⚠️ Date matches, {team_found} team matched. Likely same game."
    elif home_match and away_match:
        matched = True
        confidence = "MEDIUM"
        details = f"⚠️ Teams match but dates differ (K:{k_date} vs P:{p_date})"
    else:
        confidence = "NONE"
        details = f"❌ No match. K: {k_away} @ {k_home} ({k_date}) | P: {', '.join(p_teams)} ({p_date})"

    config = {}
    if matched:
        tickers = kalshi_game.get("tickers", [])
        # Pick the ticker that matches the home team (Kalshi uses team suffix)
        k_home_short = re.sub(r"[\s\.'\']+", "", k_home).upper()[:6]
        kalshi_market_ticker = tickers[0] if tickers else ""
        for t in tickers:
            suffix = t.split("-")[-1].upper() if "-" in t else ""
            if suffix and (suffix in k_home_short or k_home_short in suffix):
                kalshi_market_ticker = t
                break

        # Match poly_outcome_index: find which Poly outcome matches the Kalshi home team
        poly_outcome_index = 0
        k_home_words = _significant_words(k_home)
        for i, o in enumerate(poly_game.get("outcomes", [])):
            o_words = _significant_words(o.lower())
            if k_home_words & o_words:
                poly_outcome_index = i
                break

        config = {
            "kalshi_market_ticker": kalshi_market_ticker,
            "kalshi_event_ticker": kalshi_game.get("event_ticker", ""),
            "kalshi_target_outcome": kalshi_game.get("home", ""),
            "poly_slug": poly_game.get("slug", ""),
            "poly_condition_id": poly_game.get("condition_id", ""),
            "poly_outcome_index": poly_outcome_index,
            "bolt_home": kalshi_game.get("home", ""),
            "bolt_away": kalshi_game.get("away", ""),
            "bolt_home_aliases": [kalshi_game.get("home", "")],
            "bolt_away_aliases": [kalshi_game.get("away", "")],
            "home_team": kalshi_game.get("home", ""),
            "away_team": kalshi_game.get("away", ""),
            "game_date": k_date,
        }

    return {
        "matched": matched,
        "confidence": confidence,
        "details": details,
        "config": config,
    }


def _significant_words(text: str) -> set:
    """Extract significant words for matching (skip noise words)."""
    if not text:
        return set()
    noise = {"at", "the", "of", "and", "vs", "winner", "?", "st.", "st", "state", "university"}
    words = set()
    for w in re.split(r"[\s\-\.]+", text.lower()):
        w = w.strip("?.!,'\"")
        if len(w) > 2 and w not in noise:
            words.add(w)
    return words
