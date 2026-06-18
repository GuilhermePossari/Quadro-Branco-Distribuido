# PLANCONI — Plano de Conclusão do SDWB

> Foto do projeto após a implementação completa da lógica de rede da **Pessoa A**.
> Lista o que **já foi feito** (com validação) e o que **ainda falta** para a entrega.

_Atualizado em: 2026-06-18_

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

### Testes automatizados (novos, em `scripts/`) — todos passando
| Arquivo | Cobre | Resultado |
|---|---|---|
| `scripts/_comum.py` | Infra de teste: sobe SN + cria clientes com timeouts reduzidos | — |
| `scripts/teste_cenario_1_2.py` | **Cenário 1** (entrada dinâmica + onboarding) e **Cenário 2** (broadcast + exclusão mútua) | ✅ passa |
| `scripts/teste_cenario_3.py` | **Cenário 3** (morte do coordenador → detecção → Bully → recuperação de estado → SN reapontado → quadro operante) | ✅ passa |

> Rodam sem GUI (`Client(master=None)` torna os callbacks no-ops). Da raiz:
> `python scripts/teste_cenario_1_2.py` e `python scripts/teste_cenario_3.py`.

### Contrato estável para a GUI (consumido por `telas.py`)
- **Métodos:** `criar_quadro(nome)`, `listar_quadros()`, `ingressar_em_quadro(board)`,
  `desenhar(obj)`, `remover(object_id)`, `colorir(object_id, color)`, `sair()`.
- **Callbacks** (atribuir em `client.on_*`, todos disparados via `_ui` → thread-safe):
  `on_state_loaded(objetos)`, `on_draw(obj)`, `on_remove(object_id)`,
  `on_color(object_id, color)`, `on_error(msg)`, `on_coord_changed(ip, port, sou_coord)`.
- **Formato do objeto:** `{"id": str, "shape": "line"|"square", "points": [[x,y],[x,y]], "color": str}`.

---

## ❌ O que falta

### 1. `telas.py` — GUI tkinter (Pessoa B) — **bloco principal restante**
- `TelaInicial`: CRIAR (pede nome via `simpledialog`) / INGRESSAR.
- `TelaListaQuadros`: `client.listar_quadros()` → `Listbox` → `client.ingressar_em_quadro`.
- `TelaQuadro`: `Canvas` + toolbar (Linha, Quadrado, 2 cores, Remover, Selecionar);
  captura de cliques (2 pontos p/ linha/quadrado); seleção visual antes de colorir/remover.
- Implementar os callbacks (`receber_draw`, etc.) e ligá-los a `client.on_*`.
- Passar a referência `client` entre as telas.

### 2. Integração GUI ↔ rede
- Instanciar o `Client` com o `master` (raiz tkinter) e o **IP real** da máquina
  (não `0.0.0.0`/`127.0.0.1`) — exigido para os outros nós alcançarem este nó.
- Fechar a janela deve chamar `client.sair()` (saída graciosa / handoff).

### 3. Testes de demonstração com GUI
- Repetir os 3 cenários **visualmente** (com janelas), além dos scripts automatizados.
- Teste real entre **2 máquinas** (Ubuntu ↔ WSL): conferir IPs das interfaces; o nó
  deve se anunciar com o IP alcançável pela outra máquina.

### 4. Relatório (10% da nota)
- Já coberto em parte por `DECISOES_PROJETO.md` (decisões + protocolo) e este arquivo.
- Falta: seção de **fluxo de uso / telas** (Pessoa B) e fechamento do relatório.

---

## Divisão do que resta

| Frente | Responsável | Depende de |
|---|---|---|
| `telas.py` (todas as telas + canvas + callbacks) | **Pessoa B** | nada (contrato já estável) |
| Integração GUI↔rede + saída graciosa na janela | **Pessoa B** (A apoia) | `telas.py` |
| Demo visual dos 3 cenários | A + B | integração |
| Teste 2 máquinas (Ubuntu↔WSL) | A + B | integração |
| Relatório: protocolo/decisões | **Pessoa A** | incremental |
| Relatório: fluxo de uso/telas | **Pessoa B** | `telas.py` |

---

## Resumo de estado

| Camada | Estado |
|---|---|
| Infra (`protocol`, `node`, `name_service`, `coordinator`, `heartbeat`, `election`) | ✅ pronta (+1 ajuste anti-loop) |
| `client.py` (rede — Pessoa A) | ✅ **completo e testado** |
| Scripts de teste (cenários 1, 2, 3) | ✅ passando |
| `telas.py` (GUI — Pessoa B) | ❌ a fazer |
| Integração visual + demo + relatório | 🟡 parcial |
