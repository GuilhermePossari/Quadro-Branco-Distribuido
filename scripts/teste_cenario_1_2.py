"""
teste_cenario_1_2.py — Cenários obrigatórios 1 (entrada dinâmica) e 2 (concorrência).

Cobre:
  1. SN sobe → A cria quadro (vira coordenador) → B e C descobrem via SN e ingressam,
     recebendo o estado atual (sincronização de onboarding).
  2. Broadcast: operação de um nó aparece em todos os outros.
  3. Exclusão mútua: dois nós disputam o mesmo objeto; o segundo é recusado.

Rode da raiz do projeto:  python scripts/teste_cenario_1_2.py
"""

import time
from _comum import subir_sn, novo_cliente, ok, titulo


def main():
    subir_sn()

    titulo("1. Entrada dinâmica")
    A = novo_cliente(6001)
    assert A.criar_quadro("Sala1"), "A não conseguiu criar o quadro"
    assert A.sou_coordenador
    ok("A criou 'Sala1' e nasceu coordenador")

    B = novo_cliente(6002)
    boards = B.listar_quadros()
    assert any(b["name"] == "Sala1" for b in boards), f"SN não listou Sala1: {boards}"
    ok(f"B descobriu o quadro via SN: {boards}")
    assert B.ingressar_em_quadro(boards[0]), "B não ingressou"
    ok("B ingressou")

    C = novo_cliente(6003)
    assert C.ingressar_em_quadro(C.listar_quadros()[0]), "C não ingressou"
    ok("C ingressou")

    time.sleep(0.6)
    membros = A._coord.get_state()["members"]
    assert len(membros) == 3, f"esperava 3 membros, há {len(membros)}: {membros}"
    ok(f"Coordenador conhece os 3 membros: {[m['port'] for m in membros]}")

    titulo("2a. Broadcast (sincronização em tempo real)")
    # Coordenador desenha → clientes comuns recebem
    obj1 = {"id": "o1", "shape": "line", "points": [[0, 0], [10, 10]], "color": "black"}
    A.desenhar(obj1)
    time.sleep(0.5)
    assert "o1" in B.objetos and "o1" in C.objetos, "broadcast do coordenador falhou"
    ok("Desenho do coordenador (o1) chegou em B e C")

    # Cliente comum desenha → coordenador e o outro cliente recebem
    obj2 = {"id": "o2", "shape": "square", "points": [[1, 1], [5, 5]], "color": "red"}
    B.desenhar(obj2)
    time.sleep(0.5)
    assert "o2" in A.objetos and "o2" in C.objetos, "broadcast de cliente comum falhou"
    ok("Desenho de cliente comum (o2) chegou no coordenador e em C")

    titulo("2b. Exclusão mútua")
    g1, _ = B._solicitar_lock("o1")
    g2, motivo = C._solicitar_lock("o1")
    assert g1 and not g2, f"esperava B=ok, C=negado; obtido B={g1}, C={g2}"
    ok(f"B travou 'o1'; C foi recusado — motivo: \"{motivo}\"")

    B._liberar_lock("o1")
    g3, _ = C._solicitar_lock("o1")
    assert g3, "C deveria conseguir a trava após B liberar"
    ok("Após B liberar, C conseguiu travar 'o1'")
    C._liberar_lock("o1")

    print("\n\033[1;92m=== CENÁRIOS 1 e 2: TODOS OS TESTES PASSARAM ===\033[0m")


if __name__ == "__main__":
    main()
