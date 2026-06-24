"""
client.py — Cliente do SDWB (lógica de rede)  [ESQUELETO / a implementar]

Este arquivo é o "cérebro" de rede de cada terminal. A GUI (telas.py) NÃO fala
socket diretamente: ela chama métodos do `Client` e registra callbacks para ser
notificada quando algo chega da rede. Toda a infraestrutura abaixo já está pronta
e testada — o `Client` apenas a orquestra:

    protocol.py   — contrato de mensagens + framing
    node.py       — Node: servidor TCP + send/send_sem_resposta
    coordinator.py— Coordinator(Node): motor de estado autoritativo + broadcast
    heartbeat.py  — Heartbeat em anel (com contador de strikes)
    election.py   — Election (Bully)

═══════════════════════════════════════════════════════════════════════════════
DECISÕES DE DESIGN (derivadas do código atual — SEGUIR estas)
═══════════════════════════════════════════════════════════════════════════════

D1. UM ÚNICO SERVIDOR POR PROCESSO (Design B — "coordenador é um dos clientes").
    O `Client` é quem herda `Node` e abre o servidor TCP na sua porta P. Quando
    este terminal vira coordenador, NÃO subimos um segundo servidor numa outra
    porta: reutilizamos o `Coordinator` apenas como MOTOR DE ESTADO (delegate),
    SEM chamar `coordinator.start()`/`start_server()`. Assim:
      - a porta P do cliente == endereço do coordenador no Serviço de Nomes;
      - `election.py:159` anuncia `(own_ip, own_port)` == P → CORRETO sem alteração;
      - `construir_anel` (heartbeat) trata o coordenador como UM nó (dedup em :53);
      - NENHUM arquivo de infra precisa ser alterado.

D2. ROTEAMENTO POR (TIPO, PAPEL) em `handle_message`.
    A mesma mensagem significa coisas diferentes conforme o papel deste nó:
      - DRAW/REMOVE/COLOR recebidos por um CLIENTE comum  = broadcast → atualizar GUI.
      - DRAW/REMOVE/COLOR recebidos pelo COORDENADOR       = submissão de cliente
        → delegar a `self._coord.handle_message(msg, addr)` (atualiza estado
          autoritativo + faz broadcast aos OUTROS) e TAMBÉM atualizar a GUI local.
    O `Client` sempre dirige a GUI; o `Coordinator` delegate só cuida do estado
    autoritativo e do broadcast. Por isso NÃO é preciso callback de GUI no
    Coordinator (evita mexer na infra).

D3. OPERAÇÕES LOCAIS roteadas pelo papel:
      - se sou coordenador  → aplico no delegate (estado + broadcast) e na GUI;
      - se sou cliente comum → envio a operação ao coordenador via socket.
    DRAW NÃO precisa de lock (qualquer um desenha). COLOR e REMOVE PRECISAM de
    lock (exclusão mútua): LOCK_REQUEST → se concedido, opera e LOCK_RELEASE;
    se negado, dispara on_error na GUI. (enunciado §3A)

D4. THREAD-SAFETY DA GUI (tkinter): a thread de rede NUNCA toca widgets direto.
    Todo callback de GUI passa por `self._ui(fn, *args)` → `master.after(0, ...)`.

D5. CONEXÃO POR MENSAGEM (não persistente), igual ao resto do sistema: usar
    `self.send(...)` (espera resposta, retorna None em falha — SEMPRE checar None)
    e `self.send_sem_resposta(...)` para fire-and-forget. node_id == "ip:porta".

D6. CICLO DE VIDA / FALHAS (regras de negócio):
      - criador do quadro ENTRA como membro de si mesmo (senão a regra
        "coordenador sozinho sai → quadro encerra" não dispara). Ver `criar_quadro`.
      - saída voluntária → LEAVE + heartbeat.parar(); se eu for o coordenador e
        houver outros, NÃO há eleição automática (decisão de aula) → tratar handoff;
        se eu for o coordenador sozinho → o delegate já desregistra do SN.
      - vitória na eleição → semear `Coordinator` com a réplica local de objetos +
        membros conhecidos, virar coordenador e ATUALIZAR o SN com meu endereço
        (REGISTER) — requisito do enunciado §3A/§4.

═══════════════════════════════════════════════════════════════════════════════
O QUE FALTA IMPLEMENTAR (cada stub abaixo tem TODO específico)
═══════════════════════════════════════════════════════════════════════════════
  [ ] Descoberta: listar_quadros / criar_quadro / ingressar_em_quadro
  [ ] handle_message: roteador completo (D2) + HEARTBEAT/RING_UPDATE/ELECTION/COORD
  [ ] Operações de GUI: desenhar / remover / colorir + fluxo de lock (D3)
  [ ] Virar coordenador (delegate + registro no SN) e callbacks de eleição
  [ ] Wiring de Heartbeat e Election (injeção de send_fn, ring, membros, callbacks)
  [ ] Saída (sair) cobrindo os casos de D6
  [ ] Réplica local de estado (self.objetos / self.membros) consistente com STATE
      e com cada broadcast recebido
"""

