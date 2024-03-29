from __future__ import annotations
import argparse
import copy
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from time import sleep
from typing import Tuple, TypeVar, Type, Iterable, ClassVar, List
from multiprocessing import Pool
from queue import PriorityQueue
import random
import requests
import os

# maximum and minimum values for our heuristic scores (usually represents an end of game condition)
MAX_HEURISTIC_SCORE = 2000000000
MIN_HEURISTIC_SCORE = -2000000000
cwd = os.getcwd()

class UnitType(Enum):
    """Every unit type."""
    AI = 0
    Tech = 1
    Virus = 2
    Program = 3
    Firewall = 4

class Player(Enum):
    """The 2 players."""
    Attacker = 0
    Defender = 1

    def next(self) -> Player:
        """The next (other) player."""
        if self is Player.Attacker:
            return Player.Defender
        else:
            return Player.Attacker

class GameType(Enum):
    AttackerVsDefender = 0
    AttackerVsComp = 1
    CompVsDefender = 2
    CompVsComp = 3

##############################################################################################################

@dataclass(slots=True)
class Unit:
    player: Player = Player.Attacker
    type: UnitType = UnitType.Program
    health : int = 9
    # class variable: damage table for units (based on the unit type constants in order)
    damage_table : ClassVar[list[list[int]]] = [
        [3,3,3,3,1], # AI
        [1,1,6,1,1], # Tech
        [9,6,1,6,1], # Virus
        [3,3,3,3,1], # Program
        [1,1,1,1,1], # Firewall
    ]
    # class variable: repair table for units (based on the unit type constants in order)
    repair_table : ClassVar[list[list[int]]] = [
        [0,1,1,0,0], # AI
        [3,0,0,3,3], # Tech
        [0,0,0,0,0], # Virus
        [0,0,0,0,0], # Program
        [0,0,0,0,0], # Firewall
    ]

    def is_alive(self) -> bool:
        """Are we alive ?"""
        return self.health > 0

    def mod_health(self, health_delta : int):
        """Modify this unit's health by delta amount."""
        self.health += health_delta
        if self.health < 0:
            self.health = 0
        elif self.health > 9:
            self.health = 9

    def to_string(self) -> str:
        """Text representation of this unit."""
        p = self.player.name.lower()[0]
        t = self.type.name.upper()[0]
        return f"{p}{t}{self.health}"
    
    def __str__(self) -> str:
        """Text representation of this unit."""
        return self.to_string()
    
    def damage_amount(self, target: Unit) -> int:
        """How much can this unit damage another unit."""
        amount = self.damage_table[self.type.value][target.type.value]
        if target.health - amount < 0:
            return target.health
        return amount

    def repair_amount(self, target: Unit) -> int:
        """How much can this unit repair another unit."""
        amount = self.repair_table[self.type.value][target.type.value]
        if target.health + amount > 9:
            return 9 - target.health
        return amount

##############################################################################################################

@dataclass(slots=True)
class Coord:
    """Representation of a game cell coordinate (row, col)."""
    row : int = 0
    col : int = 0

    def col_string(self) -> str:
        """Text representation of this Coord's column."""
        coord_char = '?'
        if self.col < 16:
                coord_char = "0123456789abcdef"[self.col]
        return str(coord_char)

    def row_string(self) -> str:
        """Text representation of this Coord's row."""
        coord_char = '?'
        if self.row < 26:
                coord_char = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[self.row]
        return str(coord_char)

    def to_string(self) -> str:
        """Text representation of this Coord."""
        return self.row_string()+self.col_string()
    
    def __str__(self) -> str:
        """Text representation of this Coord."""
        return self.to_string()
    
    def clone(self) -> Coord:
        """Clone a Coord."""
        return copy.copy(self)      

    def iter_range(self, dist: int) -> Iterable[Coord]:
        """Iterates over Coords inside a rectangle centered on our Coord."""
        for row in range(self.row-dist,self.row+1+dist):
            for col in range(self.col-dist,self.col+1+dist):
                yield Coord(row,col)

    def iter_adjacent(self) -> Iterable[Coord]:
        """Iterates over adjacent Coords."""
        yield Coord(self.row-1,self.col)
        yield Coord(self.row,self.col-1)
        yield Coord(self.row+1,self.col)
        yield Coord(self.row,self.col+1)

    def iter_surrounding(self) -> Iterable[Coord]:
        """Iterates over surrounding coords."""
        yield Coord(self.row-1,self.col)    #left
        yield Coord(self.row,self.col-1)    #up
        yield Coord(self.row+1,self.col)    #right
        yield Coord(self.row,self.col+1)    #down
        yield Coord(self.row-1,self.col-1)  #up-left
        yield Coord(self.row-1,self.col+1)  #up-right
        yield Coord(self.row+1,self.col-1)  #down-left
        yield Coord(self.row+1,self.col+1)  #down-right

    @classmethod
    def from_string(cls, s : str) -> Coord | None:
        """Create a Coord from a string. ex: D2."""
        s = s.strip()
        for sep in " ,.:;-_":
                s = s.replace(sep, "")
        if (len(s) == 2):
            coord = Coord()
            coord.row = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".find(s[0:1].upper())
            coord.col = "0123456789abcdef".find(s[1:2].lower())
            return coord
        else:
            return None

