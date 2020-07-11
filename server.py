# Copyright © 2016-2017, John Eriksson
# https://github.com/migomipo/hqmutils
# See LICENSE for terms of use

from enum import Enum
import socket
import struct
import sys

from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
from twisted.internet import task
from bitparse import CSBitReader
from bitparse import CSBitWriter
import math
import numpy as np
from numba import jit

master_addr = "66.226.72.227"
master_port = 27590
master_server = (master_addr, master_port)

def calc_pos_int(pos):
    result = int(pos*1024)
    result = max(0, result)
    result = min(result, 131071)
    return result
    
start = np.array([[[ 0.,  1.,  0.],
                   [ 1.,  0.,  0.],
                   [ 0.,  0.,  1.]],

                  [[ 0.,  1.,  0.],
                   [ 0.,  0.,  1.],
                   [-1.,  0.,  0.]],

                  [[ 0.,  1.,  0.],
                   [ 0.,  0., -1.],
                   [ 1.,  0.,  0.]],

                  [[ 0.,  1.,  0.],
                   [-1.,  0.,  0.],
                   [ 0.,  0., -1.]],

                  [[ 0.,  0.,  1.],
                   [ 1.,  0.,  0.],
                   [ 0., -1.,  0.]],

                  [[-1.,  0.,  0.],
                   [ 0.,  0.,  1.],
                   [ 0., -1.,  0.]],

                  [[ 1.,  0.,  0.],
                   [ 0.,  0., -1.],
                   [ 0., -1.,  0.]],

                  [[ 0.,  0., -1.],
                   [-1.,  0.,  0.],
                   [ 0., -1.,  0.]]], dtype=np.float32)


@jit(nopython=True)
def calc_rot_vector(len, rot):
    

    result = 0
    if rot[0]<0:
        result |= 1
    if rot[2]<0:
        result |= 2
    if rot[1]<0:
        result |= 4
  
    a = start[result]
    for i in range(3, len, 2):
        temp = np.vstack((a[0]+a[1],a[1]+a[2],a[0]+a[2])) 
        temp /= np.sqrt(np.sum(temp**2, axis=1)) # temp = list of unit vectors
        
        temp2 = np.vstack((temp[1]-temp[0],temp[2]-temp[1],temp[0]-temp[2]))  # temp2 = list of vectors
        
        correct = np.dot(np.cross (temp2, rot-temp), rot) # list of vectors
        
        if correct[2]<0:  
            if correct[0]<0:
                if correct[1]<0:
                    result |= 3<<i
                    a = temp
                else:
                    result |= 2<<i
                    a = np.vstack((temp[2], temp[1], a[2]))                   
            else:
                result |= 1<<i
                a = np.vstack((temp[0], a[1], temp[1]))
        else:
            a = np.vstack((a[0], temp[0], temp[2]))
    return result
        
        
class HQMServerStatus(Enum):
    offline = 0
    online = 1
 
class HQMTeam(Enum):
    spec = -1
    red = 0
    blue = 1       
        

class Message():
    pass

class JoinExitMessage(Message): 
    def __init__(self, player, status):
        self.i = player.i
        self.status = status
        self.team = player.team
        self.name = player.name
        self.obj = player.obj
 
    def write(self, bw):
        bw.write_unsigned(6, 0) # Type
        bw.write_unsigned(6, self.i) #Player ID
        bw.write_unsigned(1, self.status.value) # On or offline
        bw.write_unsigned(2, self.team.value) #Team
        obj_i = -1 if self.obj is None else self.obj.obj_i
        bw.write_unsigned(6, obj_i) #Object index
        name_bytes = self.name[0:31].ljust(31, b"\0")
        for b in name_bytes:
            bw.write_unsigned(7, b)
            
class ChatMessage(Message): 

    def __init__(self, i, message):
        self.i = i
        self.message = message
 
    def write(self, bw):
        bw.write_unsigned(6, 2) #type
        size = len(self.message)
        if size > (1<<6)-1:
            size = (1<<6)-1           
        message = self.message[0:size]
        bw.write_unsigned(6, self.i)
        bw.write_unsigned(6, size)       
        for b in message:
            bw.write_unsigned(7, b)
 
