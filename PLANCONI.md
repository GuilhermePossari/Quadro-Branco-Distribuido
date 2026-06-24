# PLANCONI — Plano de Conclusão do SDWB

> Foto do projeto após a implementação completa da lógica de rede da **Pessoa A**.
> Lista o que **já foi feito** (com validação) e o que **ainda falta** para a entrega.

_Atualizado em: 2026-06-18 (GUI + integração concluídas; resta demo interativa e relatório)_

---

## ✅ O que foi feito agora

### `client.py` — lógica de rede completa (Pessoa A)
Todos os blocos do `PLANO_IMPLEMENTACAO.md` implementados, **sem nenhum `NotImplementedError`**:

| Bloco | Conteúdo | Estado |
|---|---|---|
| 1.1 | Utilitários: `_ui` (thread-safety GUI), `_aplicar_na_gui`, `_sincronizar_membros_do_coord` | ✅ |
| 1.2 | Descoberta: `listar_quadros`, `criar_quadro`, `ingressar_em_quadro` | ✅ |
| 1.3 | `handle_message` — roteador central por (tipo, papel) | ✅ |
| 1.4 | Operações: `desenhar` (sem lock), `remover`/`colorir` (com lock), `_rotear_operacao`, locks | ✅ |
| 1.5 | `_virar_coordenador` (delegate, D1) e `sair` (3 casos do D6, com **handoff**) | ✅ |
| 1.6 | Wiring + callbacks de heartbeat/eleição; `_estado_para_promocao` | ✅ |

### Decisões fechadas durante a implementação
- **Handoff sem eleição** (saída voluntária do coordenador): escolhe o sucessor de
  maior `ip:porta` e anuncia `COORDINATOR(sucessor)`. Fallback natural: se o anúncio
  se perder, o heartbeat detecta e a eleição assume — o quadro nunca fica órfão.
- **Ajuste de infra necessário** (Design B não ficou 100% congelado):
  - `coordinator.py::_broadcast` agora **nunca envia para o próprio endereço** —
    como o nó coordenador também está em `_members`, o auto-envio causava loop infinito.
    Correção universalmente válida (1 método).

### `telas.py` + `main.py` — GUI tkinter integrada (feito agora)
- **`telas.py`**: `App` (controlador + poller de UI), `TelaInicial` (CRIAR/INGRESSAR),
  `TelaListaQuadros` (lista do SN + ingressar), `TelaQuadro` (canvas + toolbar:
  Linha, Quadrado, 2 cores, Selecionar, Remover; seleção por hit-test; redesenho).
- **`main.py`**: entrada `python main.py [porta] [ip] [--ns IP:PORTA]`; detecta o IP
  real da interface (não 127.0.0.1) e sobe o `Client` + `App`. Fechar a janela chama
  `client.sair()` (saída graciosa / handoff).
- **Correção importante de thread-safety (no `client.py`):** `_ui` agora ENFILEIRA os
  callbacks numa `queue.Queue`; a `App` os drena na thread do tkinter via poller
  (`after(40, ...)`). Chamar `master.after()` da thread de rede dava
  "main thread is not in main loop" — pego pelo smoke test da GUI.

### Testes automatizados (novos, em `scripts/`) — todos passando
| Arquivo | Cobre | Resultado |
|---|---|---|
| `scripts/_comum.py` | Infra de teste: sobe SN + cria clientes com timeouts reduzidos | — |
| `scripts/teste_cenario_1_2.py` | **Cenário 1** (entrada dinâmica + onboarding) e **Cenário 2** (broadcast + exclusão mútua) | ✅ passa |
| `scripts/teste_cenario_3.py` | **Cenário 3** (morte do coordenador → detecção → Bully → recuperação de estado → SN reapontado → quadro operante) | ✅ passa |
| `scripts/teste_gui.py` | Integração GUI↔rede: criar quadro, desenho local, broadcast remoto na tela, erro de lock sem travar a GUI | ✅ passa |

> Cenários 1–3 rodam sem GUI (`Client(master=None)`). O smoke test da GUI dirige a
> `App` sem `mainloop` (via `update()`). Da raiz: `python scripts/<arquivo>.py`.

### Contrato estável para a GUI (consumido por `telas.py`)
- **Métodos:** `criar_quadro(nome)`, `listar_quadros()`, `ingressar_em_quadro(board)`,
  `desenhar(obj)`, `remover(object_id)`, `colorir(object_id, color)`, `sair()`.
- **Callbacks** (atribuir em `client.on_*`, todos disparados via `_ui` → thread-safe):
  `on_state_loaded(objetos)`, `on_draw(obj)`, `on_remove(object_id)`,
  `on_color(object_id, color)`, `on_error(msg)`, `on_coord_changed(ip, port, sou_coord)`.
- **Formato do objeto:** `{"id": str, "shape": "line"|"square", "points": [[x,y],[x,y]], "color": str}`.

---

## ❌ O que falta

### 1. Demonstração interativa (com janelas, em 2 máquinas)
Os scripts automatizados já provam a lógica dos 3 cenários, mas a **demo da entrega**
deve ser feita com as janelas abertas. Falta apenas executar/ensaiar:
- Subir `python name_service.py`, depois `python main.py 6001`, `6002`, `6003`...
- Repetir os 3 cenários visualmente (entrada, concorrência, matar o coordenador).
- Teste real **Ubuntu ↔ WSL**: conferir os IPs das interfaces (`ip addr`); o SN
  precisa estar num endereço alcançável pelos dois; passar o IP próprio em `main.py`
  se a autodetecção pegar a interface errada.

### 2. Relatório (10% da nota) — **excluído deste ciclo a pedido**
- Já coberto em parte por `DECISOES_PROJETO.md` (decisões + protocolo) e este arquivo.
- Falta: seção de **fluxo de uso / telas** e fechamento.

---

## Resumo de estado

| Camada | Estado |
|---|---|
| Infra (`protocol`, `node`, `name_service`, `coordinator`, `heartbeat`, `election`) | ✅ pronta (+1 ajuste anti-loop) |
| `client.py` (rede — Pessoa A) | ✅ completo e testado (+fix de fila no `_ui`) |
| `telas.py` + `main.py` (GUI — Pessoa B) | ✅ **feito e integrado** |
| Scripts de teste (cenários 1, 2, 3 + smoke GUI) | ✅ passando |
| Demo interativa (2 máquinas) | 🟡 a executar/ensaiar |
| Relatório | ⏸️ adiado a pedido |
