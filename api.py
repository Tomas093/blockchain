from flask import Flask, jsonify, request
import logging

from blockchain import blockchain
from models import Block, Transaction
from utils import TRANSACTION_TYPE

app = Flask(__name__)

# Configure logging to minimize output
app.logger.setLevel(logging.WARNING)
logging.getLogger('werkzeug').setLevel(logging.WARNING)


@app.route("/chain", methods=["GET"])
def get_chain():
    with blockchain.lock:
        chain = [block.to_dict() if isinstance(block, Block) else block for block in blockchain.chain]

    return jsonify({"status": "ok", "chain": chain, "length": len(chain)})


@app.route("/peers", methods=["GET"])
def get_peers():
    return jsonify({
        "status": "ok",
        "peers": list(blockchain.peers),
        "count": len(blockchain.peers)
    })


@app.route("/peers", methods=["POST"])
def register_peer():
    data = request.get_json(force=True)
    peer = data.get("peer") or data.get("url")  # Support both formats just in case

    if not peer:
        return jsonify({"status": "error", "error": {"code": "MISSING_PEER", "message": "Peer URL required"}}), 400

    blockchain.register_peers([peer])
    return jsonify({
        "status": "ok",
        "registered": peer,
        "peers": list(blockchain.peers)
    })


@app.route("/pending", methods=["GET"])
def get_pending():
    with blockchain.lock:
        pending = [tx.to_dict() if hasattr(tx, "to_dict") else tx for tx in blockchain.pending_transactions]
    return jsonify({"pending_transactions": pending, "count": len(pending)})


@app.route("/transactions", methods=["POST"])
def new_transaction():
    data = request.get_json(force=True)

    required_fields = ["id", "type", "from", "to", "amount", "publicKey", "signature", "timestamp"]
    if not all(k in data for k in required_fields):
        return jsonify({
            "status": "error",
            "error": {
                "code": "MISSING_FIELDS",
                "message": "Missing required fields"
            }
        }), 400

    # TP1 Standard: Mempool does not accept COINBASE directly
    if data.get("type") == TRANSACTION_TYPE.COINBASE:
        return jsonify({
            "status": "error",
            "error": {
                "code": "INVALID_TYPE",
                "message": "COINBASE transactions are not accepted via API"
            }
        }), 400

    tx = Transaction(
        from_addr=data["from"],
        to_addr=data["to"],
        amount=int(data["amount"]),
        public_key=data["publicKey"],
        signature=data["signature"],
        tx_type=data["type"],
        tx_id=data["id"],
        timestamp=data["timestamp"]
    )

    # add_transaction will return True if valid and newly added, False if duplicate or invalid
    if blockchain.add_transaction(tx):
        return jsonify({
            "status": "ok",
            "accepted": True,
            "txId": tx.id
        }), 202
    else:
        # It's either invalid or already exists. Return standard error.
        return jsonify({
            "status": "error",
            "error": {
                "code": "REJECTED_TRANSACTION",
                "message": "Transaction invalid or already processed"
            }
        }), 400


@app.route("/mine", methods=["POST"])
def mine():
    # TP1: We can mine an empty block containing only COINBASE if mempool is empty
    block = blockchain.mine_block()

    if block is None:
        return jsonify({
            "status": "error",
            "error": {
                "code": "MINING_FAILED",
                "message": "Chain changed during mining process"
            }
        }), 409

    # Trigger broadcast explicitly since it was mined locally
    blockchain.broadcast_block(block)

    return jsonify({
        "status": "ok",
        "mined": True,
        "trigger": "manual",
        "block": block.to_dict() if isinstance(block, Block) else block
    }), 200


# Changed from /block/new to /blocks strictly matching TP1 standards
@app.route("/blocks", methods=["POST"])
def receive_block():
    block = request.get_json(force=True)
    required = ["index", "timestamp", "transactions", "previousHash", "hash", "nonce"]

    if not all(k in block for k in required):
        return jsonify({
            "status": "error",
            "error": {
                "code": "MISSING_FIELDS",
                "message": "Missing required block fields"
            }
        }), 400

    with blockchain.lock:
        local_index = blockchain.chain[-1].index

    # Attempt to append
    if block["index"] == local_index + 1:
        added = blockchain.add_block(block)

        if added:
            return jsonify({
                "status": "ok",
                "accepted": True,
                "action": "appended",
                "chainLength": len(blockchain.chain)
            }), 200
        else:
            return jsonify({
                "status": "error",
                "error": {
                    "code": "INVALID_BLOCK",
                    "message": "Block validation failed"
                }
            }), 400

    elif block["index"] > local_index + 1:
        blockchain.resolve_conflicts()
        return jsonify({
            "status": "ok",
            "accepted": False,
            "action": "resolved_via_consensus"
        }), 200

    else:
        return jsonify({
            "status": "ok",
            "accepted": False,
            "action": "ignored"
        }), 200


@app.route("/resolve", methods=["GET"])
def consensus():
    replaced = blockchain.resolve_conflicts()
    with blockchain.lock:
        chain = list(blockchain.chain)
    if replaced:
        return jsonify({"message": "Chain replaced", "chain": chain})
    return jsonify({"message": "Local chain is authoritative", "chain": chain})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})