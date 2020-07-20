# Copyright © 2016-2017, John Eriksson
# https://github.com/migomipo/hqmutils
# See LICENSE for terms of use

from enum import Enum

from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
from twisted.internet import task
from bitparse import CSBitReader
from bitparse import CSBitWriter
import math
import numpy as np
from numba import njit, float32, int32, types, optional

master_addr = "66.226.72.227"
master_port = 27590
master_server = (master_addr, master_port)

@njit(int32[:](float32[:]))
def calcPosInt(pos):
    x = (pos*1024).astype(np.int32)
    return np.minimum(np.maximum(x, np.int32(0)), np.int32(0x1FFFF))

@njit(int32[:](float32[:], float32[:]))
def calcStickPosInt(pos, playerpos):
    x = ((pos + 4 - playerpos) * 1024).astype(np.int32)
    return np.minimum(np.maximum(x, np.int32(0)), np.int32(0x1FFF))

@njit(int32(float32))
def calcBodyRotInt (rot):
    x = int(rot * 8192 + 16384)
    return np.minimum(np.maximum(x, np.int32(0)), np.int32(0x7FFF))
    
@njit(float32[:](float32[:]))
def normalizeVector (v):
    norm = np.linalg.norm (v)
    if norm == 0:
        return np.array((0,0,0), dtype=np.float32)
    return v / norm

    
@njit(float32[:](float32[:], float32))
def limitVectorLength (v, len):
    norm = np.linalg.norm (v)
    res = v.copy()
    if norm > len:
        res /= norm
        res *= len
    return res

   
@njit(float32[:](float32[:], float32[:], float32[:], float32[:]))
def getVelocityIncludingRotation(centerpos, pos, rotationAxis, posDelta):
    return np.cross (pos - centerpos, rotationAxis) + posDelta

    
#@njit(float32[:](float32[:], float32[:], float32[:], float32[:,:], float32[:]))
def createNewRotation (centerpos, pos, deltaChange, rot, rotForceMultiplier):
    cross = np.cross (deltaChange, pos - centerpos)
    v = (cross @ rot.T) * rotForceMultiplier
    return v @ rot


@njit(float32[:,:](float32[:],float32[:,:],float32,float32))
def createPuckVertices (pos, rot, height, radius):

    res = []
    angles = np.arange(0, 2 * np.pi, np.pi / 8)
    for a in angles:
        for h in [-height, 0, height]:
            res.append((radius * np.cos(a), h, radius * np.sin(a)))
    res = np.array(res, dtype=np.float32)
    return pos + res @ rot

boxPlanes = np.array ([
    [(0, 0, 1), (1, 0, 1), (1, 0, 0), (0, 0, 0)],
    [(0, 1, 1), (1, 1, 1), (1, 0, 1), (0, 0, 1)],
    [(0, 1, 0), (0, 1, 1), (0, 0, 1), (0, 0, 0)],
    [(1, 1, 0), (0, 1, 0), (0, 0, 0), (1, 0, 0)],
    [(1, 1, 1), (1, 1, 0), (1, 0, 0), (1, 0, 1)],
    [(0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)]
], dtype=np.float32)

@njit(float32[:,:,:](float32[:],float32[:,:], float32[:]))
def createStickPlanes (pos, rot, stickSize):
    boxPlanesResized = (boxPlanes - np.float32(0.5)) * stickSize
    for boxPlane in boxPlanesResized[:]:
        boxPlane[:] = (boxPlane @ rot)
    return pos + boxPlanesResized


 # 3,         2,         1,         0
 # 7,         6,         2,         3
 # 4,         7,         3,         0
 # 5,         4,         0,         1
 # 6,         5,         1,         2
 # 4,         5,         6,         7

    
