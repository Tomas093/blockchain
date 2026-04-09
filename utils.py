import hashlib



DIFFICULTY = 4  # number of leading zeros required in block hash
TRANSACTIONS_PER_BLOCK = 5

class TRANSACTION_TYPE:
    TRANSFER = "TRANSFER"
    COINBASE = "COINBASE"


def calculate_hash(index: int, timestamp: int, transactions: list, previous_hash: str, nonce: int) -> str:

    tx_ids = []
    for tx in transactions:
        if hasattr(tx, 'id'):
            tx_ids.append(str(tx.id))
        elif isinstance(tx, dict) and "id" in tx:
            tx_ids.append(str(tx["id"]))

    tx_ids_str = ",".join(tx_ids)

    block_string = f"{index}|{timestamp}|{previous_hash}|{nonce}|{tx_ids_str}"

    return hashlib.sha256(block_string.encode('utf-8')).hexdigest()


def hash_valid(hash_value):
    return hash_value.startswith("0" * DIFFICULTY)