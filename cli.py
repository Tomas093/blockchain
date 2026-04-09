import time
import socket
import requests as http_requests

from blockchain import blockchain
from models import Transaction, Block


def resolve_periodically(interval=30):
    while True:
        blockchain.resolve_conflicts()
        time.sleep(interval)


cmd_functions = {
    "tx": lambda args: blockchain.add_transaction(Transaction(args[0], args[1], int(args[2]), args[3], args[4])) if len(
        args) >= 5 else print("Error: Faltan argumentos. Uso: tx <from> <to> <amount> <publicKey> <signature>"),
    "pt": lambda args: print(
        f"Pending transactions: {[tx.to_dict() if hasattr(tx, 'to_dict') else tx for tx in blockchain.pending_transactions]}"),
    "mine": lambda args: http_requests.post(f"http://localhost:{blockchain.port}/mine", timeout=10),
    "r": lambda args: blockchain.resolve_conflicts(),
    "chain": lambda args: print(
        f"Chain: {[block.to_dict() if isinstance(block, Block) else block for block in blockchain.chain]}"),
    "help": lambda args: print_help(),
    "reg": lambda args: register_peer_handler(args),
    "peers": lambda args: print(f"Peers: {list(blockchain.peers)}"),
    "s": lambda args: print_status(),
    "port": lambda args: print(f"Port: {blockchain.port}")
}

def get_my_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))  # No hace falta que exista conexión real
    ip_local = s.getsockname()[0]
    s.close()
    
    return ip_local

def register_peer_handler(args):
    if not args or not len(args):
        return
    
    my_ip = get_my_ip()
    print(f"Registering peer: {args[0]}")
    my_url = f"http://{my_ip}:{blockchain.port}"
    
    try:
        x = http_requests.post(
            f"{args[0]}/peers", 
            json={"peer": my_url},
            timeout=5) 
        
    except Exception as e:
        print(f"Error registering peer: {e}")
        return False
    
    y = blockchain.register_peers([args[0]])
    return x and y

def print_help():
    print(
        f"  Current chain length: {len(blockchain.chain)}, pending transactions: {len(blockchain.pending_transactions)}")
    print(f"  Latest block hash: {blockchain.chain[-1]['hash']}, nonce: {blockchain.chain[-1]['nonce']}")
    print(f"  Peers: {list(blockchain.peers)}")
    print(f"  To make a transaction type tx with args from, to, amount, sig (e.g. tx alice bob 10 signature)")
    print(f"  To show pending transactions type pt")
    print(f"  To mine a block type mine")
    print(f"  To resolve conflicts type r")
    print(f"  To show chain type chain")
    print(f"  To register a peer type reg with the peer URL (e.g. reg http://localhost:5001)")
    print(f"  To show this help message type help")
    print(f"  To exit type q")


def print_status():
    print(
        f"  Current chain length: {len(blockchain.chain)}, pending transactions: {len(blockchain.pending_transactions)}")
    print(f"  Latest block hash: {blockchain.chain[-1]['hash']}, nonce: {blockchain.chain[-1]['nonce']}")
    print(f"  Peers: {list(blockchain.peers)}")


def cli_loop():
    while True:
        time.sleep(1)

        cmd = input("Enter command: ").strip().lower()
        cmd_parts = cmd.split()

        if not cmd_parts:
            continue

        cmd_key = cmd_parts[0]
        cmd_args = cmd_parts[1:]

        cmd_functions.get(cmd_key, lambda args: print("Unknown command"))(cmd_args)
        if cmd_key == "q":
            print("Exiting...")
            break