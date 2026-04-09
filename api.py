from flask import Flask, jsonify, request
import logging

from blockchain import blockchain
from models import Block, Transaction


app = Flask(__name__)

# Configure logging to minimize output
app.logger.setLevel(logging.WARNING)
logging.getLogger('werkzeug').setLevel(logging.WARNING)


@app.route("/chain", methods=["GET"])
def get_chain():
    with blockchain.lock:
        chain = [block.to_dict() if isinstance(block, Block) else block for block in blockchain.chain]

    return jsonify({"chain": chain, "length": len(chain)})


@app.route("/peers", methods=["GET"])
def get_peers():
    return jsonify({
        "status": "ok",
        "peers": list(blockchain.peers),
        "count": len(blockchain.peers)
    })


# To register a peer, send a POST request with JSON body: {"peer": "http://localhost:5001"}
@app.route("/peers", methods=["POST"])
def register_peer():
    data = request.get_json(force=True)
    peer = data.get("peer")
    if not peer:
        return jsonify({"error": "peer field required"}), 400
    blockchain.register_peers([peer])
    return jsonify({"message": f"Peer {peer} registered", "peers": list(blockchain.peers)})


@app.route("/pending", methods=["GET"])
def get_pending():
    with blockchain.lock:
        pending = [tx.to_dict() if hasattr(tx, "to_dict") else tx for tx in blockchain.pending_transactions]
    return jsonify({"pending_transactions": pending, "count": len(pending)})

@app.route("/transactions", methods=["POST"])  # Cambiado a /transactions según el PDF
def new_transaction():
    data = request.get_json(force=True)

    if not all(k in data for k in ("from", "to", "amount", "publicKey", "signature")):
        return jsonify({"error": "Missing fields: from, to, amount, publicKey, signature"}), 400

    tx = Transaction(
        from_addr=data["from"],
        to_addr=data["to"],
        amount=int(data["amount"]),
        public_key=data["publicKey"],
        signature=data["signature"]
    )
    blockchain.add_transaction(tx)
    return jsonify({"message": "Transaction added to pool", "transaction": tx.to_dict()}), 202
@app.route("/mine", methods=["POST"])
def mine():
    if len(blockchain.pending_transactions) == 0:
        return jsonify({"error": "No transactions to mine"}), 400

    block = blockchain.mine_block()

    if block is None:
        return jsonify({"error": "Mining failed – chain changed during mining"}), 409

    blockchain.broadcast_block(block)
    return jsonify(
        {"message": "Block mined successfully", "block": block.to_dict() if isinstance(block, Block) else block})


@app.route("/block/new", methods=["POST"])
def receive_block():
    block = request.get_json(force=True)
    required = ["index", "timestamp", "transactions", "previousHash", "hash", "nonce"]

    if not all(k in block for k in required):
        return jsonify({"error": "Missing fields: index, timestamp, transactions, previousHash, hash, nonce"}), 400

    with blockchain.lock:
        local_index = blockchain.chain[-1].index

    if block["index"] == local_index + 1:
        added = blockchain.add_block(block)

        if added:
            return jsonify({"message": "Block accepted"})

        return jsonify({"error": "Block rejected – invalid"}), 400

    elif block["index"] > local_index + 1:
        blockchain.resolve_conflicts()
        return jsonify({"message": "Chain was behind – resolved via consensus"})

    else:
        return jsonify({"message": "Block already known"}), 200


@app.route("/resolve", methods=["GET"])
def consensus():
    replaced = blockchain.resolve_conflicts()
    with blockchain.lock:
        chain = list(blockchain.chain)
    if replaced:
        return jsonify({"message": "Chain replaced", "chain": chain})
    return jsonify({"message": "Local chain is authoritative", "chain": chain})