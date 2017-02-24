# Copyright © 2017, John Eriksson
# See LICENSE for terms of use

import sys
import socket
import hqm
import time
import asyncio

master_addr = "216.55.186.104"
master_port = 27590
master = (master_addr, master_port)

def print_help(args=None):
    print("MigoMipo HQM Utils © John Eriksson 2017")
    print("Commands:")
    print("  info <ip> <port> : Shows info about a specific server")
    print("  info public      : Shows info about all public servers")
    print("  state <ip> <port>: Joins a server and prints information")

    
def get_millis_truncated():
    return int(round(time.time() * 1000)) & 0xffffffff
  

def int_to_team(n):  
    if n == -1:
        team = "-"
    elif n == 0:
        team = "RED"
    elif n == 1:
        team = "BLUE"
    return team
    
    
def get_log_line(msg, format, player_list):
    type = msg["type"]
    if type=="JOIN":
        i = msg["player"]
        name = msg["name"]
        team = int_to_team(msg["team"])
        message = ""
    elif type=="EXIT":
        i = msg["player"]
        name = msg["name"]
        team = ""
        message = ""
    elif type=="GOAL":
        i = ""        
        name = ""
        team = int_to_team(msg["team"])
        scoring = player_list.get(msg["scoring_player"])
        assisting = player_list.get(msg["assisting_player"])
        if assisting:
            message = "{}(#{}), assisted by {}(#{})".format(
                scoring["name"], scoring["index"], assisting ["name"], assisting ["index"])
        elif scoring:
            message = "{}(#{}) ".format(
                scoring["name"], scoring["index"])
        else:
            message = ""
    elif type=="CHAT":
        i = msg["player"]
        if i==-1:
            i = ""
            name = ""
            team = ""
        else:
            chatter = player_list.get(i)
            name = chatter["name"]
            team = int_to_team(chatter["team"])
        message = msg["message"]
    return format.format(type, i, name, team, message) 


class StateClientProtocol:
    def __init__(self, loop):
        self.loop = loop
        
    def connection_made(self, transport):
        self.transport = transport
        self.session = hqm.HQMClientSession("MigoMibot",55)

        async def periodic():
            while True:
                self.transport.sendto(self.session.get_message())
                try:
                    await asyncio.sleep(0.1)   
                except asyncio.CancelledError:
                    break  
                  
            
        self.periodic = self.loop.create_task(periodic())

    def datagram_received(self, data, addr):
        self.gamestate = self.session.parse_message(data)
        if self.session.last_message_num == 0:  
            self.transport.sendto(self.session.get_exit_message(), addr) 
            self.transport.close()
            
    def connection_lost(self, exc):
       self.periodic.add_done_callback(lambda f: self.loop.stop())
       self.periodic.cancel()
       
    
def state(args):
    if len(args)<2:
        print("Usage: state <ip> <port>");
        return  
    ip = args[0]
    port = int(args[1])
    addr = (ip, port)

    show_log = "-l" in args
    
    loop = asyncio.get_event_loop()
    connect = loop.create_datagram_endpoint(lambda: StateClientProtocol(loop), remote_addr=addr)
    transport, protocol = loop.run_until_complete(connect)
    
    loop.run_forever()
    transport.close()
    loop.close()

    gamestate = protocol.gamestate
              
    print("Score:   {} - {}".format(gamestate.redscore, gamestate.bluescore))  
    time_left = gamestate.time
    minutes = time_left//6000
    seconds = (time_left - (minutes*6000)) // 100
    print("Time:    {}:{:0>2}".format(minutes, seconds))  
    time_out = gamestate.timeout
    minutes = time_out//6000
    seconds = (time_out - (minutes*6000)) // 100
    print("Timeout: {}:{:0>2}".format(minutes, seconds))  
    period = gamestate.period
    if period == 0:
        period = "Warmup"
    print("Period:  {}".format(period))  
    print("Players:")
    format = "{:<4}{:<30}{:<8}{:<5}{:<5}"
    print(format.format("#", "NAME", "TEAM", "G", "A"))
    for player in gamestate.players.values():
        team = int_to_team(player["team"])
        index = str(player["index"])
        if player["index"] == gamestate.you:
            index += "*"
        print(format.format(index, player["name"], team, player["goal"], player["assist"]))
    if show_log:
        print("Log:")
        player_list = {}
        events = gamestate.events
        format = "{:<6}{:<4}{:<32}{:<6}{}"
        print(format.format("TYPE", "#", "NAME", "TEAM", "MESSAGE"))  
        for msg in events:
            hqm.update_player_list(player_list, msg)
            
            print(get_log_line(msg, format, player_list))  

             
                
class MonitorClientProtocol:
    def __init__(self, loop):
        self.loop = loop
        self.format = "{:<6}{:<4}{:<32}{:<6}{}"
        
    def connection_made(self, transport):
        self.transport = transport
        self.session = hqm.HQMClientSession("MigoMibot",55)
        self.last_msg_pos = 0
        self.player_list = {}
        print(self.format.format("TYPE", "#", "NAME", "TEAM", "MESSAGE"))

        async def periodic():
            while True:
                self.transport.sendto(self.session.get_message())
                try:
                    await asyncio.sleep(0.1)   
                except asyncio.CancelledError:
                    break     
                
        self.periodic = self.loop.create_task(periodic())

    def datagram_received(self, data, addr):
        self.addr = addr
        gamestate = self.session.parse_message(data)
        if gamestate and gamestate.msg_pos>self.last_msg_pos:
            events = gamestate.events[self.last_msg_pos:gamestate.msg_pos]
            self.last_msg_pos = gamestate.msg_pos
            for msg in events:
                hqm.update_player_list(self.player_list, msg)
                print(get_log_line(msg, self.format, self.player_list)) 

    def connection_lost(self, exc):
        print(exc)
    
    def stop(self):   
        self.transport.sendto(self.session.get_exit_message(), self.addr)   
        self.periodic.cancel()  
        self.loop.run_until_complete(self.periodic)  
        self.loop.stop()         
                
def monitor(args):
    if len(args)<2:
        print("Usage: monitor <ip> <port>");
        return  
    ip = args[0]
    port = int(args[1])
    addr = (ip, port)
    
    loop = asyncio.get_event_loop()
    connect = loop.create_datagram_endpoint(lambda: MonitorClientProtocol(loop), remote_addr=addr)
    transport, protocol = loop.run_until_complete(connect)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    protocol.stop()
    transport.close()
    loop.close()

  

def server_info(args):
    if len(args)>0 and args[0] == "public":
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(3)
            sock.sendto(hqm.server_list_message, master)
            data, addr = sock.recvfrom(1024)
            addresses = hqm.parse_server_list(data)
            if "-a" in args:
                format = "{:<17}{:<8}"
                print(format.format("ADDRESS", "PORT"))
                for addr in addresses:
                    print(format.format(addr[0], addr[1]))  
            else:
                get_server_info(sock, addresses)        
    elif len(args)>=2:
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
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(3)
            get_server_info(sock, dests)        
    else:
        print("Usage: info <ip> <port> or");
        print("       info public");
        print("You can request multiple ports at once by separating port numbers with , (no spaces)");
        print("You can request an entire port range by writing <port>-<port>");
        
    
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
    "state": state,
    "monitor": monitor
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
    