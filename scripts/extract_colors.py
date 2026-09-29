import json
import urllib.request
from colorthief import ColorThief
import tempfile
import os
import colorsys

DATA_FILE = "data/paddles_data.json"

def get_best_color(palette):
    # Find the most vibrant color in the palette
    best_color = None
    max_saturation = -1
    
    for (r, g, b) in palette:
        h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
        # Ignore completely white or black backgrounds
        if v > 0.95 and s < 0.05: continue
        if v < 0.1: continue
        
        # We value saturation to find the actual accent color
        score = s * v
        if score > max_saturation:
            max_saturation = score
            best_color = (r, g, b)
            
    if best_color is None:
        best_color = palette[0]
        
    return best_color

def adjust_color(r, g, b):
    h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
    
    # Force a minimum saturation if it's not completely grayscale
    if s > 0.1:
        s = min(1.0, s * 1.5)
        
    # Ensure it's dark enough for white text (Value <= 0.7)
    v = min(0.65, v)
    
    # If it's too dark, brighten it up slightly so it doesn't look black
    v = max(0.3, v)

    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return "#{:02x}{:02x}{:02x}".format(int(r*255), int(g*255), int(b*255))

def main():
    with open(DATA_FILE, "r") as f:
        paddles = json.load(f)

    updated = 0
    for p in paddles:
        url = p.get("image_front")
        if not url:
            continue
            
        print(f"Extracting for {p['name']}...")
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    tmp.write(response.read())
                tmp_name = tmp.name
            
            color_thief = ColorThief(tmp_name)
            palette = color_thief.get_palette(color_count=6, quality=1)
            best_color = get_best_color(palette)
            hex_color = adjust_color(*best_color)
            p["theme_color"] = hex_color
            print(f" -> {hex_color}")
            updated += 1
            os.remove(tmp_name)
        except Exception as e:
            print(f" -> Error: {e}")
            
    if updated > 0:
        with open(DATA_FILE, "w") as f:
            json.dump(paddles, f, ensure_ascii=False, indent=2)
        print(f"Updated {updated} paddles with theme colors.")

if __name__ == "__main__":
    main()
