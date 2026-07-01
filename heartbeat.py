"""
heartbeat.py: detecção de falhas em anel.

O anel é a lista ordenada de nós (coordenador incluído). Cada nó pinga o próximo
a cada T segundos; após max_falhas pings perdidos seguidos, o vizinho é dado como
morto. Se o morto era o coordenador, dispara eleição; se era um cliente comum,
avisa o coordenador.
"""

import time
import threading
import protocol


# ---------------------------------------------------------------------------
# Utilitário compartilhado por coordinator.py e client.py
# ---------------------------------------------------------------------------

def construir_anel(members: list, coord_ip: str, coord_port: int) -> list:
    """Monta o anel (coordenador + membros) ordenado por (ip, port). Determinística:
    com os mesmos dados, todos os nós obtêm o mesmo anel."""
    coord = {"ip": coord_ip, "port": coord_port}
    todos = list(members)
    if coord not in todos:
        todos.append(coord)
    return sorted(todos, key=lambda m: (m["ip"], m["port"]))


# ---------------------------------------------------------------------------
# Classe principal
# ---------------------------------------------------------------------------

class Heartbeat:
    """Heartbeat em anel de um nó. Um por processo."""

    def __init__(self, own_ip: str, own_port: int, intervalo: float = 2.0,
                 max_falhas: int = 3):
        self.own_ip    = own_ip
        self.own_port  = own_port
        self.own_id    = f"{own_ip}:{own_port}"
        self.intervalo = intervalo          # T, segundos entre pings

        # Pings perdidos seguidos antes de declarar o vizinho morto (evita falso
        # positivo por oscilação de rede ou coordenador ocupado).
        self.max_falhas = max_falhas

        self._ring: list  = []             # anel atual
        self._coord_id    = ""             # "ip:porta" do coordenador
        self._lock        = threading.Lock()
        self._running     = False
        self._thread      = None
        self._send        = None           # injetado em iniciar()

        # Contador de pings perdidos do vizinho atual. Só a thread do loop mexe.
        self._vizinho_monitorado = None
        self._falhas_consecutivas = 0

        # Callbacks: definir antes de iniciar().
        self.on_membro_falhou: callable      = None   # fn(ip: str, port: int)
        self.on_coordenador_falhou: callable = None   # fn()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def iniciar(self, send_fn, ring: list, coord_ip: str, coord_port: int):
        """Liga o heartbeat. send_fn é o Node.send; ring é o anel inicial."""
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
              f"intervalo={self.intervalo}s, max_falhas={self.max_falhas}")

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
        """Registra o novo coordenador após eleição, para não pingar o antigo."""
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
            # Anel com um nó só: nada a pingar.
            self._vizinho_monitorado = None
            self._falhas_consecutivas = 0
            return

        vz_id = f"{vizinho['ip']}:{vizinho['port']}"

        # Vizinho mudou: reinicia a contagem (só vale contra um mesmo alvo).
        if vz_id != self._vizinho_monitorado:
            self._vizinho_monitorado = vz_id
            self._falhas_consecutivas = 0

        resp = self._send(
            vizinho["ip"],
            vizinho["port"],
            protocol.make_heartbeat(self.own_id),
            timeout=self.intervalo * 2,   # tolerância de 2T
        )

        if resp is not None and resp.get("type") == protocol.HEARTBEAT_OK:
            self._falhas_consecutivas = 0
            return

        self._falhas_consecutivas += 1
        print(f"[HB {self.own_id}] Vizinho {vz_id} não respondeu "
              f"({self._falhas_consecutivas}/{self.max_falhas}).")

        if self._falhas_consecutivas >= self.max_falhas:
            print(f"[HB {self.own_id}] Vizinho {vz_id} excedeu o limite — falha confirmada!")
            self._vizinho_monitorado = None
            self._falhas_consecutivas = 0
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