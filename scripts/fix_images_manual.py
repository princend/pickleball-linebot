import json

DATA_FILE = "data/paddles_data.json"
BAD_KEYWORDS = ["bag", "cover", "eraser", "grip", "gift card", "shirt", "tank", "apparel", "hat", "visor"]

with open(DATA_FILE, "r") as f:
    paddles = json.load(f)

updated = 0
for p in paddles:
    img = p.get("image_front", "")
    # Check if the image url is known to be a bag or non-paddle item.
    # The image URL for ronbus bag is bag2g1a0008.jpg
    if "bag" in img.lower() or "apparel" in img.lower() or "cover" in img.lower() or "shirt" in img.lower() or "tank" in img.lower():
        p["image_front"] = "https://images.unsplash.com/photo-1622227432807-91eb590c31bb?auto=format&fit=crop&w=400&q=80"
        updated += 1
        print(f"Fixed {p['name']} (was {img})")
        
with open(DATA_FILE, "w") as f:
    json.dump(paddles, f, ensure_ascii=False, indent=2)

print(f"Fixed {updated} paddles")
