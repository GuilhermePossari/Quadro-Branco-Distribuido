"""
coordinator.py: Coordenador de um quadro.

Mantém os objetos, os membros e as travas de exclusão mútua. Registra o quadro
no Serviço de Nomes, atende o ingresso (JOIN) enviando o estado atual, processa
DRAW/REMOVE/COLOR retransmitindo aos demais e trata a saída de membros. Expõe
remover_membro() para o heartbeat e get_state() para a eleição.
"""

import threading
import protocol
from node import Node


class Coordinator(Node):

    def __init__(
        self,
        board_name: str,
        host: str,
        port: int,
        ns_host: str,
        ns_port: int,
    ):
        super().__init__(host, port)
        self.board_name = board_name
        self.ns_host    = ns_host
        self.ns_port    = ns_port

        # Estado do quadro, protegido por _state_lock.
        self._objects: dict = {}   # { object_id: {id, shape, points, color} }
        self._members: list = []   # [{"ip": str, "port": int}]
        self._locks: dict   = {}   # { object_id: "ip:porta" do dono }
        self._state_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Inicialização
    # ------------------------------------------------------------------

    def start(self, initial_objects: list = None, initial_members: list = None):
        """Carrega o estado inicial (quando vem de uma eleição), sobe o servidor
        e registra o quadro no Serviço de Nomes."""
        if initial_objects:
            self._objects = {o["id"]: o for o in initial_objects}
        if initial_members:
            self._members = list(initial_members)

        self.start_server()
        self._registrar_no_sn()
        print(f"[COORD '{self.board_name}'] Pronto. Membros: {len(self._members)}, "
              f"Objetos: {len(self._objects)}")

    def _registrar_no_sn(self):
        """Registra (ou atualiza) o endereço do quadro no Serviço de Nomes."""
        resp = self.send(
            self.ns_host, self.ns_port,
            protocol.make_register(self.board_name, self.host, self.port)
        )
        if resp and resp["type"] == protocol.OK:
            print(f"[COORD '{self.board_name}'] Registrado no SN em {self.host}:{self.port}")
        else:
            print(f"[COORD '{self.board_name}'] AVISO: falha ao registrar no SN — {resp}")

    # ------------------------------------------------------------------
    # Roteador de mensagens (chamado pelo Node para cada conexão)
    # ------------------------------------------------------------------

    def handle_message(self, msg: dict, addr: tuple):
        tipo = msg.get("type")
        handlers = {
            protocol.JOIN:         self._tratar_join,
            protocol.DRAW:         self._tratar_draw,
            protocol.REMOVE:       self._tratar_remove,
            protocol.COLOR:        self._tratar_color,
            protocol.LOCK_REQUEST: self._tratar_lock_request,
            protocol.LOCK_RELEASE: self._tratar_lock_release,
            protocol.LEAVE:        self._tratar_leave,
            protocol.HEARTBEAT:    self._tratar_heartbeat,
        }
        handler = handlers.get(tipo)
        if handler:
            return handler(msg)
        return protocol.make_error(f"tipo desconhecido: {tipo}")

    # ------------------------------------------------------------------
    # Onboarding: novo cliente entra no quadro
    # ------------------------------------------------------------------

    def _tratar_join(self, msg: dict):
        novo = {"ip": msg["ip"], "port": msg["port"]}

        with self._state_lock:
            # Evita duplicata (reconexão)
            if novo not in self._members:
                self._members.append(novo)
            snapshot_objetos = list(self._objects.values())
            snapshot_membros = list(self._members)

        print(f"[COORD] JOIN de {novo['ip']}:{novo['port']} "
              f"— total de membros: {len(snapshot_membros)}")

        # Avisa todos os membros existentes sobre o novo anel
        outros = [m for m in snapshot_membros if m != novo]
        self._broadcast_ring_update(snapshot_membros, outros)

        # Envia estado completo ao novo cliente
        return protocol.make_state(snapshot_objetos, snapshot_membros)

    # ------------------------------------------------------------------
    # Operações do quadro: atualiza estado e repassa aos outros
    # ------------------------------------------------------------------

    def _tratar_draw(self, msg: dict):
        obj = msg["object"]
        sender_id = msg.get("sender_id", "")

        with self._state_lock:
            self._objects[obj["id"]] = obj
            outros = self._outros_membros(sender_id)

        print(f"[COORD] DRAW '{obj['id']}' ({obj['shape']}) — "
              f"repassando para {len(outros)} membro(s)")
        self._broadcast(protocol.make_draw(obj, sender_id), outros)
        return protocol.make_ok()

    def _tratar_remove(self, msg: dict):
        oid       = msg["object_id"]
        sender_id = msg.get("sender_id", "")

        with self._state_lock:
            self._objects.pop(oid, None)
            self._locks.pop(oid, None)   # libera trava se existir
            outros = self._outros_membros(sender_id)

        print(f"[COORD] REMOVE '{oid}'")
        self._broadcast(protocol.make_remove(oid, sender_id), outros)
        return protocol.make_ok()

    def _tratar_color(self, msg: dict):
        oid       = msg["object_id"]
        cor       = msg["color"]
        sender_id = msg.get("sender_id", "")

        with self._state_lock:
            if oid in self._objects:
                self._objects[oid]["color"] = cor
            outros = self._outros_membros(sender_id)

        print(f"[COORD] COLOR '{oid}' -> {cor}")
        self._broadcast(protocol.make_color(oid, cor, sender_id), outros)
        return protocol.make_ok()

    # ------------------------------------------------------------------
    # Exclusão mútua: travas de objetos
    # ------------------------------------------------------------------

    def _tratar_lock_request(self, msg: dict):
        oid      = msg["object_id"]
        node_id  = msg["node_id"]          # "ip:porta" do cliente solicitante

        with self._state_lock:
            if oid not in self._locks:
                # Objeto livre: concede a trava
                self._locks[oid] = node_id
                print(f"[COORD] LOCK concedido: '{oid}' -> {node_id}")
                return protocol.make_lock_response(oid, granted=True)
            else:
                dono = self._locks[oid]
                print(f"[COORD] LOCK negado: '{oid}' já bloqueado por {dono}")
                return protocol.make_lock_response(
                    oid, granted=False,
                    reason=f"objeto selecionado por {dono}"
                )

    def _tratar_lock_release(self, msg: dict):
        oid = msg["object_id"]
        with self._state_lock:
            dono = self._locks.pop(oid, None)
        if dono:
            print(f"[COORD] LOCK liberado: '{oid}' (era de {dono})")
        return protocol.make_ok()

    # ------------------------------------------------------------------
    # Saída voluntária de cliente
    # ------------------------------------------------------------------

    def _tratar_leave(self, msg: dict):
        node_id = msg["node_id"]            # "ip:porta"
        ip, porta = node_id.split(":")
        self._remover_membro_interno(ip, int(porta), motivo="saída voluntária")
        return protocol.make_ok()

    def _tratar_heartbeat(self, msg: dict):
        """Responde ao ping do vizinho, mantendo o coordenador vivo no anel."""
        return protocol.make_heartbeat_ok(self.node_id)

    def _broadcast_ring_update(self, todos_membros: list, destinatarios: list):
        """
        Monta o anel completo (coord + membros) e avisa todos os destinatários.
        Chamado após JOIN ou remoção de membro.
        """
        from heartbeat import construir_anel
        anel = construir_anel(todos_membros, self.host, self.port)
        self._broadcast(protocol.make_ring_update(anel), destinatarios)

    # ------------------------------------------------------------------
    # API pública para o heartbeat e a eleição
    # ------------------------------------------------------------------

    def remover_membro(self, ip: str, port: int):
        """
        Remove um membro por falha detectada pelo heartbeat.
        Também libera as travas que o membro possuía.
        """
        self._remover_membro_interno(ip, port, motivo="falha detectada pelo heartbeat")

    def get_state(self) -> dict:
        """Snapshot do estado: {"objects": [...], "members": [...]}."""
        with self._state_lock:
            return {
                "objects": list(self._objects.values()),
                "members": list(self._members),
            }

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _remover_membro_interno(self, ip: str, port: int, motivo: str):
        membro  = {"ip": ip, "port": port}
        node_id = f"{ip}:{port}"

        with self._state_lock:
            if membro not in self._members:
                return                       # já foi removido
            self._members.remove(membro)
            # Libera todas as travas do membro que saiu
            self._locks = {
                k: v for k, v in self._locks.items() if v != node_id
            }
            membros_restantes = len(self._members)

        print(f"[COORD] Membro removido ({motivo}): {node_id} "
              f"— restam {membros_restantes}")

        if membros_restantes > 0:
            with self._state_lock:
                membros_atuais = list(self._members)
            self._broadcast_ring_update(membros_atuais, membros_atuais)

        if membros_restantes == 0:
            print(f"[COORD] Nenhum membro restante — encerrando quadro '{self.board_name}'")
            threading.Thread(target=self._encerrar_quadro, daemon=True).start()

    def _encerrar_quadro(self):
        """Remove o quadro do SN e encerra o servidor. Chamado quando sobra 0 membros."""
        resp = self.send(
            self.ns_host, self.ns_port,
            protocol.make_unregister(self.board_name)
        )
        if resp:
            print(f"[COORD] Quadro '{self.board_name}' removido do SN.")
        self.stop()

    def _outros_membros(self, sender_id: str) -> list:
        """Retorna membros excluindo o remetente. Deve ser chamado com _state_lock adquirido."""
        if not sender_id:
            return list(self._members)
        try:
            ip, porta = sender_id.split(":")
            porta = int(porta)
        except ValueError:
            return list(self._members)
        return [m for m in self._members if not (m["ip"] == ip and m["port"] == porta)]

    def _broadcast(self, msg: dict, membros: list):
        """Envia a msg a todos os membros em paralelo. Nunca envia para o próprio
        endereço: o nó coordenador também está em _members e reprocessaria em loop."""
        def _enviar(m):
            if m["ip"] == self.host and m["port"] == self.port:
                return
            self.send_sem_resposta(m["ip"], m["port"], msg)

        for m in membros:
            threading.Thread(target=_enviar, args=(m,), daemon=True).start()