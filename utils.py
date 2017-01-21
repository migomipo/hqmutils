import sys
import socket
import hqm
import time

master_addr = "216.55.186.104"
master_port = 27590
master = (master_addr, master_port)

def print_help(args=None):
    print("MigoMipo HQM Utils © John Eriksson 2017")
    print("Commands:")
    print("\tinfo <ip> <addr> : Shows info about a specific server")
    print("\tall              : Shows info about all servers")
    
def get_millis_truncated():
    return int(round(time.time() * 1000)) & 0xffffffff
    
def server_info(args):
    if len(args)<2:
        print("Usage: info <ip> <port>");
        print("You can request multiple ports at once by separating port numbers with , (no spaces)");
        print("You can request an entire port range by writing <port>-<port>");
        return
    ip = args[0]
    dests = []  
    try:
        port_ranges = args[1].split(",")
        for port_range in port_ranges:
            partition = port_range.partition("-")
            start = int(partition[0])
            if partition[1]!="":
                end = int(partition[2])
                for port in range(start, end+1):
                    dests.append((ip, port))
            else:
                dests.append((ip, start))
    except ValueError:
        print("Incorrect arguments")
        return
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    get_server_info(sock, dests)
    
def all_servers(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    sock.sendto(hqm.server_list_message, master)
    data, addr = sock.recvfrom(1024)
    addresses = hqm.parse_server_list(data)
    get_server_info(sock, addresses)
    
    
def get_server_info(sock, addresses):

    start_data = {}
    for address in addresses:   
        millis = get_millis_truncated()
        start_data[address] = {"millis": millis}
        message = hqm.make_info_request_cmessage(55, millis)
        sock.sendto(message, address)
    format = "{:<17}{:<8}{:<8}{:<8}{:<8}{:<8}{}"
    print(format.format("ADDRESS", "PORT", "PING", "VERSION", "PLAYERS", "TEAM", "NAME"))
    while len(start_data) > 0:
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            break
        if addr in start_data:
            addr_data = start_data[addr]
            msg = hqm.parse_from_server(data)
            ping = get_millis_truncated()-msg["ping"]
            players = msg["players"]
            teamsize = msg["teamsize"]
            version = msg["version"]
            name = msg["name"]
            if ping < 0:
                ping += 0xffffffff
            print(format.format(addr[0], addr[1], ping, version, players, teamsize, name))    
            
            del start_data[addr]
    for addr in start_data:
        print("{:<17}{:<8}TIMED OUT".format(addr[0], addr[1]))
            
          
            
            
    

commands = {
    "help": print_help,
    "info": server_info,
    "all": all_servers
}

if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args)==0:
        print_help()
    else: 
        cmd = commands.get(args[0])
        if cmd is None:
            print("Unknown command " + args[0])
            print_help()
        else:
            cmd(args[1:])
    