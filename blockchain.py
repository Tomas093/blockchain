import threading
import time
from typing import Any

import requests as http_requests

from models import Block, Transaction
from utils import calculate_hash, hash_valid


class Blockchain:
    def __init__(self):
        self.chain: list[Block] = []
        self.pending_transactions: list[Transaction] = []
        self.peers = set()
        self.lock = threading.Lock()
        self.port = None
        self._create_genesis_block()

    # -- Genesis block ------------------------------------------------------

    def _create_genesis_block(self):
        genesis = self._mine_raw_block(
            index=0,
            transactions=[],
            previous_hash="0" * 64,
            timestamp=0,
        )
        self.chain.append(genesis)

    # -- Mining -------------------------------------------------------------

    def _mine_raw_block(self, index: int, transactions: list, previous_hash: str, timestamp: int = None) -> Block:
        if timestamp is None:
            timestamp = int(time.time())
        nonce = 0
        h = calculate_hash(
            index,
            timestamp,
            transactions,
            previous_hash,
            nonce
        )

        while not hash_valid(h):
            nonce += 1
            h = calculate_hash(
                index,
                timestamp,
                transactions,
                previous_hash,
                nonce
            )

        return Block(
            index=index,
            timestamp=timestamp,
            transactions=transactions,
            prev_hash=previous_hash,
            hash=h,
            nonce=nonce
        )

    def mine_block(self):
        with self.lock:
            txs = self.pending_transactions[:]
            self.pending_transactions = []
            last = self.chain[-1]

        block = self._mine_raw_block(
            index=last.index + 1,
            transactions=txs,
            previous_hash=last.hash
        )

        with self.lock:
            if block.prev_hash != self.chain[-1].hash:
                self.pending_transactions = txs + self.pending_transactions
                return None

            self.chain.append(block)
        return block

    def add_transaction(self, tx: Transaction):
        with self.lock:
            self.pending_transactions.append(tx)

    # -- Validation ---------------------------------------------------------

    @staticmethod
    def validate_block(block: Block, previous_block: Block = None):
        if block.index < 0:
            return False
        if block.timestamp <= 0:
            return False
        if block.transactions is None:
            return False
        if block.prev_hash is None:
            return False
        if block.hash is None:
            return False
        if block.nonce < 0:
            return False

        computed = calculate_hash(
            block.index,
            block.timestamp,
            block.transactions,
            block.prev_hash,
            block.nonce,
        )
        
        if computed != block.hash:
            return False

        if not block.hash.startswith("0" * DIFFICULTY):
            return False

        if block.index == 0:
            if block.prev_hash != "0":
                return False
            if len(block.transactions) != 0:
                return False
            return True

        if block.index > 0:
            if previous_block is None:
                return False

            if block.prev_hash != previous_block.hash:
                return False

            if block.index != previous_block.index + 1:
                return False

            if block.timestamp <= previous_block.timestamp:
                return False

            if len(block.transactions) == 0:
                return False

            def get_tx_field(tx, field):
                return tx.get(field) if isinstance(tx, dict) else getattr(tx, field, None)

            if get_tx_field(block.transactions[0], 'type') != TRANSACTION_TYPE.COINBASE:
                return False

            coinbase_count = sum(
                1 for tx in block.transactions if get_tx_field(tx, 'type') == TRANSACTION_TYPE.COINBASE)
            if coinbase_count != 1:
                return False

            if get_tx_field(block.transactions[0], 'timestamp') != block.timestamp:
                return False

            for tx in block.transactions[1:]:
                if get_tx_field(tx, 'type') != TRANSACTION_TYPE.TRANSFER:
                    return False

            return True

    @staticmethod
    def validate_chain(chain: list[Block]):
        if not chain:
            return False

        if not Blockchain.validate_block(chain[0], None):
            return False

        for i in range(1, len(chain)):
            if not Blockchain.validate_block(chain[i], chain[i - 1]):
                return False
        return True

    def add_block(self, block: Any):
        """Attempt to add a single block received from a peer."""
        if isinstance(block, dict):
            block = Block(
                block["index"],
                block["timestamp"],
                block["transactions"],
                block["previousHash"],
                block["hash"],
                block["nonce"]
            )

        with self.lock:
            last = self.chain[-1]
            if not self.validate_block(block, last):
                return False
            self.chain.append(block)
            self.pending_transactions = [
                tx for tx in self.pending_transactions
                if tx not in block.transactions
            ]
            return True

    # -- Consensus ----------------------------------------------------------

    def resolve_conflicts(self):
        """Replace local chain with the longest valid chain among peers."""
        longest_chain = None
        max_length = len(self.chain)

        for peer in list(self.peers):
            try:
                resp = http_requests.get(f"{peer}/chain", timeout=5)

                if resp.status_code != 200:
                    continue

                data = resp.json()
                peer_chain_raw = data.get("chain", [])
                peer_chain = [Block(
                    b["index"],
                    b["timestamp"],
                    b["transactions"],
                    b["previousHash"],
                    b["hash"],
                    b["nonce"]
                ) if isinstance(b, dict) else b for b in peer_chain_raw]

                if len(peer_chain) > max_length and self.validate_chain(peer_chain):
                    max_length = len(peer_chain)
                    longest_chain = peer_chain
            except Exception:
                continue

        if not longest_chain:
            return False
        print(f"  Replacing local chain with longer chain from peer (length {max_length})")
        with self.lock:
            self.chain = longest_chain
        return True

    # -- P2P helpers --------------------------------------------------------

    def broadcast_block(self, block):
        if isinstance(block, Block):
            block = block.to_dict()

        for peer in list(self.peers):
            try:
                http_requests.post(
                    f"{peer}/block/new",
                    json=block,
                    timeout=5,
                )

            except Exception:
                self.peers.remove(peer)
                continue

    def register_peers(self, peer_urls):
        for peer_url in peer_urls:
            if peer_url in self.peers:
                continue
            self.peers.add(peer_url.rstrip("/"))


# Global blockchain instance
blockchain = Blockchain()