vectorToIntVectors = np.array([[[0., 1., 0.],
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


@njit(int32(int32, float32[:]))
def calc_rot_vector(len, rot):

    result = 0
    if rot[0]<0:
        result |= 1
    if rot[2]<0:
        result |= 2
    if rot[1]<0:
        result |= 4
  
    a = vectorToIntVectors[result]
    i = 3
    temp1, temp2, temp3 = a[0], a[1], a[2]
    while i < len:
        temp4 = normalizeVector(temp1+temp2)
        temp5 = normalizeVector(temp2+temp3)
        temp6 = normalizeVector(temp1+temp3)
        cross = np.cross (temp4-temp6, rot-temp6)
        if np.dot (cross, rot) <= 0:
            cross = np.cross (temp5-temp4, rot-temp4)
            if np.dot (cross, rot) <= 0:
                cross = np.cross (temp6-temp5, rot-temp5)
                if np.dot (cross, rot) <= 0:
                    result |= 3 << i
                    temp1 = temp4
                    temp2 = temp5
                    temp3 = temp6
                else:
                    result |= 2 << i
                    temp1 = temp6
                    temp2 = temp5
            else:
                result |= 1 << i
                temp1 = temp4
                temp3 = temp5
        else:
            temp2 = temp4
            temp3 = temp6
        
    
        i += 2
    return result
    
@njit(float32[:](float32[:], float32[:], float32))
def rotateVectorAroundAxis (v, axis, angle):
    cross1 = np.cross (v, axis)
    cross2 = np.cross (axis, cross1)
    return np.dot (v, axis) * axis + np.cos(angle) * cross2 + np.sin(angle) * cross1
    
@njit(float32[:,:](float32[:,:], float32[:], float32))
def rotateMatrixAroundAxis (matrix, axis, angle):
    res = np.empty((3,3), dtype=np.float32)
    for c in range(0, 3):
        res[c] = rotateVectorAroundAxis (matrix[c], axis, angle)
    return res
        
@njit(float32[:](float32[:], float32[:], float32))
def projectionThing (a, normal, scale):
    aProjectionLen = np.dot(a, normal)
    aProjection = aProjectionLen * normal
    aRejection = a - aProjection
    aRejectionLen = np.linalg.norm (aRejection)
    if aRejectionLen > 0.00001:
        aRejectionNormal = aRejection / aRejectionLen
        if aRejectionLen > aProjectionLen * scale:
            aRejectionLen = aProjectionLen * scale
        return aProjection + aRejectionLen * aRejectionNormal
    else:
        return aProjection

@njit(float32[:,:](float32[:,:], float32, float32))
def sphericalRotation (rot, azimuth, inclination):
    rot = rotateMatrixAroundAxis(rot, rot[1], azimuth)
    rot = rotateMatrixAroundAxis(rot, rot[0], inclination)
    return rot

@njit(float32[:](float32[:], float32[:], float32[:]))
def calculateNormal (startPoint, a, b):
    return normalizeVector(np.cross(b - startPoint, a - startPoint))

def puckOverlapsPlane (p, v, planeStartPoint, planeNormal):
        if np.dot(planeStartPoint - v, planeNormal) >= 0:
            dot2 = np.dot (planeStartPoint - p, planeNormal)
            if dot2 <= 0:
                overlap = dot2
                vertexPosDiff = v - p
                dot3 = np.dot (vertexPosDiff, planeNormal)
                if dot3 == 0:
                    return None
                overlap /= dot3
                return overlap, p + overlap * vertexPosDiff
        return None

def puckOverlapsPlane2 (puckPosition, puckVertex, planeStartPoint, p1, p2, planeNormal):
    overlap1 = puckOverlapsPlane(puckPosition, puckVertex, planeStartPoint, planeNormal)
    if overlap1:
        overlap, overlapPos = overlap1

        if np.dot (np.cross (overlapPos - planeStartPoint, p1 - planeStartPoint), planeNormal) >= 0 and \
                np.dot (np.cross(overlapPos - p1, p2 - p1), planeNormal) >= 0 and \
                np.dot (np.cross (overlapPos - p2, planeStartPoint - p2), planeNormal) >= 0:
                    return overlap1
    return None

def puckVertexCollidesWithStick (position, vertex, stickPlanes):
    currentOverlap = 1.0
    currentNormal = None
    currentDot = None
    for stickPlane in stickPlanes:
        for s in [(stickPlane[0], stickPlane[1], stickPlane[2]), (stickPlane[0], stickPlane[2], stickPlane[3])]:
            normal = calculateNormal (s[0], s[1], s[2])
            overlap1 = puckOverlapsPlane2(position, vertex, s[0], s[1], s[2], normal)
            if overlap1:
                overlap, overlapPos = overlap1
                if overlap < currentOverlap:
                    currentOverlap = overlap
                    currentNormal = normal
                    currentDot = np.dot(overlapPos - vertex, normal)
    if currentOverlap < 1:
        return currentNormal, currentDot
    return None




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
        self.posDelta = None
        self.rot = None # Rotation matrix
        self.rotAxis = None
        self.obj_i = None
        self.type_num = None
        
    def get_packet (self):
        res = {
           "type": self.type_num,
           "pos": calcPosInt(self.pos),
           "rot": np.array([calc_rot_vector(31, c) for c in self.rot[1:3]])
        }
        return res

    def applySpeedChangeAtPoint (self, change, point):
        self.posDelta += change
        self.rotAxis += createNewRotation(self.pos, point, change, self.rot, self.rotForceMultiplier)
           
    
class HQMPuck(HQMObject):
    def __init__(self):
        super().__init__()
        self.type_num = 1

        self.pos = np.array((10, 2, 10), dtype=np.float32)
        self.posDelta = np.array((0, 0, 0), dtype=np.float32)

        self.rot = np.eye(3, dtype=np.float32)
        self.rotAxis = np.array((0, 0, 0), dtype=np.float32)

        self.radius = 0.125
        self.height = 0.0412500016391

        self.rotForceMultiplier = np.array((223.5, 128, 223.5), dtype=np.float32)


class HQMPlayer(HQMObject):
    def __init__(self, player):
        super().__init__()
        self.type_num = 0
        self.stickPos = None
        self.stickRot = None
        self.headRot = None
        self.bodyRot = None
        self.player = player
        self.height = 0.75
        self.rotForceMultiplier = np.array((2.75, 6.16, 2.35), dtype=np.float32)

        self.pos = np.array((10, 2, 10), dtype=np.float32)
        self.posDelta = np.array((0, 0, 0), dtype=np.float32)

        self.rot = np.eye(3, dtype=np.float32)
        self.rotAxis = np.array((0, 0, 0), dtype=np.float32)

        self.stickPos = self.pos.copy()
        self.stickPosDelta = np.array((0, 0, 0), dtype=np.float32)
        self.stickRot = np.eye(3, dtype=np.float32)

        self.stickRotCurrentPlacement = np.array((0, 0), dtype=np.float32)
        self.stickRotCurrentPlacementDelta = np.array((0, 0), dtype=np.float32)

        self.stickSize = np.array((0.0625, 0.25, 0.5), dtype=np.float32)
        
    def get_packet (self):
        res = super().get_packet()
        res.update ({
            "stickPos": calcStickPosInt(self.stickPos, self.pos),
            "stickRot": np.array([calc_rot_vector(25, c) for c in self.stickRot[1:3]]),
            "headRot": calcBodyRotInt (self.headRot),
            "bodyRot": calcBodyRotInt (self.bodyRot)
        })
        return res


        
class HQMServerPlayer():
    def __init__(self, name):
        self.obj = None
        self.name = name
        self.team = HQMTeam.spec   
        self.isRealPlayer = False
        
    def reset(self):
        pass
        
    def send(self, server):
        pass
           
class HQMExternalPlayer(HQMServerPlayer):
    def __init__(self, name, addr):
        self.obj = None
        self.name = name
        self.team = HQMTeam.spec   
        self.addr = addr
        self.gameID = 0
        self.msgpos = 0
        self.msgrepindex = -1
        self.packet = -1
        self.inactivity = 0
        
        self.stickAngleFromClient = 0
        self.turnFromClient = 0
        self.fwbwFromClient = 0
        self.stickRotFromClient = np.array((0,0), dtype=np.float32)
        self.headBodyRotFromClient = np.array((0,0), dtype=np.float32)
        self.keyInputFromClient = 0
        self.prevKeyInputFromClient = 0
        self.isRealPlayer = True

    def reset(self):
        self.msgpos = 0
        self.msgrepindex = -1
        self.packet = -1      
        self.team = HQMTeam.spec 
        self.obj = None

class HQMRink:
    def __init__(self, width, length, radius):
        self.planes = (
            (np.array((0, 0, 0), dtype=np.float32), np.array((0, 1, 0), dtype=np.float32)),
            (np.array((0, 0, length), dtype=np.float32), np.array((0, 0, -1), dtype=np.float32)),
            (np.array((0, 0, 0), dtype=np.float32), np.array((0, 0, 1), dtype=np.float32)),
            (np.array((width, 0, 0), dtype=np.float32), np.array((-1, 0, 0), dtype=np.float32)),
            (np.array((0, 0, 0), dtype=np.float32), np.array((1, 0, 0), dtype=np.float32))
        )
        self.corners = (
            (np.array((radius, 0, radius), dtype=np.float32), np.array((-1, 0, -1), dtype=np.float32), radius),
            (np.array((width-radius, 0, radius), dtype=np.float32), np.array((1, 0, -1), dtype=np.float32), radius),
            (np.array((width-radius, 0, length-radius), dtype=np.float32), np.array((1, 0, 1), dtype=np.float32), radius),
            (np.array((radius, 0, length-radius), dtype=np.float32), np.array((-1, 0, 1), dtype=np.float32), radius)
        )


    def vertexCollides (self, vertex):
        maxProj = 0
        collisionNormal = None
        for p, normal in self.planes:
            proj = np.dot(p - vertex, normal)
            if proj > maxProj:
                maxProj = proj
                collisionNormal = normal
        for p, dir, radius in self.corners:
            p2 = p - vertex;
            p2[1] = 0
            if p2[0]*dir[0]<0 and p2[2]*dir[2]<0:
                # Within the box that contains the corner
                diff = np.linalg.norm(p2) - radius
                if diff > maxProj:
                    collisionNormal = normalizeVector(p2)
                    maxProj = diff
        if maxProj > 0:
            return maxProj, collisionNormal
        return None





class HQMServer(DatagramProtocol):
    
    def __init__(self):
        
        self.gameIDalloc = 1
        
        self.numPlayers = 0
        self.players = [None]*256
        self.teamSize = 5
        self.name = b"Default name"
        self.public = False
        
        self.gameID = None
        self.redscore = 0
        self.bluescore = 0
        self.period = 0
        self.timeleft = 30000
        self.timeout = 0        
        self.gameover = 0      
        self.simstep = 0
        self.packet_id = -1
        self.msgpos = 0
        self.objects = [None]*32
        self.messages = []

        self.rink = HQMRink (30, 61, 8.5)
        
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
        self.packet_id = -1
        self.msgpos = 0
        self.objects = [None]*32
        self.messages = [] 
        for player in self.players:
            
            if player is not None:
                player.reset()
                self.messages.append(JoinExitMessage(player, HQMServerStatus.online))

        #self.spawnPuck((20, 2, 20))
        puck = self.spawnPuck((25, 5, 25))
        puck.rot = rotateMatrixAroundAxis(puck.rot,puck.rot[0], np.pi/4)
        puck.posDelta[0] = -0.1
                
        
    # Adds new player. Will initially be a spectator           
    def addPlayer(self, player):
        i = self.__findEmptyPlayerSlot()
        if i is None:
            return None 

        player.i = i
        self.players[i] = player 

        print(player.name.decode("ascii") + " joined")
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
        if player.obj is not None:
            self._removeObject(player.obj)
            player.obj = None #Should help with removing reference cycles or something
        self.players[player.i] = None    
        self.numPlayers-=1
        print((player.name + b" exited").decode("ascii"))
        if self.numPlayers==0:
            print("Stop loop")
            self.tickLoopObj.stop()
            
    def spawnPlayer (self, player, team):
        playerObj = HQMPlayer (player)
        playerObj.pos = np.array((10, 2, 10), dtype=np.float32)
        playerObj.posDelta = np.array((0,0,0), dtype=np.float32)
        
        playerObj.rot = np.eye(3, dtype=np.float32)
        playerObj.rotAxis = np.array((0,0,0), dtype=np.float32)
        
        playerObj.stickPos = playerObj.pos.copy()
        playerObj.stickPosDelta = np.array((0,0,0), dtype=np.float32)
        playerObj.stickRot = np.eye(3, dtype=np.float32)
        
        playerObj.stickRotCurrentPlacement = np.array((0,0), dtype=np.float32)
        playerObj.stickRotCurrentPlacementDelta = np.array((0,0), dtype=np.float32)
        
        playerObj.headRot = np.float32(0)
        playerObj.bodyRot = np.float32(0)

        if self._addObject(playerObj):
            return playerObj
        return None

    def spawnPuck(self, pos):
        puckObj = HQMPuck()
        puckObj.pos = np.array(pos, dtype=np.float32)
        puckObj.posDelta = np.array((0, 0, 0), dtype=np.float32)

        puckObj.rot = np.eye(3, dtype=np.float32)
        puckObj.rotAxis = np.array((0, 0, 0), dtype=np.float32)

        if self._addObject(puckObj):
            return puckObj
        return None

    def setPlayerTeam(self, player, team):
        if team == HQMTeam.spec and player.obj is not None:
            self._removeObject(player.obj)
            player.team = HQMTeam.spec
            player.obj = None
            self.messages.append(JoinExitMessage(player, HQMServerStatus.online)) # Still in the server
            return True
        elif (team == HQMTeam.blue or team == HQMTeam.red) and player.team == HQMTeam.spec:
             playerObj = self.spawnPlayer(player, team)
             
             if playerObj:
                 player.team = team
                 player.obj = playerObj
                 
                 self.messages.append(JoinExitMessage(player, HQMServerStatus.online)) # Still in the server  
                 return True
             else:
                return False
             
        elif team != player.team:
            player.team = team # Player is on the ice, but the team is magically changed
                               # Traitor!
            self.messages.append(JoinExitMessage(player, HQMServerStatus.online)) # Still in the server
            return True
        return False
        
        
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

    def incomingChatLine(self, player, chatLine):
        print(player.name.decode("ascii") + ": " + chatLine.decode("ascii"))
        self.messages.append(ChatMessage(player.i, chatLine))

    def __tickLoop(self):
        for player in self.players:
            if player is not None:
                if player.keyInputFromClient & 4 > 0:
                    self.setPlayerTeam(player, HQMTeam.red)
                    # Join red
                elif player.keyInputFromClient & 8 > 0:
                    self.setPlayerTeam(player, HQMTeam.blue)
                elif player.keyInputFromClient & 0x20 > 0:
                    self.setPlayerTeam(player, HQMTeam.spec)

        self.simulationStep()
        
        self.updateTime()
        
        if self.simstep & 1 == 0:
            self.packet_id += 1
            packets = [obj.get_packet() if obj else None for obj in self.objects]
            
            for player in self.players:              
                if player is None or not player.isRealPlayer:
                    continue
                
                player.inactivity += 1
                if player.inactivity >= 1200:
                    print ("Inactive")
                    self.removePlayer(player)
                else: 
                    if player.gameID == self.gameID:
                        self.sendUpdate(player, packets)
                    else:                 
                        self.sendNewMatch(player)
        self.simstep+=1

    def playerMovement (self, playerObjects):
        for object in playerObjects:

            player = object.player

            feet_pos = object.pos - object.height * object.rot[1]
            if feet_pos[1] < 0:
                fwbwFromClient = player.fwbwFromClient
                if fwbwFromClient > 0:
                    temp = -object.rot[2].copy()
                    temp[1] = 0

                    temp = normalizeVector(temp)
                    temp = temp * 0.05 - object.posDelta

                    dot = np.dot (object.posDelta, object.rot[2])
                    yUnit = 0.00055555 if dot > 0 else 0.000208

                    object.posDelta += limitVectorLength (temp, yUnit)
                elif fwbwFromClient < 0:
                    temp = object.rot[2].copy()
                    temp[1] = 0
                    temp = normalizeVector(temp)
                    temp = temp * 0.05 - object.posDelta

                    dot = np.dot (object.posDelta, object.rot[2])
                    yUnit = 0.00055555 if dot < 0 else 0.000208

                    object.posDelta += limitVectorLength (temp, yUnit)
                if player.keyInputFromClient & 1 == 1 and player.prevKeyInputFromClient & 1 != 1:
                    # Jump
                    object.posDelta[1] += 0.025
                    # TODO: Collision bodies
            if player.keyInputFromClient & 0x10 > 0:
                temp = object.rot[0].copy()
                temp[1] = 0

                temp = normalizeVector(temp)
                temp *= np.clip(player.turnFromClient, -1, 1) * 0.033333
                temp -= object.posDelta

                object.posDelta += limitVectorLength(temp, 0.00027777778)
                turn = -np.clip(player.turnFromClient, -1, 1) * 5.6 / 14400.0
                object.rotAxis += object.rot[1] * turn

            else:
                turn = np.clip(player.turnFromClient, -1, 1) * 6.0 / 14400.0
                object.rotAxis += object.rot[1] * turn
            rotAxisMagnitude = np.linalg.norm(object.rotAxis)
            if rotAxisMagnitude > 0.00001:
                object.rot = rotateMatrixAroundAxis (object.rot, object.rotAxis / rotAxisMagnitude, rotAxisMagnitude)
            # TODO : Head and body rotation
            # TODO: Adjust collision bodies
            posDeltaOld = object.posDelta.copy()
            rotAxisOld = object.rotAxis.copy()

            # TODO: Collision stuff
            if player.keyInputFromClient & 2 > 0:
                # Crouch (Ctrl)
                object.height = max (0.25, object.height - 0.015625)
            else:
                object.height = min (0.75, object.height + 0.125)

            isTooLow = False
            feetPos = object.pos - object.rot[1] * object.height
            if feetPos[1] < 0:
                temp = -feetPos[1] * 0.125 * 0.125 * 0.25
                yUnit = np.array((0, 1, 0), dtype=np.float32)
                temp1 = yUnit * temp - 0.25 * object.posDelta
                if np.dot (temp1, yUnit) > 0:
                    if player.keyInputFromClient & 0x10 > 0:
                        temp3 = object.rot[0].copy()
                        projectionFactor = 0.4
                    else:
                        temp3 = object.rot[2].copy()
                        projectionFactor = 1.2
                    temp3[1] = 0
                    temp3 = normalizeVector(temp3)

                    temp1 -= temp3*np.dot(temp1, temp3)
                    object.posDelta += projectionThing (temp1, yUnit, projectionFactor)
                    isTooLow = True

            if object.pos[1] < 0.5 and np.linalg.norm(object.posDelta) < 0.025:
                object.posDelta[1] += 0.000555555
                isTooLow = True
            if isTooLow:
                object.rotAxis *= 0.975  # Slow down spinning a bit
                unit = np.array((0, 1, 0), dtype=np.float32)
                if player.keyInputFromClient & 0x10 == 0:
                    spin = (-np.dot (object.posDelta, object.rot[2]) / 0.05) * player.turnFromClient * 0.225
                    unit = rotateVectorAroundAxis (unit, object.rot[2], spin)
                temp1 = np.cross (unit, object.rot[1])
                temp1_normalized = normalizeVector (temp1)
                temp1 *= 0.008333333333
                temp1 -= 0.25 * np.dot(object.rotAxis, temp1_normalized) * temp1_normalized
                temp1 = limitVectorLength(temp1, 0.000347)

                object.rotAxis += temp1

            stickPlacementDiff = player.stickRotFromClient - object.stickRotCurrentPlacement
            stickPlacementAdjust = limitVectorLength (0.0625 * stickPlacementDiff - 0.5 * object.stickRotCurrentPlacementDelta, 0.00888888888)

            object.stickRotCurrentPlacementDelta += stickPlacementAdjust
            object.stickRotCurrentPlacement += object.stickRotCurrentPlacementDelta

            hand = "LEFT"

            x1 = 0.375 if hand == "RIGHT" else -0.375

            stickPosPivot1 = object.pos + np.array((x1, -0.5, -0.125), dtype=np.float32) @ object.rot
            stickPosPivot2 = object.pos + np.array((x1, 0.5, -0.125), dtype=np.float32) @ object.rot

            defaultStickPosDiff = (object.stickPos - stickPosPivot1) @ object.rot.T

            currentAzimuth = math.atan2(defaultStickPosDiff[0], -defaultStickPosDiff[2])
            currentInclination = math.atan2(-defaultStickPosDiff[1], math.sqrt(defaultStickPosDiff[0]**2 + defaultStickPosDiff[2]**2))

            stickRotation = sphericalRotation (object.rot, currentAzimuth, currentInclination)

            if object.stickRotCurrentPlacement[1] > 0:
                stickRotation = rotateMatrixAroundAxis(stickRotation, stickRotation[1],
                                                         object.stickRotCurrentPlacement[1] * 0.5 * np.pi)

            stickHandleAxis = normalizeVector(stickRotation[2] + 0.75 * stickRotation[1])
            stickRotation = rotateMatrixAroundAxis(stickRotation, stickHandleAxis, -0.25 * np.pi * player.stickAngleFromClient)

            object.stickRot = stickRotation

            targetRotation = sphericalRotation(object.rot, object.stickRotCurrentPlacement[0],
                                               object.stickRotCurrentPlacement[1])
            rotatedTargetRotation = rotateMatrixAroundAxis(targetRotation, targetRotation[0], np.pi / 4)
            targetStickPosition = stickPosPivot2 - 1.75 * rotatedTargetRotation[2]
            if targetStickPosition[1] < 0:
                targetStickPosition[1] = 0
            stickPosMovement = 0.125 * (targetStickPosition - object.stickPos) - 0.5 * object.stickPosDelta
            stickPosMovement += 0.5 * getVelocityIncludingRotation(object.pos, targetStickPosition, rotAxisOld, posDeltaOld)

            object.stickPosDelta += 0.996 * stickPosMovement
            counterForce = -0.004 * stickPosMovement

            object.applySpeedChangeAtPoint(counterForce, targetStickPosition)


            player.prevKeyInputFromClient = player.keyInputFromClient

    def simulationStep(self):
        playerObjects = [x for x in self.objects if isinstance(x, HQMPlayer)]
        puckObjects = [x for x in self.objects if isinstance(x, HQMPuck)]

        gravity = 0.000680

        for playerObject in playerObjects:
            playerObject.pos += playerObject.posDelta
            playerObject.posDelta[1] -= gravity # Some gravitational acceleration

        self.playerMovement(playerObjects)

        for puckObject in puckObjects:
            puckObject.posDelta[1] -= gravity

        for i in range(10):
            puckObjectData = []
            playerObjectData = []

            for puckObject in puckObjects:
                puckObject.pos += puckObject.posDelta * 0.1
                puckVertices = createPuckVertices(puckObject.pos, puckObject.rot, puckObject.height, puckObject.radius)
                puckOrigPosDelta = puckObject.posDelta.copy()
                puckOrigRotAxis = puckObject.rotAxis.copy()
                puckObjectData.append ((puckObject, puckVertices, puckOrigPosDelta, puckOrigRotAxis))

            for playerObject in playerObjects:
                playerObject.stickPos += playerObject.stickPosDelta * 0.1

                stickPlanes = createStickPlanes(playerObject.stickPos, playerObject.stickRot, playerObject.stickSize)
                playerOrigStickPosDelta = playerObject.stickPosDelta.copy()
                playerObjectData.append((playerObject, stickPlanes, playerOrigStickPosDelta))


            if i == 0: # First step
                for puckObject, puckVertices, puckOrigPosDelta, puckOrigRotAxis in puckObjectData:
                    for puckVertex in puckVertices:
                        collision = self.rink.vertexCollides(puckVertex)
                        if collision:
                            proj, normal = collision
                            temp = 0.125*0.125*0.5*proj*normal
                            temp2 = getVelocityIncludingRotation(puckObject.pos, puckVertex,
                                                                           puckOrigRotAxis, puckOrigPosDelta)
                            temp -= 0.015625 * temp2
                            if np.dot (normal, temp) > 0:
                                pt = projectionThing (temp, normal, 0.05)
                                puckObject.applySpeedChangeAtPoint(pt, puckVertex)

            for puckObject, puckVertices, puckOrigPosDelta, puckOrigRotAxis in puckObjectData:
               for playerObject, stickPlanes, playerOrigStickPosDelta in playerObjectData:
                   if np.linalg.norm(playerObject.stickPos - puckObject.pos) < 1:   # Close enough to check
                       for puckVertex in puckVertices:
                           collision = puckVertexCollidesWithStick(puckObject.pos, puckVertex, stickPlanes)
                           if collision:
                               collisionNormal, collisionDot = collision
                               change = collisionDot * collisionNormal
                               change -= 0.125*getVelocityIncludingRotation(puckObject.pos, puckVertex, puckOrigRotAxis, puckOrigPosDelta)
                               change += 0.125*playerOrigStickPosDelta
                               if np.dot(change, collisionNormal) > 0:
                                   change2 = projectionThing(change, collisionNormal, 0.5)
                                   playerObject.stickPosDelta -= 0.25 * change2
                                   puckObject.applySpeedChangeAtPoint(0.75 * change2, puckVertex)



        for puckObject in puckObjects:
            velocity = np.linalg.norm(puckObject.posDelta)
            if velocity > 0.00001:
                posDeltaDir = puckObject.posDelta / velocity

                puckObject.posDelta -= (0.015625*velocity*velocity)*posDeltaDir
        for puckObject in puckObjects:
            rotationSpeed = np.linalg.norm(puckObject.rotAxis)
            if rotationSpeed > 0.00001:
                puckObject.rot = rotateMatrixAroundAxis(puckObject.rot, puckObject.rotAxis / rotationSpeed, rotationSpeed)






        
    def updateTime (self):
        self.timeleft -= 1
        if self.timeleft == 0:
            self.timeleft = 30000
                
    def sendNewMatch(self, player):
        bw = CSBitWriter()
        bw.write_bytes_aligned(b"Hock")
        bw.write_unsigned_aligned(8, 6)
        bw.write_unsigned_aligned(32, self.gameID)
        self.transport.write(bw.get_bytes(), player.addr)
        
    def sendUpdate(self, player, packets):
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
        bw.write_unsigned_aligned(32, self.packet_id) # Current packet ID
        bw.write_unsigned_aligned(32, player.packet)

        for index, obj in enumerate(packets):
            if obj is None:
                bw.write_unsigned(1, 0) 
            else:
                bw.write_unsigned(1, 1) 
                bw.write_unsigned(2, obj["type"]) # Object type
        
                bw.write_pos(17, obj["pos"][0], None)
                bw.write_pos(17, obj["pos"][1], None) 
                bw.write_pos(17, obj["pos"][2], None) 

                bw.write_pos(31, obj["rot"][0], None) 
                bw.write_pos(31, obj["rot"][1], None) 
                
                if obj["type"] == 0:
                    bw.write_pos(13, obj["stickPos"][0])
                    bw.write_pos(13, obj["stickPos"][1])
                    bw.write_pos(13, obj["stickPos"][2])

                    bw.write_pos(25, obj["stickRot"][0])
                    bw.write_pos(25, obj["stickRot"][1])

                    bw.write_pos(16, obj["headRot"])
                    bw.write_pos(16, obj["bodyRot"])

        serverMsgPos = len(self.messages)
        clientMsgPos = player.msgpos
        
        size = serverMsgPos-clientMsgPos
        if size<0:
            size += 0x10000
        size = min(size, 15)
        bw.write_unsigned(4, size)
        bw.write_unsigned(16, clientMsgPos)
        for i in range(clientMsgPos, clientMsgPos+size):            
            self.messages[i].write(bw)
        self.transport.write(bw.get_bytes(), player.addr)    
        
    def __findEmptyPlayerSlot(self):
        for index, player in enumerate(self.players):
            if player is None:
                return index           
        return None

    def __findPlayer(self, addr):
        for player in self.players:
            if player is not None and hasattr(player, 'addr') and player.addr == addr:
                return player     
        return None

    def datagramReceived(self, data, addr):
        br = CSBitReader(data)
        header = br.read_bytes_aligned(4)

        if header!=b"Hock":
            print("Not hock")
            return
        cmd = br.read_unsigned_aligned(8)
        if cmd == 0:
            # ping
            self.__handlePing(br, addr)
        elif cmd == 2:
            self.__handleJoin(br, addr)
        elif cmd == 4:
            self.__handleUpdate(br, addr)
        elif cmd == 7:
            self.__handleExit(br, addr)

    def __handlePing(self, br, addr):
        clientVersion = br.read_unsigned(8)
        if clientVersion != 55:
            return
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
        clientVersion = br.read_unsigned(8)
        if clientVersion != 55:
            return
        if self.__findPlayer(addr) is not None:
            return  # This player has already joined

        name = br.read_bytes_aligned(32)
        firstZero = name.find(0)
        if firstZero != -1:
            name = name[:firstZero]
               
        self.addPlayer(HQMExternalPlayer (name, addr))
        
    def __handleExit(self, br, addr):
        print("Exit")
        player = self.__findPlayer(addr)
        if player is None:
            return # Exit from unknown player? Weird
        
        self.removePlayer(player)
        
        
    def __handleUpdate(self, br, addr):
        player = self.__findPlayer(addr)
        if player is None:
            return #Update from unknown player? Weird
        player.inactivity = 0 # We have an update from this player
        player.gameID = br.read_unsigned_aligned(32)
        player.stickAngleFromClient = br.read_sp_float_aligned()
        player.turnFromClient = br.read_sp_float_aligned()
        br.read_sp_float_aligned() #Unknown value
        player.fwbwFromClient = br.read_sp_float_aligned()
        player.stickRotFromClient = np.array((br.read_sp_float_aligned(), br.read_sp_float_aligned()), dtype=np.float32)
        player.headBodyRotFromClient = np.array((br.read_sp_float_aligned(), br.read_sp_float_aligned()), dtype=np.float32)
        player.keyInputFromClient = br.read_unsigned_aligned(32)
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
server.name = "MigoTest (stick edition)".encode("ascii")
server.public=True
reactor.listenUDP(27585, server)
reactor.run()


