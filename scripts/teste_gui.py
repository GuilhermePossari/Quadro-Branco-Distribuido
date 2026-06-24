"""
teste_gui.py — Smoke test da integração GUI ↔ rede.

Valida o caminho completo: thread de rede → Client._ui → master.after →
callback do App → TelaQuadro → canvas. Dirige a App sem mainloop (usa update()
para processar os eventos enfileirados por master.after) e fecha ao final.

Rode da raiz:  python scripts/teste_gui.py
"""

import time
from _comum import subir_sn, novo_cliente, ok, titulo

from client import Client
from telas import App, TelaQuadro
from main import detectar_ip


def pump(app, segundos=1.0):
    """Processa o loop de eventos do tkinter por um tempo (substitui mainloop)."""
    fim = time.time() + segundos
    while time.time() < fim:
        app.update()
        time.sleep(0.02)


def main():
    subir_sn()
    ip = "127.0.0.1"

    titulo("GUI: criar quadro e abrir TelaQuadro")
    A = Client(ip, 6001, "127.0.0.1", 5000, master=None)
    A.heartbeat.intervalo = 0.5
    A.start()
    app = App(A)
    A.master = app

    assert A.criar_quadro("SalaGUI"), "criar_quadro falhou"
    tela = app.mostrar(TelaQuadro, nome="SalaGUI")
    pump(app, 0.3)
    assert isinstance(app._tela_atual, TelaQuadro)
    ok("Quadro criado e TelaQuadro ativa (papel COORDENADOR)")

    titulo("GUI: desenho local aparece no canvas")
    obj = {"id": "g1", "shape": "line", "points": [[10, 10], [80, 80]], "color": "#d62728"}
    A.desenhar(obj)
    pump(app, 0.3)
    assert "g1" in tela.objetos, "desenho local não entrou no espelho da tela"
    assert tela.canvas.find_withtag("g1"), "item não foi renderizado no canvas"
    ok("Desenho local renderizado no canvas (tag g1 presente)")

    titulo("GUI: broadcast de outro nó atualiza a tela")
    B = novo_cliente(6002)
    assert B.ingressar_em_quadro(B.listar_quadros()[0])
    obj2 = {"id": "g2", "shape": "square", "points": [[20, 20], [60, 60]], "color": "#1f77b4"}
    B.desenhar(obj2)
    pump(app, 0.8)   # tempo para o broadcast chegar e o master.after processar
    assert "g2" in tela.objetos, "broadcast de B não chegou à GUI de A"
    assert tela.canvas.find_withtag("g2"), "objeto de B não renderizado"
    ok("Desenho de B (g2) propagou e foi renderizado na GUI de A")

    titulo("GUI: exclusão mútua na SELEÇÃO")
    # A seleciona g1 pela GUI (clique simulado no meio da linha) → adquire a trava
    tela.ferramenta = "selecionar"
    (x1, y1), (x2, y2) = tela.objetos["g1"]["points"]
    tela._selecionar_em((x1 + x2) // 2, (y1 + y2) // 2)
    pump(app, 0.2)
    assert tela.selecionado == "g1", "A não conseguiu selecionar g1"
    ok("A selecionou g1 (trava adquirida)")

    # B tenta selecionar o MESMO objeto → negado (sem tocar a GUI de A)
    concedido, motivo = B.selecionar("g1")
    assert not concedido, "B não deveria selecionar objeto já selecionado por A"
    ok(f"B foi recusado ao selecionar g1 — motivo: \"{motivo}\"")

    # A deixa de selecionar → B consegue
    A.desselecionar("g1")
    tela.selecionado = None
    concedido2, _ = B.selecionar("g1")
    assert concedido2, "B deveria conseguir selecionar após A desselecionar"
    ok("Após A desselecionar, B conseguiu selecionar g1")
    B.desselecionar("g1")

    app.destroy()
    print("\n\033[1;92m=== SMOKE TEST GUI: PASSOU ===\033[0m")


if __name__ == "__main__":
    main()
