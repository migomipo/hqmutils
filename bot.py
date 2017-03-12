import hqm
import socket

from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
from twisted.internet import task

class HQMBot(DatagramProtocol):
    def __init__(self, host, port, team, name):
        self.team = team
        self.host = host
        self.port = port
        self.session = hqm.HQMClientSession(name, 55)
        self.syncing = True
               
    def run(self):
        reactor.listenUDP(0, self)
        reactor.run()
        
    def startProtocol(self):
        self.transport.connect(self.host, self.port)
        send = self.session.get_message()
        self.transport.write(send)
        
    def datagramReceived(self, data, addr):
        self.session.parse_message(data)
        if self.session.last_message_num == 0:
            self.syncing = False
        gamestate = self.session.gamestate    
        if not self.syncing and gamestate:
            you = gamestate.you
            you_player = gamestate.players.get(you)
            if you_player["team"] == -1: #Still spectating
                self.session.join_team(self.team)
                self.spectate()
            else:
                if you_player["team"] != self.team:
                    self.session.join_team(-1) # Back to spectator so we can switch team
                else:
                    self.session.join_team(None)                              
                self.action() #Let's do stuff
                
        send = self.session.get_message()
        self.transport.write(send)
        
    def spectate(self):
        pass
        
    def action(self):
        pass #Insert your code here
        
class TestBot(HQMBot):
    
    def action(self):
        session = self.session   
        # Session contains the current gamestate and some other useful functions such as add_chat
        gamestate = session.gamestate
        # Gamestate contains score, time, and a player and object list
        
        players = gamestate.players
        # A dictionary of all the players in the server. One of them is you
        # Each player object is a dictionary with the keys:
        #   name : The player name
        #      i : The player index
        #   team : The team this player is in.
        #                -1 is spectating
        #                 0 is red
        #                 1 is blue
        #     obj: The index of the player objects
        you = gamestate.you
        # An index that identifies who this bot is
        
        objects = gamestate.objects
        # A dictionary of all the objects in the server. These include both players and pucks.
        # For player objects, you need the player list to determine which object belongs to which player.
        # Each object is a dictonary. You need to run object.calculate_positions()
        # for each object to calculate some useful position data.
        # Both players and pucks have these keys:
        #   type       : Identifies the type, either the string PLAYER or the string PUCK
        #   pos        : The object position, a numpy array with 3 elements.
        #   rot        : The object rotation, a numpy 3x3 rotation matrix
        # Players object also have:
        #   stick_pos  : The stick position, a numpy array with 3 elements
        #   stick_rot  : The stick rotation, a numpy 3x3 rotation matrix
        #   head_rot   : Head rotation, left (-)/right (+), a float with rotation in radians
        #   body_rot   : Body rotation, backwards (-)/forwards (+), a float with rotation in radians
             
        pucks = []
        teammates = []
        opponents = []
        you = None
        
        for object in objects.values():
            object.calculate_positions()
            if object["type"] == "PUCK":
                pucks.append(object)
                
        you_player = players[gamestate.you]
        
        you_obj = objects[you_player["obj"]]
        
        for i, player in players.items():  
            if i==you or player["obj"] == -1: # If the player is you, or a spectator
                continue
            player_obj = objects[player["obj"]]

            if player["team"]==you_player["team"]:
                teammates.append(player_obj)
            else:
                opponents.append(player_obj)
         
            
        session.move_lr = 1        # Turn left/right, normal values are -1.0 (move left), 0 or 1.0 (move right)
        session.move_fwbw = 1.0    # Forwards/Backwards, normal values are -1.0 (backwards), 0 or 1.0 (forwards)
        #session.stick_x           # Stick left/right rotation, normal values are from -pi/2 (left) to pi/2 (right)
        #session.stick_y           # Stick up/down rotation, normal values are -0.98 (up) to 0.39 (down)
        #session.head_rot          # Head rotation, normal values are -2.74 (left) to 2.74 (right)
        #session.body_rot          # Body rotation, normal values are -pi/2 (backwards) to pi/2 (forwards)
        #session.jump = True       # Jump key
        #session.crouch = True     # Crouch key
        #session.shift = True      # Shift key        
        if gamestate.simstep%2000==500:
            session.add_chat("MigoBot")
           
