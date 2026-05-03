import os
import requests
import json

# Manually load .env easily
env_vars = {}
try:
    with open('.env', 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            if '=' in line:
                key, val = line.split('=', 1)
                env_vars[key.strip()] = val.strip().strip('"').strip("'")
except FileNotFoundError:
    print(".env file not found.")

host = env_vars.get('OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
api_key = env_vars.get('OLLAMA_API_KEY', '')
model = env_vars.get('OLLAMA_MODEL', 'nemotron-3-nano:30b-cloud')

url = f"{host}/api/generate"

headers = {}
if api_key:
    headers['Authorization'] = f"Bearer {api_key}"

prompt = """You are a structured data extractor and decision analyst.
Your job is to extract key attributes from unstructured venue descriptions,
build a comparison table, and recommend the top 3 venues based on the client's priorities.

Always return:
1. A markdown table with columns: Venue, Capacity, Approx. Price/Night, Catering, Outdoor, Parking, Vibe (1 word)
2. A ranked shortlist of top 3 venues with 1-sentence justification each
3. One sentence noting any venues you had to exclude due to missing information

Be concise. Do not invent data that is not in the descriptions.

Here are the couple's priorities:
- Budget: flexible, up to $15,000
- Guest count: ~200 people
- Vibe: elegant, grand
- Outdoor is a nice-to-have but not required
- No catering constraint

Here are descriptions of 16 venues. Please analyze and recommend.

Venue 1 — The Rosewood Estate
A sprawling property in the Hudson Valley with manicured gardens and a restored barn.
Capacity up to 175 guests. Rental fee is $17,500 Friday–Sunday. They have a preferred
catering list with 4 approved vendors. Outdoor ceremony space available with a rain
backup tent. Parking for ~80 cars on site.

Venue 2 — The Grand Metropolitan Hotel
Downtown ballroom, seats up to 300. In-house catering only. Pricing starts at $12,000
for the ballroom rental, catering packages extra. Valet parking. No outdoor space.

Venue 3 — Lakeview Pavilion
Outdoor lakeside pavilion. No indoor backup. BYOB catering. Fits about 90 people
comfortably, 110 at a squeeze. Very affordable — around $2,500 for a weekend.

Venue 4 — Thornfield Manor
Historic manor house, 8 acres. Exclusive use for the weekend. Price: $18,000.
In-house catering team. Ceremony can be held on the grounds or in the chapel.
Capacity 150. Featured in several bridal magazines.

Venue 5 — The Foundry at Millworks
Industrial-chic converted factory. Very trendy. Capacity 250. Bring your own vendors.
Rental is $5,000. Rooftop available for cocktail hour. No on-site parking — street
parking and nearby garage only.

Venue 6 — Sunrise Farm & Vineyard
Working vineyard with barn and outdoor ceremony terrace. Stunning views. Capacity 130.
Weekend rental $9,800. Catering through their in-house team or 2 approved vendors.
Ample parking. Very popular — books 18 months out.

Venue 7 — The Atrium Club
Corporate event space that does weddings on weekends. Very flexible on catering.
Fits 300+. Located downtown. Pricing on request — sales team says "typically $9,000–$14,000
depending on date." Not particularly romantic but very professional.

Venue 8 — Cedar Hollow Retreat
Rustic woodland lodge. Intimate and cozy. Max 60 guests. $3,200 for a Saturday.
Outside catering allowed. No formal parking lot — guests park in a field.

Venue 9 — The Belvedere
Upscale rooftop venue with skyline views. Indoor/outdoor setup. Capacity 180.
In-house catering required. Rental + minimum catering spend is $28,000.
Very elegant. Valet only.

Venue 10 — Harborside Event Center
Waterfront venue, brand new. Capacity 220. Pricing TBD — still finalizing packages.
Flexible on catering. Outdoor terrace available. Large parking lot.

Venue 11 — The Ivy House
Garden venue in a residential neighborhood. Permits outdoor ceremonies.
Capacity 100. $4,500 rental. BYOB catering. Street parking only — coordinator
recommends a shuttle from a nearby lot.

Venue 12 — Maple Ridge Country Club
Classic country club setting. Capacity 160. In-house catering only, known for
being very good. Rental from $28,500. Golf course backdrop for photos.
Ample parking. Private feel.

Venue 13 — The Glasshouse Conservatory
All-glass event space surrounded by botanical gardens. Very dramatic.
Capacity 140. $18,000 rental, catering open. Outdoor garden available for ceremonies.
Parking on site. Popular for spring weddings.

Venue 14 — Millbrook Inn
Country inn with event lawn. Venue rental $10,500. Capacity 120. Outside catering
allowed. Some overnight rooms available for wedding party. Very charming.

Venue 15 — The Warehouse District Loft
Raw, urban space. Very minimal. No catering kitchen. Capacity 200.
$8,800 rental. Not ideal for traditional weddings.

Venue 16 — Cloverfield Farms
Family-owned working farm. Barn + outdoor space. Capacity 135.
$6,000 Friday–Sunday. Preferred caterer list (3 vendors).
Casual, warm atmosphere. Lots of parking. Dogs welcome.
"""

payload = {
    "model": model,
    "prompt": prompt,
    "stream": False
}

try:
    print(f"Sending prompt to {url} using model {model}...")
    response = requests.post(url, headers=headers, json=payload, timeout=120)
    # Print the raw text if json parsing fails
    if response.status_code != 200:
        print(f"Failed with status code {response.status_code}: {response.text}")
    else:
        data = response.json()
        print("\n--- OLLAMA RESPONSE ---\n")
        print(data.get("response", ""))
except Exception as e:
    print(f"Error: {e}")
