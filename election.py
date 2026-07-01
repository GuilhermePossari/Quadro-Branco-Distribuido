"""
election.py: eleição pelo Algoritmo do Valentão.

Vence o nó de maior (ip, porta); com IP compartilhado, a porta desempata.
O nó envia ELECTION aos de prioridade maior: se ninguém responde, ele vence e
anuncia COORDINATOR; se algum responde, aguarda o anúncio dele e reinicia se
não chegar a tempo.
"""

import threading
import protocol


class Election:

    def __init__(self, own_ip: str, own_port: int):
        self.own_ip   = own_ip
        self.own_port = own_port
        self.own_id   = f"{own_ip}:{own_port}"

        # Timeouts (ajustáveis nos testes)
        self.timeout_ok    = 3.0   # aguarda ELECTION_OK após enviar ELECTION
        self.timeout_coord = 6.0   # aguarda COORDINATOR após receber ELECTION_OK

        self._members: list = []   # todos os nós conhecidos (sem o coord morto)
        self._send          = None # Node.send, injetado em configurar()

        self._lock          = threading.Lock()
        self._em_eleicao    = False
        self._recebeu_ok    = threading.Event()
        self._recebeu_coord = threading.Event()

        # Callbacks
        self.on_tornou_coordenador: callable = None  # fn()
        self.on_novo_coordenador:   callable = None  # fn(ip: str, port: int)

    # ------------------------------------------------------------------
    # Configuração e atualização
    # ------------------------------------------------------------------

    def configurar(self, send_fn, members: list):
        """Injeta o Node.send e a lista de nós vivos antes do uso."""
        self._send    = send_fn
        with self._lock:
            self._members = list(members)

    def atualizar_membros(self, members: list):
        """Atualiza a lista quando membros entram ou saem."""
        with self._lock:
            self._members = list(members)

    # ------------------------------------------------------------------
    # Disparar eleição (chamado pelo heartbeat)
    # ------------------------------------------------------------------

    def iniciar(self):
        """Inicia uma rodada de eleição. Disparos simultâneos são ignorados."""
        with self._lock:
            if self._em_eleicao:
                return
            self._em_eleicao = True

        threading.Thread(
            target=self._conduzir_eleicao,
            name=f"eleicao-{self.own_id}",
            daemon=True,
        ).start()

    # ------------------------------------------------------------------
    # Lógica principal (roda em thread separada)
    # ------------------------------------------------------------------

    def _conduzir_eleicao(self):
        print(f"[ELEC {self.own_id}] Eleição iniciada.")
        self._recebeu_ok.clear()
        self._recebeu_coord.clear()

        superiores = self._nos_superiores()

        # Sem ninguém de prioridade maior: vence de imediato.
        if not superiores:
            self._proclamar_coordenador()
            return

        # Envia ELECTION aos superiores em paralelo.
        def enviar_election(no):
            resp = self._send(
                no["ip"], no["port"],
                protocol.make_election(self.own_id),
                timeout=self.timeout_ok,
            )
            if resp and resp.get("type") == protocol.ELECTION_OK:
                self._recebeu_ok.set()

        threads = [
            threading.Thread(target=enviar_election, args=(m,), daemon=True)
            for m in superiores
        ]
        for t in threads:
            t.start()

        got_ok = self._recebeu_ok.wait(timeout=self.timeout_ok)

        if not got_ok:
            # Nenhum superior respondeu: este nó vence.
            print(f"[ELEC {self.own_id}] Nenhum superior respondeu, vencedor.")
            self._proclamar_coordenador()
            return

        # Algum superior está vivo: aguarda o anúncio dele.
        print(f"[ELEC {self.own_id}] ELECTION_OK recebido, aguardando COORDINATOR...")
        got_coord = self._recebeu_coord.wait(timeout=self.timeout_coord)

        if not got_coord:
            # O superior que respondeu também caiu: reinicia.
            print(f"[ELEC {self.own_id}] Timeout aguardando COORDINATOR, reiniciando.")
            with self._lock:
                self._em_eleicao = False
            self.iniciar()
            return

        with self._lock:
            self._em_eleicao = False

    def _proclamar_coordenador(self):
        """Anuncia vitória para todos os membros e dispara o callback."""
        print(f"[ELEC {self.own_id}] Venceu a eleição! Anunciando COORDINATOR.")

        with self._lock:
            outros = [
                m for m in self._members
                if not (m["ip"] == self.own_ip and m["port"] == self.own_port)
            ]

        def notificar(m):
            self._send(
                m["ip"], m["port"],
                protocol.make_coordinator(self.own_ip, self.own_port),
                timeout=3.0,
            )

        threads = [
            threading.Thread(target=notificar, args=(m,), daemon=True)
            for m in outros
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        with self._lock:
            self._em_eleicao = False

        if self.on_tornou_coordenador:
            threading.Thread(
                target=self.on_tornou_coordenador,
                daemon=True,
            ).start()

    # ------------------------------------------------------------------
    # Handlers integrados ao handle_message do Node
    # ------------------------------------------------------------------

    def tratar_election(self, msg: dict):
        """
        Recebeu ELECTION de um nó com ID menor.
        Se este nó tem ID maior: responde ELECTION_OK e inicia sua própria eleição.
        """
        candidato_id = msg.get("candidate_id", "")
        if self._sou_superior(candidato_id):
            # Inicia a própria eleição em thread para não travar a resposta.
            threading.Thread(target=self.iniciar, daemon=True).start()
            return protocol.make_election_ok()
        return protocol.make_ok()

    def tratar_coordinator(self, msg: dict):
        """Recebeu COORDINATOR: atualiza a referência ao coordenador e encerra."""
        novo_ip   = msg["ip"]
        novo_port = msg["port"]
        print(f"[ELEC {self.own_id}] Novo coordenador: {novo_ip}:{novo_port}")

        # Desbloqueia quem estava aguardando o anúncio
        self._recebeu_coord.set()

        with self._lock:
            self._em_eleicao = False

        if self.on_novo_coordenador:
            threading.Thread(
                target=self.on_novo_coordenador,
                args=(novo_ip, novo_port),
                daemon=True,
            ).start()

        return protocol.make_ok()

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------

    def _nos_superiores(self) -> list:
        """Retorna membros com ID maior que o próprio."""
        with self._lock:
            members = list(self._members)
        return [
            m for m in members
            if (m["ip"], m["port"]) > (self.own_ip, self.own_port)
        ]

    def _sou_superior(self, outro_id: str) -> bool:
        """Retorna True se este nó tem ID maior que outro_id."""
        try:
            ip, port_s = outro_id.split(":")
            return (self.own_ip, self.own_port) > (ip, int(port_s))
        except ValueError:
            return False