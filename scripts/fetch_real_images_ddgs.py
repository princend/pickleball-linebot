import json
import time
from duckduckgo_search import DDGS

DATA_FILE = "data/paddles_data.json"

def get_image_url(paddle_name):
    query = f"{paddle_name} pickleball paddle"
    try:
        results = DDGS().images(
            keywords=query,
            region="wt-wt",
            safesearch="moderate",
            size="Wallpaper", # Try to get decent resolution
            max_results=3,
        )
        for r in results:
            url = r.get("image")
            if url and url.startswith("http") and ("unsplash" not in url):
                return url
    except Exception as e:
        print(f"Error fetching image for {paddle_name}: {e}")
    return None

def main():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        paddles = json.load(f)
        
    print(f"Loaded {len(paddles)} paddles. Starting DDGS search...")
    
    updated = 0
    # URLs we know are bad placeholders
    bad_urls = [
        "7c4fad2f-f7ff-4fd0-8627-edefac3f85f0", 
        "joola.tw/wp-content",
        "justpaddles.com",
        "unsplash.com"
    ]
    
    for p in paddles:
        needs_update = False
        current_img = p.get("image_front", "")
        
        for bad in bad_urls:
            if bad in current_img:
                needs_update = True
                break
                
        if needs_update or not current_img:
            print(f"Fetching image for {p['name']}...")
            new_url = get_image_url(p["name"])
            if new_url:
                p["image_front"] = new_url
                print(f" -> Found: {new_url}")
                updated += 1
            else:
                print(" -> No image found.")
            time.sleep(1) # Be nice to DDGS
            
    if updated > 0:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(paddles, f, ensure_ascii=False, indent=2)
        print(f"Successfully updated {updated} images!")
    else:
        print("No images needed updating or failed to fetch.")

if __name__ == "__main__":
    main()
