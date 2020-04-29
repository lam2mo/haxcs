"""
    haxcs: an old-school roguelike with a computer science theme
    Copyright (C) 2018 Mike Lam

    This file contains the class that holds the entire game state, and includes
    a lot of "glue" code that ties together the rest of the files.

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import json
import os
import pickle
import random
import time

from floor import Floor
from fov import fieldOfView
from obj import Loot, Potion
from npc import NPC, Bug, Segfault, Spectre
from player import Player
from save import GenericJSONEncoder

HELP_TEXT = '''
        haxcs - an old-school roguelike with a computer science theme
                            written by Mike Lam

  Instructions: Explore the dungeon and find a way out, gaining as much XP and
                loot as you can along the way!

  Game controls:

    ?   help screen
    M   show message history
    S   save and quit
    Q   quit

  Movement (vi-keys):

      y  k  u
       \ | /
    h -- o -- l         Hold SHIFT to walk until stopped
       / | \\
      b  j  n

  Actions:

    o   open door (must then indicate direction)
    q   quaff a potion
    s   sleep for a turn
    <   go upstairs (must be on stairs)
    >   go downstairs (must be on stairs)
'''

DEFAULT_NUM_FLOORS   =  3
DEFAULT_FLOOR_WIDTH  = 80
DEFAULT_FLOOR_HEIGHT = 25

SAVEGAME_FILENAME    = ".savegame"
HISTORY_FILENAME     = ".history"
HALL_OF_FAME_SLOTS   = 10

class Game:
    '''
    Stores all information needed to track, display, save, and restore the state
    of a single game.
    '''

    def __init__(self, player=None):

        # generate first floor
        self.floors = [Floor.generate_basic_floor(DEFAULT_FLOOR_WIDTH,
                                                  DEFAULT_FLOOR_HEIGHT)]

        # generate other floors
        for i in range(1, DEFAULT_NUM_FLOORS):
            self.floors.append(Floor.generate_basic_floor(DEFAULT_FLOOR_WIDTH,
                                                          DEFAULT_FLOOR_HEIGHT,
                                                          self.floors[i-1].down))

        # close off top and bottom
        self.floors[ 0].set_base_pt(self.floors[ 0].up,   '.')
        self.floors[-1].set_base_pt(self.floors[-1].down, '.')

        # generate a random player if none is given
        if player is None:
            self.player = Player()
        else:
            self.player = player

        # place player on upstairs of floor of dungeon
        self.player.pos = self.floors[0].up

        # generate NPCs
        self.npcs = []
        Bug.generate(self)
        Segfault.generate(self)
        Spectre.generate(self)

        # generate loot and potions
        self.objs = []
        for f in range(len(self.floors)):
            for i in range(random.randrange(3,8)):
                self.objs.append(Loot(f, self.floors[f].random_point_in_room(),
                    random.randrange((f+1), 2*(f+1)+1)))
            for i in range(random.randrange(0,3)):
                self.objs.append(Potion(f, self.floors[f].random_point_in_room()))

        # victory square
        self.break_floor = DEFAULT_NUM_FLOORS-1
        self.break_pos = self.floors[self.break_floor].random_point_in_room()

        # game info
        self.cur_turn  = 1
        self.history = []
        self.set_status("Welcome! Press '?' for help text.")
        self.xray_vis  = False

        # starting visibility
        self.update_visibility()


    def run(self, screen):
        while self.player.hp > 0:

            # draw game screen
            self.render(screen)

            # grab user input
            c = screen.getch()
            cc = chr(c) if c in range(256) else '\0'

            # clear status message
            self.stat_msg = ""

            # help
            if cc == '?':
                screen.clear()
                screen.addstr(0, 0, HELP_TEXT)
                screen.getch()

            # show message history
            elif cc == 'M':
                screen.clear()
                screen.addstr(0,0, "Messages:")
                row = 2
                if len(self.history) > 20:
                    screen.addstr(row, 2, "[...]")
                    row += 1
                for msg in self.history[-20:]:
                    screen.addstr(row, 2, msg)
                    row += 1
                screen.getch()

            # save
            elif cc == 'S':
                f = open(SAVEGAME_FILENAME, "wb")
                pickle.dump(self, f, protocol=2)
                f.close
                self.add_status("Game saved.")
                break

            # quit
            elif cc == 'Q':
                self.set_status("Are you sure you want to quit? Press 'y' to confirm.")
                self.render(screen)
                if screen.getch() == ord('y'):
                    self.set_status("You quit.")
                    self.add_player_to_hof("quit")
                    break
                self.set_status("")
                self.render(screen)

            # dump
            elif cc == 'D':
                f = open(time.strftime("%Y_%m_%d-%H_%M_%M-") + self.player.name +
                        "-" + self.player.race + "-" + self.player.pclass + ".sav",
                        "w")
                json.dump(self, f, cls=GenericJSONEncoder, indent=2)
                f.close
                self.add_status("Game status dumped.")

            # enable x-ray vision
            elif cc == 'X':
                self.xray_vis = True
                self.add_status("H4XX0rz!!1")

            # player command
            else:
                self.player.handle_input(self, screen, c)

            # victory condition
            if self.player.hp > 0 and \
                    self.player.floor == self.break_floor and \
                    self.player.pos == self.break_pos:
                self.add_status("You found a break in the game loop! You win!")
                self.add_player_to_hof("won!")
                break

        # wait for final keypress (so player can see final status message)
        self.add_status("Press a key to exit.")
        self.render(screen)
        screen.getch()


    def render(self, screen):
        screen.clear()
        base = self.get_cur_floor().base

        # display game info
        field_height = len(base)
        screen.addstr(0, 0, self.stat_msg.ljust(DEFAULT_FLOOR_WIDTH))
        screen.addstr(field_height + 3, 0,
                self.player.name + ", Level " + str(self.player.level) + " " +
                self.player.pclass + " (" + self.player.race + ")")
        screen.addstr(field_height + 4, 0,
                "Turn "  + str(self.cur_turn).ljust(4) + "  Floor " +
                str(self.player.floor+1) + "  HP: " + str(self.player.hp) +
                "/" + str(self.player.max_hp) + "  XP: " + str(self.player.xp) +
                "/" + str(self.player.next_lvl) + "  Loot: $" + str(self.player.gp) +
                "  Potions: " + str(self.player.potions))

        # display knowledge previously gained from exploration
        for row in range(len(base)):
            for col in range(len(base[0])):
                screen.addstr(row+1, col, self.get_cur_floor().explored[row][col])

        # display visible game field
        for row in range(len(base)):
            for col in range(len(base[0])):
                if self.is_visible(row, col):
                    screen.addstr(row+1, col, base[row][col])

        # display victory square
        if self.player.floor == self.break_floor and \
                    self.is_visible(self.break_pos.row, self.break_pos.col):
            screen.addstr(self.break_pos.row+1, self.break_pos.col, "\\")

        # display objects
        for obj in self.objs:
            if obj.floor == self.player.floor and \
                    self.is_visible(obj.pos.row, obj.pos.col):
                screen.addstr(obj.pos.row+1, obj.pos.col, str(obj.glyph))

        # display NPCs
        for npc in self.npcs:
            if npc.floor == self.player.floor and \
                    self.is_visible(npc.pos.row, npc.pos.col):
                screen.addstr(npc.pos.row+1, npc.pos.col, str(npc.glyph))

        # display player and set final cursor position
        if self.player.hp > 0:
            screen.addstr(self.player.pos.row+1, self.player.pos.col, "@")
        screen.move(self.player.pos.row+1, self.player.pos.col)

        # refresh view
        screen.refresh()


    def next_turn(self):
        self.cur_turn += 1      # increment turn counter

        # run NPC AI routines
        for npc in self.npcs:
            if npc.floor == self.player.floor:
                npc.do_turn(self)

        # handle any object acquisition
        for obj in self.objs:
            if obj.floor == self.player.floor and obj.pos == self.player.pos:
                if isinstance(obj, Loot):
                    self.add_status("You picked up " + str(obj.amount) + " gold pieces.")
                    self.player.gp += obj.amount
                elif isinstance(obj, Potion):
                    self.add_status("You picked up a potion.")
                    self.player.potions += 1
                self.objs.remove(obj)

        # handle any leveling up
        self.player.level_up(self)

        # check for player death
        if self.player.hp <= 0:
            self.add_status("You died!")
            self.player.hp = 0
            self.add_player_to_hof("died")

        self.update_visibility()


    def set_status(self, msg):
        self.stat_msg = msg + " "
        self.history.append(msg)

    def add_status(self, msg):
        self.stat_msg += msg + " "
        self.history.append(msg)

    def get_cur_floor(self):
        return self.floors[self.player.floor]

    def get_cur_floor_base_pt(self, pt):
        return self.get_cur_floor().get_base_pt(pt)

    def npcs_at(self, floor, pos):
        npcs = []
        for npc in self.npcs:
            if npc.floor == floor and npc.pos == pos:
                npcs.append(npc)
        return npcs

    def no_npcs_at(self, floor, pos):
        return len(self.npcs_at(floor, pos)) == 0

    def nothing_at(self, floor, pos):
        return self.no_npcs_at(floor, pos) and not (self.player.pos == pos)

    def clear_visibility(self):
        self.visible = []
        for row in range(len(self.get_cur_floor().base)):
            line = [False] * len(self.get_cur_floor().base[0])
            self.visible.append(line)

    def update_visibility(self):
        self.clear_visibility()
        fieldOfView(self.player.pos.col, self.player.pos.row,
                len(self.get_cur_floor().base[0])-1,
                len(self.get_cur_floor().base)-1,
                self.player.vis_range,
                (lambda x, y: self.set_visible(y,x) ),
                (lambda x, y: self.get_cur_floor().base_blocks_vision(y,x) ))

    def set_visible(self, row, col):
        self.visible[row][col] = True
        self.get_cur_floor().explore(row, col)

    def is_visible(self, row, col):
        return self.xray_vis or self.visible[row][col]

    def add_player_to_hof(self, status):
        try:
            f = open(HISTORY_FILENAME, "rb")
            all_games = pickle.load(f)
            f.close()
        except IOError:
            all_games = []
        all_games.append([self.player.xp + self.player.gp, status, self.cur_turn,
                    self.player.name + " the level " + str(self.player.level) +
                    " " + self.player.race + " " + self.player.pclass,
                    self.xray_vis])
        f = open(HISTORY_FILENAME, "wb")
        pickle.dump(all_games, f, protocol=2)
        f.close()

    @staticmethod
    def print_hof():
        try:
            f = open(HISTORY_FILENAME, "rb")
            all_games = pickle.load(f)
            f.close()
        except IOError:
            all_games = []
        all_games.sort()
        all_games.reverse()
        print ("Hall of fame:")
        print (    "  %5s   %6s   %5s   %-50s   %s" % ("SCORE", "STATUS", "TURNS", "NAME", "CHEATED?"))
        for rec in all_games[:HALL_OF_FAME_SLOTS]:
            print ("  %5d   %6s   %5d   %-50s   %c" % (rec[0], rec[1], rec[2], rec[3],
                'X' if rec[4] else ' '))

    @staticmethod
    def load_savegame():
        try:
            f = open(SAVEGAME_FILENAME, "rb")
            game = pickle.load(f)
            f.close
            os.remove(SAVEGAME_FILENAME)
            return game
        except IOError:
            return None

