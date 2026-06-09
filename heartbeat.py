"""
heartbeat.py — Heartbeat em anel para o SDWB

Como funciona:
  - O anel é uma lista ordenada de nós: [coord, clienteA, clienteB, ...]
  - Cada nó pinga o próximo no anel a cada T segundos
  - Se não houver resposta em 2T, o vizinho é declarado morto
  - Se o morto era o coordenador → dispara eleição (on_coordenador_falhou)
  - Se era um cliente comum     → notifica o coordenador (on_membro_falhou)

Uso típico (dentro do cliente):
    hb = Heartbeat(meu_ip, minha_porta, intervalo=2.0)
    hb.on_membro_falhou      = lambda ip, p: node.send(coord_ip, coord_port,
                                               protocol.make_leave(f'{ip}:{p}'))
    hb.on_coordenador_falhou = lambda: election.iniciar()
    hb.iniciar(
        send_fn   = node.send,
        ring      = construir_anel(membros, coord_ip, coord_port),
        coord_ip  = coord_ip,
        coord_port= coord_port,
    )

    # Quando receber RING_UPDATE do coordenador:
    hb.atualizar_anel(msg["members"])

    # Quando a eleição eleger um novo coordenador:
    hb.atualizar_coordenador(novo_coord_ip, novo_coord_port)
"""

import time
import threading
import protocol


# ---------------------------------------------------------------------------
# Função utilitária — usada por coordinator.py e client.py
# ---------------------------------------------------------------------------

def construir_anel(members: list, coord_ip: str, coord_port: int) -> list:
    """
    Constrói o anel de heartbeat: coordenador + todos os membros, ordenados
    por (ip, port). Qualquer nó que chamar esta função com os mesmos dados
    obtém o mesmo anel — garante que todos concordem sobre quem pinga quem.

    Parâmetros:
      members    — lista de clientes: [{"ip": str, "port": int}]
      coord_ip/port — endereço do coordenador

    Retorna lista ordenada incluindo o coordenador.
    """
    coord = {"ip": coord_ip, "port": coord_port}
    todos = list(members)
    if coord not in todos:
        todos.append(coord)
    return sorted(todos, key=lambda m: (m["ip"], m["port"]))


# ---------------------------------------------------------------------------
# Classe principal
# ---------------------------------------------------------------------------

class Heartbeat:
    """
    Gerencia o heartbeat em anel de um único nó.
    Instanciar um por processo (cliente ou coordenador).
    """

    def __init__(self, own_ip: str, own_port: int, intervalo: float = 2.0):
        self.own_ip    = own_ip
        self.own_port  = own_port
        self.own_id    = f"{own_ip}:{own_port}"
        self.intervalo = intervalo          # T — segundos entre pings

        self._ring: list  = []             # anel atual
        self._coord_id    = ""             # "ip:porta" do coordenador
        self._lock        = threading.Lock()
        self._running     = False
        self._thread      = None
        self._send        = None           # injetado em iniciar()

        # ── Callbacks — defina antes de chamar iniciar() ──────────────
        self.on_membro_falhou: callable      = None   # fn(ip: str, port: int)
        self.on_coordenador_falhou: callable = None   # fn()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def iniciar(self, send_fn, ring: list, coord_ip: str, coord_port: int):
        """
        Liga o heartbeat.

        send_fn    — Node.send (injetado para evitar dependência circular)
        ring       — anel inicial (use construir_anel())
        coord_ip/port — coordenador atual
        """
        if self._running:
            return   # já está rodando

        self._send     = send_fn
        self._coord_id = f"{coord_ip}:{coord_port}"
        with self._lock:
            self._ring = list(ring)

        self._running = True
        self._thread  = threading.Thread(
            target=self._loop,
            name=f"hb-{self.own_id}",
            daemon=True,
        )
        self._thread.start()
        print(f"[HB {self.own_id}] Iniciado — {len(ring)} nó(s) no anel, "
              f"intervalo={self.intervalo}s")

    def parar(self):
        """Para o heartbeat (usado quando o nó sai voluntariamente)."""
        self._running = False
        print(f"[HB {self.own_id}] Parado.")

    # ------------------------------------------------------------------
    # Atualização dinâmica
    # ------------------------------------------------------------------

    def atualizar_anel(self, novo_ring: list):
        """
        Substitui o anel atual.
        Chamar ao receber RING_UPDATE do coordenador.
        """
        with self._lock:
            self._ring = list(novo_ring)
        print(f"[HB {self.own_id}] Anel atualizado — {len(novo_ring)} nó(s)")

    def atualizar_coordenador(self, coord_ip: str, coord_port: int):
        """
        Registra o novo coordenador após eleição.
        Sem isso, o heartbeat continuaria tentando pingar o coordenador morto.
        """
        with self._lock:
            self._coord_id = f"{coord_ip}:{coord_port}"
        print(f"[HB {self.own_id}] Coordenador atualizado → {self._coord_id}")

    # ------------------------------------------------------------------
    # Loop de detecção
    # ------------------------------------------------------------------

    def _loop(self):
        while self._running:
            time.sleep(self.intervalo)
            if self._running:
                self._checar_vizinho()

    def _checar_vizinho(self):
        vizinho = self._proximo_vizinho()
        if vizinho is None:
            return   # anel com ≤ 1 nó — nada a pingar

        resp = self._send(
            vizinho["ip"],
            vizinho["port"],
            protocol.make_heartbeat(self.own_id),
            timeout=self.intervalo * 2,   # tolerância de 2T
        )

        if resp is None or resp.get("type") != protocol.HEARTBEAT_OK:
            vz_id = f"{vizinho['ip']}:{vizinho['port']}"
            print(f"[HB {self.own_id}] Vizinho {vz_id} não respondeu — falha!")
            self._tratar_falha(vizinho)

    # ------------------------------------------------------------------
    # Tratamento de falha
    # ------------------------------------------------------------------

    def _tratar_falha(self, membro: dict):
        membro_id = f"{membro['ip']}:{membro['port']}"

        # Remove imediatamente do anel para não tentar pingar de novo
        with self._lock:
            self._ring = [
                m for m in self._ring
                if not (m["ip"] == membro["ip"] and m["port"] == membro["port"])
            ]
            eh_coordenador = (membro_id == self._coord_id)

        if eh_coordenador:
            print(f"[HB {self.own_id}] Coordenador {membro_id} falhou → eleição!")
            if self.on_coordenador_falhou:
                threading.Thread(
                    target=self.on_coordenador_falhou,
                    daemon=True,
                ).start()
        else:
            print(f"[HB {self.own_id}] Membro {membro_id} falhou → notificando coord.")
            if self.on_membro_falhou:
                threading.Thread(
                    target=self.on_membro_falhou,
                    args=(membro["ip"], membro["port"]),
                    daemon=True,
                ).start()

    # ------------------------------------------------------------------
    # Cálculo do próximo vizinho
    # ------------------------------------------------------------------

    def _proximo_vizinho(self):
        with self._lock:
            ring = list(self._ring)

        if len(ring) < 2:
            return None

        idx = next(
            (i for i, m in enumerate(ring)
             if m["ip"] == self.own_ip and m["port"] == self.own_port),
            -1,
        )
        if idx == -1:
            print(f"[HB {self.own_id}] AVISO: nó ausente do próprio anel")
            return None

        return ring[(idx + 1) % len(ring)]