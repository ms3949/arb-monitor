import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

def find_poly_game(team1, team2):
    print(f"Searching Polymarket for {team1} or {team2}...")
    # Gamma API doesn't support fuzzy search well, need to page or use dedicated search endpoint if available.
    # Actually, try `events` endpoint with `slug` or `id` approach.
    # Or just iterate markets.
    
    url = "https://gamma-api.polymarket.com/events?limit=100&closed=false"
    try:
        r = requests.get(url)
        data = r.json()
        found = False
        for event in data:
            title = event.get("title", "")
            slug = event.get("slug", "")
            if (team1.lower() in title.lower() or team1.lower() in slug.lower()) and \
               (team2.lower() in title.lower() or team2.lower() in slug.lower()):
                print(f"FOUND POLYMARKET EVENT:")
                print(f"  Title: {title}")
                print(f"  Slug: {slug}")
                print(f"  ID: {event.get('id')}")
                # Get Markets in Event
                markets = event.get("markets", [])
                for m in markets:
                    print(f"    Market: {m.get('question')} (ID: {m.get('conditionId')})")
                found = True
        if not found:
            print("  No match found in top 100 events.")
    except Exception as e:
        print(f"Poly Error: {e}")

def find_kalshi_game(team1, team2):
    print(f"Searching Kalshi for {team1} or {team2}...")
    url = "https://api.elections.kalshi.com/trade-api/v2/markets?limit=1000&status=active"
    try:
        r = requests.get(url)
        data = r.json()
        markets = data.get("markets", [])
        found = False
        for m in markets:
            ticker = m.get("ticker", "")
            title = m.get("title", "")
            subtitle = m.get("subtitle", "")
            
            # Kalshi Basketball usually has titles like "Florida vs Kentucky"
            if (team1.lower() in title.lower() or team1.lower() in subtitle.lower()) and \
               (team2.lower() in title.lower() or team2.lower() in subtitle.lower()):
                 print(f"FOUND KALSHI MARKET:")
                 print(f"  Ticker: {ticker}")
                 print(f"  Title: {title}")
                 print(f"  Subtitle: {subtitle}")
                 found = True
        if not found:
             print("  No match found in active markets.")
    except Exception as e:
        print(f"Kalshi Error: {e}")

if __name__ == "__main__":
    # Search for nicknames
    print("--- Searching for Gators/Wildcats ---")
    find_poly_game("Gators", "Wildcats")
    find_kalshi_game("Gators", "Wildcats")
    
    print("\n--- Searching for Florida/Kentucky again (just in case) ---")
    find_poly_game("Florida", "Kentucky")
    find_kalshi_game("Florida", "Kentucky")
