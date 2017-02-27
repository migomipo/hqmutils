
import sys
import time
import hqm
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtNetwork import *


master_addr = QHostAddress("216.55.186.104")
master_port = 27590

old_format = QTextCharFormat()
player_format = QTextCharFormat()
player_format.setFontWeight(QFont.Bold)       
server_format = QTextCharFormat(player_format)
server_format.setForeground(QBrush(QColor("magenta")))
goal_format = QTextCharFormat(player_format)
goal_format.setForeground(QBrush(QColor("green")))
        
def get_millis_truncated():
    return int(round(time.time() * 1000)) & 0xffffffff
    
class ServerListProxyTableModel(QSortFilterProxyModel):
    pass

class ServerListTableModel(QAbstractTableModel):
    def __init__(self):
        QAbstractTableModel.__init__(self)
        self.socket = QUdpSocket()
        self.socket.readyRead.connect(self._on_ready_read)
        self.servers = []
        self.server_map = {}
        
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_timeout)
        self.timer.setInterval(1000)
        self.use_update = False
        self.use_public = False
        self.public_timer = QTimer()
        self.public_timer.timeout.connect(self._on_public_timeout)
        self.public_timer.setInterval(2000)

        
    def _on_ready_read(self):
        while self.socket.hasPendingDatagrams():
            
            data,host,port= self.socket.readDatagram(self.socket.pendingDatagramSize())
            host = QHostAddress(host.toIPv4Address())
            if host==master_addr and data.startswith(b"Hock!") and self.use_public:
                addresses = hqm.parse_server_list(data)
                self.layoutAboutToBeChanged.emit()
                
                for ip, port in addresses:
                    ip = QHostAddress(ip)
                    addr = (ip, port)
                    if addr not in self.server_map:
                        new_server = {"ip":ip, "port":port}
                        self.servers.append(new_server)
                        self.server_map[addr] = new_server
                self.layoutChanged.emit()
            elif self.use_update:
                host = QHostAddress(host.toIPv4Address())
                msg = hqm.parse_from_server(data)
                server = self.server_map.get((host, port))
                if server is None:
                    return

                server["ping"] = get_millis_truncated()-msg["ping"]
                server["players"] = msg["players"]
                server["teamsize"] = msg["teamsize"]
                server["version"] = msg["version"]
                server["name"] = msg["name"]
                index = self.servers.index(server)

                self.dataChanged.emit(self.createIndex(index, 2),self.createIndex(index, 6))

        
    def _on_timeout(self):
        for server in self.servers:
            address = server["ip"]
            port = server["port"]
            millis = get_millis_truncated()
            message = hqm.make_info_request_cmessage(55, millis)
            self.socket.writeDatagram(message, address, port)
            
    def _on_public_timeout(self):
        self.socket.writeDatagram(hqm.server_list_message, master_addr, master_port)
        
    def add_server(self, ip, port):
        addr = (ip, port)
        if addr not in self.server_map:
        
            new_server = {"ip":ip, "port":port}
            self.layoutAboutToBeChanged.emit()
            self.servers.append(new_server)
            self.server_map[addr] = new_server
            self.layoutChanged.emit()
            
    def remove_server(self, index):
        self.layoutAboutToBeChanged.emit()
        server = self.servers[index]
        del self.server_map[(server["ip"], server["port"])]
        del self.servers[index]
        self.layoutChanged.emit()

    def clear(self):
        self.layoutAboutToBeChanged.emit()
        self.servers = []
        self.server_map = {}
        self.layoutChanged.emit()
            
    def add_public(self, state):
        self.use_public = state
        if(state):
            self._on_public_timeout()
            self.public_timer.start()
        else:
            self.public_timer.stop()
        
    def update(self, state):
        self.use_update = state
        if(state):
            self._on_timeout()
            self.timer.start()
        else:
            self.timer.stop()       
    

    def headerData(self, col, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if col==0:
                return "IP"
            elif col==1:
                return "Port"
            elif col==2:
                return "Ping"
            elif col==3:
                return "Version"
            elif col==4:
                return "Players"
            elif col==5:
                return "Team size"
            elif col==6:
                return "Name"
        return QVariant()

    def rowCount(self, parent):
        return len(self.servers)
        
    def columnCount(self, parent):
        return 7
        
    def data(self, index, role):
        if not index.isValid(): 
            return QVariant() 
        elif role != Qt.DisplayRole: 
            return QVariant() 
        row = index.row()
        col = index.column()
        server = self.servers[row]
        if col==0:
            return QVariant(server["ip"].toString())
        elif col==1:
            return server["port"]
        elif col==2:
            ping = server.get("ping")
            if ping is not None:
                return ping
        elif col==3:
            version = server.get("version")
            if version is not None:
                return version
        elif col==4:
            players = server.get("players")
            if players is not None:
                return players    
        elif col==5:
            teamsize = server.get("teamsize")
            if teamsize is not None:
                return teamsize
        elif col==6:
            name = server.get("name")
            if name is not None:
                return name          
        return QVariant() 
        
class ServerStateInfoTableModel(QAbstractTableModel):
    def __init__(self, ip, port):
        QAbstractTableModel.__init__(self)
        self.ip = ip
        self.port = port
        self.gamestate = None
        
    def rowCount(self, parent):
        return 6
        
    def columnCount(self, parent):
        return 2
        
    def set_state(self, state):
        self.gamestate = state
        self.dataChanged.emit(self.createIndex(1,1),self.createIndex(self.rowCount(None),1))
        

    def data(self, index, role):
        if not index.isValid(): 
            return QVariant()             
        elif role != Qt.DisplayRole: 
            return QVariant() 
        row = index.row()
        col = index.column()
        if row==0:
            if col==0:
                return "Address"
            elif col==1:
                return self.ip.toString()
        elif row==1:
            if col==0:
                return "Port"
            elif col==1:
                return self.port
        elif row==2:
            if col==0:
                return "Period"
            elif col==1 and self.gamestate:
                period = self.gamestate.period
                if period == 0:
                    period = "Warmup"
                return period
        elif row==3:
            if col==0:
                return "Time"
            elif col==1 and self.gamestate:
                time_left = self.gamestate.time
                minutes = time_left//6000
                seconds = (time_left - (minutes*6000)) // 100
                return "{}:{:0>2}".format(minutes, seconds)
        elif row==4:
            if col==0:
                return "Timeout"
            elif col==1 and self.gamestate:
                time_left = self.gamestate.timeout
                minutes = time_left//6000
                seconds = (time_left - (minutes*6000)) // 100
                return "{}:{:0>2}".format(minutes, seconds)
        elif row==5:
            if col==0:
                return "Score"
            elif col==1 and self.gamestate:
                return "{} - {}".format(self.gamestate.redscore, self.gamestate.bluescore)                
        return QVariant() 
        
class ServerUserListTableModel(QAbstractTableModel):
    def __init__(self):
        QAbstractTableModel.__init__(self)
        self.players = []
        self.you = None
        
    def rowCount(self, parent):
        return len(self.players)
        
    def columnCount(self, parent):
        return 5
        
    def set_state(self, state):
        self.you = state.you
        new_players = sorted(state.players.values(), key=lambda s: s["index"])
        if(len(new_players)!=len(self.players)):
            self.layoutAboutToBeChanged.emit()
            self.players = new_players
            self.layoutChanged.emit()
        else:
            self.players = new_players
            self.dataChanged.emit(self.createIndex(0,0),self.createIndex(len(self.players),4))
            
    def data(self, index, role):

        if not index.isValid(): 
            return QVariant() 
        row = index.row()
        col = index.column()
        player = self.players[row]
        
        if role == Qt.BackgroundRole: 
            if player["index"]==self.you:
               color = QColor(0xCC, 0xFF, 0xCC)        
               return QBrush(color);
            elif player["team"]==0:
               color = QColor(0xFF, 0xCC, 0xCC)        
               return QBrush(color);
            elif player["team"]==1:
               color = QColor(0xCC, 0xCC, 0xFF)        
               return QBrush(color);
        if role != Qt.DisplayRole: 
            return QVariant() 

        if col==0:
            return player["index"]
        elif col==1:
            return player["name"]
        elif col==2:
            team = player["team"]
            if team==0:
                return "Red"
            elif team==1:
                return "Blue"
        elif col==3:
            return player["goal"]  
        elif col==4:
            return player["assist"]              
        return QVariant()  

        
    def headerData(self, col, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if col==0:
                return "#"
            elif col==1:
                return "Name"
            elif col==2:
                return "Team"
            elif col==3:
                return "G"
            elif col==4:
                return "A"
        return QVariant()
        
        
class HQMServerGUI(QWidget):
    closedServerDialog = pyqtSignal(QHostAddress, int)

    def __init__(self, ip, port, username):
        QWidget.__init__(self)
        self.ip = ip
        self.port = port
        self.setWindowTitle("{}:{}".format(self.ip.toString(), self.port))
        
        self.socket = QUdpSocket()
        self.socket.connectToHost(self.ip, self.port)
        self.socket.readyRead.connect(self._on_ready_read)
        self.last_msg_pos = 0
        self.gameID = 0
        self.session = hqm.HQMClientSession(username,55)
        self.player_list = {}
        
        main_layout = QGridLayout()
        
        self.event_list = QTextEdit()
        self.event_list.setReadOnly(True)
        
        
        self.info_table = QFormLayout()
        self.info_table.addRow(QLabel("Address"), QLabel(self.ip.toString()))
        self.info_table.addRow(QLabel("Port"), QLabel(str(self.port)))
        self.period_label = QLabel()
        self.info_table.addRow(QLabel("Period"), self.period_label)
        self.time_label = QLabel()
        self.info_table.addRow(QLabel("Time"), self.time_label)
        self.timeout_label = QLabel()
        self.info_table.addRow(QLabel("Timeout"), self.timeout_label)
        self.score_label = QLabel()
        self.info_table.addRow(QLabel("Score"), self.score_label)
        
        
        self.user_table = QTableView()
        self.user_table_model = ServerUserListTableModel()
        self.user_table.setModel(self.user_table_model)
        self.user_table.setColumnWidth(0, 30)
        self.user_table.setColumnWidth(1, 150)
        self.user_table.setColumnWidth(2, 50)
        self.user_table.setColumnWidth(3, 30)
        self.user_table.setColumnWidth(4, 30)

        self.chat_field = QLineEdit()

        chat_settings = QHBoxLayout()
        self.chat_button = QPushButton("Chat")
        self.chat_hide = QCheckBox("Hide text")
        
        def chat():
            text = self.chat_field.text()
            self.chat_field.clear()
            self.session.add_chat(text)
        
        self.chat_button.clicked.connect(chat)
        self.chat_field.returnPressed.connect(chat)
        
        def chat_hide(state):
            if state==2:
                self.chat_field.setEchoMode(QLineEdit.Password)
            else:
                self.chat_field.setEchoMode(QLineEdit.Normal)
            
        self.chat_hide.stateChanged.connect(chat_hide)
              
        chat_settings.addStretch(1)
        chat_settings.addWidget(self.chat_hide)
        chat_settings.addWidget(self.chat_button)

        
        main_layout.addWidget(self.event_list, 0, 0, 2, 1)
        main_layout.addLayout(self.info_table, 0, 1)
        main_layout.addWidget(self.user_table, 1, 1)
        main_layout.addWidget(self.chat_field, 2, 0)
        main_layout.addLayout(chat_settings, 3, 0)

        main_layout.setColumnStretch(0,2)
        main_layout.setColumnMinimumWidth(1,300)
        
        self.resize(800, 600)
        self.setLayout(main_layout)
        
        self.update_timer = QTimer()
        self.update_timer.setInterval(20)
        self.update_timer.timeout.connect(self._on_timeout)
        self.update_timer.start()
        
    def _on_timeout(self):
        send = self.session.get_message()
        self.socket.write(send)
        
    def _on_ready_read(self):
        while self.socket.hasPendingDatagrams():            
            data = self.socket.read(8192)
            self.gamestate = self.session.parse_message(data)
            self.update_info_label()
            self.user_table_model.set_state(self.gamestate)
            if self.gameID != self.gamestate.id:  
                self.reset_log(self.gamestate.id)
            if(self.gamestate.msg_pos>self.last_msg_pos):
                events = self.gamestate.events[self.last_msg_pos:self.gamestate.msg_pos]
                self.last_msg_pos = self.gamestate.msg_pos
                for msg in events:
                    hqm.update_player_list(self.player_list, msg)
                    self.insert_event(msg)
                    
                    
    def update_info_label(self):
        period = self.gamestate.period
        if period == 0:
            period = "Warmup"
        else:
            period = str(period)
        self.period_label.setText(period)
        time_left = self.gamestate.time
        minutes = time_left//6000
        seconds = (time_left - (minutes*6000)) // 100
        self.time_label.setText("{}:{:0>2}".format(minutes, seconds))
        time_left = self.gamestate.timeout
        minutes = time_left//6000
        seconds = (time_left - (minutes*6000)) // 100
        self.timeout_label.setText("{}:{:0>2}".format(minutes, seconds))
        self.score_label.setText("<font color='red'>{}</font> - <font color='blue'>{}</font>".format(self.gamestate.redscore, self.gamestate.bluescore))
        


                         
    def insert_event(self, msg):   
        cursor = self.event_list.textCursor()
        cursor.movePosition(QTextCursor.End)
              
        def get_team_format(team):
            team_format = QTextCharFormat()
            team_format.setFontWeight(QFont.Bold)
            if team==-1:
                team_format.setForeground(QBrush(QColor("grey")))
            elif team==0:
                team_format.setForeground(QBrush(QColor("red")))
            elif team==1:
                team_format.setForeground(QBrush(QColor("blue")))
            return team_format
            
        def insert_player(cursor, name, i):
            cursor.setCharFormat(player_format)
            cursor.insertText(name)
            cursor.setCharFormat(old_format)
            cursor.insertText(" (#{})".format(i))  
            
        def insert_team(cursor, team):
            team_format = get_team_format(team)
            cursor.setCharFormat(team_format)
            if team==-1:                   
                cursor.insertText("the spectators")  
            elif team==0:
                cursor.insertText("the red team")  
            elif team==1:
                cursor.insertText("the blue team")
            cursor.setCharFormat(old_format)                    
            


        if msg["type"]=="JOIN" or msg["type"]=="EXIT":
            name = msg["name"]
            i = msg["player"]
            team = msg["team"]
            insert_player(cursor, name, i)
            if msg["type"]=="JOIN":
                cursor.insertText(" has joined ")             
                insert_team(cursor, team)
            else:
                cursor.insertText(" has exited")
            cursor.insertText(".\n") 
        elif msg["type"]=="CHAT":
            i = msg["player"]
            message = msg["message"]
            if i==-1:
                cursor.setCharFormat(server_format)
                cursor.insertText("Server")
                cursor.setCharFormat(old_format)
            else:    
                player = self.player_list[i]
                name = player["name"]
                insert_player(cursor, name, i)
            cursor.insertText(": {}\n".format(message))
        elif msg["type"]=="GOAL":
            team = msg["team"]
            scoring = self.player_list.get(msg["scoring_player"])
            assisting = self.player_list.get(msg["assisting_player"])
            cursor.setCharFormat(goal_format)
            cursor.insertText("GOAL! ")
            cursor.setCharFormat(old_format)
            if scoring:
                insert_player(cursor, scoring["name"], scoring["index"])
                if assisting:
                    cursor.insertText(" (assisted by ")
                    insert_player(cursor, assisting["name"], assisting["index"])
                    cursor.insertText(")")
            else:
                cursor.insertText("The puck")
            cursor.insertText(" scored for ")
            insert_team(cursor, team)
            cursor.insertText(".\n") 
        
            
           
    def reset_log(self, gameID):
        cursor = self.event_list.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.setCharFormat(server_format)
        cursor.insertText("New game starting ({})\n".format(gameID))
        cursor.setCharFormat(old_format)
        self.last_msg_pos = 0
        self.player_list = {}
        self.gameID = gameID 
        
    def closeEvent(self, event):
        self.update_timer.stop()
        self.socket.write(self.session.get_exit_message())
        self.socket.close() 
        self.closedServerDialog.emit(self.ip, self.port)
        QWidget.closeEvent(self, event)

        
class HQMUtilsGUI(QWidget):
    def __init__(self):
        QWidget.__init__(self)
                
        self.server_gui = {}
        self.setWindowTitle("HQM Utils GUI")
        
        main_layout = QVBoxLayout()
        
        ip_group = QGroupBox("Add server")
          
        ip_form_layout = QFormLayout()
        
        self.address_field = QLineEdit()
        self.port_field = QLineEdit()
        ip_form_layout.addRow(QLabel("Address"), self.address_field)
        ip_form_layout.addRow(QLabel("Port"), self.port_field)
        buttons = QDialogButtonBox()
        
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self.add_server)
        buttons.addButton(self.add_button, QDialogButtonBox.AcceptRole)

        ip_box_layout = QVBoxLayout()
        ip_box_layout.addLayout(ip_form_layout)
        ip_box_layout.addWidget(buttons)
        ip_group.setLayout(ip_box_layout)
        self.table = QTableView() 
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);
        self.table.setSelectionMode(QAbstractItemView.SingleSelection);

        self.model = ServerListTableModel()
        self.proxy_model = ServerListProxyTableModel()
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setDynamicSortFilter(True)
        self.table.setModel(self.proxy_model)
        self.table.setSortingEnabled(True)
        self.table.setColumnWidth(0, 125)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 60)
        self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 60)
        self.table.setColumnWidth(6, 200)

        self.load_public_box = QCheckBox("Load public servers")
        self.load_public_box.stateChanged.connect(self.load_public_servers)
        self.update_box = QCheckBox("Update servers")
        self.update_box.stateChanged.connect(self.update_servers)
        self.update_box.setCheckState(2)
        self.join_button = QPushButton("Join")
        self.join_button.clicked.connect(self.show_server)
        self.clear_button = QPushButton("Remove all")
        self.clear_button.clicked.connect(self.clear_servers)
        self.remove_button = QPushButton("Remove") 
        self.remove_button.clicked.connect(self.remove_server)
       
        self.user_name_field = QLineEdit()
        
        def user_name_changed():
            text = self.user_name_field.text()
            self.join_button.setEnabled(self.is_valid_username(text))
        user_name_changed()
        self.user_name_field.textChanged.connect(user_name_changed)
        
        lower_box = QGridLayout()
        lower_box.addWidget(QLabel("User name"), 0, 0)
        lower_box.addWidget(self.user_name_field, 0, 1)
        lower_box.addWidget(self.load_public_box, 1, 0, 1, 2)
        lower_box.addWidget(self.update_box, 2, 0, 1, 2)
       
        lower_box.setColumnStretch(2,1)
        lower_box.addWidget(self.remove_button, 0, 3)
        lower_box.addWidget(self.clear_button, 0, 4)
        lower_box.addWidget(self.join_button, 0, 5)
              
        main_layout.addWidget(ip_group)
        main_layout.addWidget(self.table)
        main_layout.addLayout(lower_box)

        self.setLayout(main_layout) 
        
    def is_valid_username(self, username):
        b = username.encode("ascii", "ignore")
        return len(b)>0
                         
    def show_server(self):
        username = self.user_name_field.text()
        if not self.is_valid_username(username):
            return
    
        row = self.table.selectionModel().currentIndex();
        row = self.proxy_model.mapToSource(row).row()
        server = self.model.servers[row]
        ip = server["ip"]
        port = server["port"]
        
        def on_close(ip, port):
            del self.server_gui[(ip, port)]
        if (ip, port) not in self.server_gui:
            self.server_gui[(ip, port)] = HQMServerGUI(ip, port, username)
            self.server_gui[(ip, port)].closedServerDialog.connect(on_close)      
        self.server_gui[(ip, port)].show()
        self.server_gui[(ip, port)].setWindowState(Qt.WindowActive)
        self.server_gui[(ip, port)].activateWindow()
        
    def remove_server(self):
        row = self.table.selectionModel().currentIndex();
        row = self.proxy_model.mapToSource(row).row()
        self.model.remove_server(row)
       
    def add_server(self):
        address = self.address_field.text()
        port = self.port_field.text()
        self.model.add_server(QHostAddress(address), int(port))
        
    def load_public_servers(self, state):
        self.model.add_public(state==2)

    def update_servers(self, state):
        self.model.update(state==2)
        
    def clear_servers(self):
        self.model.clear()
        
def show_gui():
    app = QApplication(sys.argv)
    w = HQMUtilsGUI()
    w.resize(700, 500);  
    w.show()
    sys.exit(app.exec_())    

if __name__ == '__main__':
    
    show_gui()