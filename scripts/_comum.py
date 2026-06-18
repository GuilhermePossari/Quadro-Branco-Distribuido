"""
_comum.py — utilidades compartilhadas pelos scripts de teste (sem GUI).

Todos os nós rodam no mesmo processo Python, cada um com seu servidor TCP numa
porta de 127.0.0.1. Isso é suficiente para exercitar TODA a lógica de rede da
Pessoa A (descoberta, broadcast, exclusão mútua, heartbeat, eleição) sem depender
do telas.py — o Client com master=None transforma os callbacks de GUI em no-ops.
"""

import os
import sys
import time
import threading

# Permite importar os módulos do projeto a partir de scripts/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import name_service              # noqa: E402
from client import Client        # noqa: E402

NS_HOST, NS_PORT = "127.0.0.1", 5000
HOST = "127.0.0.1"


def subir_sn():
    """Sobe o Serviço de Nomes numa thread daemon e espera ficar pronto."""
    t = threading.Thread(
        target=name_service.start,
        kwargs={"host": NS_HOST, "port": NS_PORT},
        daemon=True,
    )
    t.start()
    time.sleep(0.3)
    return t


def novo_cliente(porta: int) -> Client:
    """
    Cria e sobe um Client com timeouts REDUZIDOS para os testes correrem rápido
    (heartbeat de 0.5s/3 strikes ≈ 1.5s de detecção; eleição com timeouts curtos).
    """
    c = Client(HOST, porta, NS_HOST, NS_PORT, master=None)
    c.heartbeat.intervalo  = 0.5
    c.heartbeat.max_falhas = 3
    c.eleicao.timeout_ok    = 1.0
    c.eleicao.timeout_coord = 2.0
    c.start()
    return c


def ok(msg: str):
    print(f"  \033[92m✓\033[0m {msg}")


def titulo(msg: str):
    print(f"\n\033[1m{msg}\033[0m")
