#!/usr/bin/env python3
"""
Système d'animation pour les Pacs basé sur les spritesheets blue.json et red.json

Ce script analyse les fichiers JSON des spritesheets et définit les animations
pour les différents types de pacs et états (vivant, mort, collision).
"""

import json
import os
import re
from typing import Dict, List, Tuple

class PacAnimationSystem:
    """Système de gestion des animations des Pacs"""

    def __init__(self):
        self.sprite_data = {}
        self.animations = {}

    def load_spritesheet(self, json_path: str, color: str):
        """Charge une spritesheet depuis un fichier JSON"""
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.sprite_data[color] = data
        print(f"Chargé spritesheet {color}: {len(data['frames'])} frames")

    def parse_frame_name(self, frame_name: str) -> Tuple[str, int, str, int]:
        """
        Parse un nom de frame selon les patterns:
        - mort_[color]_[type]_mort000[1-7]
        - paku_[color]_[type]_walk000[1-4]

        Returns: (color, type, animation_type, frame_number)
        """
        # Pattern pour frames de mort: mort_blue_2_mort0001
        mort_pattern = r'mort_(blue|red)_(\d+)_mort000(\d+)'
        mort_match = re.match(mort_pattern, frame_name)

        if mort_match:
            color, pac_type, frame_num = mort_match.groups()
            return color, int(pac_type), 'mort', int(frame_num)

        # Pattern pour frames de marche: paku_blue_1_walk0001
        walk_pattern = r'paku_(blue|red)_(\d+)_walk000(\d+)'
        walk_match = re.match(walk_pattern, frame_name)

        if walk_match:
            color, pac_type, frame_num = walk_match.groups()
            return color, int(pac_type), 'walk', int(frame_num)

        return None, None, None, None

    def build_animations(self):
        """Construit les définitions d'animation pour tous les types de pacs"""

        for color in ['blue', 'red']:
            if color not in self.sprite_data:
                continue

            frames = self.sprite_data[color]['frames']

            # Grouper les frames par type de pac et type d'animation
            pac_animations = {}

            for frame_name in frames.keys():
                color_parsed, pac_type, anim_type, frame_num = self.parse_frame_name(frame_name)

                if color_parsed != color:
                    continue

                if pac_type not in pac_animations:
                    pac_animations[pac_type] = {}

                if anim_type not in pac_animations[pac_type]:
                    pac_animations[pac_type][anim_type] = []

                pac_animations[pac_type][anim_type].append((frame_num, frame_name))

            # Trier les frames par numéro et créer les animations
            for pac_type in pac_animations:
                self.animations[f"{color}_{pac_type}"] = {}

                # Animation de marche (vivant)
                if 'walk' in pac_animations[pac_type]:
                    walk_frames = sorted(pac_animations[pac_type]['walk'])
                    walk_frame_names = [frame_name for _, frame_name in walk_frames]

                    # Animation normale: 8 frames (aller-retour)
                    normal_animation = walk_frame_names + walk_frame_names[::-1]
                    self.animations[f"{color}_{pac_type}"]['normal'] = {
                        'frames': normal_animation,
                        'duration': 8,  # 8 frames pour une animation complète
                        'loop': True
                    }

                    # Animation de collision: avancer et reculer
                    self.animations[f"{color}_{pac_type}"]['collision'] = {
                        'frames': walk_frame_names[:2] + walk_frame_names[:2][::-1],  # 1-2-2-1
                        'duration': 4,
                        'loop': False
                    }

                # Animation de mort
                if 'mort' in pac_animations[pac_type]:
                    mort_frames = sorted(pac_animations[pac_type]['mort'])
                    mort_frame_names = [frame_name for _, frame_name in mort_frames]

                    self.animations[f"{color}_{pac_type}"]['mort'] = {
                        'frames': mort_frame_names,
                        'duration': 7,  # 7 frames pour l'animation de mort
                        'loop': False
                    }

    def get_animation(self, pac_color: str, pac_type: int, animation_type: str) -> Dict:
        """Récupère une animation spécifique"""
        key = f"{pac_color}_{pac_type}"
        if key in self.animations and animation_type in self.animations[key]:
            return self.animations[key][animation_type]
        return None

    def generate_javascript_constants(self) -> str:
        """Génère le code JavaScript pour les constantes d'animation"""

        js_code = "// Constantes d'animation pour les Pacs\n"
        js_code += "// Généré automatiquement par pac_animation_builder.py\n\n"

        js_code += "export const PAC_ANIMATIONS = {\n"

        for pac_key, animations in self.animations.items():
            js_code += f"  {pac_key}: {{\n"

            for anim_type, anim_data in animations.items():
                frames_js = "[" + ", ".join(f'"{frame}"' for frame in anim_data['frames']) + "]"
                js_code += f"    {anim_type}: {{\n"
                js_code += f"      frames: {frames_js},\n"
                js_code += f"      duration: {anim_data['duration']},\n"
                js_code += f"      loop: {str(anim_data['loop']).lower()}\n"
                js_code += "    },\n"

            js_code += "  },\n"

        js_code += "};\n\n"

        # Ajouter les constantes de types
        js_code += "// Types de pacs par ligue\n"
        js_code += "export const PAC_TYPES = {\n"
        js_code += "  WOOD_BRONZE: 1,  // Type 1: ligues Wood et Bronze\n"
        js_code += "  SCISSOR: 2,      // Type 2: SCISSOR\n"
        js_code += "  PAPER: 3,        // Type 3: PAPER\n"
        js_code += "  ROCK: 4          // Type 4: ROCK\n"
        js_code += "};\n\n"

        # Ajouter les couleurs
        js_code += "// Couleurs disponibles\n"
        js_code += "export const PAC_COLORS = {\n"
        js_code += "  BLUE: 'blue',\n"
        js_code += "  RED: 'red'\n"
        js_code += "};\n\n"

        # Ajouter les types d'animation
        js_code += "// Types d'animation\n"
        js_code += "export const ANIMATION_TYPES = {\n"
        js_code += "  NORMAL: 'normal',    // Animation normale de déplacement\n"
        js_code += "  MORT: 'mort',        // Animation de mort\n"
        js_code += "  COLLISION: 'collision' // Animation de collision (avancer-reculer)\n"
        js_code += "};\n"

        return js_code

    def save_javascript_file(self, output_path: str):
        """Sauvegarde les constantes JavaScript dans un fichier"""
        js_code = self.generate_javascript_constants()

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(js_code)

        print(f"Fichier JavaScript sauvegardé: {output_path}")

def main():
    # Créer le système d'animation
    system = PacAnimationSystem()

    # Charger les spritesheets
    script_dir = os.path.dirname(os.path.abspath(__file__))
    frontend_dir = os.path.join(script_dir, 'frontend', 'public', 'sprites')

    blue_json = os.path.join(frontend_dir, 'blue.json')
    red_json = os.path.join(frontend_dir, 'red.json')

    if os.path.exists(blue_json):
        system.load_spritesheet(blue_json, 'blue')

    if os.path.exists(red_json):
        system.load_spritesheet(red_json, 'red')

    # Construire les animations
    system.build_animations()

    # Afficher un résumé
    print("\n=== RÉSUMÉ DES ANIMATIONS ===\n")
    for pac_key, animations in system.animations.items():
        print(f"Pac {pac_key}:")
        for anim_type, anim_data in animations.items():
            print(f"  {anim_type}: {len(anim_data['frames'])} frames, durée: {anim_data['duration']}, loop: {anim_data['loop']}")
        print()

    # Générer le fichier JavaScript
    output_js = os.path.join(script_dir, 'frontend', 'src', 'pac_animations.js')
    system.save_javascript_file(output_js)

    print("Système d'animation des Pacs créé avec succès!")

if __name__ == "__main__":
    main()