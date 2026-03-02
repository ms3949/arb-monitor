import requests
import json

def get_kalshi_markets():
    print("Listing ALL open Kalshi markets (first 200)...")
    url = "https://api.elections.kalshi.com/trade-api/v2/markets?limit=200&status=open"
    r = requests.get(url)
    
    if r.status_code == 200:
        data = r.json()
        markets = data.get("markets", [])
        print(f"Fetched {len(markets)} markets.")
        
        found_count = 0
        for m in markets:
            title = m.get("title", "")
            ticker = m.get("ticker", "")
            subtitle = m.get("subtitle", "")
            
            # Broad filter
            if "NMSU" in title or "New Mexico" in title or "Jacksonville" in title or "NCAA" in title or "Basketball" in title:
                 print(f"MATCH: {ticker} | {title} | {subtitle}")
                 found_count += 1
        
        if found_count == 0:
            print("No NCAAB/NMSU markets found in the first 200 results.")
            
    else:
        print(f"Error fetching markets: {r.status_code}")

def get_poly_market():
    slug = "cbb-nmxst-jaxst-2026-02-14"
    print(f"\nFetching Polymarket for slug {slug}...")
    
    gamma_url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    try:
        r = requests.get(gamma_url)
        data = r.json()
        
        if isinstance(data, list) and len(data) > 0:
            event = data[0]
            print(f"Event Found: {event.get('title')}")
            mkts = event.get('markets', [])
            for m in mkts:
                group_item = m.get("groupItemTitle", "Unknown")
                question = m.get("question", "Unknown")
                print(f"  Poly Market: {m['conditionId']}")
                print(f"    Question: {question}")
                print(f"    Outcome: {group_item}")
                print(f"    TokenID: {m.get('clobTokenIds')}")
        else:
            print(f"No Poly data found for slug: {data}")

    except Exception as e:
        print(f"Poly Error: {e}")

if __name__ == "__main__":
    get_kalshi_markets()
    get_poly_market()
