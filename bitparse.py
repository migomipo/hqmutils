import struct

class CSBitWriter():


    def __init__(self):
        self.pos = 0
        self.bytes = bytearray()
        
    def get_bytes(self):
        return bytes(self.bytes)
        
    def write_bytes_aligned(self, bytes):      
        if self.pos % 8 != 0:
            self.pos += 8 - (self.pos%8)      
        self.bytes += bytes
        self.pos+=(len(bytes)*8)
        
    def write_unsigned_aligned(self, length, val):
        if(length%8!=0):
            return -1
        if self.pos % 8 != 0:
            self.pos += 8 - (self.pos%8)
        self.write_unsigned(length, val)
          
        
    def write_unsigned(self, length, val):

        p = 0
        val &= ((1 << length)-1)
        while length>0:        
            b = self.pos // 8;
            o = self.pos % 8;  
            l = 8 - o;
            chunk = (val >> p) & ((1<< min(length, l))-1)
            
            if o!=0:
                self.bytes[b] |= chunk << o
            else:
                self.bytes.append(chunk)
                          
            if l>=length:               
                self.pos += length
                length = 0
            else:              
                self.pos += l
                p += l
                length -= l

                
    def write_signed(self, length, val):      
        result = self.write_unsigned(length, val)
        return result
             
    def write_sp_float_aligned(self, val):
        self.write_bytes_aligned(struct.pack("f", val))
        
    def write_dp_float_aligned(self, val):
        self.write_bytes_aligned(struct.pack("d", val))
        
    def write_struct_aligned(self, format, *data):
        self.write_bytes_aligned(struct.pack(format, *val))
        
    def write_pos(self, len, pos, old=None):

        self.write_unsigned(2, 3)
        self.write_unsigned(len, pos)
        
            

class CSBitReader():
    def __init__(self, bytes):
        self.pos = 0
        self.bytes = bytes
      
    def read_bytes_aligned(self, length):      
        if self.pos % 8 != 0:
            self.pos += 8 - (self.pos%8)      
        b = self.pos // 8
        result = self.bytes[b:b+length]
        self.pos+=(length*8)
        if len(result)!=length:
            return None
        return result
        
    def read_unsigned_aligned(self, length):
        result = 0
        if(length%8!=0):
            return -1
        if self.pos % 8 != 0:
            self.pos += 8 - (self.pos%8)
        return self.read_unsigned(length)
          
        
    def read_unsigned(self, length):
        p = 0
        result = 0
        while length>0:        
            b = self.pos // 8;
            if b >= len(self.bytes):
                byte = 0
            else:
                byte = self.bytes[b]
            o = self.pos % 8;  
            l = 8 - o;
            if l>=length:
                mask = ~(-1 << length)
                d = (self.bytes[b] >> o) & mask
                result |= d << p
                self.pos+=length
                length = 0
            else:
                mask = ~(-1 << l)
                d = (self.bytes[b] >> o) & mask
                result |= d << p
                self.pos += l
                p += l
                length -= l
        return result
                
    def read_signed(self, length):
        result = self.read_unsigned(length)
        if result is None:
            return None
        if result >= (1 << length-1):
            result = (-1 << length) | result 
        return result
        
    def read_unsigned_or_minus_one(self, length):
        result = self.read_unsigned(length)
        if result == (1 << length)-1:
            result = -1
        return result
        
    def read_sp_float_aligned(self):
        b = self.read_bytes_aligned(4)
        if b is None:
            return None
        return struct.unpack("f", b)[0]
        
    def read_dp_float_aligned(self):
        b = self.read_bytes_aligned(8)
        if b is None:
            return None
        return struct.unpack("d", b)[0]
        
    def read_struct_aligned(self, format):
        length = struct.calcsize(format)
        b = read_bytes_aligned(self, length)
        if b is None:
            return None
        return struct.unpack(format, b)
        
        
    def read_pos(self, len, old=None):
            
        #if old is None:
        #    print("No known value")
        
        type = self.read_unsigned(2)
        if type==0: 
            r = self.read_signed(3)
            pos = old + r if old is not None else None
        elif type==1:
            r = self.read_signed(6)
            pos = old + r if old is not None else None
        elif type==2:
            r = self.read_signed(12)
            pos = old + r if old is not None else None
        elif type==3:
            pos = self.read_unsigned(len)
        else:
            pos = None
        return pos