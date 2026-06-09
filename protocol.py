"""
protocol.py — Contrato de mensagens do SDWB
Ambos (Pessoa A e Pessoa B) importam este arquivo.
Nunca escreva {"type": "JOIN"} na mão em outro arquivo — use as constantes daqui.
"""

import json
import struct
import socket

# ---------------------------------------------------------------------------
# Tipos de mensagem
# ---------------------------------------------------------------------------

# Serviço de Nomes
REGISTER       = "REGISTER"        # coordenador registra/atualiza quadro
UNREGISTER     = "UNREGISTER"      # coordenador remove quadro (quadro encerrado)
LIST           = "LIST"            # cliente pede lista de quadros disponíveis
LIST_RESPONSE  = "LIST_RESPONSE"   # serviço de nomes responde com a lista

# Entrada no quadro (Onboarding)
JOIN           = "JOIN"            # cliente pede para entrar no quadro
STATE          = "STATE"           # coordenador envia estado completo ao novo cliente

# Operações do quadro
DRAW           = "DRAW"            # desenhar objeto (linha ou quadrado)
REMOVE         = "REMOVE"          # remover objeto
COLOR          = "COLOR"           # colorir objeto

# Exclusão mútua
LOCK_REQUEST   = "LOCK_REQUEST"    # cliente pede trava de um objeto
LOCK_RESPONSE  = "LOCK_RESPONSE"   # coordenador responde à trava
LOCK_RELEASE   = "LOCK_RELEASE"    # cliente libera a trava após a operação

# Tolerância a falhas
HEARTBEAT      = "HEARTBEAT"       # ping para o vizinho no anel
HEARTBEAT_OK   = "HEARTBEAT_OK"    # resposta ao ping

# Eleição (Bully)
ELECTION       = "ELECTION"        # candidato inicia eleição
ELECTION_OK    = "ELECTION_OK"     # nó com ID maior responde que está vivo
COORDINATOR    = "COORDINATOR"     # vencedor anuncia que é o novo coordenador

# Anel de heartbeat
RING_UPDATE    = "RING_UPDATE"     # coordenador notifica todos sobre mudança no anel

# Saída
LEAVE          = "LEAVE"           # saída voluntária do quadro

# Utilitários
OK             = "OK"
ERROR          = "ERROR"


# ---------------------------------------------------------------------------
# Framing TCP — prefixo de 4 bytes com o tamanho do payload
# ---------------------------------------------------------------------------
# TCP é um stream: sem framing, não dá para saber onde uma mensagem termina
# e a próxima começa. A solução é prefixar cada mensagem com 4 bytes (big-endian)
# indicando o comprimento do JSON que vem a seguir.

def encode(msg: dict) -> bytes:
    """Serializa um dict para bytes prontos para enviar pelo socket."""
    payload = json.dumps(msg, ensure_ascii=False).encode('utf-8')
    return struct.pack('>I', len(payload)) + payload


def _recv_exato(sock: socket.socket, n: int):
    """Lê exatamente n bytes do socket. Retorna None se a conexão fechar."""
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def decode(sock: socket.socket):
    """Lê uma mensagem completa do socket. Retorna None se a conexão fechar."""
    header = _recv_exato(sock, 4)
    if header is None:
        return None
    length = struct.unpack('>I', header)[0]
    payload = _recv_exato(sock, length)
    if payload is None:
        return None
    return json.loads(payload.decode('utf-8'))


# ---------------------------------------------------------------------------
# Construtores — use estas funções em vez de montar dicts na mão
# ---------------------------------------------------------------------------

# Serviço de Nomes
def make_register(name: str, ip: str, port: int) -> dict:
    return {"type": REGISTER, "name": name, "ip": ip, "port": port}

def make_unregister(name: str) -> dict:
    return {"type": UNREGISTER, "name": name}

def make_list() -> dict:
    return {"type": LIST}

def make_list_response(boards: list) -> dict:
    # boards: lista de {"name": str, "ip": str, "port": int}
    return {"type": LIST_RESPONSE, "boards": boards}

# Onboarding
def make_join(ip: str, port: int) -> dict:
    return {"type": JOIN, "ip": ip, "port": port}

def make_state(objects: list, members: list) -> dict:
    # objects: lista de objetos do quadro (cada um é um dict com id, shape, points, color)
    # members: lista de {"ip": str, "port": int}
    return {"type": STATE, "objects": objects, "members": members}

# Operações
def make_draw(obj: dict, sender_id: str) -> dict:
    # obj deve ter: {"id": str, "shape": "line"|"square", "points": [[x,y],[x,y]], "color": str}
    # sender_id: "ip:porta" de quem está desenhando (para o coord. não reenviar ao remetente)
    return {"type": DRAW, "object": obj, "sender_id": sender_id}

def make_remove(object_id: str, sender_id: str) -> dict:
    # sender_id: "ip:porta" de quem está removendo
    return {"type": REMOVE, "object_id": object_id, "sender_id": sender_id}

def make_color(object_id: str, color: str, sender_id: str) -> dict:
    # sender_id: "ip:porta" de quem está colorindo
    return {"type": COLOR, "object_id": object_id, "color": color, "sender_id": sender_id}

# Exclusão mútua
def make_lock_request(object_id: str, node_id: str) -> dict:
    # node_id: "ip:porta" de quem quer a trava (porta do servidor do cliente, não a efêmera)
    return {"type": LOCK_REQUEST, "object_id": object_id, "node_id": node_id}

def make_lock_response(object_id: str, granted: bool, reason: str = "") -> dict:
    return {"type": LOCK_RESPONSE, "object_id": object_id, "granted": granted, "reason": reason}

def make_lock_release(object_id: str) -> dict:
    return {"type": LOCK_RELEASE, "object_id": object_id}

# Heartbeat
def make_heartbeat(node_id: str) -> dict:
    # node_id: "ip:porta" do nó que está pingando
    return {"type": HEARTBEAT, "node_id": node_id}

def make_heartbeat_ok(node_id: str) -> dict:
    return {"type": HEARTBEAT_OK, "node_id": node_id}

# Eleição
def make_election(candidate_id: str) -> dict:
    # candidate_id: "ip:porta" de quem iniciou a eleição
    return {"type": ELECTION, "candidate_id": candidate_id}

def make_election_ok() -> dict:
    return {"type": ELECTION_OK}

def make_coordinator(ip: str, port: int) -> dict:
    return {"type": COORDINATOR, "ip": ip, "port": port}

def make_ring_update(members: list) -> dict:
    # members: anel completo [{"ip": str, "port": int}] já ordenado
    return {"type": RING_UPDATE, "members": members}

# Saída
def make_leave(node_id: str) -> dict:
    # node_id: "ip:porta" de quem está saindo
    return {"type": LEAVE, "node_id": node_id}

# Utilitários
def make_ok() -> dict:
    return {"type": OK}

def make_error(reason: str) -> dict:
    return {"type": ERROR, "reason": reason}