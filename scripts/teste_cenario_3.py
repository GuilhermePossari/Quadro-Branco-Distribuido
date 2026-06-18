"""
teste_cenario_3.py — Cenário obrigatório 3: morte do coordenador.

Cobre:
  - SN → A (coordenador) → B e C ingressam; A desenha algo (estado a preservar).
  - "Mata" A (fecha o servidor + para o heartbeat, SEM saída graciosa = crash).
  - O heartbeat em anel detecta a ausência → eleição Bully → novo coordenador assume.
  - Verifica: o vencedor esperado (maior ip:porta entre os vivos) virou coordenador,
    os demais o reconhecem, o estado foi preservado e o SN foi reapontado.

Rode da raiz do projeto:  python scripts/teste_cenario_3.py
"""

import time
from _comum import subir_sn, novo_cliente, ok, titulo


def main():
    subir_sn()

    titulo("Preparação: quadro com 3 nós e um desenho")
    A = novo_cliente(6001)
    assert A.criar_quadro("Sala1")
    B = novo_cliente(6002)
    assert B.ingressar_em_quadro(B.listar_quadros()[0])
    C = novo_cliente(6003)
    assert C.ingressar_em_quadro(C.listar_quadros()[0])
    time.sleep(0.6)

    obj = {"id": "o1", "shape": "line", "points": [[0, 0], [9, 9]], "color": "black"}
    A.desenhar(obj)
    time.sleep(0.5)
    assert "o1" in B.objetos and "o1" in C.objetos
    ok("Quadro montado: A=coord(6001), B(6002), C(6003), objeto 'o1' replicado")

    titulo("Morte do coordenador A (simula crash)")
    A.heartbeat.parar()
    A.stop()
    ok("A foi 'morto' (servidor fechado, heartbeat parado) — não responde mais")

    titulo("Detecção + eleição (aguardando convergência)")
    # HB ~0.5s * 3 strikes ≈ 1.5s para detectar + eleição. Damos folga.
    deadline = time.time() + 8
    while time.time() < deadline:
        if C.sou_coordenador and B.coord_port == 6003:
            break
        time.sleep(0.3)

    # C (maior porta entre os vivos) deve vencer o Bully
    assert C.sou_coordenador, "C deveria ter virado coordenador (maior id entre os vivos)"
    assert not B.sou_coordenador, "B não deveria ser coordenador"
    ok("Eleição Bully: C (maior ip:porta entre os vivos) assumiu como coordenador")

    assert B.coord_port == 6003, f"B ainda aponta para {B.coord_port}, esperado 6003"
    ok("B reconhece C como o novo coordenador")

    titulo("Recuperação de estado e do Serviço de Nomes")
    estado = C._coord.get_state()
    assert "o1" in {o["id"] for o in estado["objects"]}, "estado não foi preservado"
    ok("Novo coordenador preservou o estado (objeto 'o1' presente)")

    boards = B.listar_quadros()
    sala1 = next(b for b in boards if b["name"] == "Sala1")
    assert sala1["port"] == 6003, f"SN ainda aponta para {sala1['port']}, esperado 6003"
    ok(f"SN reapontado para o novo coordenador: {sala1}")

    titulo("Quadro segue operante após a eleição")
    obj2 = {"id": "o2", "shape": "square", "points": [[2, 2], [4, 4]], "color": "red"}
    B.desenhar(obj2)
    time.sleep(0.5)
    assert "o2" in C.objetos, "broadcast parou de funcionar após a eleição"
    ok("Novo desenho (o2) propagou normalmente — quadro 100% operante")

    print("\n\033[1;92m=== CENÁRIO 3: TODOS OS TESTES PASSARAM ===\033[0m")


if __name__ == "__main__":
    main()
