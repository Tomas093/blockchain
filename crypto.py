import base64
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_keys import keys


def create_wallet():
    """
    Generates a new keypair and its derived Address.
    Uses secp256k1 by default under the Ethereum standard.
    """

    acct = Account.create()

    return {
        "private_key": acct.key.hex(),
        "address": acct.address,
        "public_key": acct._key_obj.public_key.to_hex()
    }


def get_address_from_public_key(public_key_hex: str) -> str:
    """
    Takes a Public Key in hexadecimal format and derives its Address (0x...).
    """
    if public_key_hex.startswith('0x'):
        public_key_hex = public_key_hex[2:]

    pk_bytes = bytes.fromhex(public_key_hex)

    public_key_obj = keys.PublicKey(pk_bytes)

    return public_key_obj.to_address()


def validate_from_matches_public_key(from_address: str, public_key_hex: str) -> bool:
    """
    Strictly validates that the 'from' address is the mathematical owner of the 'publicKey'.
    """
    try:
        derived_address = get_address_from_public_key(public_key_hex)

        return from_address.lower() == derived_address.lower()
    except Exception:
        return False

def get_canonical_payload(from_addr: str, to_addr: str, amount: int, timestamp: int) -> str:
    """
    Builds the exact string required by TP1 to be signed.
    Format: TRANSFER|from|to|amount|timestamp
    """
    return f"TRANSFER|{from_addr}|{to_addr}|{amount}|{timestamp}"


def sign_payload(private_key_hex: str, payload: str) -> str:
    """
    Signs the canonical payload in UTF-8 and returns the signature in Base64 format.
    """
    message = encode_defunct(text=payload)

    signed_message = Account.sign_message(message, private_key=private_key_hex)

    signature_b64 = base64.b64encode(signed_message.signature).decode('utf-8')
    return signature_b64


def verify_signature(payload: str, signature_b64: str, expected_address: str) -> bool:
    """
    Decodes the Base64 signature, recovers the address that signed the payload,
    and verifies that it matches the 'from' (expected_address).
    """
    try:
        signature_bytes = base64.b64decode(signature_b64)

        message = encode_defunct(text=payload)

        recovered_address = Account.recover_message(message, signature=signature_bytes)

        return recovered_address.lower() == expected_address.lower()
    except Exception as e:
        return False