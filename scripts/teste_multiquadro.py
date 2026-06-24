"""
teste_multiquadro.py — Suporte a MÚLTIPLOS quadros por processo + "Sair do quadro".

Valida a regra pedida:
  - "Sair do quadro" como CLIENTE COMUM  → sai de fato (volta ao lobby, é removido
    dos membros do coordenador) e a sessão pode ser reaproveitada.
  - "Sair do quadro" como COORDENADOR    → NÃO abre mão do papel: continua
    hospedando o quadro original, mesmo que uma NOVA sessão crie outro quadro.
  - Dois quadros coordenados ao mesmo tempo, cada um registrado no SN no seu
    próprio ip:porta, ambos operantes de forma independente.

A GUI mantém uma sessão Client por quadro; aqui simulamos isso com Clients
independentes (mesma mecânica que App._nova_sessao usa).

Rode da raiz:  python scripts/teste_multiquadro.py
"""

import time
from _comum import subir_sn, novo_cliente, ok, titulo, HOST
from client import porta_livre


def main():
    subir_sn()

    titulo("Preparação: A coordena 'Sala1'; B ingressa como cliente comum")
    A = novo_cliente(6001)
    assert A.criar_quadro("Sala1")
    assert A.sou_coordenador
    B = novo_cliente(6002)
    assert B.ingressar_em_quadro(
        [b for b in B.listar_quadros() if b["name"] == "Sala1"][0])
    time.sleep(0.6)
    ok("A=coord(6001) de 'Sala1', B(6002) ingressou")

    titulo("Cliente comum 'Sai do quadro' → sai de fato e volta ao lobby")
    assert B.sair_do_quadro() is True, "cliente comum deveria sair e reaproveitar a sessão"
    assert B.board_name is None and not B.sou_coordenador
    time.sleep(1.0)   # coordenador processa o LEAVE
    membros = A._coord.get_state()["members"]
    assert all(m["port"] != 6002 for m in membros), f"B ainda consta nos membros: {membros}"
    ok("B saiu de 'Sala1' (coordenador o removeu) e voltou ao estado de lobby")

    titulo("Coordenador 'Sai do quadro' → mantém hospedando em segundo plano")
    assert A.sair_do_quadro() is False, "coordenador NÃO deve abrir mão ao voltar à tela inicial"
    assert A.sou_coordenador and A.board_name == "Sala1"
    boards = A.listar_quadros()
    assert any(b["name"] == "Sala1" and b["port"] == 6001 for b in boards), boards
    ok("A continua coordenando 'Sala1' em 6001 (segundo plano)")

    titulo("Nova sessão de primeiro plano cria 'Sala2' (A segue hospedando 'Sala1')")
    A2 = novo_cliente(porta_livre(HOST))
    assert A2.criar_quadro("Sala2")
    assert A2.sou_coordenador
    time.sleep(0.4)
    nomes = {b["name"]: b["port"] for b in A2.listar_quadros()}
    assert nomes.get("Sala1") == 6001, f"'Sala1' sumiu/mudou de host: {nomes}"
    assert "Sala2" in nomes, f"'Sala2' não foi registrada: {nomes}"
    ok(f"SN lista os DOIS quadros simultâneos: {nomes}")

    titulo("Ambos os quadros seguem operantes e independentes")
    A.desenhar({"id": "s1", "shape": "line", "points": [[0, 0], [5, 5]], "color": "black"})
    A2.desenhar({"id": "s2", "shape": "square", "points": [[1, 1], [3, 3]], "color": "red"})
    time.sleep(0.3)
    assert "s1" in A.objetos and "s1" not in A2.objetos, "estado vazou entre quadros"
    assert "s2" in A2.objetos and "s2" not in A.objetos, "estado vazou entre quadros"
    ok("A desenha em 'Sala1' e A2 em 'Sala2' sem vazamento de estado")

    print("\n\033[1;92m=== MULTIQUADRO: TODOS OS TESTES PASSARAM ===\033[0m")


if __name__ == "__main__":
    main()
