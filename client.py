"""
client.py: lógica de rede do terminal.

A interface (telas.py) não fala socket: chama métodos do Client e é avisada por
callbacks, sempre entregues de forma segura para a thread da interface. O Client
consulta o Serviço de Nomes, cria e ingressa em quadros, encaminha as operações
da tela ao coordenador, aplica as operações recebidas e integra o heartbeat e a
eleição.

Quando o terminal cria um quadro ou vence uma eleição, ele passa a acumular o
papel de coordenador no mesmo processo e na mesma porta, reaproveitando o
Coordinator apenas como motor de estado, sem abrir um segundo servidor.
"""

import threading

import queue
import socket

import protocol
from node import Node
from coordinator import Coordinator
from heartbeat import Heartbeat, construir_anel
from election import Election


def porta_livre(host: str = "0.0.0.0") -> int:
    """Retorna uma porta TCP livre. Usada para abrir uma sessão por quadro quando
    o processo hospeda mais de um, cada uma com seu próprio servidor e porta."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, 0))
        return s.getsockname()[1]
    finally:
        s.close()


class Client(Node):
    """Terminal do SDWB. Herda Node (servidor TCP e envio)."""

    def __init__(self, host: str, port: int, ns_host: str, ns_port: int, master=None):
        super().__init__(host, port)
        self.ns_host = ns_host
        self.ns_port = ns_port
        self.master = master          # raiz tkinter usada por _ui(); None nos testes
        # A thread de rede só enfileira callbacks aqui; a thread da interface os
        # consome em drenar_ui(). Tocar tkinter fora dela quebra a interface.
        self._ui_queue = queue.Queue()

        # Identidade do quadro e papel deste nó.
        self.board_name: str = None
        self.coord_ip: str = None
        self.coord_port: int = None
        self.sou_coordenador: bool = False
        self._coord: Coordinator = None      # motor de estado quando sou coordenador

        # Réplica local do estado, mantida pelo STATE inicial e pelas retransmissões.
        self.objetos: dict = {}              # { object_id: {id, shape, points, color} }
        self.membros: list = []              # [{"ip": str, "port": int}], inclui o coordenador
        self._estado_lock = threading.Lock()

        # Heartbeat e eleição, configurados ao criar ou ingressar em um quadro.
        self.heartbeat: Heartbeat = Heartbeat(host, port)
        self.eleicao: Election    = Election(host, port)

        # Callbacks para a interface (opcionais), sempre disparados via _ui().
        self.on_state_loaded: callable = None  # fn(objetos: list)
        self.on_draw: callable         = None  # fn(obj: dict)
        self.on_remove: callable       = None  # fn(object_id: str)
        self.on_color: callable        = None  # fn(object_id: str, color)
        self.on_error: callable        = None  # fn(mensagem: str)
        self.on_coord_changed: callable = None # fn(ip, port, sou_coord)

    # ==================================================================
    # Ciclo de vida
    # ==================================================================

    def start(self):
        """Sobe o servidor TCP deste nó (o único do processo)."""
        self.start_server()

    def sair(self):
        """
        Saída ao encerrar o programa. Três casos conforme o papel:
          1. Cliente comum: envia LEAVE ao coordenador.
          2. Coordenador com outros membros: transfere o papel ao sucessor de maior
             (ip, porta), sem eleição, e avisa os demais.
          3. Coordenador sozinho: encerra o quadro (UNREGISTER no Serviço de Nomes).
        """
        self.heartbeat.parar()

        # Caso 1: cliente comum
        if not self.sou_coordenador:
            if self.coord_ip is not None:
                self.send_sem_resposta(self.coord_ip, self.coord_port,
                                       protocol.make_leave(self.node_id))
            self.stop()
            return

        # Sou coordenador: separa os demais membros (todos exceto eu).
        membros = self._coord.get_state()["members"]
        outros = [m for m in membros
                  if not (m["ip"] == self.host and m["port"] == self.port)]

        # Caso 3: coordenador sozinho
        if not outros:
            self.send_sem_resposta(self.ns_host, self.ns_port,
                                   protocol.make_unregister(self.board_name))
            self.stop()
            return

        # Caso 2: tenta os sucessores do maior (ip, porta) para o menor. Só considera
        # transferido se o sucessor responder. Se nenhum vivo assumir, desregistra o
        # quadro em vez de deixá-lo órfão no Serviço de Nomes.
        candidatos = sorted(outros, key=lambda m: (m["ip"], m["port"]), reverse=True)
        sucessor = None
        for c in candidatos:
            resp = self.send(c["ip"], c["port"],
                             protocol.make_coordinator(c["ip"], c["port"]), timeout=2)
            if resp is not None and resp.get("type") == protocol.OK:
                sucessor = c
                break

        if sucessor is None:
            self.send_sem_resposta(self.ns_host, self.ns_port,
                                   protocol.make_unregister(self.board_name))
            self.stop()
            return

        # Avisa os demais membros do novo coordenador.
        anuncio = protocol.make_coordinator(sucessor["ip"], sucessor["port"])
        for m in outros:
            if m["ip"] == sucessor["ip"] and m["port"] == sucessor["port"]:
                continue
            self.send_sem_resposta(m["ip"], m["port"], anuncio)
        self.stop()

    def sair_do_quadro(self) -> bool:
        """
        Volta à tela inicial sem encerrar o processo (diferente de sair()).

        Cliente comum: sai de fato (LEAVE, para o heartbeat e volta ao lobby) e
        retorna True, para o chamador reaproveitar esta sessão.
        Coordenador: mantém o papel e o quadro ativos em segundo plano e retorna
        False, para o chamador manter esta sessão e usar outra no primeiro plano.
        O papel só é cedido no encerramento do programa (ver sair()).
        """
        if self.sou_coordenador:
            return False

        self.heartbeat.parar()
        if self.board_name is not None and self.coord_ip is not None:
            self.send_sem_resposta(self.coord_ip, self.coord_port,
                                   protocol.make_leave(self.node_id))
        self._resetar_para_lobby()
        return True

    def _resetar_para_lobby(self):
        """Zera o estado do quadro, deixando a sessão pronta para um novo ciclo."""
        with self._estado_lock:
            self.objetos = {}
            self.membros = []
        self.board_name      = None
        self.coord_ip        = None
        self.coord_port      = None
        self.sou_coordenador = False
        self._coord          = None

    # ==================================================================
    # Descoberta / Serviço de Nomes
    # ==================================================================

    def listar_quadros(self) -> list:
        """Consulta o Serviço de Nomes. Retorna [{"name", "ip", "port"}, ...],
        ou [] se ele estiver fora do ar."""
        resp = self.send(self.ns_host, self.ns_port, protocol.make_list())
        if resp is None or resp.get("type") != protocol.LIST_RESPONSE:
            return []
        return resp.get("boards", [])

    def criar_quadro(self, nome: str) -> bool:
        """Cria um quadro e assume como coordenador. Retorna False se já existir um
        quadro com esse nome."""
        if nome in {b["name"] for b in self.listar_quadros()}:
            return False

        self.board_name = nome
        self.coord_ip   = self.host
        self.coord_port = self.port

        # O criador entra como membro de si mesmo, senão a regra "coordenador
        # sozinho sai encerra o quadro" nunca dispararia.
        meu_endereco = {"ip": self.host, "port": self.port}
        self._virar_coordenador(objetos=[], membros=[meu_endereco])

        # Anel e eleição já armados com um nó só, prontos para quando alguém ingressar.
        self._setup_heartbeat(construir_anel([meu_endereco], self.host, self.port))
        self._setup_election([meu_endereco])
        return True

    def ingressar_em_quadro(self, board: dict) -> bool:
        """Ingressa em um quadro existente: envia JOIN, recebe o STATE, popula a
        réplica local e arma heartbeat e eleição. Retorna False se o coordenador
        não responder. board = {"name", "ip", "port"}."""
        self.board_name = board["name"]
        self.coord_ip   = board["ip"]
        self.coord_port = board["port"]

        resp = self.send(self.coord_ip, self.coord_port,
                         protocol.make_join(self.host, self.port))
        if resp is None or resp.get("type") != protocol.STATE:
            return False

        with self._estado_lock:
            self.objetos = {o["id"]: o for o in resp["objects"]}
            self.membros = list(resp["members"])     # o coordenador já me incluiu
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
        """Encaminha a operação ao coordenador: chama o motor local se sou
        coordenador, senão envia por socket. Retorna a resposta ou None."""
        if self.sou_coordenador:
            return self._coord.handle_message(msg, None)
        return self.send(self.coord_ip, self.coord_port, msg)

    def desenhar(self, obj: dict):
        """DRAW, sem trava. Roteia ao coordenador e aplica na tela local."""
        msg = protocol.make_draw(obj, self.node_id)
        self._rotear_operacao(msg)
        self._aplicar_na_gui(msg)

    def remover(self, object_id: str) -> bool:
        """REMOVE do objeto selecionado (já travado por este nó). O coordenador
        libera a trava ao remover."""
        msg = protocol.make_remove(object_id, self.node_id)
        self._rotear_operacao(msg)
        self._aplicar_na_gui(msg)
        return True

    def colorir(self, object_id: str, color: str) -> bool:
        """COLOR do objeto selecionado (já travado por este nó). A trava permanece
        até a desseleção."""
        msg = protocol.make_color(object_id, color, self.node_id)
        self._rotear_operacao(msg)
        self._aplicar_na_gui(msg)
        return True

    def selecionar(self, object_id: str) -> tuple:
        """Seleciona um objeto adquirindo sua trava no coordenador. Retorna
        (concedido, motivo). Coordenador indisponível conta como negado."""
        return self._solicitar_lock(object_id)

    def desselecionar(self, object_id: str):
        """Libera a trava, deixando o objeto disponível para os outros nós."""
        self._liberar_lock(object_id)

    def _solicitar_lock(self, object_id: str) -> tuple:
        """Pede a trava ao coordenador. Retorna (granted, reason)."""
        resp = self._rotear_operacao(protocol.make_lock_request(object_id, self.node_id))
        if resp is None or resp.get("type") != protocol.LOCK_RESPONSE:
            return False, "coordenador indisponível"
        return resp.get("granted", False), resp.get("reason", "")

    def _liberar_lock(self, object_id: str):
        self._rotear_operacao(protocol.make_lock_release(object_id))

    # ==================================================================
    # Roteador de mensagens recebidas (override de Node.handle_message)
    # ==================================================================

    def handle_message(self, msg: dict, addr: tuple):
        """Roteia a mensagem recebida conforme o tipo e o papel deste nó. Roda na
        thread de conexão; nunca toca a interface direto, sempre via _ui()."""
        tipo = msg.get("type")

        # Operações do quadro: o significado depende do papel.
        if tipo in (protocol.DRAW, protocol.REMOVE, protocol.COLOR):
            if self.sou_coordenador:
                # Submissão de um cliente: atualiza o estado, retransmite e mostra na tela.
                resp = self._coord.handle_message(msg, addr)
                self._aplicar_na_gui(msg)
                return resp
            # Cliente comum: é uma retransmissão do coordenador, só atualiza a tela.
            self._aplicar_na_gui(msg)
            return protocol.make_ok()

        # Mensagens que só o coordenador processa.
        if tipo in (protocol.JOIN, protocol.LOCK_REQUEST,
                    protocol.LOCK_RELEASE, protocol.LEAVE):
            if not self.sou_coordenador:
                return protocol.make_error("não sou o coordenador deste quadro")
            resp = self._coord.handle_message(msg, addr)
            if tipo in (protocol.JOIN, protocol.LEAVE):
                self._sincronizar_membros_do_coord()   # membros mudaram
            return resp

        # Heartbeat: respondido em qualquer papel, pois estou no anel.
        if tipo == protocol.HEARTBEAT:
            return protocol.make_heartbeat_ok(self.node_id)

        # Anel atualizado pelo coordenador.
        if tipo == protocol.RING_UPDATE:
            anel = msg["members"]
            self.heartbeat.atualizar_anel(anel)
            with self._estado_lock:
                self.membros = list(anel)
                vivos = list(self.membros)
            self.eleicao.atualizar_membros(vivos)
            return protocol.make_ok()

        # Eleição: delega aos handlers do Election.
        if tipo == protocol.ELECTION:
            return self.eleicao.tratar_election(msg)
        if tipo == protocol.COORDINATOR:
            return self.eleicao.tratar_coordinator(msg)

        return protocol.make_error(f"tipo desconhecido: {tipo}")

    def _aplicar_na_gui(self, msg: dict):
        """Atualiza a réplica local de estado e notifica a tela via _ui(). Caminho
        único por onde uma operação, própria ou de outro nó, chega à interface."""
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
    # Virar coordenador (na criação ou ao vencer a eleição)
    # ==================================================================

    def _virar_coordenador(self, objetos, membros: list):
        """Promove este terminal a coordenador, usando o Coordinator como motor de
        estado. Chamado ao criar um quadro e ao vencer ou receber a transferência."""
        self._coord = Coordinator(self.board_name, self.host, self.port,
                                  self.ns_host, self.ns_port)

        # Semeia o estado sem subir um segundo servidor (não chama _coord.start()).
        self._coord._objects = {o["id"]: o for o in objetos}
        self._coord._members = list(membros)

        # Registra ou reaponta o quadro no Serviço de Nomes para o meu endereço.
        self.send(self.ns_host, self.ns_port,
                  protocol.make_register(self.board_name, self.host, self.port))

        self.sou_coordenador = True
        self.coord_ip   = self.host
        self.coord_port = self.port
        with self._estado_lock:
            self.membros = list(membros)

        # Evita que o heartbeat siga mirando o coordenador antigo.
        self.heartbeat.atualizar_coordenador(self.host, self.port)

        # Atualiza o meu anel e avisa os demais membros do novo coordenador.
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
        """Liga os callbacks e inicia o heartbeat (iniciar() é idempotente)."""
        self.heartbeat.on_membro_falhou      = self._on_membro_falhou
        self.heartbeat.on_coordenador_falhou = self._on_coordenador_falhou
        self.heartbeat.iniciar(self.send, anel, self.coord_ip, self.coord_port)

    def _setup_election(self, membros: list):
        """Liga os callbacks e injeta as dependências da eleição."""
        self.eleicao.on_tornou_coordenador = self._on_tornou_coordenador
        self.eleicao.on_novo_coordenador   = self._on_novo_coordenador
        self.eleicao.configurar(self.send, membros)

    # Callbacks do heartbeat
    def _on_membro_falhou(self, ip: str, port: int):
        """Um membro comum caiu. Quem remove é sempre o coordenador."""
        if self.sou_coordenador:
            self._coord.remover_membro(ip, port)
            self._sincronizar_membros_do_coord()
        else:
            self.send_sem_resposta(self.coord_ip, self.coord_port,
                                   protocol.make_leave(f"{ip}:{port}"))

    def _on_coordenador_falhou(self):
        """O coordenador caiu: dispara a eleição, tirando-o antes da lista de candidatos."""
        coord_id = f"{self.coord_ip}:{self.coord_port}"
        with self._estado_lock:
            vivos = [m for m in self.membros
                     if f"{m['ip']}:{m['port']}" != coord_id]
        self.eleicao.atualizar_membros(vivos)
        self.eleicao.iniciar()

    # Callbacks da eleição
    def _on_tornou_coordenador(self):
        """Venci a eleição: assumo com a réplica local de objetos e membros."""
        self._virar_coordenador(*self._estado_para_promocao())

    def _on_novo_coordenador(self, ip: str, port: int):
        """Recebi COORDINATOR. Se aponta para mim, assumo; senão, atualizo a referência."""
        if ip == self.host and port == self.port:
            self._virar_coordenador(*self._estado_para_promocao())
            return

        self.sou_coordenador = False
        self.coord_ip   = ip
        self.coord_port = port
        self.heartbeat.atualizar_coordenador(ip, port)
        self._ui(self.on_coord_changed, ip, port, False)

    def _estado_para_promocao(self):
        """Snapshot (objetos, membros) para assumir: tira o coordenador antigo e
        garante que eu esteja na lista."""
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
        """Enfileira fn(*args) para a thread da interface consumir em drenar_ui(),
        já que o tkinter não é seguro fora dela. Sem master (testes), chama direto."""
        if fn is None:
            return
        if self.master is not None:
            self._ui_queue.put((fn, args))
        else:
            fn(*args)

    def drenar_ui(self):
        """Executa os callbacks pendentes. Chamado pela thread da interface."""
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
        """Sendo coordenador, alinha membros, anel e eleição locais ao estado do
        motor. Chamado após JOIN ou LEAVE."""
        if not self.sou_coordenador or self._coord is None:
            return
        estado = self._coord.get_state()
        with self._estado_lock:
            self.membros = list(estado["members"])
            membros = list(self.membros)
        anel = construir_anel(membros, self.host, self.port)
        self.heartbeat.atualizar_anel(anel)
        self.eleicao.atualizar_membros(membros)
