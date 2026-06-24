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
# Poda de quadros órfãos (verificação de vivacidade no LIST)
# ---------------------------------------------------------------------------
# O SN não é avisado quando um coordenador CRASHA (kill -9) nem quando um handoff
# de saída falha: a entrada ficaria na tabela apontando para um nó morto — aparece
# no LIST, mas o JOIN falha ("coordenador não disponível"). Para evitar esses
# quadros "fantasma", antes de responder o LIST o SN faz um probe rápido em cada
# coordenador (conecta + HEARTBEAT) e remove da tabela os que não respondem.

def _coordenador_vivo(ip: str, port: int, timeout: float = 1.0) -> bool:
    """True se o coordenador em ip:port responde a um HEARTBEAT dentro do timeout."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        s.sendall(protocol.encode(protocol.make_heartbeat("name_service")))
        resp = protocol.decode(s)
        return resp is not None and resp.get("type") == protocol.HEARTBEAT_OK
    except OSError:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def _separar_vivos_e_mortos(itens: list):
    """
    Faz probe EM PARALELO de cada (nome, {ip, port}) — para não somar timeouts —
    e separa vivos de mortos.
    Retorna (vivos: [(nome, dados)], mortos: [(nome, ip, port)]).
    """
    resultado = {}

    def _probe(nome, ip, port):
        resultado[nome] = _coordenador_vivo(ip, port)

    threads = [
        threading.Thread(target=_probe, args=(n, d["ip"], d["port"]), daemon=True)
        for n, d in itens
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    vivos  = [(n, d) for n, d in itens if resultado.get(n)]
    mortos = [(n, d["ip"], d["port"]) for n, d in itens if not resultado.get(n)]
    return vivos, mortos


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
                itens = list(_quadros.items())
            vivos, mortos = _separar_vivos_e_mortos(itens)
            # Poda os órfãos — mas só apaga se a entrada ainda apontar para o mesmo
            # endereço morto que foi sondado (evita remover um quadro que acabou de
            # ser RE-registrado, ex.: novo coordenador após eleição).
            if mortos:
                with _lock:
                    for nome, ip, port in mortos:
                        atual = _quadros.get(nome)
                        if atual and atual["ip"] == ip and atual["port"] == port:
                            _quadros.pop(nome, None)
                            print(f"[SN] Podado (coordenador não responde): '{nome}' -> {ip}:{port}")
            lista = [
                {"name": nome, "ip": dados["ip"], "port": dados["port"]}
                for nome, dados in vivos
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