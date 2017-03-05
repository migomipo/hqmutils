# Copyright © 2017, John Eriksson
# https://github.com/migomipo/hqmutils
# See LICENSE for terms of use

from bitparse import CSBitReader
from bitparse import CSBitWriter
from collections import deque
import struct
import math
 
header = b"Hock"
server_list_message = b"Hock!"

CCMD_INFO_REQUEST = 0 
CCMD_JOIN = 2
CCMD_UPDATE = 4
CCMD_EXIT = 7

SCMD_INFO_RESPONSE = 1 
SCMD_GAME_UPDATE = 5
SCMD_NEW_MATCH = 6

def string_strip_null(str):
    firstZero = str.find(0)
    if firstZero != -1:
        str = str[:firstZero]
    return str

def convert_pos(pos):
    if pos is None:
        return None
    return pos/1024
            
def convert_stick_pos(pos, playerpos):
    if pos is None or playerpos is None:
        return None
    return (pos / 1024) + playerpos - 4.0 
    
def convert_unknown_rot(rot):
    if rot is None:
        return None
    return (rot-16384)/8192
    
    
try:
    import numpy as np
    pi = math.pi
    
    unitVectors = [
        np.array(( 0, -1,  0), dtype=np.float32, order='C'),
        np.array((-1,  0,  0), dtype=np.float32, order='C'),
        np.array(( 0,  0, -1), dtype=np.float32, order='C'),
        np.array(( 1,  0,  0), dtype=np.float32, order='C'),
        np.array(( 0,  0,  1), dtype=np.float32, order='C'),
        np.array(( 0,  1,  0), dtype=np.float32, order='C')
    ]
    
    vChoice1 = [5,5,5,5,4,1,3,2]
    vChoice2 = [3,4,2,1,3,4,2,1]
    vChoice3 = [4,1,3,2,0,0,0,0]

    def normalize(v): 
        norm=math.sqrt(np.dot(v,v))
        v/=norm   
        return v

    def convert_rot_vector(n, bits):
        if n is None:
            return None


        lowest = n & 0x7
        a1 = np.copy(unitVectors[vChoice1[lowest]], order='C')
        a2 = np.copy(unitVectors[vChoice2[lowest]], order='C')
        a3 = np.copy(unitVectors[vChoice3[lowest]], order='C')
        for i in range(3, bits, 2):
            c = (n >> i) & 3 # Two bits at a time
            if c==0:
                a2+=a1
                a3+=a1
                normalize(a2)
                normalize(a3)
            elif c==1:
                a1+=a2
                a3+=a2
                normalize(a1)
                normalize(a3)
            elif c==2:
                a2+=a3
                a1+=a3
                normalize(a1)
                normalize(a2)
            elif c==3:
                temp1 = normalize(a1+a2)
                temp2 = normalize(a2+a3)
                temp3 = normalize(a3+a1)
                a1 = temp1
                a2 = temp2
                a3 = temp3
        a1+=a2
        a1+=a3
        return normalize(a1)   
except ImportError:
    pass # No numpy
    
       


def parse_from_server(msg):
    br = CSBitReader(msg)
    if br.read_bytes_aligned(4) != header:
        return None
    type = br.read_unsigned_aligned(8)
    ret = { "type": type }
    if type == SCMD_INFO_RESPONSE:
        ret = parse_info_response(ret, br)
    return ret
    
def parse_info_response(ret, br):
    ret["version"] = br.read_unsigned(8)
    ret["ping"] = br.read_unsigned(32)
    ret["players"] = br.read_unsigned(8)
    br.read_unsigned(4)
    ret["teamsize"] = br.read_unsigned(4)
    name = br.read_bytes_aligned(32)
    ret["name"] = string_strip_null(name).decode("ascii", "ignore")
    return ret
    
def parse_server_list(data):
    result = []
    br = CSBitReader(data)
    if br.read_bytes_aligned(4) != header:
        return None
    type = br.read_unsigned_aligned(8)
    l = br.read_unsigned_aligned(32)
    for i in range(l):
        address = br.read_bytes_aligned(4)
        port = br.read_unsigned_aligned(16)
        address_bytes = struct.unpack(">BBBB",address)
        address = [str(int(x)) for x in address_bytes[::-1]]
        address = ".".join(address)
        result.append((address, port))
    return result

