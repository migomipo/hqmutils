from bitparse import CSBitReader
from bitparse import CSBitWriter
import struct

header = b"Hock"

CCMD_INFO_REQUEST = 0 

SCMD_INFO_RESPONSE = 1 


server_list_message = b"Hock!"

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
    firstZero = name.find(0)
    if firstZero != -1:
        name = name[:firstZero]
    ret["name"] = name.decode("iso-8859-1")
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
    
    
    