class HQMObject():
    def __init__(self):
        self.pos = None # Position vector
        self.rot = None # Rotation matrix
        self.obj_i = None
        self.type_num = None
        
    def calculateRotData (self):
        self.pos_int = [calc_pos_int(self.pos[i]) for i in range(3)]
        self.rot_int = [calc_rot_vector(31, c) for c in self.rot.T[1:3]]
        
    def send (self, bw):
        bw.write_unsigned(2, self.type_num) # Object type
        
        for i in range(3):
            bw.write_pos(17, self.pos_int[i], None)  
            
        for i in range(2):
            bw.write_pos(31, self.rot_int[i], None) 
                
    
class HQMPuck(HQMObject):
    def __init__(self):
        super().__init__()
        self.type_num = 1

    
class HQMPlayer(HQMObject):
    def __init__(self, player):
        super().__init__()
        self.type_num = 0
        self.stick_pos = None
        self.stick_rot = None
        self.head_rot = None
        self.body_rot = None
        self.player = player
        
           
class HQMServerPlayer():
    def __init__(self, server, name, addr):
        self.obj = None
        self.server = server
        self.name = name
        self.team = HQMTeam.spec   
        self.addr = addr
        self.gameID = 0
        self.msgpos = 0
        self.msgrepindex = -1
        self.packet = -1
        self.inactivity = 0
        
    def reset(self):
        self.msgpos = 0
        self.msgrepindex = -1
        self.packet = -1      
        self.team = HQMTeam.spec 
        self.obj = None
 
   