##############################################################################################################

@dataclass(slots=True)
class CoordPair:
    """Representation of a game move or a rectangular area via 2 Coords."""
    src : Coord = field(default_factory=Coord)
    dst : Coord = field(default_factory=Coord)

    def to_string(self) -> str:
        """Text representation of a CoordPair."""
        return self.src.to_string()+" "+self.dst.to_string()
    
    def __str__(self) -> str:
        """Text representation of a CoordPair."""
        return self.to_string()

    def clone(self) -> CoordPair:
        """Clones a CoordPair."""
        return copy.copy(self)

    def reverse_move(self) -> CoordPair:
        """Reverses a move."""
        return CoordPair(self.dst,self.src)

    def iter_rectangle(self) -> Iterable[Coord]:
        """Iterates over cells of a rectangular area."""
        for row in range(self.src.row,self.dst.row+1):
            for col in range(self.src.col,self.dst.col+1):
                yield Coord(row,col)

    @classmethod
    def from_quad(cls, row0: int, col0: int, row1: int, col1: int) -> CoordPair:
        """Create a CoordPair from 4 integers."""
        return CoordPair(Coord(row0,col0),Coord(row1,col1))
    
    @classmethod
    def from_dim(cls, dim: int) -> CoordPair:
        """Create a CoordPair based on a dim-sized rectangle."""
        return CoordPair(Coord(0,0),Coord(dim-1,dim-1))
    
    @classmethod
    def from_string(cls, s : str) -> CoordPair | None:
        """Create a CoordPair from a string. ex: A3 B2"""
        s = s.strip()
        for sep in " ,.:;-_":
                s = s.replace(sep, "")
        if (len(s) == 4):
            coords = CoordPair()
            coords.src.row = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".find(s[0:1].upper())
            coords.src.col = "0123456789abcdef".find(s[1:2].lower())
            coords.dst.row = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".find(s[2:3].upper())
            coords.dst.col = "0123456789abcdef".find(s[3:4].lower())
            return coords
        else:
            return None

##############################################################################################################

@dataclass(slots=True)
class Options:
    """Representation of the game options."""
    dim: int = 5
    max_depth : int | None = 4
    min_depth : int | None = 2
    max_time : float | None = 5.0
    game_type : GameType = GameType.AttackerVsDefender
    alpha_beta : bool = True
    max_turns : int | None = 100
    randomize_moves : bool = True
    broker : str | None = None

##############################################################################################################

@dataclass(slots=True)
class Stats:
    """Representation of the global game statistics."""
    evaluations_per_depth : dict[int,int] = field(default_factory=dict)
    total_seconds: float = 0.0

##############################################################################################################

