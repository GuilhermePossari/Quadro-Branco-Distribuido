"""
teste_orfaos.py — Quadros órfãos no Serviço de Nomes (correções A e B).

Contexto: um quadro pode ficar registrado no SN apontando para um coordenador que
não existe mais (coordenador crashou, ou um handoff de saída falhou). Ele aparece
no LIST mas o JOIN falha ("coordenador não disponível").

Fix A (name_service.py): o SN faz um probe de vivacidade no LIST e PODA os
  coordenadores que não respondem.
Fix B (client.py::sair): ao sair, um coordenador só transfere o papel se o sucessor
  RESPONDER; se nenhum sucessor vivo responder, DESREGISTRA o quadro (não orfana).

Rode da raiz:  python scripts/teste_orfaos.py
"""

import time
from _comum import subir_sn, novo_cliente, ok, titulo, HOST, NS_HOST, NS_PORT
import protocol
from client import porta_livre


def main():
    subir_sn()

    titulo("Fix A: SN poda quadro com coordenador morto no LIST")
    A = novo_cliente(6001)
    # Registra um quadro 'Fantasma' apontando para uma porta sem ninguém escutando.
    porta_morta = porta_livre(HOST)
    A.send(NS_HOST, NS_PORT, protocol.make_register("Fantasma", HOST, porta_morta))
    boards = A.listar_quadros()
    assert all(b["name"] != "Fantasma" for b in boards), f"'Fantasma' não foi podado: {boards}"
    ok("Quadro 'Fantasma' (coordenador morto) foi podado do LIST")

    titulo("Fix B: coordenador sem sucessor vivo desregistra ao sair (não orfana)")
    assert A.criar_quadro("Sala1")
    B = novo_cliente(6002)
    assert B.ingressar_em_quadro([b for b in B.listar_quadros() if b["name"] == "Sala1"][0])
    time.sleep(0.5)

    # B 'crasha' sem saída graciosa (servidor + heartbeat parados) → fica inalcançável.
    B.heartbeat.parar()
    B.stop()
    time.sleep(0.2)

    # A sai sendo coordenador: o único sucessor (B) está morto → deve DESREGISTRAR.
    A.sair()
    time.sleep(0.3)

    C = novo_cliente(6003)
    boards = C.listar_quadros()
    assert all(b["name"] != "Sala1" for b in boards), f"'Sala1' ficou órfã no SN: {boards}"
    ok("Coordenador sem sucessor vivo desregistrou 'Sala1' — sem quadro fantasma")

    print("\n\033[1;92m=== ÓRFÃOS (Fix A + Fix B): TODOS OS TESTES PASSARAM ===\033[0m")


if __name__ == "__main__":
    main()
