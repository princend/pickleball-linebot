import json

DATA_FILE = "data/paddles_data.json"

with open(DATA_FILE, "r") as f:
    paddles = json.load(f)

for p in paddles:
    if "PINKFRONT.png" in p.get("image_front", ""):
        p["image_front"] = "https://images.unsplash.com/photo-1622227432807-91eb590c31bb?auto=format&fit=crop&w=400&q=80"
        
with open(DATA_FILE, "w") as f:
    json.dump(paddles, f, ensure_ascii=False, indent=2)

