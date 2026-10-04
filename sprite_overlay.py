#!/usr/bin/env python3
import json
from PIL import Image, ImageDraw, ImageFont

# Charger le JSON
with open('frontend/public/assets/sprites/tiles_no_padding.json', 'r') as f:
    data = json.load(f)

# Charger l'image
img = Image.open('frontend/public/assets/sprites/tiles_no_padding.png')
draw = ImageDraw.Draw(img)

# Police
try:
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
except:
    font = ImageFont.load_default()

# Dessiner le nom de chaque frame
for name, frame_data in data['frames'].items():
    frame = frame_data['frame']
    x, y, w, h = frame['x'], frame['y'], frame['w'], frame['h']
    
    # Texte centré
    text = str(name)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = x + (w - text_w) // 2
    text_y = y + (h - text_h) // 2
    
    # Fond noir pour lisibilité
    draw.rectangle([text_x - 2, text_y - 2, text_x + text_w + 2, text_y + text_h + 2], fill='black')
    draw.text((text_x, text_y), text, fill='yellow', font=font)

# Sauvegarder
img.save('tiles_overlay.png')
print("Image sauvegardée: tiles_overlay.png")
