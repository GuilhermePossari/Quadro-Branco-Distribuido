"""
name_service.py — Serviço de Nomes do SDWB
Processo separado com IP e porta FIXOS — o único do sistema.
Mantém a tabela: { nome_do_quadro -> (ip, porta) }

Uso:
    python name_service.py
    python name_service.py --host 0.0.0.0 --port 5000
"""

import socket
import threading
import argparse
import protocol

# ---------------------------------------------------------------------------
# Configuração — único endereço fixo do sistema
# ---------------------------------------------------------------------------
HOST_PADRAO = '0.0.0.0'
PORTA_PADRAO = 5000

# ---------------------------------------------------------------------------
# Estado do Serviço de Nomes
# ---------------------------------------------------------------------------
# Tabela de quadros ativos: { nome: {"ip": str, "port": int} }
_quadros: dict = {}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Lógica de cada conexão
# ---------------------------------------------------------------------------

def _tratar_cliente(conn: socket.socket, addr: tuple):
    """Trata uma única requisição recebida. Cada conexão = uma mensagem + resposta."""
    try:
        msg = protocol.decode(conn)
        if msg is None:
            return

        tipo = msg.get("type")

        # --- REGISTER: coordenador registra ou atualiza um quadro ---
        if tipo == protocol.REGISTER:
            nome  = msg["name"]
            ip    = msg["ip"]
            porta = msg["port"]
            with _lock:
                _quadros[nome] = {"ip": ip, "port": porta}
            print(f"[SN] Registrado: '{nome}' -> {ip}:{porta}")
            conn.sendall(protocol.encode(protocol.make_ok()))

        # --- UNREGISTER: quadro foi encerrado ---
        elif tipo == protocol.UNREGISTER:
            nome = msg["name"]
            with _lock:
                _quadros.pop(nome, None)
            print(f"[SN] Removido: '{nome}'")
            conn.sendall(protocol.encode(protocol.make_ok()))

        # --- LIST: cliente pede a lista de quadros disponíveis ---
        elif tipo == protocol.LIST:
            with _lock:
                lista = [
                    {"name": nome, "ip": dados["ip"], "port": dados["port"]}
                    for nome, dados in _quadros.items()
                ]
            conn.sendall(protocol.encode(protocol.make_list_response(lista)))

        else:
            print(f"[SN] Tipo desconhecido recebido de {addr}: {tipo}")
            conn.sendall(protocol.encode(protocol.make_error(f"tipo desconhecido: {tipo}")))

    except (KeyError, ValueError) as e:
        print(f"[SN] Mensagem malformada de {addr}: {e}")
        try:
            conn.sendall(protocol.encode(protocol.make_error(str(e))))
        except Exception:
            pass
    except Exception as e:
        print(f"[SN] Erro inesperado ao tratar {addr}: {e}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Servidor principal
# ---------------------------------------------------------------------------

def start(host: str = HOST_PADRAO, port: int = PORTA_PADRAO):
    """Inicia o Serviço de Nomes e fica aceitando conexões indefinidamente."""
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        servidor.bind((host, port))
    except OSError as e:
        print(f"[SN] Não foi possível iniciar em {host}:{port} — {e}")
        return

    servidor.listen()
    print(f"[SN] Serviço de Nomes ativo em {host}:{port}")
    print(f"[SN] Aguardando conexões...")

    try:
        while True:
            conn, addr = servidor.accept()
            t = threading.Thread(
                target=_tratar_cliente,
                args=(conn, addr),
                daemon=True   # encerra junto com o processo principal
            )
            t.start()
    except KeyboardInterrupt:
        print("\n[SN] Encerrando Serviço de Nomes.")
    finally:
        servidor.close()


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serviço de Nomes do SDWB")
    parser.add_argument("--host", default=HOST_PADRAO, help="Endereço de escuta")
    parser.add_argument("--port", type=int, default=PORTA_PADRAO, help="Porta de escuta")
    args = parser.parse_args()

    start(host=args.host, port=args.port)