"""
node.py: classe base de rede. Coordenador e Cliente herdam daqui.
Cuida do servidor TCP e do envio; a subclasse implementa handle_message().
"""

import socket
import threading
import protocol


class Node:
    """Servidor TCP em uma porta própria, com envio para outros nós."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.node_id = f"{host}:{port}"   # identidade usada no heartbeat e na eleição

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
        # accept() com timeout para o loop reavaliar _running periodicamente
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
                # Timeout normal: volta para checar _running
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
        """Trata uma mensagem. Sobrescrito pelas subclasses. Retorna o dict de
        resposta, ou None quando não há resposta a enviar."""
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
    # Cliente TCP: envio de mensagens para outros nós
    # ------------------------------------------------------------------

    def send(self, ip: str, port: int, msg: dict, timeout: int = 5):
        """Envia e aguarda resposta. Retorna o dict recebido, ou None em falha
        de conexão (nó fora do ar, timeout, recusa). Sempre checar None."""
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
        """Envia sem esperar resposta. Usado nas retransmissões."""
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