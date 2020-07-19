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
import numba

master_addr = "66.226.72.227"
master_port = 27590
master_server = (master_addr, master_port)

@numba.njit(numba.int32[:](numba.float32[:]))
def calc_pos_int(pos):
    return (pos*1024).astype(np.int32)

@numba.njit(numba.int32[:](numba.float32[:], numba.float32[:]))
def calc_stickPos_int(pos, playerpos):
    return ((pos + 4 - playerpos)*1024).astype(np.int32)

@numba.njit(numba.int32(numba.int32))
def calc_bodyRot_int (rot):
    return int(rot * 8192 + 16384)
    
@numba.njit(numba.float32[:](numba.float32[:]))
def normalizeVector (v):
    norm = np.linalg.norm (v)
    if norm == 0:
        return np.array((0,0,0), dtype=np.float32)
    return v / norm
    
@numba.njit(numba.float32[:](numba.float32[:], numba.float32))
def limitVectorLength (v, len):
    norm = np.linalg.norm (v)
    res = v.copy()
    if norm > len:
        res /= norm
        res *= len
    return res
   
@numba.njit(numba.float32[:](numba.float32[:], numba.float32[:], numba.float32[:], numba.float32[:]))
def getVelocityIncludingRotation(centerpos, pos, rotationAxis, posDelta):
    return np.cross (pos - centerpos, rotationAxis) + posDelta 
    
@numba.njit(numba.float32[:](numba.float32[:], numba.float32[:], numba.float32[:], numba.float32[:,:], numba.float32[:]))
def createNewRotation (centerpos, pos, deltaChange, rot, rotForceMultiplier):
    cross = np.cross (deltaChange, pos - centerpos)
    return rot[0]*(np.dot(rot[0], cross)) + rot[1]*(np.dot(rot[1], cross)) + rot[2]*(np.dot(rot[2], cross))
    
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


@numba.njit(numba.int32(numba.int32, numba.float32[:]))
def calc_rot_vector(len, rot):

    result = 0
    if rot[0]<0:
        result |= 1
    if rot[2]<0:
        result |= 2
    if rot[1]<0:
        result |= 4
  
    a = start[result]
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
    
@numba.njit(numba.float32[:](numba.float32[:], numba.float32[:], numba.float32))
def rotateVectorAroundAxis (v, axis, angle):
    cross1 = np.cross (v, axis)
    cross2 = np.cross (axis, cross1)
    return np.dot (v, axis) * axis + np.cos(angle) * cross2 + np.sin(angle) * cross1
    
@numba.njit(numba.float32[:,:](numba.float32[:,:], numba.float32[:], numba.float32))
def rotateMatrixAroundAxis (matrix, axis, angle):
    res = np.empty((3,3), dtype=np.float32)
    for c in range(0, 3):
        res[c] = rotateVectorAroundAxis (matrix[c], axis, angle)
    return res
        
@numba.njit(numba.float32[:](numba.float32[:], numba.float32[:], numba.float32))
def projectionThing (a, normal, scale):
    aProjectionLen = np.dot(a, normal)
    aProjection = aProjectionLen * normal
    aRejection = a - aProjection
    aRejectionLen = np.linalg.norm (aRejection)
    if aRejectionLen > 0.00001:
        aRejectionNormal = aRejection / aRejectionLen
        aRejectionLen = max (aRejectionLen, aProjectionLen * scale)
        return aProjection + aRejectionLen * aRejectionNormal
    else:
        return aProjection

        
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
           "pos": calc_pos_int(self.pos),
           "rot": np.array([calc_rot_vector(31, c) for c in self.rot[1:3]])
        }
        return res
           
    
