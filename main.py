"""
main.py — Ponto de entrada do cliente SDWB (GUI).

Uso:
    python main.py [porta] [ip_proprio] [--ns IP:PORTA]

  porta       porta TCP deste nó (default 6001). Cada nó na mesma máquina usa uma.
  ip_proprio  IP com que este nó se anuncia aos outros. Default: detectado
              automaticamente (a interface de saída). NUNCA use 127.0.0.1 num
              teste entre máquinas (Ubuntu↔WSL) — os outros nós não te alcançariam.
  --ns        endereço do Serviço de Nomes (default 127.0.0.1:5000).

Antes de subir clientes, rode o Serviço de Nomes:  python name_service.py
"""

import sys
import socket

from client import Client
from telas import App


def detectar_ip() -> str:
    """Descobre o IP da interface de saída (sem enviar nada de fato)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def parse_args(argv):
    porta, ip = 6001, None
    ns_host, ns_port = "127.0.0.1", 5000
    posicionais = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--ns" and i + 1 < len(argv):
            host, _, port = argv[i + 1].partition(":")
            ns_host = host or ns_host
            ns_port = int(port) if port else ns_port
            i += 2
            continue
        posicionais.append(a)
        i += 1
    if len(posicionais) >= 1:
        porta = int(posicionais[0])
    if len(posicionais) >= 2:
        ip = posicionais[1]
    return porta, ip, ns_host, ns_port


def main():
    porta, ip, ns_host, ns_port = parse_args(sys.argv[1:])
    if ip is None:
        ip = detectar_ip()

    print(f"[main] Subindo cliente em {ip}:{porta} | SN em {ns_host}:{ns_port}")
    client = Client(ip, porta, ns_host, ns_port, master=None)
    client.start()

    app = App(client)          # App registra callbacks e assume client.master = self
    app.mainloop()


if __name__ == "__main__":
    main()
