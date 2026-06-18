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
        Saída voluntária (D6).
        TODO:
          - parar heartbeat (self.heartbeat.parar()).
          - se NÃO sou coordenador: enviar LEAVE ao coordenador (make_leave(node_id)).
          - se sou coordenador e há outros membros: tratar handoff (sem eleição;
            decisão de aula). Ex.: escolher sucessor e transferir, ou encerrar o
            quadro — DECIDIR com a dupla. Documentar a escolha aqui.
          - se sou coordenador sozinho: o delegate encerra o quadro ao chegar a 0
            membros (coordinator._remover_membro_interno desregistra do SN).
          - self.stop() para fechar o servidor.
        """
        raise NotImplementedError

    # ==================================================================
    # Descoberta / Serviço de Nomes
    # ==================================================================

    def listar_quadros(self) -> list:
        """
        Consulta o SN e retorna [{"name", "ip", "port"}, ...].
        TODO: self.send(ns_host, ns_port, protocol.make_list()); checar None;
              extrair resp["boards"]. Retornar [] em falha.
        """
        raise NotImplementedError

    def criar_quadro(self, nome: str) -> bool:
        """
        Cria um quadro novo: este terminal já nasce coordenador (D1).
        TODO:
          - guardar board_name = nome; coord_ip/port = host/port próprios.
          - _virar_coordenador(objetos=[], membros=[meu_endereco])  (D6: entro como membro).
          - garantir registro no SN (REGISTER) — feito dentro de _virar_coordenador.
          - configurar heartbeat/eleição com o anel inicial (só eu).
          - retornar True/False conforme sucesso (ex.: nome já existe?).
        """
        raise NotImplementedError

    def ingressar_em_quadro(self, board: dict) -> bool:
        """
        Ingressa num quadro existente. `board` = {"name", "ip", "port"} do SN.
        TODO:
          - guardar board_name, coord_ip, coord_port a partir de `board`.
          - enviar JOIN (make_join(self.host, self.port)) ao coordenador; checar None.
          - resposta é STATE: popular self.objetos e self.membros (com _estado_lock);
            disparar self._ui(self.on_state_loaded, list(objetos)).
          - montar o anel: construir_anel(self.membros, coord_ip, coord_port).
          - _setup_heartbeat(anel) e _setup_election(self.membros).
          - retornar True/False.
        """
        raise NotImplementedError

    # ==================================================================
    # Operações do quadro (chamadas pela GUI)
    # ==================================================================

    def desenhar(self, obj: dict):
        """
        DRAW — sem lock (D3). obj = {id, shape: 'line'|'square', points, color}.
        TODO:
          - atualizar réplica local (self.objetos[obj['id']] = obj) e a GUI local.
          - rotear (D3): se sou_coordenador → self._coord.handle_message(make_draw(obj, self.node_id))
                         senão → self.send(coord_ip, coord_port, make_draw(obj, self.node_id)).
        """
        raise NotImplementedError

    def remover(self, object_id: str):
        """
        REMOVE — exige lock (D3).
        TODO: _solicitar_lock(object_id); se negado → on_error e abortar.
              Se concedido: aplicar/rotear make_remove(object_id, self.node_id),
              atualizar réplica + GUI, e _liberar_lock(object_id).
        """
        raise NotImplementedError

    def colorir(self, object_id: str, color: str):
        """
        COLOR — exige lock (D3). Duas cores disponíveis (enunciado §1.1).
        TODO: igual a remover(), porém com make_color(object_id, color, self.node_id).
        """
        raise NotImplementedError

    def _solicitar_lock(self, object_id: str) -> tuple:
        """
        Pede a trava do objeto ao coordenador (ou ao delegate, se sou coordenador).
        Retorna (granted: bool, reason: str).
        TODO: rotear make_lock_request(object_id, self.node_id); ler LOCK_RESPONSE.
        """
        raise NotImplementedError

    def _liberar_lock(self, object_id: str):
        """TODO: rotear make_lock_release(object_id) (fire-and-forget tolerável)."""
        raise NotImplementedError

    # ==================================================================
    # Roteador de mensagens recebidas (override de Node.handle_message)
    # ==================================================================

    def handle_message(self, msg: dict, addr: tuple):
        """
        Roteador central (D2). Esboço da estrutura a implementar:

            tipo = msg.get("type")

            # Operações de quadro: significado depende do papel (D2)
            if tipo in (protocol.DRAW, protocol.REMOVE, protocol.COLOR):
                if self.sou_coordenador:
                    resp = self._coord.handle_message(msg, addr)  # estado + broadcast
                    self._aplicar_na_gui(msg)                     # GUI do host
                    return resp
                else:
                    self._aplicar_na_gui(msg)                     # broadcast → só GUI
                    return protocol.make_ok()

            # JOIN / LOCK_* / LEAVE só fazem sentido se sou coordenador → delega
            if tipo in (protocol.JOIN, protocol.LOCK_REQUEST,
                        protocol.LOCK_RELEASE, protocol.LEAVE):
                if self.sou_coordenador:
                    resp = self._coord.handle_message(msg, addr)
                    self._sincronizar_membros_do_coord()         # manter réplica/anel
                    return resp
                return protocol.make_error("não sou coordenador")

            # Heartbeat: responder sempre (estou no anel), independente de papel
            if tipo == protocol.HEARTBEAT:
                return protocol.make_heartbeat_ok(self.node_id)

            # Anel atualizado pelo coordenador
            if tipo == protocol.RING_UPDATE:
                self.heartbeat.atualizar_anel(msg["members"])
                # atualizar self.membros e Election.atualizar_membros(...)
                return protocol.make_ok()

            # Eleição (Bully) — delegar aos handlers prontos
            if tipo == protocol.ELECTION:
                return self.eleicao.tratar_election(msg)
            if tipo == protocol.COORDINATOR:
                return self.eleicao.tratar_coordinator(msg)

            return protocol.make_error(f"tipo desconhecido: {tipo}")
        """
        raise NotImplementedError

    def _aplicar_na_gui(self, msg: dict):
        """
        Atualiza réplica local + dispara o callback de GUI correspondente via _ui().
        TODO: switch por msg['type'] → on_draw / on_remove / on_color, mantendo
              self.objetos coerente (com _estado_lock).
        """
        raise NotImplementedError

    # ==================================================================
    # Virar coordenador (criação OU vitória na eleição) — D1, D6
    # ==================================================================

    def _virar_coordenador(self, objetos: list, membros: list):
        """
        Promove este terminal a coordenador usando o Coordinator como delegate (D1).
        TODO:
          - self._coord = Coordinator(board_name, host, port, ns_host, ns_port)
          - SEMEAR estado SEM subir 2º servidor: NÃO chamar _coord.start().
            Em vez disso, popular _coord._objects/_members a partir de (objetos, membros)
            — avaliar expor um seed() no Coordinator se preferir não tocar atributos
            "privados" (única alteração de infra OPCIONAL; ver nota no fim do arquivo).
          - REGISTER no SN apontando para o MEU endereço:
              self.send(ns_host, ns_port, protocol.make_register(board_name, host, port))
            (no caso de eleição isto ATUALIZA o endereço do quadro — requisito §4).
          - self.sou_coordenador = True
          - self.eleicao... / self.heartbeat.atualizar_coordenador(host, port)
          - disparar self._ui(self.on_coord_changed, host, port, True) (opcional).
        """
        raise NotImplementedError

    # ==================================================================
    # Wiring de Heartbeat e Election
    # ==================================================================

    def _setup_heartbeat(self, anel: list):
        """
        TODO:
          self.heartbeat.on_membro_falhou      = self._on_membro_falhou
          self.heartbeat.on_coordenador_falhou = self._on_coordenador_falhou
          self.heartbeat.iniciar(self.send, anel, self.coord_ip, self.coord_port)
        """
        raise NotImplementedError

    def _setup_election(self, membros: list):
        """
        TODO:
          self.eleicao.on_tornou_coordenador = self._on_tornou_coordenador
          self.eleicao.on_novo_coordenador   = self._on_novo_coordenador
          self.eleicao.configurar(self.send, membros)
        """
        raise NotImplementedError

    # ── Callbacks do Heartbeat ─────────────────────────────────────────
    def _on_membro_falhou(self, ip: str, port: int):
        """
        Vizinho comum caiu. TODO: avisar o coordenador para removê-lo.
          - se sou coordenador: self._coord.remover_membro(ip, port).
          - senão: self.send(coord_ip, coord_port, make_leave(f"{ip}:{port}")).
        """
        raise NotImplementedError

    def _on_coordenador_falhou(self):
        """
        Coordenador caiu → iniciar eleição. TODO: garantir Election.atualizar_membros
        com os nós vivos (sem o coord morto) e chamar self.eleicao.iniciar().
        """
        raise NotImplementedError

    # ── Callbacks da Election ──────────────────────────────────────────
    def _on_tornou_coordenador(self):
        """
        Venci a eleição. TODO: _virar_coordenador(self.objetos.values(), self.membros)
        (semeia a partir da réplica local) e reconfigurar o anel/heartbeat.
        """
        raise NotImplementedError

    def _on_novo_coordenador(self, ip: str, port: int):
        """
        Outro nó venceu. TODO: atualizar coord_ip/port, heartbeat.atualizar_coordenador,
        e on_coord_changed(ip, port, False).
        """
        raise NotImplementedError

    # ==================================================================
    # Utilitários
    # ==================================================================

    def _ui(self, fn, *args):
        """
        Executa `fn(*args)` na thread da GUI (D4). Se não há master (testes), chama direto.
        TODO:
          if fn is None: return
          if self.master is not None: self.master.after(0, lambda: fn(*args))
          else: fn(*args)
        """
        raise NotImplementedError

    def _sincronizar_membros_do_coord(self):
        """
        Quando sou coordenador, manter self.membros/anel/Election coerentes com o
        delegate após JOIN/LEAVE. TODO: ler self._coord.get_state()["members"].
        """
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# NOTA sobre alteração OPCIONAL de infra
# ─────────────────────────────────────────────────────────────────────────────
# A única coisa que poderia justificar tocar a infra (coordinator.py) é expor um
# método público `seed(objects, members)` para semear o estado sem subir servidor,
# evitando que o Client mexa em _objects/_members "privados". É trivial e não muda
# comportamento — decidir com a dupla. Fora isso, o Design B mantém TODA a infra
# (node, coordinator, heartbeat, election, protocol, name_service) CONGELADA.
