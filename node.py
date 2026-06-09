"""
node.py — Classe base para todos os processos do SDWB
Todo processo (Coordenador, Cliente) herda desta classe.
Ela cuida de toda a mecânica de socket TCP — subclasses só precisam
implementar handle_message() para definir o que fazer com cada mensagem.
"""

import socket
import threading
import protocol


class Node:
    """
    Cada instância abre um servidor TCP numa porta própria e
    consegue enviar mensagens para qualquer outro nó do sistema.

    Uso básico (subclasse):

        class MeuProcesso(Node):
            def handle_message(self, msg, addr):
                if msg["type"] == protocol.PING:
                    return protocol.make_ok()
                return protocol.make_error("desconhecido")

        p = MeuProcesso("0.0.0.0", 6001)
        p.start_server()
        # ... lógica principal ...
        p.stop()
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.node_id = f"{host}:{port}"   # identificador único usado no heartbeat e eleição

        self._server_socket = None
        self._running = False
        self._server_thread = None

    # ------------------------------------------------------------------
    # Servidor TCP
    # ------------------------------------------------------------------

    def start_server(self):
        """Abre o servidor TCP e começa a aceitar conexões em background."""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self._server_socket.bind((self.host, self.port))
        except OSError as e:
            raise RuntimeError(f"[{self.node_id}] Não foi possível abrir porta {self.port}: {e}")

        self._server_socket.listen()
        # Timeout no accept() para que o loop consiga checar _running periodicamente
        self._server_socket.settimeout(1.0)

        self._running = True
        self._server_thread = threading.Thread(
            target=self._loop_aceitar,
            name=f"servidor-{self.node_id}",
            daemon=True
        )
        self._server_thread.start()
        print(f"[{self.node_id}] Servidor ativo.")

    def _loop_aceitar(self):
        """Loop principal do servidor: aceita conexões e despacha para threads."""
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
                t = threading.Thread(
                    target=self._tratar_conexao,
                    args=(conn, addr),
                    daemon=True
                )
                t.start()
            except socket.timeout:
                # Timeout normal — volta para checar _running
                continue
            except OSError:
                # Socket foi fechado por stop()
                break

    def _tratar_conexao(self, conn: socket.socket, addr: tuple):
        """Trata uma conexão: decodifica, chama handle_message, envia resposta."""
        try:
            msg = protocol.decode(conn)
            if msg is None:
                return  # conexão fechada antes de receber mensagem completa

            resposta = self.handle_message(msg, addr)

            if resposta is not None:
                conn.sendall(protocol.encode(resposta))

        except Exception as e:
            print(f"[{self.node_id}] Erro ao tratar conexão de {addr}: {e}")
            try:
                conn.sendall(protocol.encode(protocol.make_error(str(e))))
            except Exception:
                pass
        finally:
            conn.close()

    def handle_message(self, msg: dict, addr: tuple):
        """
        Trata uma mensagem recebida. Deve ser sobrescrito pelas subclasses.

        Retorne um dict para enviar como resposta.
        Retorne None se não há resposta (ex: mensagem de broadcast que não precisa de ACK).
        """
        print(f"[{self.node_id}] Mensagem sem handler: {msg.get('type')}")
        return protocol.make_error(f"tipo não reconhecido: {msg.get('type')}")

    def stop(self):
        """Encerra o servidor TCP."""
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        print(f"[{self.node_id}] Servidor encerrado.")

    # ------------------------------------------------------------------
    # Cliente TCP — envio de mensagens para outros nós
    # ------------------------------------------------------------------

    def send(self, ip: str, port: int, msg: dict, timeout: int = 5):
        """
        Envia uma mensagem para outro nó e aguarda resposta.

        Retorna o dict de resposta, ou None se a conexão falhar
        (nó está fora do ar, timeout, recusa de conexão, etc.).

        O chamador deve sempre checar se o retorno é None antes de usar.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((ip, port))
            s.sendall(protocol.encode(msg))
            return protocol.decode(s)
        except ConnectionRefusedError:
            print(f"[{self.node_id}] Conexão recusada por {ip}:{port} — nó fora do ar?")
            return None
        except socket.timeout:
            print(f"[{self.node_id}] Timeout ao conectar em {ip}:{port}")
            return None
        except OSError as e:
            print(f"[{self.node_id}] Erro de rede ao contactar {ip}:{port}: {e}")
            return None
        finally:
            try:
                s.close()
            except Exception:
                pass

    def send_sem_resposta(self, ip: str, port: int, msg: dict, timeout: int = 5):
        """
        Envia uma mensagem sem esperar resposta (fire-and-forget).
        Útil para broadcasts onde a resposta não importa.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((ip, port))
            s.sendall(protocol.encode(msg))
        except OSError:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------

    def __repr__(self):
        status = "ativo" if self._running else "parado"
        return f"Node({self.node_id}, {status})"