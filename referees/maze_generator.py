"""Générateur de labyrinthe basé sur l'algorithme Tetris du Spring Challenge 2020."""
import random
from typing import List, Set, Tuple, Dict
from collections import deque


class TetrisPiece:
    """Pièce de Tetris pour générer le labyrinthe."""
    def __init__(self, blocks: Set[Tuple[int, int]]):
        self.blocks = blocks
        self.max_x = max(x for x, y in blocks)
        self.max_y = max(y for x, y in blocks)


class MazeGenerator:
    """Générateur de labyrinthe symétrique avec pièces Tetris."""
    
    def __init__(self):
        self.pieces: List[TetrisPiece] = []
        self._init_pieces()
    
    def _init_pieces(self):
        """Initialise les pièces de Tetris."""
        # Carré 2x2
        self.pieces.append(TetrisPiece({(0,0), (1,0), (0,1), (1,1)}))
        
        # L-shape et variations
        piece = TetrisPiece({(0,0), (0,1), (1,1)})
        self.pieces.extend([piece, self._flip_x(piece), self._flip_y(piece), self._transpose(piece)])
        
        # T-shape vertical
        piece = TetrisPiece({(0,0), (0,1), (1,1), (0,2)})
        self.pieces.extend([piece, self._flip_x(piece), self._transpose(piece), self._flip_y(self._transpose(piece))])
        
        # Croix
        self.pieces.append(TetrisPiece({(1,0), (0,1), (1,1), (2,1), (1,2)}))
        
        # T-shape horizontal et variations
        piece = TetrisPiece({(0,0), (0,1), (1,1), (2,1)})
        self.pieces.extend([
            piece, self._flip_x(piece), self._flip_y(piece),
            self._flip_x(self._flip_y(piece)),
            self._flip_x(self._flip_y(self._transpose(piece))),
            self._transpose(piece),
            self._flip_y(self._transpose(piece)),
            self._flip_x(self._transpose(piece))
        ])
    
    def _flip_x(self, piece: TetrisPiece) -> TetrisPiece:
        return TetrisPiece({(piece.max_x - x, y) for x, y in piece.blocks})
    
    def _flip_y(self, piece: TetrisPiece) -> TetrisPiece:
        return TetrisPiece({(x, piece.max_y - y) for x, y in piece.blocks})
    
    def _transpose(self, piece: TetrisPiece) -> TetrisPiece:
        return TetrisPiece({(y, x) for x, y in piece.blocks})
    
    def _piece_fits(self, piece: TetrisPiece, occupied: Set[Tuple[int, int]], pos: Tuple[int, int]) -> bool:
        """Vérifie si une pièce peut être placée."""
        for bx, by in piece.blocks:
            if (pos[0] + bx, pos[1] + by) in occupied:
                return False
        return True
    
    def _place_piece(self, piece: TetrisPiece, pos: Tuple[int, int], 
                     occupied: Set[Tuple[int, int]], 
                     block_origin: Dict[Tuple[int, int], Tuple[int, int]],
                     generated_pieces: Dict[Tuple[int, int], TetrisPiece]):
        """Place une pièce sur la grille."""
        generated_pieces[pos] = piece
        for bx, by in piece.blocks:
            block_pos = (pos[0] + bx, pos[1] + by)
            occupied.add(block_pos)
            block_origin[block_pos] = pos
    
    def generate_with_horizontal_symmetry(self, width: int, height: int, seed: int = None) -> List[List[str]]:
        """Génère un labyrinthe avec symétrie horizontale."""
        if seed is not None:
            random.seed(seed)
        
        # Générer la moitié gauche
        half_w = width // 2 + 1
        mini_grid = self._generate_base(half_w, height)
        
        # Créer la grille complète avec symétrie
        grid = [['#' for _ in range(width)] for _ in range(height)]
        
        for y in range(height):
            for x in range(half_w):
                if x < len(mini_grid[0]) and mini_grid[y][x] == ' ':
                    grid[y][x] = ' '
                    grid[y][width - x - 1] = ' '
        
        # Forcer les bordures haut et bas
        for x in range(width):
            grid[0][x] = '#'
            grid[height - 1][x] = '#'
        
        # Tunnels de wrapping : 1 cellule de hauteur avec murs au-dessus et en-dessous
        for x in [0, width - 1]:
            y = 1
            while y < height - 1:
                if grid[y][x] == ' ':
                    # Début d'un groupe de passages
                    start_y = y
                    while y < height - 1 and grid[y][x] == ' ':
                        y += 1
                    end_y = y - 1
                    
                    # Si le groupe fait plus d'1 cellule, garder seulement celle du milieu
                    if end_y > start_y:
                        mid_y = (start_y + end_y) // 2
                        for cy in range(start_y, end_y + 1):
                            if cy != mid_y:
                                grid[cy][x] = '#'
                        # Forcer murs au-dessus et en-dessous du tunnel
                        if mid_y > 0:
                            grid[mid_y - 1][x] = '#'
                        if mid_y < height - 1:
                            grid[mid_y + 1][x] = '#'
                else:
                    y += 1
        
        # Supprimer les îlots isolés APRES symétrie et tunnels
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🗺️ Détection des îlots après symétrie...")
        self._remove_islands(grid)
        logger.info(f"✅ Îlots nettoyés")
        
        return grid
    
    def _generate_base(self, width: int, height: int) -> List[List[str]]:
        """Génère la grille de base avec les pièces Tetris."""
        gen_w = width // 2 + 1
        gen_h = height // 2 + 1
        
        occupied: Set[Tuple[int, int]] = set()
        block_origin: Dict[Tuple[int, int], Tuple[int, int]] = {}
        generated_pieces: Dict[Tuple[int, int], TetrisPiece] = {}
        
        # Placer les pièces
        for y in range(gen_h):
            for x in range(gen_w):
                pos = (x, y)
                if pos not in occupied:
                    random.shuffle(self.pieces)
                    # Prendre la première pièce disponible, sauf si c'est la seule
                    available = [p for p in self.pieces if self._piece_fits(p, occupied, pos)]
                    if len(available) > 1:
                        piece = available[1]
                        self._place_piece(piece, pos, occupied, block_origin, generated_pieces)
        
        # Créer la grille finale
        grid = [['#' for _ in range(width)] for _ in range(height)]
        
        for y in range(1, gen_h):
            for x in range(1, gen_w):
                pos = (x, y)
                origin = block_origin.get(pos)
                grid_pos = (x * 2 - 1, y * 2 - 1)
                
                if origin and grid_pos[0] < width and grid_pos[1] < height:
                    piece = generated_pieces[origin]
                    block = (pos[0] - origin[0], pos[1] - origin[1])
                    
                    # Créer des couloirs entre les blocs (3 cellules de large)
                    for dx, dy in [(0, -1), (1, 0), (0, 1), (-1, 0)]:
                        adj = (block[0] + dx, block[1] + dy)
                        if adj not in piece.blocks:
                            for i in range(3):
                                if dx == 0:  # Vertical: couloir horizontal de 3 cellules
                                    cx, cy = grid_pos[0] - 1 + i, grid_pos[1] + dy
                                else:  # Horizontal: couloir vertical de 3 cellules
                                    cx, cy = grid_pos[0] + dx, grid_pos[1] - 1 + i
                                
                                if 0 <= cx < width and 0 <= cy < height:
                                    grid[cy][cx] = ' '
        
        return grid
    
    def _remove_islands(self, grid: List[List[str]]):
        """Supprime les îlots isolés (garde seulement la plus grande zone connectée)."""
        import logging
        logger = logging.getLogger(__name__)
        
        height = len(grid)
        width = len(grid[0])
        
        # Trouver toutes les zones connectées
        visited = set()
        islands = []
        
        for y in range(height):
            for x in range(width):
                if grid[y][x] == ' ' and (x, y) not in visited:
                    island = self._flood_fill(grid, x, y, visited)
                    islands.append(island)
        
        logger.info(f"🏝️ Trouvé {len(islands)} îlot(s)")
        
        # Garder seulement la plus grande île
        if islands:
            islands_sorted = sorted(islands, key=len, reverse=True)
            largest = islands_sorted[0]
            logger.info(f"🏆 Plus grande île: {len(largest)} cellules")
            if len(islands) > 1:
                removed = sum(len(isl) for isl in islands_sorted[1:])
                logger.info(f"🧹 Suppression de {len(islands)-1} îlot(s) ({removed} cellules)")
            
            for y in range(height):
                for x in range(width):
                    if grid[y][x] == ' ' and (x, y) not in largest:
                        grid[y][x] = '#'
    
    def _flood_fill(self, grid: List[List[str]], start_x: int, start_y: int, 
                    visited: Set[Tuple[int, int]]) -> Set[Tuple[int, int]]:
        """Remplit une zone connectée et retourne les coordonnées."""
        height = len(grid)
        width = len(grid[0])
        island = set()
        queue = deque([(start_x, start_y)])
        
        while queue:
            x, y = queue.popleft()
            if (x, y) in visited or x < 0 or x >= width or y < 0 or y >= height:
                continue
            if grid[y][x] != ' ':
                continue
            
            visited.add((x, y))
            island.add((x, y))
            
            for dx, dy in [(0, -1), (1, 0), (0, 1), (-1, 0)]:
                queue.append((x + dx, y + dy))
        
        return island
