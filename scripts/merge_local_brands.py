import json
import csv
import os

DATA_FILE = "data/paddles_data.json"
CSV_FILE = "data/local_brands.csv"

def determine_budget(price):
    if price < 1500: return "budget"
    elif price < 3500: return "intermediate"
    elif price < 6500: return "advanced"
    else: return "flagship"

def determine_style(title_l, desc_l):
    style_cat = "control"
    if any(w in title_l for w in ["power", "elongated", "fury", "cannon", "ignite"]):
        style_cat = "power"
    elif any(w in title_l for w in ["speed", "aero", "air", "swift", "glider", "flare"]):
        style_cat = "speed"
    elif any(w in title_l for w in ["spin", "grit", "ruby", "kevlar"]):
        style_cat = "spin"
    else:
        full_t = title_l + " " + desc_l
        p_score = sum(full_t.count(w) for w in ["power", "elongated", "smash", "drive", "pop"])
        s_score = sum(full_t.count(w) for w in ["speed", "aero", "aerodynamic", "fast", "quick", "maneuver"])
        sp_score = sum(full_t.count(w) for w in ["spin", "grit", "friction", "texture", "bite"])
        c_score = sum(full_t.count(w) for w in ["control", "precision", "soft", "touch", "forgiving", "sweet spot"])
        if "14mm" in title_l or "13mm" in title_l:
            p_score += 1
            s_score += 1
        elif "16mm" in title_l:
            c_score += 2
        scores = {"power": p_score, "speed": s_score, "spin": sp_score, "control": c_score}
        best_s = max(scores, key=scores.get)
        if scores[best_s] > 0:
            style_cat = best_s
    if style_cat in ["speed", "spin"]:
        style_cat = "all_around"
    return style_cat

def main():
    if not os.path.exists(DATA_FILE) or not os.path.exists(CSV_FILE):
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        paddles = json.load(f)

    # 讀取 CSV
    local_paddles = {}
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row["id"]
            price = int(row["price_ntd"])
            
            # 組裝球拍物件
            paddle_obj = {
                "id": pid,
                "name": row["name"],
                "brand": row["brand"],
                "price_ntd": price,
                "budget_category": determine_budget(price),
                "style_category": determine_style(row["name"].lower(), row["description"].lower()),
                "thickness": row["thickness"],
                "weight": row["weight"],
                "shape": row["shape"],
                "core": row["core"],
                "surface": row["surface"],
                "usapa_approved": row["usapa_approved"].upper() == "TRUE",
                "features": [
                    f"台灣實體通路 / 電商精選 {row['brand']} 球拍",
                    f"原廠官方說明：{row['description']}"
                ],
                "tags": [t.strip() for t in row["tags"].split(",") if t.strip()],
                "image_front": row["image_front"],
                "description": row["description"]
            }
            local_paddles[pid] = paddle_obj

    # 移除舊的 local paddles，以 CSV 為主
    paddles = [p for p in paddles if p["id"] not in local_paddles]

    # 加入 CSV 內所有的 paddles
    for pid, p_obj in local_paddles.items():
        paddles.append(p_obj)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(paddles, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