class HQMServer(DatagramProtocol):
    
    def __init__(self):
        
        self.gameIDalloc = 1
        
        self.maxPlayers = 16
        self.numPlayers = 0
        self.players = [None]*self.maxPlayers
        self.teamSize = 5
        self.name = b"Default name"
        self.public = True
        
        self.gameID = None
        self.redscore = 0
        self.bluescore = 0
        self.period = 0
        self.timeleft = 30000
        self.timeout = 0        
        self.gameover = 0      
        self.simstep = 0
        self.packet = 0
        self.msgpos = 0
        self.objects = [None]*32
        self.messages = []
        
        
        def tickLoop():
            self.__tickLoop()
            #sys.stdout.flush()
            
        def masterServer():
            message = b"Hock\x20"
            self.transport.write(message, master_server)
            
        self.tickLoopObj = task.LoopingCall(tickLoop)
        
        self.masterServerLoopObj = task.LoopingCall(masterServer)

            
    def startProtocol(self):
        if(self.public):
            self.masterServerLoopObj.start(10)
            
                           
    def start_new_game(self):
        
        self.gameID = self.gameIDalloc
        self.gameIDalloc += 1
        print("Start new game " + str(self.gameID))
        self.redscore = 0
        self.bluescore = 0
        self.period = 0
        self.timeleft = 30000
        self.timeout = 0        
        self.gameover = 0      
        self.simstep = 0
        self.packet = 0
        self.msgpos = 0
        self.objects = [None]*32
        self.messages = [] 
        for player in self.players:
            
            if player is not None:
                if player.obj:
                    self._removeObject(playerObj)
                player.reset()
                self.messages.append(JoinExitMessage(player, HQMServerStatus.online))
                
        for i in range(-1,2):
            for j in range(-5,5):
                puck = self.createPuck()
                puck.pos = np.array((15+5*i,1, 30+2*j), dtype=np.float32)
        
       

    # Adds new player. Will initially be a spectator           
    def addPlayer(self, name, addr):
        if self.numPlayers >= self.maxPlayers:
            print("Too many players")
            return None
        i = self.__findEmptyPlayerSlot()
        if i is None:
            print("No empty slots")
            return None 
        player = HQMServerPlayer(self, name, addr)
        player.i = i
        self.players[i] = player 

        print((player.name + b" joined").decode("ascii"))
        self.numPlayers+=1
        if self.numPlayers==1:
            print("Start loop")
            self.start_new_game()
            
            self.tickLoopObj.start(0.01)
        else:
            self.messages.append(JoinExitMessage(player, HQMServerStatus.online))
        self.messages.append(ChatMessage(-1, player.name + b" joined"))
        
        return player
                
    def removePlayer(self, player):
        self.messages.append(ChatMessage(-1, player.name + b" exited"))
        self.messages.append(JoinExitMessage(player, HQMServerStatus.offline)) 
        if player.obj != None:
            self._removeObject(player.obj)
            player.obj = None #Should help with removing reference cycles or something
        self.players[player.i] = None    
        self.numPlayers-=1
        print((player.name + b" exited").decode("ascii"))
        if self.numPlayers==0:
            print("Stop loop")
            self.tickLoopObj.stop()
            
            
    def createPuck(self):
        puck = HQMPuck()
        self.setStartPuckPosition(puck)
        if self._addObject(puck):
            return puck
        else: return None
        
    def setStartPlayerPosition(self, player):
        pass
        
    def setStartPuckPosition(self, puck):
        puck.pos = np.array((10, 2, 10), dtype=np.float32)
        puck.rot = np.array(((1,0,0),(0,1,0), (0,0,1)),dtype=np.float32)
        
    def setPlayerTeam(self, player, team):
        if team == HQMTeam.spec and player.o is not None:
            self._removeObject(player.obj)
            player.team = HQMTeam.spec
            player.obj = None
            self.messages.append(JoinExitMessage(player, HQMServerStatus.online)) # Still in the server
            return True
        elif (team == HQMSpec.blue or HQMSpec.red) and player.team == HQMTeam.spec:
             playerObj = HQMPlayer(player)
             
             if self._addObject(playerObj):
                 player.team = team
                 player.obj = playerObj
                 self.startPlayerPosition(player)
                 self.messages.append(JoinExitMessage(player, HQMServerStatus.online)) # Still in the server  
                 return True
             else:
                return False
             
        elif team != player.team:
            player.team = team # Player is on the ice, but the team is magically changed
                               # Traitor!
            self.messages.append(JoinExitMessage(player, HQMServerStatus.online)) # Still in the server
        pass
        
        
    def _addObject(self, obj):
        index = self.__findEmptyObjectSlot()
        if index is None:
            return False
        self.objects[index] = obj
        obj.obj_i = index
        return True
        
    def _removeObject(self, obj):
        self.objects[obj.obj_i] = None
    
    def __findEmptyObjectSlot(self):
        for index, object in enumerate(self.objects):
            if object is None:
                return index           
        return None
        
    def updateTime(self):
        self.timeleft-=1
        if(self.timeleft==0):
            self.timeleft = 30000
        pass #Let's not do anything this time        
                
    def incomingChatLine(self, player, chatLine):
        print((player.name + b": " + chatLine).decode("ascii"))
        self.messages.append(ChatMessage(player.i, chatLine))
              
        
    def __tickLoop(self):
       # print("Tick")
        self.simulationStep()
        self.updateTime()
        for obj in self.objects:
            if obj:
                obj.calculateRotData()
        
        for player in self.players: 
            if player is not None:
                player.inactivity += 1
                if player.inactivity >= 1200:
                    self.removePlayer(player)
        if self.simstep % 2 == 1:
            for player in self.players:              
                if player is None:
                    continue
                
                if player.gameID == self.gameID:
                    #print("Sending update")
                    self.__sendUpdate(player)
                else: 
                    print("New match")                
                    self.__sendNewMatch(player)
                self.packet+=1
                
        self.simstep+=1
                
    def simulationStep(self):
        angle = 0.05
        cos = math.cos(angle)
        sin = math.sin(angle)
        
        rot_matrix = np.array(((1,0,0),(0, cos, -sin),(0, sin, cos)), dtype=np.float32)
    
        for obj in self.objects:
            if type(obj).__name__=="HQMPuck":
                obj.rot = np.matmul(obj.rot, rot_matrix)
                
        pass #Where physics would happen if we had any
                
    def __sendNewMatch(self, player):
        bw = CSBitWriter()
        bw.write_bytes_aligned(b"Hock")
        bw.write_unsigned_aligned(8, 6)
        bw.write_unsigned_aligned(32, self.gameID)
        self.transport.write(bw.get_bytes(), player.addr)
        
    def __sendUpdate(self, player):
        bw = CSBitWriter()
        bw.write_bytes_aligned(b"Hock")
        bw.write_unsigned_aligned(8, 5)
        bw.write_unsigned_aligned(32, self.gameID)
        bw.write_unsigned_aligned(32, self.simstep)
        bw.write_unsigned(1, self.gameover)
        bw.write_unsigned(8, self.redscore)
        bw.write_unsigned(8, self.bluescore)
        bw.write_unsigned(16, self.timeleft)
        bw.write_unsigned(16, self.timeout)
        bw.write_unsigned(8, self.period)
        bw.write_unsigned(8, player.i)
        bw.write_unsigned_aligned(32, self.packet)
        bw.write_unsigned_aligned(32, player.packet)
        for index, obj in enumerate(self.objects):
            if obj is None:
                bw.write_unsigned(1, 0) 
            else:
                bw.write_unsigned(1, 1) 
                obj.send (bw)

                
        serverMsgPos = len(self.messages)
        clientMsgPos = player.msgpos
        
        size = serverMsgPos-clientMsgPos
        if size<0:
            size += 0x10000
        size = min(size, 15)
        bw.write_unsigned(4, size)
        bw.write_unsigned(16, clientMsgPos)
        #print(self.messages[clientMsgPos:])
        for i in range(clientMsgPos, clientMsgPos+size):            
            self.messages[i].write(bw)
        #print(bw.get_bytes())
        self.transport.write(bw.get_bytes(), player.addr)    
        
    def __findEmptyPlayerSlot(self):
        for index, player in enumerate(self.players):
            if player is None:
                return index           
        return None
       
        
    def __findPlayer(self, addr):
        for player in self.players:
            if player is not None and player.addr == addr:
                return player     
        return None
            
    
    def datagramReceived(self, data, addr):
        #print("received %r from %s" % (data, addr))
        br = CSBitReader(data)
        header = br.read_bytes_aligned(4)

        if header!=b"Hock":
            print("Not hock")
            return
        cmd = br.read_unsigned_aligned(8)
        if cmd==0:
            #print("Ping")
            # ping
            self.__handlePing(br, addr)
        elif cmd==2:
            #print("Join")
            self.__handleJoin(br, addr)
        elif cmd==4:
            #print("Update")
            self.__handleUpdate(br, addr)
        elif cmd==7:
            #print("Exit")
            self.__handleExit(br, addr)
        
        
    def __handlePing(self, br, addr):
        clientVersion = br.read_unsigned(8)
        deltaTime = br.read_unsigned(32)
        bw = CSBitWriter()
        bw.write_bytes_aligned(b"Hock")
        bw.write_unsigned(8, 1) # Server info command
        bw.write_unsigned(8, 55) # Version number
        bw.write_unsigned(32, deltaTime) #deltaTime, for ping calculations
        bw.write_unsigned(8, self.numPlayers)
        bw.write_unsigned(4, 0)
        bw.write_unsigned(4, self.teamSize)
        bw.write_bytes_aligned(self.name.ljust(32, b"\0"))
        self.transport.write(bw.get_bytes(), addr)
        
    def __handleJoin(self, br, addr):
        if self.numPlayers == self.maxPlayers:
            return
        clientVersion = br.read_unsigned(8)
        if clientVersion!=55:
            print("Wrong version")
            return
        if self.__findPlayer(addr) is not None:
            print("Player has already joined")
            return # This player has already joined
        
        
        name = br.read_bytes_aligned(32)
        firstZero = name.find(0)
        if firstZero != -1:
            name = name[:firstZero]
               
        self.addPlayer(name, addr)
        
        #print("{} wants to join".format(name))
        
    def __handleExit(self, br, addr):
        print("Exit")
        player = self.__findPlayer(addr)
        if player is None:
            return #Exit from unknown player? Weird
        
        self.removePlayer(player)
        

        
    def __handleUpdate(self, br, addr):
        player = self.__findPlayer(addr)
        if player is None:
            return #Update from unknown player? Weird
        player.inactivity = 0 # We have an update from this player
        player.gameID = br.read_unsigned_aligned(32)
        stickAngle = br.read_sp_float_aligned()
        turn = br.read_sp_float_aligned()
        whatever = br.read_sp_float_aligned()
        forwardBackward = br.read_sp_float_aligned()
        stickX = br.read_sp_float_aligned()
        stickY = br.read_sp_float_aligned()
        headX = br.read_sp_float_aligned()
        headY = br.read_sp_float_aligned()
        keys = br.read_unsigned_aligned(32)
        player.packet = br.read_unsigned_aligned(32)
        player.msgpos = br.read_unsigned(16)
        isChatting = br.read_unsigned(1) == 1
        if isChatting:
            chatRep = br.read_unsigned(3)
            if chatRep!=player.msgrepindex:
                player.msgrepindex = chatRep
                chatSize = br.read_unsigned(8)
                chatLine = br.read_bytes_aligned(chatSize)
                self.incomingChatLine(player, chatLine)
                
                


server = HQMServer()
server.name = "MigoTest".encode("ascii")
server.public=True
reactor.listenUDP(27585, server)
#reactor.run()
import cProfile
cProfile.run("reactor.run()")

