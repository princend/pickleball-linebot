from PIL import Image, ImageDraw, ImageFont
import urllib.request
import os

# Download a Chinese font (NotoSansTC)
font_url = "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Bold.otf"
font_path = "NotoSansCJKtc-Bold.otf"
if not os.path.exists(font_path):
    urllib.request.urlretrieve(font_url, font_path)

img = Image.new('RGB', (600, 600), color=(243, 244, 246)) # #F3F4F6
d = ImageDraw.Draw(img)

try:
    font = ImageFont.truetype(font_path, 64)
except IOError:
    font = ImageFont.load_default()

text = "尚無圖片"

# Get text bounding box
bbox = d.textbbox((0, 0), text, font=font)
text_w = bbox[2] - bbox[0]
text_h = bbox[3] - bbox[1]

x = (600 - text_w) / 2
y = (600 - text_h) / 2 - 20

d.text((x, y), text, font=font, fill=(161, 161, 170)) # #A1A1AA

os.makedirs("data/images", exist_ok=True)
img.save("data/images/no_image.png")
print("Saved data/images/no_image.png")
