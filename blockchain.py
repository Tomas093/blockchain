import threading
import time
from typing import Any

import requests as http_requests

from crypto import get_canonical_payload, verify_signature, validate_from_matches_public_key
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
            previous_hash="0",
            timestamp=0,
        )
        self.chain.append(genesis)

    # -- Mining -------------------------------------------------------------

    def _mine_raw_block(self, index: int, transactions: list, previous_hash: str, timestamp: int = None) -> Block:
        if timestamp is None:
            timestamp = int(time.time() * 1000)
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
        # (No-op helpers here: validation helpers are defined as
        # class-level static methods below.)

    # -- Validation Helper ---------------------------------------------------------
    @staticmethod
    def _validate_ownership(tx) -> bool:
        """Validate that: from == address(publicKey)"""
        return validate_from_matches_public_key(tx.from_addr, tx.public_key)

    @staticmethod
    def _validate_signature(tx) -> bool:
        """Verify the cryptographic signature with the canonical payload"""
        payload = get_canonical_payload(
            tx.from_addr,
            tx.to_addr,
            tx.amount,
            tx.timestamp
        )
        return verify_signature(payload, tx.signature, tx.from_addr)

    # -- Balance calculation --

    def get_balance(self, address: str) -> int:
        """Calculate an account's balance by scanning the blockchain and the mempool."""
        balance = 0

        # 1. Add/subtract from blocks already mined in the chain
        for block in self.chain:
            for tx in block.transactions:
                # Handle both Transaction objects and dictionaries
                tx_from = tx.get("from") if isinstance(tx, dict) else tx.from_addr
                tx_to = tx.get("to") if isinstance(tx, dict) else tx.to_addr
                tx_amount = tx.get("amount") if isinstance(tx, dict) else tx.amount

                if tx_to == address:
                    balance += tx_amount
                if tx_from == address:
                    balance -= tx_amount

        # 2. Subtract amounts already spent in pending transactions (prevents quick double-spend)
        for tx in self.pending_transactions:
            tx_from = tx.get("from") if isinstance(tx, dict) else tx.from_addr
            tx_amount = tx.get("amount") if isinstance(tx, dict) else tx.amount

            if tx_from == address:
                balance -= tx_amount

        return balance

    # -- Helper functions for transaction validation --

    @staticmethod
    def _validate_basic_rules(tx) -> bool:
        """Basic logical rules: amount > 0 and from != to"""
        if tx.amount <= 0:
            print("Error: Amount must be greater than 0")
            return False

        if tx.from_addr == tx.to_addr:
            print("Error: 'from' and 'to' cannot be the same address")
            return False

        return True

    @staticmethod
    def _validate_ownership(tx) -> bool:
        """Validate that: from matches the address derived from the public key"""
        if not validate_from_matches_public_key(tx.from_addr, tx.public_key):
            print("Error: 'from' does not match the public key")
            return False
        return True

    @staticmethod
    def _validate_signature(tx) -> bool:
        """Verify the cryptographic signature against the canonical payload"""
        payload = get_canonical_payload(
            tx.from_addr,
            tx.to_addr,
            tx.amount,
            tx.timestamp
        )
        if not verify_signature(payload, tx.signature, tx.from_addr):
            print("Error: Invalid cryptographic signature")
            return False
        return True

    def _validate_balance(self, tx) -> bool:
        """Verify that the sender has sufficient funds"""
        if self.get_balance(tx.from_addr) < tx.amount:
            print(f"Error: Insufficient balance. Account {tx.from_addr} does not have {tx.amount} coins.")
            return False
        return True

    # -- Main transaction validation --

    def validate_transaction(self, tx) -> bool:
        """Strictly execute all TP1 validation rules"""

        # 1. Special rule: COINBASE is validated together with other rules in the block
        if tx.type == "COINBASE":
            return True

        # 2. amount > 0 and from != to
        if not self._validate_basic_rules(tx):
            return False

        # 3. publicKey mathematically derives to the from address
        if not self._validate_ownership(tx):
            return False

        # 4. valid signature
        if not self._validate_signature(tx):
            return False

        # 5. sufficient balance
        if not self._validate_balance(tx):
            return False

        return True

    # -- Block and chain validation ----------------------------------------

    @staticmethod
    def validate_block(block: Block, previous_block: Block):
        if block.index != previous_block.index + 1:
            return False

        if block.prev_hash != previous_block.hash:
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

        if block.timestamp <= previous_block.timestamp:
            return False

        if not hash_valid(block.hash):
            return False

        current_time_ms = int(time.time() * 1000)
        if block.timestamp > current_time_ms + 60000:
            return False

        return True

    @staticmethod
    def validate_chain(chain: list[Block]):
        if not chain:
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