import threading

import queue

import protocol
from node import Node
from coordinator import Coordinator
from heartbeat import Heartbeat, construir_anel
from election import Election


class Client(Node):
    """
    Cliente do SDWB. Herda `Node` (já fornece servidor TCP + send/recv).

    Uso esperado pela GUI (telas.py):
        cli = Client("0.0.0.0", 6001, ns_host="127.0.0.1", ns_port=5000, master=root)
        cli.on_draw  = tela.receber_draw        # callbacks (ver seção "Callbacks")
        cli.on_error = tela.mostrar_erro
        cli.start()
        quadros = cli.listar_quadros()
        cli.ingressar_em_quadro(quadros[0])      # ou cli.criar_quadro("Meu Quadro")
    """

    def __init__(self, host: str, port: int, ns_host: str, ns_port: int, master=None):
        super().__init__(host, port)
        self.ns_host = ns_host
        self.ns_port = ns_port
        self.master = master          # raiz tkinter — usada por _ui() (D4). Pode ser None em testes.
        # Fila de callbacks de GUI: a thread de rede só ENFILEIRA; a thread do
        # tkinter drena via drenar_ui() (D4). Chamar master.after() direto da
        # thread de rede dispara "main thread is not in main loop".
        self._ui_queue = queue.Queue()

        # ── Identidade do quadro / papel ───────────────────────────────
        self.board_name: str = None
        self.coord_ip: str = None
        self.coord_port: int = None
        self.sou_coordenador: bool = False
        self._coord: Coordinator = None      # delegate de estado quando sou coordenador (D1)

        # ── Réplica local do estado (mantida por STATE + broadcasts) ───
        self.objetos: dict = {}              # { object_id: {id, shape, points, color} }
        self.membros: list = []              # [{"ip": str, "port": int}] (inclui o coordenador)
        self._estado_lock = threading.Lock()

        # ── Subsistemas P2P (configurados no ingresso/criação) ─────────
        self.heartbeat: Heartbeat = Heartbeat(host, port)
        self.eleicao: Election    = Election(host, port)

        # ── Callbacks para a GUI (telas.py atribui; todos opcionais) ───
        # Sempre disparados via _ui() → thread-safe (D4).
        self.on_state_loaded: callable = None  # fn(objetos: list)          — após JOIN/STATE
        self.on_draw: callable         = None  # fn(obj: dict)              — novo objeto
        self.on_remove: callable       = None  # fn(object_id: str)
        self.on_color: callable        = None  # fn(object_id: str, color)
        self.on_error: callable        = None  # fn(mensagem: str)          — ex: lock negado
        self.on_coord_changed: callable = None # fn(ip, port, sou_coord)    — eleição/handoff (opcional)

    # ==================================================================
    # Ciclo de vida
    # ==================================================================

    def start(self):
        """Sobe o servidor TCP do cliente (D1: este é o ÚNICO servidor do processo)."""
        self.start_server()

    def sair(self):
        """
        Saída voluntária (D6). Três casos, decididos pelo papel/quantidade de membros:

          1. Cliente comum  → envia LEAVE ao coordenador (ele me remove do anel).
          2. Coordenador COM outros → HANDOFF sem eleição: escolho o sucessor de
             maior (ip,porta) — mesma regra do Bully — e anuncio COORDINATOR(sucessor)
             a todos. O sucessor assume com a réplica local dele. Decisão de aula:
             saída voluntária NÃO dispara eleição.
          3. Coordenador SOZINHO → encerro o quadro (UNREGISTER no SN).

        Limitação conhecida do handoff: por ~6s (até o heartbeat do sucessor me
        pingar e falhar), o sucessor ainda me terá no anel. Auto-corrige via HB.
        Se o anúncio COORDINATOR se perder, o heartbeat detecta minha ausência e a
        eleição assume como fallback — o quadro nunca fica órfão de forma permanente.
        """
        self.heartbeat.parar()

        # Caso 1 — cliente comum
        if not self.sou_coordenador:
            if self.coord_ip is not None:
                self.send_sem_resposta(self.coord_ip, self.coord_port,
                                       protocol.make_leave(self.node_id))
            self.stop()
            return

        # Sou coordenador: separar os OUTROS (membros exceto eu)
        membros = self._coord.get_state()["members"]
        outros = [m for m in membros
                  if not (m["ip"] == self.host and m["port"] == self.port)]

        # Caso 3 — coordenador sozinho
        if not outros:
            self.send_sem_resposta(self.ns_host, self.ns_port,
                                   protocol.make_unregister(self.board_name))
            self.stop()
            return

        # Caso 2 — handoff: sucessor = maior (ip,porta), igual ao critério do Bully
        sucessor = max(outros, key=lambda m: (m["ip"], m["port"]))
        anuncio = protocol.make_coordinator(sucessor["ip"], sucessor["port"])
        for m in outros:
            self.send_sem_resposta(m["ip"], m["port"], anuncio)
        self.stop()

    # ==================================================================
    # Descoberta / Serviço de Nomes
    # ==================================================================

    def listar_quadros(self) -> list:
        """
        Consulta o Serviço de Nomes e retorna [{"name", "ip", "port"}, ...].
        Retorna [] se o SN estiver fora do ar (send → None, D5).
        """
        resp = self.send(self.ns_host, self.ns_port, protocol.make_list())
        if resp is None or resp.get("type") != protocol.LIST_RESPONSE:
            return []
        return resp.get("boards", [])

    def criar_quadro(self, nome: str) -> bool:
        """
        Cria um quadro novo: este terminal já nasce coordenador (D1).
        Retorna False se já existe um quadro com esse nome (evita sobrescrever
        o REGISTER de outro coordenador no SN — name_service.py:44).

        IMPORTANTE: host/port aqui devem ser o IP REAL acessível pelos outros nós,
        não "0.0.0.0"/"127.0.0.1" — é este endereço que vai para o SN e para o anel.
        """
        if nome in {b["name"] for b in self.listar_quadros()}:
            return False

        self.board_name = nome
        self.coord_ip   = self.host
        self.coord_port = self.port

        # D6: o criador entra como membro de si mesmo — senão a regra
        # "coordenador sozinho sai → quadro encerra" nunca dispararia.
        meu_endereco = {"ip": self.host, "port": self.port}
        self._virar_coordenador(objetos=[], membros=[meu_endereco])

        # Anel/eleição iniciais com um único nó (eu). O HB não terá vizinho para
        # pingar (anel de 1), mas já fica armado para quando alguém ingressar.
        self._setup_heartbeat(construir_anel([meu_endereco], self.host, self.port))
        self._setup_election([meu_endereco])
        return True

    def ingressar_em_quadro(self, board: dict) -> bool:
        """
        Ingressa num quadro existente. `board` = {"name", "ip", "port"} (vindo do SN).
        Faz o onboarding: JOIN → recebe STATE (coordinator.py:112) → popula a réplica
        local → arma heartbeat/eleição. Retorna False se o coordenador não responder.
        """
        self.board_name = board["name"]
        self.coord_ip   = board["ip"]
        self.coord_port = board["port"]

        resp = self.send(self.coord_ip, self.coord_port,
                         protocol.make_join(self.host, self.port))
        if resp is None or resp.get("type") != protocol.STATE:
            return False

        with self._estado_lock:
            self.objetos = {o["id"]: o for o in resp["objects"]}
            self.membros = list(resp["members"])     # já me inclui (coordinator.py:117)
            objetos = list(self.objetos.values())
            membros = list(self.membros)

        self._ui(self.on_state_loaded, objetos)

        anel = construir_anel(membros, self.coord_ip, self.coord_port)
        self._setup_heartbeat(anel)
        self._setup_election(membros)
        return True

    # ==================================================================
    # Operações do quadro (chamadas pela GUI)
    # ==================================================================

    def _rotear_operacao(self, msg: dict):
        """
        Encaminha uma operação ao coordenador e devolve a resposta (D3):
          - sou coordenador  → chamo o delegate em processo (sem socket);
          - sou cliente comum → envio via socket ao coordenador.
        Retorna o dict de resposta (ou None se o coordenador remoto não respondeu).
        """
        if self.sou_coordenador:
            return self._coord.handle_message(msg, None)
        return self.send(self.coord_ip, self.coord_port, msg)

    def desenhar(self, obj: dict):
        """
        DRAW — sem lock (D3). obj = {id, shape: 'line'|'square', points, color}.
        Roteia ao coordenador (que faz broadcast aos outros) e atualiza a tela local
        de forma otimista — o coordenador me exclui do broadcast (sender_id).
        """
        msg = protocol.make_draw(obj, self.node_id)
        self._rotear_operacao(msg)
        self._aplicar_na_gui(msg)

    def remover(self, object_id: str):
        """
        REMOVE — exige lock (D3, §3A). Pede a trava; se negada, avisa a GUI e aborta.
        Retorna True se removeu, False se foi barrado pela exclusão mútua.
        """
        return self._operar_com_lock(
            object_id, protocol.make_remove(object_id, self.node_id))

    def colorir(self, object_id: str, color: str):
        """
        COLOR — exige lock (D3). Duas cores disponíveis (enunciado §1.1).
        Mesmo fluxo de remover(): trava → opera → libera.
        """
        return self._operar_com_lock(
            object_id, protocol.make_color(object_id, color, self.node_id))

    def _operar_com_lock(self, object_id: str, msg: dict) -> bool:
        """Sequência da exclusão mútua: LOCK_REQUEST → operação → LOCK_RELEASE."""
        granted, reason = self._solicitar_lock(object_id)
        if not granted:
            self._ui(self.on_error, reason or "objeto em uso por outro usuário")
            return False
        try:
            self._rotear_operacao(msg)
            self._aplicar_na_gui(msg)
        finally:
            self._liberar_lock(object_id)
        return True

    def _solicitar_lock(self, object_id: str) -> tuple:
        """
        Pede a trava ao coordenador (coordinator.py:180). Retorna (granted, reason).
        Coordenador indisponível conta como negação (não dá para garantir exclusão).
        """
        resp = self._rotear_operacao(protocol.make_lock_request(object_id, self.node_id))
        if resp is None or resp.get("type") != protocol.LOCK_RESPONSE:
            return False, "coordenador indisponível"
        return resp.get("granted", False), resp.get("reason", "")

    def _liberar_lock(self, object_id: str):
        """Libera a trava após a operação (coordinator.py:198)."""
        self._rotear_operacao(protocol.make_lock_release(object_id))

    # ==================================================================
    # Roteador de mensagens recebidas (override de Node.handle_message)
    # ==================================================================

    def handle_message(self, msg: dict, addr: tuple):
        """
        Roteador central (D2). Roda na thread de conexão do Node (node.py:86) —
        NUNCA toca a GUI direto; sempre via _ui(). O significado de uma operação
        depende do meu papel (cliente comum vs. coordenador).
        """
        tipo = msg.get("type")

        # --- Operações de quadro: significado depende do papel (D2) ---
        if tipo in (protocol.DRAW, protocol.REMOVE, protocol.COLOR):
            if self.sou_coordenador:
                # Submissão de um cliente: estado autoritativo + broadcast aos outros...
                resp = self._coord.handle_message(msg, addr)
                self._aplicar_na_gui(msg)        # ...e atualizo minha própria tela
                return resp
            # Sou cliente comum: isto é um broadcast do coordenador → só a tela
            self._aplicar_na_gui(msg)
            return protocol.make_ok()

        # --- Mensagens que só o coordenador processa ---
        if tipo in (protocol.JOIN, protocol.LOCK_REQUEST,
                    protocol.LOCK_RELEASE, protocol.LEAVE):
            if not self.sou_coordenador:
                return protocol.make_error("não sou o coordenador deste quadro")
            resp = self._coord.handle_message(msg, addr)
            if tipo in (protocol.JOIN, protocol.LEAVE):
                self._sincronizar_membros_do_coord()   # membros mudaram → atualizar HB/eleição
            return resp

        # --- Heartbeat: respondo sempre (estou no anel), qualquer papel ---
        if tipo == protocol.HEARTBEAT:
            return protocol.make_heartbeat_ok(self.node_id)

        # --- Anel atualizado pelo coordenador ---
        if tipo == protocol.RING_UPDATE:
            anel = msg["members"]
            self.heartbeat.atualizar_anel(anel)
            with self._estado_lock:
                self.membros = list(anel)
                vivos = list(self.membros)
            self.eleicao.atualizar_membros(vivos)
            return protocol.make_ok()

        # --- Eleição (Bully): delegar aos handlers prontos (election.py) ---
        if tipo == protocol.ELECTION:
            return self.eleicao.tratar_election(msg)
        if tipo == protocol.COORDINATOR:
            return self.eleicao.tratar_coordinator(msg)

        return protocol.make_error(f"tipo desconhecido: {tipo}")

    def _aplicar_na_gui(self, msg: dict):
        """
        Atualiza a réplica local de estado e dispara o callback de GUI via _ui().

        É o caminho ÚNICO por onde uma operação (própria ou de outro nó) chega à
        tela. Primeiro mexe em self.objetos sob _estado_lock; só depois notifica a
        GUI (que então roda na thread do tkinter). Formato do objeto: protocol.py:119.
        """
        tipo = msg.get("type")

        if tipo == protocol.DRAW:
            obj = msg["object"]
            with self._estado_lock:
                self.objetos[obj["id"]] = obj
            self._ui(self.on_draw, obj)

        elif tipo == protocol.REMOVE:
            oid = msg["object_id"]
            with self._estado_lock:
                self.objetos.pop(oid, None)
            self._ui(self.on_remove, oid)

        elif tipo == protocol.COLOR:
            oid = msg["object_id"]
            cor = msg["color"]
            with self._estado_lock:
                if oid in self.objetos:
                    self.objetos[oid]["color"] = cor
            self._ui(self.on_color, oid, cor)

    # ==================================================================
    # Virar coordenador (criação OU vitória na eleição) — D1, D6
    # ==================================================================

    def _virar_coordenador(self, objetos, membros: list):
        """
        Promove este terminal a coordenador usando o Coordinator como delegate (D1).
        Chamado em DOIS momentos: ao criar um quadro, e ao vencer/receber um handoff.

        `objetos` pode ser lista ou dict_values (vem de self.objetos.values()).
        """
        self._coord = Coordinator(self.board_name, self.host, self.port,
                                  self.ns_host, self.ns_port)

        # Semeia o estado SEM subir 2º servidor (D1): NÃO chamamos _coord.start().
        # Seguro popular direto: o delegate só passa a ser usado após sou_coordenador
        # = True, então não há acesso concorrente ainda (dispensa _state_lock).
        self._coord._objects = {o["id"]: o for o in objetos}
        self._coord._members = list(membros)

        # Registra/ATUALIZA o endereço do quadro no SN apontando para MIM.
        # Na vitória de eleição/handoff, isto reaponta o quadro (enunciado §4).
        self.send(self.ns_host, self.ns_port,
                  protocol.make_register(self.board_name, self.host, self.port))

        self.sou_coordenador = True
        self.coord_ip   = self.host
        self.coord_port = self.port
        with self._estado_lock:
            self.membros = list(membros)

        # Evita que o HB continue tratando o coordenador antigo como alvo.
        self.heartbeat.atualizar_coordenador(self.host, self.port)

        # Sincroniza o anel: atualiza o meu HB e avisa os OUTROS membros do novo
        # anel/coordenador (essencial após eleição/handoff; no-op na criação).
        anel = construir_anel(list(membros), self.host, self.port)
        self.heartbeat.atualizar_anel(anel)
        ring_msg = protocol.make_ring_update(anel)
        for m in membros:
            if m["ip"] == self.host and m["port"] == self.port:
                continue
            self.send_sem_resposta(m["ip"], m["port"], ring_msg)

        self._ui(self.on_coord_changed, self.host, self.port, True)

    # ==================================================================
    # Wiring de Heartbeat e Election
    # ==================================================================

    def _setup_heartbeat(self, anel: list):
        """
        Liga os callbacks e inicia o heartbeat. `iniciar` é idempotente
        (heartbeat.py:97): chamar de novo num nó que já monitora não reinicia —
        por isso na eleição/handoff basta atualizar_coordenador, sem re-setup.
        """
        self.heartbeat.on_membro_falhou      = self._on_membro_falhou
        self.heartbeat.on_coordenador_falhou = self._on_coordenador_falhou
        self.heartbeat.iniciar(self.send, anel, self.coord_ip, self.coord_port)

    def _setup_election(self, membros: list):
        """Liga os callbacks e injeta dependências da eleição (election.py:57)."""
        self.eleicao.on_tornou_coordenador = self._on_tornou_coordenador
        self.eleicao.on_novo_coordenador   = self._on_novo_coordenador
        self.eleicao.configurar(self.send, membros)

    # ── Callbacks do Heartbeat ─────────────────────────────────────────
    def _on_membro_falhou(self, ip: str, port: int):
        """
        Meu vizinho no anel (um membro comum) caiu. Quem trata a remoção é sempre
        o coordenador — ele libera as travas do morto e faz broadcast do novo anel.
        """
        if self.sou_coordenador:
            self._coord.remover_membro(ip, port)
            self._sincronizar_membros_do_coord()
        else:
            self.send_sem_resposta(self.coord_ip, self.coord_port,
                                   protocol.make_leave(f"{ip}:{port}"))

    def _on_coordenador_falhou(self):
        """
        Meu vizinho era o coordenador e caiu → disparar eleição (Bully). Atualizo a
        lista de candidatos removendo o coordenador morto antes de iniciar.
        """
        coord_id = f"{self.coord_ip}:{self.coord_port}"
        with self._estado_lock:
            vivos = [m for m in self.membros
                     if f"{m['ip']}:{m['port']}" != coord_id]
        self.eleicao.atualizar_membros(vivos)
        self.eleicao.iniciar()

    # ── Callbacks da Election ──────────────────────────────────────────
    def _on_tornou_coordenador(self):
        """
        Venci a eleição. Assumo com a réplica local (objetos que recebi por broadcast
        + membros vivos, sem o coordenador morto). _virar_coordenador reaponta o SN e
        sincroniza o anel de todos.
        """
        self._virar_coordenador(*self._estado_para_promocao())

    def _on_novo_coordenador(self, ip: str, port: int):
        """
        Recebi COORDINATOR. Dois casos:
          - aponta para MIM (handoff: fui o sucessor escolhido) → assumo.
          - aponta para outro nó (eleição/handoff normal) → atualizo minha referência.
        """
        if ip == self.host and port == self.port:
            self._virar_coordenador(*self._estado_para_promocao())
            return

        self.sou_coordenador = False
        self.coord_ip   = ip
        self.coord_port = port
        self.heartbeat.atualizar_coordenador(ip, port)
        self._ui(self.on_coord_changed, ip, port, False)

    def _estado_para_promocao(self):
        """
        Snapshot (objetos, membros) para virar coordenador, removendo o coordenador
        antigo e garantindo que EU esteja na lista. Usado por eleição e handoff.
        """
        coord_id_antigo = f"{self.coord_ip}:{self.coord_port}"
        with self._estado_lock:
            objetos = list(self.objetos.values())
            membros = [m for m in self.membros
                       if f"{m['ip']}:{m['port']}" != coord_id_antigo]
        meu = {"ip": self.host, "port": self.port}
        if meu not in membros:
            membros.append(meu)
        return objetos, membros

    # ==================================================================
    # Utilitários
    # ==================================================================

    def _ui(self, fn, *args):
        """
        Agenda `fn(*args)` para rodar na thread da GUI (D4).

        handle_message roda numa thread de conexão do Node (node.py:86) e o tkinter
        NÃO é thread-safe — nem `master.after()` pode ser chamado de outra thread
        ("main thread is not in main loop"). Por isso apenas ENFILEIRAMOS aqui; a
        thread do tkinter consome via drenar_ui() num poller periódico.

        Sem `master` (testes sem GUI) chamamos direto. `fn` None é ignorado.
        """
        if fn is None:
            return
        if self.master is not None:
            self._ui_queue.put((fn, args))
        else:
            fn(*args)

    def drenar_ui(self):
        """
        Executa todos os callbacks de GUI pendentes. DEVE ser chamado pela thread
        do tkinter (a App agenda um poller periódico com self.after()).
        """
        while True:
            try:
                fn, args = self._ui_queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn(*args)
            except Exception as e:
                print(f"[client] erro em callback de GUI: {e}")

    def _sincronizar_membros_do_coord(self):
        """
        Quando sou coordenador, mantém self.membros/anel/Election coerentes com o
        delegate (fonte da verdade dos membros). Chamar após JOIN/LEAVE delegados.

        O Coordinator já avisa os OUTROS via RING_UPDATE (coordinator.py:220), mas
        o próprio nó coordenador precisa atualizar seu HB/eleição localmente.
        """
        if not self.sou_coordenador or self._coord is None:
            return
        estado = self._coord.get_state()           # coordinator.py:240
        with self._estado_lock:
            self.membros = list(estado["members"])
            membros = list(self.membros)
        anel = construir_anel(membros, self.host, self.port)   # heartbeat.py:39
        self.heartbeat.atualizar_anel(anel)
        self.eleicao.atualizar_membros(membros)


# ─────────────────────────────────────────────────────────────────────────────
# NOTA sobre alterações de infra exigidas pelo Design B
# ─────────────────────────────────────────────────────────────────────────────
# O Design B (coordenador = um dos clientes, no mesmo processo/porta) exigiu DUAS
# alterações pequenas em coordinator.py:
#   1. [FEITA] _broadcast nunca envia para o próprio endereço — como o nó
#      coordenador também está em _members, enviar a si mesmo causaria
#      reprocessamento em loop. Correção universalmente válida.
#   2. [OPCIONAL] expor seed(objects, members) público para o Client semear o
#      estado sem subir 2º servidor, evitando tocar _objects/_members "privados".
# Fora isso, o restante da infra (node, heartbeat, election, protocol,
# name_service) permanece CONGELADO.
