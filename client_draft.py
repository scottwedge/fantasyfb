import socket
from os import fsync,system,_exit
from time import strftime,localtime,sleep
import sys
import threading
import select
from multiprocessing import *
from draft import Draft
from roster import Roster
from player import Player
import msvcrt
import time


send_address = ("192.168.0.106", 7096)
confirm_selection_str = "It's your turn. Would you like to select one of those players? if so please send y<selection> for example if you want #10 from that list please send 'y10'\n"

'''
Controls received events and decides to send acks.
'''

class SendingThread(threading.Thread):
    def __init__(self, sock, queue, draft, send_addr):
        threading.Thread.__init__(self)
        self.name = 'SendingThread'
        self.sock = sock
        self.queue = queue
        self.draft = draft
        self.send_addr = send_addr

    def run(self):
        while True:
            while not self.queue.empty():
                data = self.queue.get()
                self.sock.sendto(data,self.send_addr)
                self.queue.task_done()
            time.sleep(1)


class ReceiverThread(threading.Thread):
    def __init__(self, port, keyqueue, txqueue, draft):
        threading.Thread.__init__(self)
        self.keyqueue = keyqueue
        self.name = 'ReceiverThread'
        self.txqueue = txqueue
        self.draft = draft

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(0)
        self.sock.settimeout(3)
        self.sock.bind(('',port))
        out_string = "Socket open on {}! Listening...".format(port)
        self.draft.logger.logg(out_string, 1)

    def run(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
                out_string = (strftime("[%H:%M:%S] ",localtime()) + data + " from " + str(addr[0]) + ":" + str(addr[1]))
                self.draft.acquire()
                self.draft.logger.logg(out_string, 1)
                splitter = data.split(",")
                self.draft.logger.logg(splitter, 1)
                if splitter[0] == "sync":
                    for i in range(1, len(splitter)):
                        self.draft.draft_player(int(splitter[i]))
                    self.keyqueue.put("sync")
                if splitter[0] == "error":
                    self.keyqueue.put(data)
                    self.txqueue.put("ack")
                if splitter[0] == "draftack":
                    self.keyqueue.put(data)
                    self.txqueue.put("ack")
                self.draft.release()
            except:
                pass

    def send_server(self, msg):
        self.txqueue.put("{0},{1}".format(self.draft.user_roster.name, msg))

class KeyboardThread(threading.Thread):
    def __init__(self, draft, txqueue, rxqueue):
        threading.Thread.__init__(self)
        self.name = 'KeyboardThread'
        self.draft = draft
        self.rxqueue = rxqueue
        self.txqueue = txqueue
        self.state = 0
        self.synced = 0
        self.selected = 0
        self.pick_outcome = 0
        self.selections = []

    def run(self):
        while True:
            try:
                uIn = input()
                if uIn:
                    self.parse_input(uIn)
            except EOFError:
                _exit(1)
            except TimeoutExpired:
                pass
    def wait_server(self):
        while not self.rxqueue.empty():
            data = self.rxqueue.get()
            if data == "sync":
                self.synced = 1
            if data == "draftack":
                #improve this. 
                self.draft.logger.logg("Congrats you drafted the player you wanted.", 1)
                self.pick_outcome = "success"
            if data == "error":
                self.pick_outcome = "failure"
            self.rxqueue.task_done()
        return
    def parse_input(self, uIn):
        draft = self.draft
        if self.state == 0:
            if uIn == "h":
                draft.logger.logg("help menu\nInput | Function|", 1)
                draft.logger.logg("1  | Print Best available", 1)
                draft.logger.logg("2  | Print Current Roster todo", 1)
                draft.logger.logg("3  | Revert Pick todo", 1)
                draft.logger.logg("start fuzzy finding any name to search for a player you would like. See creator for what fuzzy finding means:) (he stole the idea from a vim plugin he uses)", 1)
                return
            elif uIn.startswith("1:"):
                try:
                    position = uIn.split(':')[1]
                except:
                    position = None
                self.selections = draft.show_topavail(position)
                if draft.my_turn():
                    draft.logger.logg(confirm_selection_str, 1)
                    self.state = "confirm_selections"
            elif uIn.startswith("1"):
                selections = draft.show_topavail(None)
                if draft.my_turn():
                    draft.logger.logg(confirm_selection_str, 1)
                    self.state = "confirm_selections"
        elif self.state == "confirm_selections":
            name, player_idx = draft.confirm_selection(self.selections, uIn)
            if (name != None) and (player_idx != None):
                self.synced = 0
                self.pick_outcome = 0
                while ((self.synced == 0) and (self.pick_outcome == 0)):
                    self.wait_server()
                    if self.pick_outcome == "success":
                        draft.logger.logg("Congrats you draft the player you wanted", 1)
                        draft.logger.logg("waiting sync", 1)
                        self.state = "wait_sync"
                    if self.pick_outcome == "failure":
                        draft.logger.logg("Error :( Vince can't write code", 1)
                        draft.logger.logg("waiting sync", 1)
                        self.synced = 0
                        self.state = "wait_sync"
        return 

    def send_server(self, msg):
        self.txqueue.put("{0},{1}".format(self.draft.user_name, msg))


def player_generate_fromcsv(line):
    if line == "":
        return None
    lis = line.replace("\"", "").split(",")
    try:
        rank = int(lis[0], 10)
    except:
        return
    try:
        position = lis[5]
        uppers = [l for l in position if l.isupper()]
        position = "".join(uppers)
        while (len(position) < 3):
            position += " "
    except:
        return
    name = lis[3]
    team = lis[4]
    while (len(team) < 3):
        team += " "
    try:
        bye = int(lis[6], 10)
    except:
        bye = None
    try:
        adp = lis[11].split('.')[0]
    except IndexError:
        #unlucky see if it is not a float
        pass
    try:
        adp = int(adp, 10)
    except ValueError:
        adp = "No data"
    player = Player(position, rank, name, team, bye, adp)
    return player


def main():
    port = int(input("Enter the Port: "), 10)
    players = []
    player_csv = "FantasyPros_2020_Draft_Overall_Rankings.csv"
    with open(player_csv,'r') as f:
        f.__next__()
        for line in f:
            player = player_generate_fromcsv(line)
            if player != None:
                players.append(player)

    # position = int(input("Welcome to Vince's Mock Draft. Please Enter your position:"), 10)
    # name = input("Welcome to Vince's Mock Draft. Please Enter your team name:")
    # n_rosters = int(input("Welcome to Vince's Mock Draft. Please Enter the number of players in the draft: "), 10)
    position = 6
    name = "vinny"
    n_rosters = 8
    draft = Draft(position, name, players, n_rosters, player_csv)

    txqueue = Queue()
    keyboard_rxqueue = Queue()

    receive_thr = ReceiverThread(port, keyboard_rxqueue, txqueue, draft)
    threadpool = []
    threadpool.append(receive_thr)
    send_thr = SendingThread(receive_thr.sock, txqueue, draft, send_address)
    threadpool.append(send_thr)
    key_thr = KeyboardThread(draft, txqueue, keyboard_rxqueue)

    threadpool.append(key_thr)

    for t in threadpool:
        t.start()
    alive = True
    try:
        while alive:
            for t in threadpool:
                if not t.is_alive():
                    try:
                        print(t.name + " has died! Exiting.")
                    except:
                        _exit(1)
                    _exit(1)
                    alive = False
    except KeyboardInterrupt:
        _exit(1)
    return

if __name__ == '__main__':
    main()