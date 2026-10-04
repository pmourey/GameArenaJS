import sys
import math
from collections import defaultdict

def manhattan_distance(x1, y1, x2, y2):
    """Calcule la distance de Manhattan entre deux points"""
    return abs(x1 - x2) + abs(y1 - y2)

def find_nearest_pellet(pac_x, pac_y, pellets, assigned_targets):
    """Trouve le pellet le plus proche non assigné, en priorisant les super pellets"""
    best_pellet = None
    best_distance = float('inf')
    best_value = 0
    
    for (px, py, value) in pellets:
        if (px, py) in assigned_targets:
            continue
        
        distance = manhattan_distance(pac_x, pac_y, px, py)
        
        # Prioriser les super pellets (value=10) avec un bonus de distance
        effective_distance = distance - (value * 2)  # Super pellet vaut le détour
        
        if effective_distance < best_distance or (effective_distance == best_distance and value > best_value):
            best_pellet = (px, py, value)
            best_distance = effective_distance
            best_value = value
    
    return best_pellet

def explore_map(pac_x, pac_y, width, height, visited_positions, assigned_targets):
    """Trouve une position non visitée pour exploration"""
    best_pos = None
    best_distance = float('inf')
    
    # Chercher les coins et centre non visités
    explore_targets = [
        (width // 4, height // 4),
        (3 * width // 4, height // 4),
        (width // 4, 3 * height // 4),
        (3 * width // 4, 3 * height // 4),
        (width // 2, height // 2)
    ]
    
    for tx, ty in explore_targets:
        if (tx, ty) in assigned_targets or (tx, ty) in visited_positions:
            continue
        distance = manhattan_distance(pac_x, pac_y, tx, ty)
        if distance < best_distance:
            best_pos = (tx, ty)
            best_distance = distance
    
    # Si tous les points stratégiques sont visités, chercher aléatoirement
    if best_pos is None:
        import random
        for _ in range(10):
            tx = random.randint(1, width - 2)
            ty = random.randint(1, height - 2)
            if (tx, ty) not in assigned_targets:
                best_pos = (tx, ty)
                break
    
    return best_pos or (width // 2, height // 2)

# Initialisation
width, height = [int(i) for i in input().split()]
grid = []
for i in range(height):
    row = input()
    grid.append(row)

visited_positions = set()
turn_count = 0

# Boucle de jeu
while True:
    turn_count += 1
    my_score, opponent_score = [int(i) for i in input().split()]
    
    # Collecter les pacs
    my_pacs = []
    enemy_pacs = []
    visible_pac_count = int(input())
    
    for i in range(visible_pac_count):
        inputs = input().split()
        pac_id = int(inputs[0])
        mine = inputs[1] != "0"
        x = int(inputs[2])
        y = int(inputs[3])
        type_id = inputs[4]
        speed_turns_left = int(inputs[5])
        ability_cooldown = int(inputs[6])
        
        if mine:
            my_pacs.append({
                'id': pac_id,
                'x': x,
                'y': y,
                'type': type_id,
                'speed': speed_turns_left,
                'ability_cd': ability_cooldown
            })
            visited_positions.add((x, y))
        else:
            enemy_pacs.append({'id': pac_id, 'x': x, 'y': y, 'type': type_id})
    
    # Collecter les pellets
    pellets = []
    visible_pellet_count = int(input())
    
    for i in range(visible_pellet_count):
        x, y, value = [int(j) for j in input().split()]
        pellets.append((x, y, value))
    
    # Générer les commandes pour chaque pac
    commands = []
    assigned_targets = set()
    
    # Trier les pacs par ID pour cohérence
    my_pacs.sort(key=lambda p: p['id'])
    
    for pac in my_pacs:
        pac_id = pac['id']
        pac_x = pac['x']
        pac_y = pac['y']
        
        target = None
        
        # Stratégie 1: Chercher le pellet le plus proche
        if pellets:
            nearest = find_nearest_pellet(pac_x, pac_y, pellets, assigned_targets)
            if nearest:
                target = (nearest[0], nearest[1])
                assigned_targets.add(target)
                commands.append(f"MOVE {pac_id} {target[0]} {target[1]}")
                continue
        
        # Stratégie 2: Explorer la carte
        explore_target = explore_map(pac_x, pac_y, width, height, visited_positions, assigned_targets)
        assigned_targets.add(explore_target)
        commands.append(f"MOVE {pac_id} {explore_target[0]} {explore_target[1]}")
    
    # Envoyer toutes les commandes
    if commands:
        print(" | ".join(commands))
    else:
        print("MOVE 0 1 1")