@dataclass(slots=True)
class Game:
    """Representation of the game state."""
    board: list[list[Unit | None]] = field(default_factory=list)
    next_player: Player = Player.Attacker
    turns_played : int = 0
    options: Options = field(default_factory=Options)
    stats: Stats = field(default_factory=Stats)
    _attacker_has_ai : bool = True
    _defender_has_ai : bool = True

    def __post_init__(self):
        """Automatically called after class init to set up the default board state."""
        dim = self.options.dim
        self.board = [[None for _ in range(dim)] for _ in range(dim)]
        md = dim-1
        self.set(Coord(0,0),Unit(player=Player.Defender,type=UnitType.AI))
        self.set(Coord(1,0),Unit(player=Player.Defender,type=UnitType.Tech))
        self.set(Coord(0,1),Unit(player=Player.Defender,type=UnitType.Tech))
        self.set(Coord(2,0),Unit(player=Player.Defender,type=UnitType.Firewall))
        self.set(Coord(0,2),Unit(player=Player.Defender,type=UnitType.Firewall))
        self.set(Coord(1,1),Unit(player=Player.Defender,type=UnitType.Program))
        self.set(Coord(md,md),Unit(player=Player.Attacker,type=UnitType.AI))
        self.set(Coord(md-1,md),Unit(player=Player.Attacker,type=UnitType.Virus))
        self.set(Coord(md,md-1),Unit(player=Player.Attacker,type=UnitType.Virus))
        self.set(Coord(md-2,md),Unit(player=Player.Attacker,type=UnitType.Program))
        self.set(Coord(md,md-2),Unit(player=Player.Attacker,type=UnitType.Program))
        self.set(Coord(md-1,md-1),Unit(player=Player.Attacker,type=UnitType.Firewall))

    def clone(self) -> Game:
        """Make a new copy of a game for minimax recursion.

        Shallow copy of everything except the board (options and stats are shared).
        """
        new = copy.copy(self)
        new.board = copy.deepcopy(self.board)
        return new
    
    def player_count_units(self, player: Player, unit_type: UnitType) -> int:
        mid_cell = Coord(2, 2)
        grid = mid_cell.iter_range(2)
        count = 0
        for cell in grid:
            if (
                self.get(cell) is not None
                and self.get(cell).type == unit_type
                and self.get(cell).player == player
            ):
                count += 1
        return count
    

    def is_adjacent_occupied(self, player, coord : Coord) -> bool:
        """Check if any adjacent cell of the game at Coord is occupied (must be valid coord)."""
        values = []
        for adj in coord.iter_adjacent():
            try:
                if self.is_valid_coord(adj):        #checks if valid coord
                    if self.is_empty(adj):          #checks if empty
                        values.append(True)         #appends true if empty
                    try:
                        if(player != self.get(adj).to_string()[0]):     #checks if the adjacent cell is occupied by the other player
                            values.append(False)                        #appends false if occupied by other player
                    except:
                        continue
            except:
                continue
        return not all(values)          #returns true if adjacent cells are occupied by other player 
        

    def valid_movement(self, attacker_or_defender, unit_type, src_row, dst_row, src_col, dst_col):
        dict_for_attacker_and_defender = {'a': ['A', 'F', 'P', 'T', 'V'], 'd': ['A', 'F', 'P', 'T', 'V']}
        
        units = dict_for_attacker_and_defender[attacker_or_defender]        
        for which_unit in units:
            if unit_type == which_unit:
                if which_unit == 'A' or which_unit == 'F' or which_unit == 'P':
                    if attacker_or_defender == 'a':
                        if(((dst_row <= src_row and dst_col < src_col) or (dst_col <= src_col and dst_row < src_row)) and not self.is_adjacent_occupied(attacker_or_defender, Coord(src_row, src_col))):
                            return True
                        else:
                            destination_unit = self.get(Coord(dst_row,dst_col))
                            if destination_unit and attacker_or_defender != destination_unit.to_string()[0] and ((dst_row <= src_row and dst_col < src_col) or (dst_col <= src_col and dst_row < src_row)):                               
                                return True
                            else:
                                return False
                    elif attacker_or_defender == 'd':
                        if(((dst_row <= src_row and dst_col > src_col) or (dst_col <= src_col and dst_row > src_row)) and not self.is_adjacent_occupied(attacker_or_defender, Coord(src_row, src_col))):
                            return True
                        else:
                            unit = self.get(Coord(dst_row,dst_col))
                            if unit and attacker_or_defender != unit.to_string()[0] and ((dst_row <= src_row and dst_col > src_col) or (dst_col <= src_col and dst_row > src_row)):                                
                                return True
                            else:                                
                                return False
                else:
                    return True


    def is_empty(self, coord : Coord) -> bool:
        """Check if contents of a board cell of the game at Coord is empty (must be valid coord)."""
        return self.board[coord.row][coord.col] is None

    def get(self, coord : Coord) -> Unit | None:
        """Get contents of a board cell of the game at Coord."""
        if self.is_valid_coord(coord):
            return self.board[coord.row][coord.col]
        else:
            return None

    def set(self, coord : Coord, unit : Unit | None):
        """Set contents of a board cell of the game at Coord."""
        if self.is_valid_coord(coord):
            self.board[coord.row][coord.col] = unit

    def remove_dead(self, coord: Coord):
        """Remove unit at Coord if dead."""
        unit = self.get(coord)
        if unit is not None and not unit.is_alive():
            self.set(coord,None)
            if unit.type == UnitType.AI:
                if unit.player == Player.Attacker:
                    self._attacker_has_ai = False
                else:
                    self._defender_has_ai = False

    def mod_health(self, coord : Coord, health_delta : int):
        """Modify health of unit at Coord (positive or negative delta)."""
        target = self.get(coord)
        if target is not None:
            target.mod_health(health_delta)
            self.remove_dead(coord)

    def is_valid_move(self, coords : CoordPair) -> bool:
        """Validate a move expressed as a CoordPair. TODO: WRITE MISSING CODE!!!"""
        if not self.is_valid_coord(coords.src) or not self.is_valid_coord(coords.dst):
            return False
        unit = self.get(coords.src)
        if unit is None or unit.player != self.next_player:
            return False
        unit = self.get(coords.dst)
        #logic for one step at a time here 
        if ( ((abs(coords.src.row - coords.dst.row)==1 and coords.dst.col == coords.src.col) or (abs(coords.src.col - coords.dst.col) == 1 and coords.dst.row == coords.src.row ))):
            return(Game.valid_movement(self, self.get(coords.src).to_string()[0], self.get(coords.src).to_string()[1], coords.src.row, coords.dst.row, coords.src.col, coords.dst.col))
        # logic for self killing or meaning entering the same coordinates like C4 C4
        elif(abs(coords.src.row - coords.dst.row)==0 and abs(coords.src.col - coords.dst.col) == 0):
            return True
        else:            
            return False
        # returns true is the dest attacker or dest defender is empty else returns false
        return (unit is None)


    def splash_damage(self, coord: Coord):
        """If this unit self-destructs, inflict splash damage (2 units) on units situated on the 8 surrounding tiles."""
        for adj in coord.iter_surrounding():
            try:
                if self.is_valid_coord(adj):        #checks if valid coord
                    if not self.is_empty(adj):          #checks if empty
                        self.mod_health(adj,-2)     #inflict 2 units of damage
            except:
                continue

        
    def perform_move(self, coords : CoordPair) -> Tuple[bool,str]:
        """Validate and perform a move expressed as a CoordPair. TODO: WRITE MISSING CODE!!!"""
        if self.is_valid_move(coords):
            # Retrieving the source and distance coordinates 
            source_coordinates = coords.src
            destination_coordinates = coords.dst
            # Retrieving the attacker and defender units from cordinates of source and attacker
            source_unit = self.get(source_coordinates)
            destination_unit = self.get(destination_coordinates)
            under_attack = False
            if source_unit is not None and destination_unit is not None and source_unit.player != destination_unit.player:
                under_attack = True
                # Calculate damage amounts
                src_damage = destination_unit.damage_amount(source_unit)
                dst_damage = source_unit.damage_amount(destination_unit)                
                # Inflict damage on both units
                self.mod_health(source_coordinates, -src_damage)
                self.mod_health(destination_coordinates, -dst_damage)

                # Check if units are destroyed and eliminate them from the board
                if self.get(source_coordinates) is not None and self.get(source_coordinates).health == 0:
                    self.set(source_coordinates, None)
                if self.get(destination_coordinates) is not None and self.get(destination_coordinates).health == 0:
                    self.set(destination_coordinates, None) 
            if not under_attack:
                if self.get(destination_coordinates) is not None and source_unit.player == destination_unit.player:
                    # checks if two players of the same team can repair each other or results in an invalid move
                    if self.get(source_coordinates) != self.get(destination_coordinates):
                        if(source_unit.to_string()[1] == 'A' or source_unit.to_string()[1] == 'T'):
                            if(source_unit.to_string()[1] == 'A' and (destination_unit.to_string()[1] != 'V' and destination_unit.to_string()[1] != 'T')):
                                return(False,"invalid move")
                            elif(source_unit.to_string()[1] == 'T' and (destination_unit.to_string()[1] != 'A' and destination_unit.to_string()[1] != 'F' and destination_unit.to_string()[1] != 'P')):
                                return(False,"invalid move")
                            else:
                                if(destination_unit.health >= 9):
                                    return(False,"invalid move!")
                                dst_repair = source_unit.repair_amount(destination_unit)
                                self.mod_health(destination_coordinates,+dst_repair)                            
                                return(True,"")     
                        else:
                            return(False,"invalid move")
                    # checks if for example AV9 is self killing or swaping with AV9 of other coordiante
                    elif self.get(source_coordinates) == self.get(destination_coordinates): 
                        self.splash_damage(coords.src)
                        self.remove_dead(source_coordinates)
                        if self.get(source_coordinates).type == UnitType.AI:
                            if self.get(source_coordinates).player == Player.Attacker:
                                self._attacker_has_ai = False
                            else:
                                self._defender_has_ai = False
                        self.is_finished()
                    else:
                        return(False,"invalid move")

                file_path = cwd + "/gameTrace-false-0-{self.options.max_turns}.txt"        
                with open(file_path,'a') as f:
                    f.write("Move from "+source_coordinates.to_string()+" to "+destination_coordinates.to_string()+"\n")
                self.set(coords.dst,self.get(coords.src))
                self.set(coords.src,None)
            return (True,"")
        file_path = cwd + "/gameTrace-false-0-{self.options.max_turns}.txt"        
        with open(file_path,'a') as f:
            f.write("Move from "+coords.src.to_string()+" to "+coords.dst.to_string()+"\n")
        return (False,"invalid move")

    def next_turn(self):
        """Transitions game to the next turn."""
        self.next_player = self.next_player.next()
        self.turns_played += 1  

    def to_string(self) -> str:
        """Pretty text representation of the game."""       
        dim = self.options.dim
        output = ""
        output += f"Next player: {self.next_player.name}\n"
        output += f"Turns played: {self.turns_played}\n"
        coord = Coord()
        output += "\n   "
        for col in range(dim):
            coord.col = col
            label = coord.col_string()
            output += f"{label:^3} "
        output += "\n"
        for row in range(dim):
            coord.row = row
            label = coord.row_string()
            output += f"{label}: "
            for col in range(dim):
                coord.col = col
                unit = self.get(coord)
                if unit is None:
                    output += " .  "
                else:
                    output += f"{str(unit):^3} "
            output += "\n"
        return output

    def __str__(self) -> str:
        """Default string representation of a game."""
        file_path = cwd + "/gameTrace-false-0-{self.options.max_turns}.txt"        
        with open(file_path,'a') as f:
            f.write(self.to_string()+"\n")
        return self.to_string()
    
    def is_valid_coord(self, coord: Coord) -> bool:
        """Check if a Coord is valid within out board dimensions."""
        dim = self.options.dim
        if coord.row < 0 or coord.row >= dim or coord.col < 0 or coord.col >= dim:
            return False
        return True

    def read_move(self) -> CoordPair:
        """Read a move from keyboard and return as a CoordPair."""
        while True:
            s = input(F'Player {self.next_player.name}, enter your move: ')
            coords = CoordPair.from_string(s)
            if coords is not None and self.is_valid_coord(coords.src) and self.is_valid_coord(coords.dst):
                return coords
            else:
                print('Invalid coordinates! Try again.')
    
    def human_turn(self):
        """Human player plays a move (or get via broker)."""
        if self.options.broker is not None:
            print("Getting next move with auto-retry from game broker...")
            while True:
                mv = self.get_move_from_broker()
                if mv is not None:
                    (success,result) = self.perform_move(mv)
                    print(f"Broker {self.next_player.name}: ",end='')
                    print(result)
                    if success:
                        self.next_turn()
                        break
                sleep(0.1)
        else:
            while True:
                mv = self.read_move()
                (success,result) = self.perform_move(mv)
                if success:
                    print(f"Player {self.next_player.name}: ",end='')
                    print(result)
                    self.next_turn()
                    break
                else:
                    print("The move is not valid! Try again.")                    
                    file_path = cwd + "/gameTrace-false-0-{self.options.max_turns}.txt"        
                    with open(file_path,'a') as f:
                        f.write("Move from "+str(mv.src)+" to "+str(mv.dst)+"\n")
                        f.write("The move is not valid! Try again. \n")

    def computer_turn(self) -> CoordPair | None:
        """Computer plays a move."""
        mv = self.suggest_move()
        if mv is not None:
            (success,result) = self.perform_move(mv)
            if success:
                print(f"Computer {self.next_player.name}: ",end='')
                print(result)
                self.next_turn()
        return mv

    def player_units(self, player: Player) -> Iterable[Tuple[Coord,Unit]]:
        """Iterates over all units belonging to a player."""
        for coord in CoordPair.from_dim(self.options.dim).iter_rectangle():
            unit = self.get(coord)
            if unit is not None and unit.player == player:
                yield (coord,unit)

    def is_finished(self) -> bool:
        """Check if the game is over."""
        return self.has_winner() is not None

    def has_winner(self) -> Player | None:
        """Check if the game is over and returns winner"""
        if self.options.max_turns is not None and self.turns_played >= self.options.max_turns:
            return Player.Defender
        if self._attacker_has_ai:
            if self._defender_has_ai:
                return None
            else:
                return Player.Attacker    
        return Player.Defender

    def move_candidates(self) -> Iterable[CoordPair]:
        """Generate valid move candidates for the next player."""
        move = CoordPair()
        for (src,_) in self.player_units(self.next_player):
            move.src = src
            for dst in src.iter_adjacent():
                move.dst = dst
                if self.is_valid_move(move):
                    yield move.clone()
            move.dst = src
            yield move.clone()

    def random_move(self) -> Tuple[int, CoordPair | None, float]:
        """Returns a random move."""
        move_candidates = list(self.move_candidates())
        random.shuffle(move_candidates)
        if len(move_candidates) > 0:
            return (0, move_candidates[0], 1)
        else:
            return (0, None, 0)

    def suggest_move(self) -> CoordPair | None:
        """Suggest the next move using minimax alpha beta. """
        start_time = datetime.now()
        depth = Options.max_depth
        abprune = Options.alpha_beta

        if self.next_player == Player.Attacker:
            maximizing_player = True
        else:
            maximizing_player = False
        
        best_move = self.minimax_suggest_move(maximizing_player, depth, abprune)

        # for unit in self.player_units(Player.Defender if maximizing_player else Player.Attacker):
        #     if unit[1].player != self.next_player:
        #         move = self.minimax_suggest_move(unit, depth, abprune)
        #         score = self.heuristic_combined()
        #         if maximizing_player and score > best_score:
        #             best_score = score
        #             best_unit = unit
        #             best_move = move
        #             alpha = max(alpha, best_score)
        #         elif not maximizing_player and score < best_score:
        #             best_score = score
        #             best_unit = unit
        #             best_move = move
        #             beta = min(beta, best_score)

        #         if abprune and beta <= alpha:
        #             break


        elapsed_seconds = (datetime.now() - start_time).total_seconds()
        self.stats.total_seconds += elapsed_seconds
        print(f"Heuristic score: {self.heuristic_combined():0.1f}")
        print(f"Evals per depth: ",end='')
        for k in sorted(self.stats.evaluations_per_depth.keys()):
            print(f"{k}:{self.stats.evaluations_per_depth[k]} ",end='')
        print()
        total_evals = sum(self.stats.evaluations_per_depth.values())
        if self.stats.total_seconds > 0:
            print(f"Eval perf.: {total_evals/self.stats.total_seconds/1000:0.1f}k/s")
        print(f"Elapsed time: {elapsed_seconds:0.1f}s")
        print(best_move)
        return best_move

    def minimax_suggest_move(self, maximizingPlayer: Player, depth: int, abprune: bool) -> CoordPair | None:
        """Suggest the next move for the given unit using minimax alpha beta."""
        _, best_move = self.minimax(depth=depth, alpha=MIN_HEURISTIC_SCORE, beta=MAX_HEURISTIC_SCORE, maximizing_player=maximizingPlayer, abprune=abprune)
        return best_move

    def post_move_to_broker(self, move: CoordPair):
        """Send a move to the game broker."""
        if self.options.broker is None:
            return
        data = {
            "from": {"row": move.src.row, "col": move.src.col},
            "to": {"row": move.dst.row, "col": move.dst.col},
            "turn": self.turns_played
        }
        try:
            r = requests.post(self.options.broker, json=data)
            if r.status_code == 200 and r.json()['success'] and r.json()['data'] == data:
                # print(f"Sent move to broker: {move}")
                pass
            else:
                print(f"Broker error: status code: {r.status_code}, response: {r.json()}")
        except Exception as error:
            print(f"Broker error: {error}")

    def get_move_from_broker(self) -> CoordPair | None:
        """Get a move from the game broker."""
        if self.options.broker is None:
            return None
        headers = {'Accept': 'application/json'}
        try:
            r = requests.get(self.options.broker, headers=headers)
            if r.status_code == 200 and r.json()['success']:
                data = r.json()['data']
                if data is not None:
                    if data['turn'] == self.turns_played+1:
                        move = CoordPair(
                            Coord(data['from']['row'],data['from']['col']),
                            Coord(data['to']['row'],data['to']['col'])
                        )
                        print(f"Got move from broker: {move}")
                        return move
                    else:
                        # print("Got broker data for wrong turn.")
                        # print(f"Wanted {self.turns_played+1}, got {data['turn']}")
                        pass
                else:
                    # print("Got no data from broker")
                    pass
            else:
                print(f"Broker error: status code: {r.status_code}, response: {r.json()}")
        except Exception as error:
            print(f"Broker error: {error}")
        return None

