import argparse
import threading
import requests as http_requests
import socket

from api import app
from blockchain import blockchain
from cli import cli_loop, resolve_periodically
from utils import DIFFICULTY


def bootstrap_node(seeds_str, my_port):
    """Ejecuta la política de bootstrap obligatoria de la red."""
    if not seeds_str:
        return

    # Construir la URL propia para registrarse en el seed
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip_local = s.getsockname()[0]
    except Exception:
        ip_local = "127.0.0.1"
    finally:
        s.close()

    my_url = f"http://{ip_local}:{my_port}"
    seeds = [s.strip() for s in seeds_str.split(",") if s.strip()]

    for seed in seeds:
        print(f"  [Bootstrap] Intentando conectar al seed {seed}...")
        try:
            # 1. Intenta contactar a un seed por /status
            res_status = http_requests.get(f"{seed}/status", timeout=5)
            if res_status.status_code != 200:
                print(f"  [Bootstrap] Status fallido en {seed}.")
                continue

            # 2. Descarga la cadena por /chain
            # Al agregarlo a los peers y resolver conflictos, reutilizamos la lógica
            # que ya llama a /chain y se queda con la longest valid chain.
            blockchain.register_peers([seed])
            blockchain.resolve_conflicts()
            print(f"  [Bootstrap] Cadena validada. Longitud actual: {len(blockchain.chain)}")

            # 3. Registra su propia URL con POST /peers
            res_peers = http_requests.post(f"{seed}/peers", json={"url": my_url}, timeout=5)

            # 4. Recibe la lista actual de peers
            if res_peers.status_code == 200:
                peers_data = res_peers.json().get("peers", [])
                blockchain.register_peers(peers_data)
                print(f"  [Bootstrap] Red sincronizada. Descubiertos {len(peers_data)} peers.")

            # 5. Empieza a operar en la red (rompemos el bucle al ser exitoso)
            break

        except Exception as e:
            print(f"  [Bootstrap] Falló el bootstrap con {seed}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Blockchain P2P Node")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to listen on")
    parser.add_argument("--port", type=int, default=5001, help="Port to listen on")
    parser.add_argument(
        "--peers",
        type=str,
        default="",
        help="Comma-separated list of peer URLs (e.g. http://localhost:5001,http://localhost:5002)",
    )
    args = parser.parse_args()

    # Asignar puerto antes de arrancar
    blockchain.port = args.port
    print(f"  Starting node on port {args.port}")

    if args.peers:
        bootstrap_node(args.peers, args.port)

    print(f"  Starting node on port {args.port}")
    blockchain.port = args.port
    print(f"  Peers: {list(blockchain.peers)}")
    print(f"  Difficulty: {DIFFICULTY} (leading zeros)")
    print(f"  Genesis block hash: {blockchain.chain[0]['hash']}")

    resolve_task = threading.Thread(target=resolve_periodically, kwargs={"interval": 30}, daemon=True)
    app_task = threading.Thread(target=app.run,
                                kwargs={"host": args.host, "port": args.port, "debug": False, "use_reloader": False},
                                daemon=True)

    resolve_task.start()
    app_task.start()

    cli_loop()

    # wait for the cli task terminate (when user types 'q')
    print("Shutting down node...")
    resolve_task.join(timeout=.1)
    app_task.join(timeout=.1)


if __name__ == "__main__":
    main()