class HQMPuck(HQMObject):
    def __init__(self):
        super().__init__()
        self.type_num = 1
        
        
    
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
        
    def get_packet (self):
        res = super().get_packet()
        res.update ({
            "stickPos": calc_stickPos_int(self.stickPos, self.pos),
            "stickRot": np.array([calc_rot_vector(25, c) for c in self.stickRot[1:3]]),
            "headRot": calc_bodyRot_int (self.headRot),
            "bodyRot": calc_bodyRot_int (self.bodyRot)
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
        if player.obj != None:
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
        return playerObj
                    
        
    def setPlayerTeam(self, player, team):
        if team == HQMTeam.spec and player.obj is not None:
            self._removeObject(player.obj)
            player.team = HQMTeam.spec
            player.obj = None
            self.messages.append(JoinExitMessage(player, HQMServerStatus.online)) # Still in the server
            return True
        elif (team == HQMTeam.blue or HQMTeam.red) and player.team == HQMTeam.spec:
             playerObj = self.spawnPlayer(player, team)
             
             if self._addObject(playerObj):
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

    def incomingChatLine(self, player, chatLine):
        print(player.name.decode("ascii") + ": " + chatLine.decode("ascii"))
        self.messages.append(ChatMessage(player.i, chatLine))

    def __tickLoop(self):
        for player in self.players:
            if player is not None:
                if player.keyInputFromClient & 4 > 0:
                    self.setPlayerTeam (player, HQMTeam.red)
                    # Join red
                elif player.keyInputFromClient & 8 > 0:
                    self.setPlayerTeam (player, HQMTeam.blue)

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
                
    def simulationStep(self):
        for object in self.objects:
            if isinstance(object, HQMPlayer):
                player = object.player
                object.pos += object.posDelta
                object.posDelta[1] -= 0.000680 # Some gravitational acceleration
                
                feet_pos = object.pos - object.height * object.rot[1]
                if feet_pos[1] < 0:
                    fwbwFromClient = player.fwbwFromClient
                    if fwbwFromClient > 0:
                        temp = -object.rot[2].copy()
                        temp[1] = 0
                        
                        temp = normalizeVector(temp)
                        temp = temp * 0.05 - object.posDelta
                        
                        dot = np.dot (object.posDelta, object.rot[2])
                        temp2 = 0.00055555 if dot > 0 else 0.000208
                            
                        object.posDelta += limitVectorLength (temp, temp2)
                    elif fwbwFromClient < 0:
                        temp = object.rot[2].copy()
                        temp[1] = 0
                        temp = normalizeVector(temp)
                        temp = temp * 0.05 - object.posDelta

                        dot = np.dot (object.posDelta, object.rot[2])
                        temp2 = 0.00055555 if dot < 0 else 0.000208
                            
                        object.posDelta += limitVectorLength (temp, temp2)
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
                    temp2 = np.array((0, 1, 0), dtype=np.float32)
                    temp1 = temp2 * temp - 0.25 * object.posDelta
                    if np.dot (temp1, temp2) > 0:
                        temp3 = object.rot[2].copy()

                        temp3[1] = 0
                        temp3 = normalizeVector(temp3)
    
                        temp1 -= temp3*np.dot(temp1, temp3)
                        projectionFactor = 0.4 if player.keyInputFromClient & 0x10 > 0 else 1.2
                        object.posDelta += projectionThing (temp1, temp2, projectionFactor)
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

                stickPosPivot1 = object.pos + np.array((-0.375, -0.5, -0.125), dtype=np.float32) @ object.rot
                stickPosPivot2 = object.pos + np.array((-0.375, 0.5, -0.125), dtype=np.float32) @ object.rot

                defaultStickPosDiff = (object.stickPos - stickPosPivot1) @ object.rot.T

                currentAzimuth = math.atan2(defaultStickPosDiff[0], -defaultStickPosDiff[2])
                currentInclination = math.atan2(-defaultStickPosDiff[1], math.sqrt(defaultStickPosDiff[0]**2 + defaultStickPosDiff[2]**2))

                newStickRotation = object.rot
                newStickRotation = rotateMatrixAroundAxis(newStickRotation, newStickRotation[1], currentAzimuth)
                newStickRotation = rotateMatrixAroundAxis(newStickRotation, newStickRotation[0], currentInclination)

                object.stickRot = newStickRotation

                targetRotation = object.rot
                targetRotation = rotateMatrixAroundAxis (targetRotation, targetRotation[1], object.stickRotCurrentPlacement[0])
                targetRotation = rotateMatrixAroundAxis (targetRotation, targetRotation[0], object.stickRotCurrentPlacement[1])

                if object.stickRotCurrentPlacement[1] > 0:
                    object.stickRot = rotateMatrixAroundAxis(object.stickRot, object.stickRot[1],
                                                             object.stickRotCurrentPlacement[1] * 0.5 * np.pi)

                stickHandleAxis = normalizeVector(object.stickRot[2] + 0.75 * object.stickRot[1])
                object.stickRot = rotateMatrixAroundAxis(object.stickRot, stickHandleAxis,
                                                         -0.25 * np.pi * player.stickAngleFromClient)

                rotatedTargetRotation = rotateMatrixAroundAxis(targetRotation, targetRotation[0], np.pi / 4)
                stickTemp = stickPosPivot2 - 1.75 * rotatedTargetRotation[2]
                if stickTemp[1] < 0:
                    stickTemp[1] = 0
                stickTemp2 = 0.125 * (stickTemp - object.stickPos) - 0.5 * object.stickPosDelta
                stickTemp2 += 0.5 * getVelocityIncludingRotation(object.pos, stickTemp, rotAxisOld, posDeltaOld)

                object.stickPosDelta += 0.996 * stickTemp2
                counterForce = -0.004 * stickTemp2

                object.posDelta += counterForce
                object.rotAxis += createNewRotation(object.pos, stickTemp, counterForce, object.rot, object.rotForceMultiplier)


                player.prevKeyInputFromClient = player.keyInputFromClient
        for object in self.objects:
            if isinstance(object, HQMPlayer):
                for i in range(10):
                    object.stickPos += object.stickPosDelta*0.1
                
                    
        
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
server.name = "MigoTest".encode("ascii")
server.public=False
reactor.listenUDP(27585, server)
reactor.run()