def make_info_request_cmessage(version, ping):
    bw = CSBitWriter()
    bw.write_bytes_aligned(header)
    bw.write_unsigned(8, CCMD_INFO_REQUEST) # CMD=0 for info requests
    bw.write_unsigned(8, version) # Version number
    bw.write_unsigned(32, ping) # Value is used for ping calculations
    return bw.get_bytes()
    
def update_player_list(list, msg):
    if msg["type"] == "JOIN":
        player_obj = list.get(msg["player"], {})
        player_obj["team"] = msg["team"]
        player_obj["name"] = msg["name"]
        player_obj["obj"] = msg["offset"]
        player_obj["index"] = msg["player"]
        if "goal" not in player_obj:
            player_obj["goal"] = 0
        if "assist" not in player_obj:
            player_obj["assist"] = 0
        list[msg["player"]] = player_obj
    elif msg["type"] == "EXIT":
        del list[msg["player"]]
    elif msg["type"] == "GOAL":
        scoring = list.get(msg["scoring_player"])
        assisting = list.get(msg["assisting_player"])
        if scoring:
            scoring["goal"]+=1
        if assisting:
            assisting["assist"]+=1
    
class HQMGameState:
    def __init__(self, id):
        self.id = id
        self.packet = -1
        self.msg_pos = 0
        self.simstep = 0
        self.gameover = 0
        self.redscore = 0
        self.bluescore = 0
        self.period = 0
        self.time = 0
        self.timeout = 0
        self.you = None
        self.saved_states = {}
        self.players = {}
        self.events = []
        
    def copy_state(self, other):
        self.saved_states = other.saved_states.copy()
        self.players = other.players.copy()
        self.events = other.events[:]
        
    @property
    def object_state(self):
        cur_packet_mask = self.packet & 0xff
        state = self.saved_states.get(cur_packet_mask)
        if state is None:
            state = {}
        return state
        
        
        
class HQMObjectState(dict):
    def __init__(self):
        dict.__init__(self)
        self.calculated = False
    
    def calculate_positions(self):
        if not self.calculated:
            import numpy as np
            self.calculated = True
            pos_x = convert_pos(self["pos_x_int"])
            pos_y = convert_pos(self["pos_y_int"])
            pos_z = convert_pos(self["pos_z_int"])
            
            self["pos"] = np.array((pos_x, pos_y, pos_z), dtype=np.float32)
            
            rot_2 = convert_rot_vector(self["rot_a_int"], 31)
            rot_3 = convert_rot_vector(self["rot_b_int"], 31)
            if rot_2 is not None and rot_3 is not None:
                rot_1 = np.cross(rot_2, rot_3)
                self["rot"] = np.column_stack((rot_1, rot_2, rot_3))
            else:
                self["rot"] = None        
            
            if(self["type"]=="PLAYER"):
                               
                stick_x = convert_stick_pos(self["stick_x_int"], pos_x)
                stick_y = convert_stick_pos(self["stick_y_int"], pos_y) 
                stick_z = convert_stick_pos(self["stick_z_int"], pos_z)                
                    
                self["stick_pos"] = np.array((stick_x, stick_y, stick_z), dtype=np.float32)    
                    
                stick_rot_2 = convert_rot_vector(self["stick_rot_a_int"], 25)
                stick_rot_3 = convert_rot_vector(self["stick_rot_b_int"], 25)
                if stick_rot_2 is not None and stick_rot_3 is not None:
                    stick_rot_1 = np.cross(stick_rot_2, stick_rot_3)
                    self["stick_rot"] = np.column_stack((stick_rot_1, stick_rot_2, stick_rot_3))
                else:
                    self["stick_rot"] = None                
                
                self["head_rot"] = convert_unknown_rot(self["head_rot_int"])
                self["body_rot"] = convert_unknown_rot(self["body_rot_int"])        

