import threading
import time
import requests as http_requests

from typing import Any
from crypto import get_canonical_payload, verify_signature, validate_from_matches_public_key

from models import Block, Transaction
from utils import calculate_hash, hash_valid, TRANSACTION_TYPE, AUTO_MINE_THRESHOLD


class Blockchain:
    def __init__(self):
        self.chain: list[Block] = []
        self.pending_transactions: list[Transaction] = []
        self.peers = set()

        # Cache to prevent infinite loops in the gossip protocol
        self.seen_transactions = set()
        self.seen_blocks = set()

        self.lock = threading.Lock()
        self.port = None
        self._create_genesis_block()

    # -- Genesis block ------------------------------------------------------

    def _create_genesis_block(self):
        genesis = self._mine_raw_block(
            index=0,
            transactions=[],
            previous_hash="0",
            timestamp=1,
        )
        self.chain.append(genesis)
        self.seen_blocks.add(genesis.hash)

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

    def mine_block(self, miner_address="MINER_NODE_ADDRESS"):
        with self.lock:
            block_timestamp = int(time.time() * 1000)

            coinbase_tx = Transaction(
                from_addr="SYSTEM",
                to_addr=miner_address,
                amount=10,
                public_key="0000000000000000000000000000000000000000000000000000000000000000",
                signature="0000000000000000000000000000000000000000000000000000000000000000",
                tx_type=TRANSACTION_TYPE.COINBASE,
                timestamp=block_timestamp
            )

            txs = [coinbase_tx] + self.pending_transactions[:]

            self.pending_transactions = []
            last = self.chain[-1]

        block = self._mine_raw_block(
            index=last.index + 1,
            transactions=txs,
            previous_hash=last.hash,
            timestamp=block_timestamp
        )

        with self.lock:
            if block.prev_hash != self.chain[-1].hash:
                # Chain changed while mining, restore mempool
                self.pending_transactions = txs[1:] + self.pending_transactions
                return None

            self.chain.append(block)
            self.seen_blocks.add(block.hash)  # Cache the newly mined block

        return block

    def _auto_mine_and_broadcast(self):
        """Mina un bloque automáticamente y lo propaga a la red."""
        with self.lock:
            if len(self.pending_transactions) < AUTO_MINE_THRESHOLD:
                return

        block = self.mine_block()

        if block:
            self.broadcast_block(block)

    def add_transaction(self, tx: Transaction):
        """Adds a transaction to the mempool and broadcasts it if it is new."""
        tx_id = tx.id if hasattr(tx, "id") else tx.get("id")

        with self.lock:
            # Check cache to avoid broadcasting and processing loops
            if tx_id in self.seen_transactions:
                return False

            # Strictly execute all validation rules before accepting
            if not self.validate_transaction(tx):
                return False

            self.pending_transactions.append(tx)
            self.seen_transactions.add(tx_id)

            pending_count = len(self.pending_transactions)

        # Broadcast asynchronously to avoid blocking the API thread
        threading.Thread(target=self.broadcast_transaction, args=(tx,), daemon=True).start()

        if pending_count >= AUTO_MINE_THRESHOLD:
            threading.Thread(target=self._auto_mine_and_broadcast, daemon=True).start()

        return True

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
        """Calcula el balance actual de una cuenta (Chain + Mempool)"""
        balance = self.get_chain_balance(address)

        for tx in self.pending_transactions:
            tx_from = tx.get("from") if isinstance(tx, dict) else tx.from_addr
            tx_amount = tx.get("amount") if isinstance(tx, dict) else tx.amount

            if tx_from == address:
                balance -= tx_amount

        return balance

    def get_chain_balance(self, address: str) -> int:
        """Calcula el balance usando SOLO la blockchain (sin mempool)"""
        balance = 0
        for block in self.chain:
            for tx in block.transactions:
                tx_from = tx.get("from") if isinstance(tx, dict) else getattr(tx, "from_addr", None)
                tx_to = tx.get("to") if isinstance(tx, dict) else getattr(tx, "to_addr", None)
                tx_amount = tx.get("amount") if isinstance(tx, dict) else getattr(tx, "amount", 0)

                if tx_to == address:
                    balance += tx_amount
                if tx_from == address:
                    balance -= tx_amount
        return balance

    # -- Helper functions for transaction validation --

    @staticmethod
    def _validate_basic_rules(tx) -> bool:
        """Basic logical rules: amount > 0 and from != to"""
        if tx.amount <= 0:
            return False

        if tx.from_addr == tx.to_addr:
            return False

        return True

    def _validate_balance(self, tx) -> bool:
        """Verify that the sender has sufficient funds"""
        if self.get_balance(tx.from_addr) < tx.amount:
            return False
        return True

    # -- Main transaction validation --

    def validate_transaction(self, tx) -> bool:
        """Strictly execute all TP1 validation rules"""
        if tx.type == "COINBASE":
            return True

        if not self._validate_basic_rules(tx):
            return False

        if not self._validate_ownership(tx):
            return False

        if not self._validate_signature(tx):
            return False

        if not self._validate_balance(tx):
            return False

        return True

    # -- Block and chain validation ----------------------------------------

    def validate_block(self, block: Block, previous_block: Block = None, external_balances: dict = None, is_full_chain_validation: bool = False):
        if block.index < 0: return False
        if block.timestamp <= 0: return False
        if block.transactions is None: return False
        if block.prev_hash is None: return False
        if block.hash is None: return False
        if block.nonce < 0: return False

        computed = calculate_hash(
            block.index, block.timestamp, block.transactions, block.prev_hash, block.nonce
        )
        if computed != block.hash: return False
        if not hash_valid(block.hash): return False

        if block.index == 0:
            if block.prev_hash != "0": return False
            if len(block.transactions) != 0: return False
            return True

        if previous_block is None: return False
        if block.index != previous_block.index + 1: return False
        if block.prev_hash != previous_block.hash: return False
        if block.timestamp <= previous_block.timestamp: return False

        current_time_ms = int(time.time() * 1000)
        if block.timestamp > current_time_ms + 60000: return False

        if len(block.transactions) == 0: return False

        def get_tx_field(tx, field):
            return tx.get(field) if isinstance(tx, dict) else getattr(tx, field, None)

        first_tx = block.transactions[0]

        if get_tx_field(first_tx, 'type') != TRANSACTION_TYPE.COINBASE: return False
        if get_tx_field(first_tx, 'from') != "SYSTEM": return False
        if int(get_tx_field(first_tx, 'amount')) != 10: return False
        if get_tx_field(first_tx, 'timestamp') != block.timestamp: return False

        coinbase_count = sum(1 for tx in block.transactions if get_tx_field(tx, 'type') == TRANSACTION_TYPE.COINBASE)
        if coinbase_count != 1: return False

        # --- NUEVA SIMULACIÓN DE ESTADO Y VALIDACIÓN ESTRICTA ---
        simulated_balances = external_balances.copy() if external_balances is not None else {}

        def get_simulated_balance(addr):
            if addr not in simulated_balances:
                if is_full_chain_validation:
                    # Si validamos una cadena entera desde 0, el balance base es 0
                    simulated_balances[addr] = 0
                else:
                    # Si validamos un solo bloque nuevo, usamos nuestra blockchain como base
                    simulated_balances[addr] = self.get_chain_balance(addr)
            return simulated_balances[addr]

        # 1. Sumamos la recompensa de minado de la COINBASE al nodo minero
        miner_addr = get_tx_field(first_tx, 'to')
        miner_amount = int(get_tx_field(first_tx, 'amount'))
        simulated_balances[miner_addr] = get_simulated_balance(miner_addr) + miner_amount

        # 2. Validamos el resto de las transacciones (TRANSFER)
        for tx in block.transactions[1:]:
            if get_tx_field(tx, 'type') != TRANSACTION_TYPE.TRANSFER: return False

            if isinstance(tx, dict):
                tx_obj = Transaction(
                    from_addr=tx.get("from"), to_addr=tx.get("to"), amount=tx.get("amount"),
                    public_key=tx.get("publicKey"), signature=tx.get("signature"),
                    tx_type=tx.get("type"), tx_id=tx.get("id"), timestamp=tx.get("timestamp")
                )
            else:
                tx_obj = tx

            # Validación de propiedades intrínsecas
            if not self._validate_basic_rules(tx_obj): return False
            if not self._validate_ownership(tx_obj): return False
            if not self._validate_signature(tx_obj): return False

            # Chequeamos balance suficiente basándonos EXCLUSIVAMENTE en el estado acumulado
            sender_balance = get_simulated_balance(tx_obj.from_addr)
            if sender_balance < tx_obj.amount:
                return False

            # Actualizamos el estado para la siguiente transacción en el mismo bloque
            simulated_balances[tx_obj.from_addr] -= tx_obj.amount
            simulated_balances[tx_obj.to_addr] = get_simulated_balance(tx_obj.to_addr) + tx_obj.amount

        # Guardar estado por si estamos validando múltiples bloques (validate_chain)
        if external_balances is not None:
            external_balances.update(simulated_balances)

        return True

    def validate_chain(self, chain: list[Block]):
        if not chain:
            return False

        if not self.validate_block(chain[0], None):
            return False

        state_balances = {}

        for i in range(1, len(chain)):
            # Validamos cada bloque suministrando los balances arrastrados
            if not self.validate_block(chain[i], chain[i - 1], external_balances=state_balances, is_full_chain_validation=True):
                return False

        return True

    def add_block(self, block: Any):
        """Attempt to add a single block received from a peer and broadcast it."""
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
            block_hash = block.hash

            # Check cache to avoid gossip loops
            if block_hash in self.seen_blocks:
                return False

            last = self.chain[-1]
            if not self.validate_block(block, last):
                return False

            self.chain.append(block)
            self.seen_blocks.add(block_hash)

            # Remove mined transactions from mempool
            mined_tx_ids = [tx["id"] if isinstance(tx, dict) else tx.id for tx in block.transactions]
            self.pending_transactions = [
                tx for tx in self.pending_transactions
                if (tx.get("id") if isinstance(tx, dict) else getattr(tx, "id")) not in mined_tx_ids
            ]

        # Successfully added to chain, broadcast to peers
        threading.Thread(target=self.broadcast_block, args=(block,), daemon=True).start()
        return True

    # -- Consenso ----------------------------------------------------------

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
            # Update cache to include blocks from the new chain
            for b in self.chain:
                self.seen_blocks.add(b.hash)
        return True

    # -- P2P helpers (Gossip Protocol) --------------------------------------

    def broadcast_block(self, block):
        """Broadcasts a block to all registered peers."""
        block_dict = block.to_dict() if isinstance(block, Block) else block

        for peer in list(self.peers):
            try:
                # Sending via TP1 standardized endpoint /blocks
                http_requests.post(
                    f"{peer}/blocks",
                    json=block_dict,
                    timeout=5,
                )
            except Exception:
                # Do not remove the peer immediately; it might be a temporary network issue
                continue

    def broadcast_transaction(self, tx):
        """Broadcasts a transaction to all registered peers."""
        tx_dict = tx.to_dict() if hasattr(tx, "to_dict") else tx

        for peer in list(self.peers):
            try:
                http_requests.post(
                    f"{peer}/transactions",
                    json=tx_dict,
                    timeout=5,
                )
            except Exception:
                continue

    def register_peers(self, peer_urls):
        for peer_url in peer_urls:
            if peer_url in self.peers:
                continue
            self.peers.add(peer_url.rstrip("/"))


# Global blockchain instance
blockchain = Blockchain()