##############################################################################################################
############################################### D2 Related Code ##############################################
##############################################################################################################

    # e0 = (3VP1 + 3TP1 + 3FP1 + 3PP1 + 9999AIP1) − (3VP2 + 3TP2 + 3FP2 + 3PP2 + 9999AIP2)
    # where the variables represent the number of units left on the board for each type of unit
    # admissible, but not monotonic
    def heuristicE0(self) -> float:
            attacker_VP = 3 * self.player_count_units(Player.Attacker,UnitType.Virus)
            attacker_TP = 3 * self.player_count_units(Player.Attacker, UnitType.Tech)
            attacker_FP = 3 * self.player_count_units(Player.Attacker, UnitType.Firewall)
            attacker_PP = 3 * self.player_count_units(Player.Attacker, UnitType.Program)
            attacker_AIP = 9999 * self.player_count_units(Player.Attacker, UnitType.AI)

            defender_VP = 3 * self.player_count_units(Player.Defender, UnitType.Virus)
            defender_TP = 3 * self.player_count_units(Player.Defender, UnitType.Tech)
            defender_FP = 3 * self.player_count_units(Player.Defender, UnitType.Firewall)
            defender_PP = 3 * self.player_count_units(Player.Defender, UnitType.Program)
            defender_AIP = 9999 * self.player_count_units(Player.Defender, UnitType.AI)

            return (attacker_VP + attacker_TP + attacker_FP + attacker_PP + attacker_AIP) - (defender_VP + defender_TP + defender_FP + defender_PP + defender_AIP)

    # e1 = sum(di)
    # where di = distance of unit to opposing AI in number of steps (uses A* algorithm)
    # uses a worker pool to parallelize the computation of the shortest path
    # admissible, most informed, not monotonic (purposely not monotonic to allow V and T to backtrack as needed)
    def heuristicE1(self) -> float:
            player = self.player_units(self)
            opponent = self.player_units(self.next_player)
            start_coords = [unit[0] for unit in player if unit[1].is_alive()]
            end_coords = [unit[0] for unit in opponent if "AI" in unit[1].to_string()] * len(start_coords)
            paths = self.parallel_shortest_path(start_coords, end_coords)
            total_distance = sum(len(path) for path in paths if path is not None)
            return total_distance

    # e2 = (3AP1 + 9VP1 + 1TP1 + 1FP1 + 3PP1) − (3AP2 + 9VP2 + 1TP2 + 1FP2 + 3PP2)
    # where the numerical coefficients correspond to the damage that can be done to an AI unit by each type of unit
    # admissible, not monotonic
    def heuristicE2(self) -> float:

            attacker_VP = 9 * self.player_count_units(Player.Attacker, UnitType.Virus)
            attacker_TP = 1 * self.player_count_units(Player.Attacker, UnitType.Tech)
            attacker_FP = 1 * self.player_count_units(Player.Attacker, UnitType.Firewall)
            attacker_PP = 3 * self.player_count_units(Player.Attacker, UnitType.Program)
            attacker_AIP = 3 * self.player_count_units(Player.Attacker, UnitType.AI)

            defender_VP = 9 * self.player_count_units(Player.Defender, UnitType.Virus)
            defender_TP = 1 * self.player_count_units(Player.Defender, UnitType.Tech)
            defender_FP = 1 * self.player_count_units(Player.Defender, UnitType.Firewall)
            defender_PP = 3 * self.player_count_units(Player.Defender, UnitType.Program)
            defender_AIP = 3 * self.player_count_units(Player.Defender, UnitType.AI)

            return (attacker_VP + attacker_TP + attacker_FP + attacker_PP + attacker_AIP) - (defender_VP + defender_TP + defender_FP + defender_PP + defender_AIP)

    # # combined heuristic function
    # # TODO: adjust weights
    def heuristic_combined(self) -> float:
        e0_weight = 1.0     # least informed
        e1_weight = 5.0     # most informed
        e2_weight = 3.0     # semi informed
        e0_score = self.heuristicE0()
        e1_score = self.heuristicE1()
        e2_score = self.heuristicE2()
        combined_score = (e0_weight * e0_score + e1_weight * e1_score + e2_weight * e2_score) / (e0_weight + e1_weight + e2_weight)
        return combined_score


    def minimax(self, depth: int, alpha: float, beta: float, maximizing_player: bool, abprune: bool) -> Tuple[float, CoordPair | None]:
        if depth == 0 or self.is_finished():        # base case
            return self.heuristicE0(), None

        if maximizing_player:
            max_score = MAX_HEURISTIC_SCORE
            best_move = None
            with Pool() as pool:
                results = []
                for move in self.move_candidates():
                    self.perform_move(move)
                    result = pool.apply_async(self.minimax_worker(depth, alpha, beta, False, abprune))
                    self.perform_move(move.reverse_move())
                    results.append((move, result))

                for move, result in results:
                    score, _ = result.get()
                    if score > max_score:
                        max_score = score
                        best_move = move
                    alpha = max(alpha, max_score)

                    if abprune:     # checks if alpha-beta pruning is turned on or off
                        if beta <= alpha:
                            break
            return max_score, best_move
        else:
            min_score = MIN_HEURISTIC_SCORE
            best_move = None
            with Pool() as pool:
                results = []
                for move in self.move_candidates():
                    self.perform_move(move)
                    result = pool.apply_async(self.minimax_worker(depth, alpha, beta, True, abprune))
                    self.perform_move(move.reverse_move)
                    results.append((move, result))

                for move, result in results:
                    score, _ = result.get()
                    if score < min_score:
                        min_score = score
                        best_move = move
                    beta = min(beta, min_score)

                    if abprune:     # checks if alpha-beta pruning is turned on or off
                        if beta <= alpha:
                            break
            return min_score, best_move
        

    # Find the shortest path between two coordinates using the A* algorithm
    def shortest_path(self, start: Coord, end: Coord) -> List[Coord]:
        frontier = PriorityQueue()
        frontier.put(start, 0)
        came_from = {start: None}
        cost_so_far = {start: 0}

        while not frontier.empty():
            current = frontier.get()

            if current == end:
                break

            for next_coord in current.iter_neighbors():
                new_cost = cost_so_far[current] + 1
                if next_coord not in cost_so_far or new_cost < cost_so_far[next_coord]:
                    cost_so_far[next_coord] = new_cost
                    priority = new_cost + self.distance(end, next_coord)
                    frontier.put(next_coord, priority)
                    came_from[next_coord] = current

        if end not in came_from:
            return None

        path = []
        current = end
        while current != start:
            path.append(current)
            current = came_from[current]
        path.append(start)
        path.reverse()
        return path


    # Assigns a worker to each pair of start and end coordinates
    def shortest_path_worker(self, args):
        start, end = args
        return self.shortest_path(start, end)


    # Parallelize the computation of the shortest path
    def parallel_shortest_path(self, start_coords: List[Coord], end_coords: List[Coord]) -> List[List[Coord]]:
        with Pool() as pool:
            args = [(start, end) for start, end in zip(start_coords, end_coords)]
            paths = pool.map(self.shortest_path_worker, args)
        return paths


    # assigns a worker to each move candidate in minimax
    def minimax_worker(self, depth: int, alpha: float, beta: float, maximizing_player: bool, abprune: bool) -> Tuple[float, CoordPair | None]:
        return self.minimax(depth, alpha, beta, maximizing_player, abprune)

