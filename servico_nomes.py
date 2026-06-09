import socket
import threading
import sys

class NodeP2P:
    def __init__(self, host, porta_local):
        self.host = host
        self.porta_local = porta_local
        
        # Criação do socket do servidor (para escutar conexões)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.host, self.porta_local))

    def escutar_conexoes(self):
        """Função que roda em segundo plano aceitando mensagens (Servidor)"""
        self.server_socket.listen()
        print(f"[+] Escutando mensagens na porta {self.porta_local}...\n")
        
        while True:
            # Aceita a conexão de outro peer
            conexao, endereco = self.server_socket.accept()
            
            with conexao:
                dados = conexao.recv(1024)
                if dados:
                    mensagem = dados.decode('utf-8')
                    # Imprime a mensagem recebida e o cursor de digitação na linha de baixo
                    print(f"\r[Peer {endereco[1]} diz]: {mensagem}")
                    print("Você: ", end="", flush=True)

    def enviar_mensagens(self, porta_destino):
        """Função que captura o input do usuário e envia ao destino (Cliente)"""
        while True:
            try:
                mensagem = input("Você: ")
                if mensagem.lower() == 'sair':
                    break
                
                # Abre uma conexão rápida, envia a mensagem e fecha
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as cliente_socket:
                    cliente_socket.connect((self.host, porta_destino))
                    cliente_socket.sendall(mensagem.encode('utf-8'))
                    
            except ConnectionRefusedError:
                print(f"[-] O peer na porta {porta_destino} está offline ou não foi encontrado.")

    def iniciar(self, porta_destino):
        # 1. Inicia a thread do Servidor para escutar conexões de forma assíncrona
        thread_servidor = threading.Thread(target=self.escutar_conexoes)
        thread_servidor.daemon = True # Permite que a thread morra ao fechar o programa
        thread_servidor.start()

        # 2. O loop principal do programa assume o papel do Cliente
        self.enviar_mensagens(porta_destino)


if __name__ == "__main__":
    # Verifica se o usuário passou as portas corretas no terminal
    if len(sys.argv) != 3:
        print("Uso correto: python node.py <sua_porta> <porta_do_peer_destino>")
        sys.exit(1)
        
    minha_porta = int(sys.argv[1])
    porta_peer = int(sys.argv[2])
    
    # Instancia e inicia o nó (usando localhost para testes)
    meu_node = NodeP2P('127.0.0.1', minha_porta)
    meu_node.iniciar(porta_peer)