class HQMClientSession:
    def __init__(self, username, version):
        self.username = username
        self.version = version
        self.state = "join"
        self.gamestate = None
        self.last_message_num = None
        self.chat_messages = deque()
        self.chat_message_index = 0
        
    def add_chat(self, str):
        self.chat_messages.append(str)
        
    def get_message(self):
        bw = CSBitWriter()
        if self.state == "join":
            byte_name = self.username.encode("ascii","ignore").ljust(32, b"\0")
            bw.write_bytes_aligned(header)
            bw.write_unsigned(8, CCMD_JOIN) 
            bw.write_unsigned(8, self.version)
            bw.write_bytes_aligned(byte_name)
        elif self.state == "ingame":
            bw.write_bytes_aligned(header)
            bw.write_unsigned(8, CCMD_UPDATE) 
            bw.write_unsigned_aligned(32, self.gamestate.id)
            bw.write_sp_float_aligned(0) # Stick angle
            bw.write_sp_float_aligned(0) # Movement X, +/- 1.0 or 0.0
            bw.write_sp_float_aligned(0) # ????
            bw.write_sp_float_aligned(0) # Movement Y, +/- 1.0 or 0.0
            bw.write_sp_float_aligned(0) # Stick X
            bw.write_sp_float_aligned(0) # Stick Y
            bw.write_sp_float_aligned(0) # Head rotation
            bw.write_sp_float_aligned(0) # Body rotation
            bw.write_unsigned_aligned(32, 0) # Input keys, such as jump, crouch, join team
            bw.write_unsigned_aligned(32, self.gamestate.packet) # Last read packet
            bw.write_unsigned_aligned(16, self.gamestate.msg_pos) # Last received message
            if len(self.chat_messages) != 0:
                self.chat_message_index = (self.chat_message_index+1) & 7 
                bw.write_unsigned(1, 1)
                bw.write_unsigned(3, self.chat_message_index)             
                message = self.chat_messages.popleft().encode("ascii", "ignore")
                message_len = min(255, len(message))
                bw.write_unsigned(8, message_len)
                bw.write_bytes_aligned(message[0:message_len])
            else:    
                bw.write_unsigned(1, 0)
        return bw.get_bytes()
        
    def get_exit_message(self):
        bw = CSBitWriter()
        bw.write_bytes_aligned(header)
        bw.write_unsigned(8, CCMD_EXIT) 
        return bw.get_bytes()
        
    def parse_message(self, message):
        br = CSBitReader(message)
        if br.read_bytes_aligned(4) != header:
            return None
        type = br.read_unsigned_aligned(8)
        if type == SCMD_NEW_MATCH:
            gameID = br.read_unsigned_aligned(32)
            self.state = "ingame"
            if self.gamestate is None or self.gamestate.id != gameID:
                self.gamestate = HQMGameState(gameID)
        elif type == SCMD_GAME_UPDATE:
            if self.state == "join":
                self.state = "ingame"
                self.gamestate = HQMGameState()
            self.parse_game_update(br)
            
        else:
            # Unknown type
            return None
        return self.gamestate
            
    def parse_game_update(self, br):
        gameID = br.read_unsigned_aligned(32)
        if gameID != self.gamestate.id:
            return
        simstep = br.read_unsigned_aligned(32)
        if simstep<self.gamestate.simstep and self.gamestate.simstep-simstep<100:
            return
        self.new_gamestate = HQMGameState(gameID)
        self.new_gamestate.copy_state(self.gamestate)
        self.new_gamestate.simstep = simstep
        self.new_gamestate.gameover = br.read_unsigned(1)
        self.new_gamestate.redscore = br.read_unsigned(8)
        self.new_gamestate.bluescore = br.read_unsigned(8)
        self.new_gamestate.time = br.read_unsigned(16)
        self.new_gamestate.timeout = br.read_unsigned(16)
        self.new_gamestate.period = br.read_unsigned(8)
        self.new_gamestate.you = br.read_unsigned(8)
        self.parse_objects(br)
        self.parse_messages(br)
        self.gamestate = self.new_gamestate

        
    def parse_objects(self, br):
        cur_packet = br.read_unsigned_aligned(32)
        old_packet = br.read_unsigned_aligned(32)
        cur_packet_mask = cur_packet & 0xff
        old_packet_mask = old_packet & 0xff
        self.new_gamestate.saved_states[cur_packet_mask] = {}
        for i in range(32):
            self.parse_object(br, i, cur_packet_mask, old_packet_mask)
        self.new_gamestate.packet = cur_packet
        
    def parse_object(self, br, i, cur_packet, old_packet):
           
        if old_packet not in self.gamestate.saved_states:
            old_obj = HQMObjectState()
        elif i not in self.gamestate.saved_states[old_packet]:
            old_obj = HQMObjectState()
        else:
            old_obj = self.gamestate.saved_states[old_packet][i]    
        
        obj = HQMObjectState()
        ingame = br.read_unsigned(1) == 1
        if not ingame:
            return

        typenum = br.read_unsigned(2)
        if typenum == 0:
            obj["type"] = "PLAYER"
        elif typenum == 1:
            obj["type"] = "PUCK"
        else:
            obj["type"] = typenum
                  
        obj["pos_x_int"] = br.read_pos(17, old_obj.get("pos_x_int"))
        obj["pos_y_int"] = br.read_pos(17, old_obj.get("pos_y_int"))
        obj["pos_z_int"] = br.read_pos(17, old_obj.get("pos_z_int"))
        obj["rot_a_int"] = br.read_pos(31, old_obj.get("rot_a_int"))
        obj["rot_b_int"] = br.read_pos(31, old_obj.get("rot_b_int"))

        if(obj["type"]=="PLAYER"):
            obj["stick_x_int"] = br.read_pos(13, old_obj.get("stick_x_int"))
            obj["stick_y_int"] = br.read_pos(13, old_obj.get("stick_y_int"))
            obj["stick_z_int"] = br.read_pos(13, old_obj.get("stick_z_int"))
                  
            obj["stick_rot_a_int"] = br.read_pos(25, old_obj.get("stick_rot_a_int"))     
            obj["stick_rot_b_int"] = br.read_pos(25, old_obj.get("stick_rot_b_int"))  
        
            obj["head_rot_int"] = br.read_pos(16, old_obj.get("head_rot_int"))    
            obj["body_rot_int"] = br.read_pos(16, old_obj.get("body_rot_int"))  
      
        self.new_gamestate.saved_states[cur_packet][i] = obj;
   
    def parse_messages(self, br):
        message_num = br.read_unsigned(4)
        self.last_message_num = message_num
        msg_pos     = br.read_unsigned(16)  
        for i in range(msg_pos, msg_pos+message_num):
    
            msg = self.parse_state_message(br)

            if i < self.gamestate.msg_pos:
                continue
            
            update_player_list(self.new_gamestate.players, msg)
            self.new_gamestate.events.append(msg)
        self.new_gamestate.msg_pos = max(self.gamestate.msg_pos, msg_pos+message_num)

        
    def parse_state_message(self, br):
        msg = {}
        type = br.read_unsigned(6)
        
        if type == 0: #player exited/joined
            msg["player"] = br.read_unsigned(6)
            bit = br.read_unsigned(1)
            if bit==1:
                msg["type"] = "JOIN"
            elif bit==0:
                msg["type"] = "EXIT"
            msg["team"] = br.read_unsigned_or_minus_one(2)
            msg["offset"] = br.read_unsigned_or_minus_one(6)
            name = []
            for i in range(31):
                name.append(br.read_unsigned(7))
            name = bytes(name)
            msg["name"] = string_strip_null(name).decode("ascii", "ignore")
        elif type==1: #Goal scored
            msg["type"] = "GOAL"
            msg["team"] = br.read_unsigned(2)
            msg["scoring_player"] = br.read_unsigned_or_minus_one(6)
            msg["assisting_player"] = br.read_unsigned_or_minus_one(6)
        elif type==2: #Normal chat
            msg["type"] = "CHAT"
            msg["player"] = br.read_unsigned_or_minus_one(6)
            msg["size"] = br.read_unsigned(6)
            #print(msg["size"])
            name = []
            for i in range(msg["size"]):
                name.append(br.read_unsigned(7))
            name = bytes(name)
            msg["message"] = string_strip_null(name).decode("ascii", "ignore")
        return msg
    
        
        
        
        
        
     
    
    
    