##############################################################################################################

def main():
    # parse command line arguments
    parser = argparse.ArgumentParser(
        prog='ai_wargame',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--max_depth', type=int, help='maximum search depth')
    parser.add_argument('--max_time', type=float, help='maximum search time')
    # Modified the input parameter for game_type
    parser.add_argument('--game_type', type=str, default="H-H", help='game type: AI-AI|H-AI|AI-H|H-H')
    parser.add_argument('--broker', type=str, help='play via a game broker')
    # Added the input parameter for max_turns
    parser.add_argument('--max_turns',type=int, help='Max Turns: Default is 100')
    # Added the input parameter for alpha_beta
    parser.add_argument('--alpha_beta',default=True,action='store_false',help='force the use of either minimax (FALSE) or alpha-beta (TRUE)')
    args = parser.parse_args()

    # parse the game type
    if args.game_type == "H-AI":
        game_type = GameType.AttackerVsComp
    elif args.game_type == "AI-H":
        game_type = GameType.CompVsDefender
    elif args.game_type == "H-H":
        game_type = GameType.AttackerVsDefender
    else:
        game_type = GameType.CompVsComp

    # set up game options
    options = Options(game_type=game_type)  

    # override class defaults via command line options
    if args.alpha_beta is not None:
        options.alpha_beta = args.alpha_beta
    if args.max_depth is not None:
        options.max_depth = args.max_depth
    if args.max_turns is not None:
        options.max_turns = args.max_turns
    if args.max_time is not None:
        options.max_time = args.max_time
    if args.broker is not None:
        options.broker = args.broker

    # Printing and writing max turns 
    print("Max Turns = "+str(options.max_turns))
    file_path = cwd + "/gameTrace-false-0-{self.options.max_turns}.txt"        
    with open(file_path,'a') as f:
        f.write("Max turns = "+str(options.max_turns) +"\n")

    # create a new game
    game = Game(options=options)

    # the main game loop
    while True:
        print()
        print(game)
        winner = game.has_winner()
        if winner is not None:
            print(f"{winner.name} wins! in {game.turns_played} turns ")
            file_path = cwd + "/gameTrace-false-0-{self.options.max_turns}.txt"        
            with open(file_path,'a') as f:  
                winner = winner.name
                f.write(winner+" wins! in "+ str(game.turns_played) + " turns")
            break
        if game.options.game_type == GameType.AttackerVsDefender:
            game.human_turn()
        elif game.options.game_type == GameType.AttackerVsComp and game.next_player == Player.Attacker:
            game.human_turn()
        elif game.options.game_type == GameType.CompVsDefender and game.next_player == Player.Defender:
            game.human_turn()
        else:
            player = game.next_player
            move = game.computer_turn()
            if move is not None:
                game.post_move_to_broker(move)
            else:
                print("Computer doesn't know what to do!!!")
                exit(1)

##############################################################################################################

if __name__ == '__main__':
    main()
