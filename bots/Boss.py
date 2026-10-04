"""Player bot template (stdin/stdout) for GameArena.

This skeleton reads the initial map (width, height, rows) once, then enters a
loop reading per-turn inputs and printing a single action.

The referee accepts a single-line action in one of the forms:
  - "MOVE <x> <y>"          (legacy)
  - "MOVE <pac_id> <x> <y>" (recommended: include pac id)

Note: "STAY" is NO LONGER allowed. To stay in place, use MOVE to your current position.

Example usage (print with flush=True):
  print(f"MOVE {pac_id} {px} {py}", flush=True)  # stay in place at (px, py)
  print("MOVE 0 3 2", flush=True)  # move pac id 0 to absolute coords (3,2)

Use stderr prints for debugging: print('dbg', file=sys.stderr, flush=True)

IMPROVEMENTS:
- Collision avoidance: predicts opponent's next move and avoids targeting the same pellet
- Chooses alternative targets when collision is likely
- Avoids moving to cells where opponent might move
"""
import sys

# --- init (read once)
# read width/height and the map rows (map lines are not used in this template,
# but are provided by the referee for completeness)
width, height = [int(i) for i in input().split()]
for _ in range(height):
    _ = input()

# --- optional persistent state
# memory = {}

def mdist(a, b):
    """Manhattan distance between two points."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def get_next_step(current, target, w, h):
    """Calculate the next step towards target using simple pathfinding.
    Returns the next position that is one step closer to target."""
    cx, cy = current
    tx, ty = target

    # Move horizontally if not aligned
    if cx < tx and cx + 1 < w:
        return (cx + 1, cy)
    elif cx > tx and cx - 1 >= 0:
        return (cx - 1, cy)
    # Move vertically if horizontally aligned or can't move horizontally
    elif cy < ty and cy + 1 < h:
        return (cx, cy + 1)
    elif cy > ty and cy - 1 >= 0:
        return (cx, cy - 1)

    return current

def predict_opponent_targets(opponent_pacs, pellets):
    """Predict which pellet each opponent pac is likely to target.
    Returns a set of pellet positions that opponents are likely heading to."""
    predicted_targets = set()

    for pac_id, mine, ox, oy in opponent_pacs:
        if pellets:
            # Assume opponent uses greedy strategy (nearest pellet)
            nearest = min(pellets, key=lambda p: mdist((ox, oy), (p[0], p[1])))
            predicted_targets.add((nearest[0], nearest[1]))

    return predicted_targets

def predict_opponent_next_positions(opponent_pacs, pellets, w, h):
    """Predict where each opponent pac will move next turn.
    Returns a set of positions where opponents might be next turn."""
    predicted_positions = set()

    for pac_id, mine, ox, oy in opponent_pacs:
        # Current position is dangerous
        predicted_positions.add((ox, oy))

        if pellets:
            # Predict they'll move toward nearest pellet
            nearest = min(pellets, key=lambda p: mdist((ox, oy), (p[0], p[1])))
            next_pos = get_next_step((ox, oy), (nearest[0], nearest[1]), w, h)
            predicted_positions.add(next_pos)

    return predicted_positions

def find_best_pellet(my_pos, pellets, opponent_predicted_targets, opponent_next_positions, w, h):
    """Find the best pellet to target, avoiding collisions.

    Strategy:
    1. Filter out pellets that opponents are likely targeting
    2. Filter out pellets where we'd collide on the next step
    3. Choose the nearest safe pellet
    """
    px, py = my_pos

    # Score each pellet
    pellet_scores = []
    for pellet in pellets:
        tx, ty = pellet[0], pellet[1]
        value = pellet[2]

        # Calculate distance
        dist = mdist((px, py), (tx, ty))

        # Check if opponent is targeting this pellet
        target_contested = (tx, ty) in opponent_predicted_targets

        # Calculate next step toward this pellet
        next_step = get_next_step((px, py), (tx, ty), w, h)

        # Check if our next step would collide with opponent's predicted position
        collision_risk = next_step in opponent_next_positions

        # Scoring: prefer closer, non-contested, non-collision pellets
        score = dist
        if target_contested:
            score += 50  # Heavy penalty for contested targets
        if collision_risk:
            score += 100  # Very heavy penalty for collision risk on next step

        pellet_scores.append((pellet, score))

    if pellet_scores:
        # Return pellet with lowest score (best choice)
        return min(pellet_scores, key=lambda x: x[1])[0]

    return None

# --- game loop
while True:
    # Read per-turn inputs
    my_score, opponent_score = [int(i) for i in input().split()]
    visible_pac_count = int(input())
    pacs = []  # list of tuples (pac_id, mine_bool, x, y)
    for _ in range(visible_pac_count):
        parts = input().split()
        pac_id = int(parts[0])
        mine = parts[1] != '0'
        x = int(parts[2]); y = int(parts[3])
        pacs.append((pac_id, mine, x, y))

    visible_pellet_count = int(input())
    pellets = []  # list of tuples (x,y,value)
    for _ in range(visible_pellet_count):
        x, y, value = [int(j) for j in input().split()]
        pellets.append((x, y, value))

    # --- Improved decision: avoid collisions with opponent
    my_pacs = [p for p in pacs if p[1]]
    opponent_pacs = [p for p in pacs if not p[1]]

    if my_pacs and pellets:
        pac0 = my_pacs[0]
        pac_id, _, px, py = pac0

        # Predict where opponents are heading
        opponent_predicted_targets = predict_opponent_targets(opponent_pacs, pellets)
        opponent_next_positions = predict_opponent_next_positions(opponent_pacs, pellets, width, height)

        # Find best pellet avoiding collisions
        best_pellet = find_best_pellet((px, py), pellets, opponent_predicted_targets,
                                       opponent_next_positions, width, height)

        if best_pellet:
            tx, ty = best_pellet[0], best_pellet[1]
            print(f"MOVE {pac_id} {tx} {ty}", flush=True)
            # Debug info (uncomment to see decision-making)
            # print(f"Target: ({tx},{ty}) | Opp targets: {opponent_predicted_targets} | Opp next: {opponent_next_positions}", file=sys.stderr, flush=True)
        else:
            # No safe pellet found, stay at current position
            print(f"MOVE {pac_id} {px} {py}", flush=True)
    else:
        # Nothing to do or no visible pellets - stay at current position
        if my_pacs:
            pac0 = my_pacs[0]
            pac_id, _, px, py = pac0
            print(f"MOVE {pac_id} {px} {py}", flush=True)
        else:
            # Fallback: send MOVE 0 0 0 (will likely be invalid but better than nothing)
            print("MOVE 0 0 0", flush=True)

