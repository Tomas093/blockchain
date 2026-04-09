import json
import time
import uuid
from utils import TRANSACTION_TYPE


class Block:
    def __init__(self, index: int, timestamp: int, transactions, prev_hash, hash="", nonce=0):
        self.index = index
        self.timestamp = timestamp
        self.transactions: list[Transaction] = transactions
        self.prev_hash = prev_hash
        self.hash = hash
        self.nonce = nonce

    def to_dict(self):
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": [tx.to_dict() if hasattr(tx, "to_dict") else tx for tx in self.transactions],
            "previousHash": self.prev_hash,
            "hash": self.hash,
            "nonce": self.nonce
        }

    def __str__(self):
        return json.dumps(self.to_dict(), sort_keys=True)

    def __getitem__(self, key):
        return self.to_dict()[key]


class Transaction:
    def __init__(self, from_addr: str, to_addr: str, amount: int, public_key: str, signature: str, tx_type: str = TRANSACTION_TYPE.TRANSFER, tx_id: str = None, timestamp: int = None):
        self.id = tx_id if tx_id else str(uuid.uuid4())
        self.type = tx_type
        self.from_addr = from_addr
        self.to_addr = to_addr
        self.amount = int(amount)
        self.timestamp = timestamp if timestamp else int(time.time() * 1000)
        self.public_key = public_key
        self.signature = signature

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "from": self.from_addr,
            "to": self.to_addr,
            "amount": self.amount,
            "timestamp": self.timestamp,
            "publicKey": self.public_key,
            "signature": self.signature
        }

    def __getitem__(self, key):
        return self.to_dict()[key]

    def __str__(self):
        return json.dumps(self.to_dict(), sort_keys=True)