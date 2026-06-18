# Plano de Implementação — Trabalho Restante do SDWB

> Detalha **tudo que falta implementar no `client.py`** (com a base de cada parte
> em decisões já tomadas no resto do código), o trabalho de GUI e integração, e a
> **divisão completa do que resta entre as duas pessoas** da dupla.

## Estado atual

| Componente | Estado |
|---|---|
| `protocol.py`, `node.py`, `name_service.py`, `coordinator.py`, `heartbeat.py`, `election.py` | ✅ prontos e testados (infra **congelada** — ver Design B) |
| `client.py` | 🟡 **esqueleto** — assinaturas + docstrings, corpos são `NotImplementedError` |
| `telas.py` | ❌ não existe no repositório |
| Integração + 3 cenários de demo | ❌ |
| Relatório (10%) | 🟡 coberto em parte por `DECISOES_PROJETO.md` |

**Princípio que rege tudo (Design B):** o `Client` é o **único servidor TCP** do processo;
ao virar coordenador, reutiliza `Coordinator` como **motor de estado** (delegate) sem subir
segundo servidor. Consequência: **nenhum arquivo de infra muda** (no máximo um `seed()`
opcional em `coordinator.py`). Detalhado em `client.py` (D1) e `DECISOES_PROJETO.md`.

---

## Parte 1 — `client.py`: o que falta, e em que se baseia

Cada item lista a **base** (decisão/código de onde a implementação deriva) e os **cuidados**.

### 1.1 Utilitários de base (fazer primeiro — todo o resto depende deles)

| Método | O que faz | Base / dependência | Cuidados |
|---|---|---|---|
| `_ui(fn, *args)` | Roda callback de GUI na thread do tkinter | **D4**; padrão `master.after(0, ...)` | Se `master is None` (testes), chamar direto. `fn` pode ser `None`. |
| `_aplicar_na_gui(msg)` | Atualiza réplica local + dispara `on_draw/on_remove/on_color` | Formato de objeto fixo em `protocol.py:119-130` | Mexer em `self.objetos` sob `_estado_lock`; só depois `_ui(...)`. |
| `_sincronizar_membros_do_coord()` | Mantém `self.membros`/anel coerentes quando sou coordenador | `coordinator.get_state()` (`coordinator.py:240`) | Chamar após JOIN/LEAVE delegados. |

### 1.2 Descoberta / Serviço de Nomes

| Método | Base / dependência | Cuidados |
|---|---|---|
| `listar_quadros()` | `make_list()` / `LIST_RESPONSE` (`protocol.py:102-107`); SN trata em `name_service.py:62` | `send` pode retornar `None` (**D5**) → retornar `[]`. Ler `resp["boards"]`. |
| `criar_quadro(nome)` | Nasce coordenador (**D1**); regra "criador é membro de si" (**D6**) | Chamar `_virar_coordenador([], [meu_endereco])`. Registro no SN acontece lá dentro. |
| `ingressar_em_quadro(board)` | `make_join` → resposta `STATE` (`coordinator.py:112-130`); `construir_anel` (`heartbeat.py:39`) | Popular `objetos`/`membros` do `STATE`; `_ui(on_state_loaded, ...)`; montar anel e chamar `_setup_heartbeat`/`_setup_election`. |

### 1.3 Roteador `handle_message` (coração do cliente)

- **Base:** **D2** (significado por papel) + handlers prontos de `election.py` (`tratar_election`/`tratar_coordinator`) e `coordinator.py` (`handle_message`).
- **Estrutura** (já esboçada no docstring do método em `client.py`):
  - `DRAW/REMOVE/COLOR`: se coordenador → `self._coord.handle_message(msg, addr)` (estado+broadcast) **e** `_aplicar_na_gui`; senão → só `_aplicar_na_gui` (é broadcast).
  - `JOIN/LOCK_*/LEAVE`: só válidos se coordenador → delegar e `_sincronizar_membros_do_coord`; senão `make_error`.
  - `HEARTBEAT` → `make_heartbeat_ok(self.node_id)` (responder **sempre**, estou no anel).
  - `RING_UPDATE` → `heartbeat.atualizar_anel(msg["members"])` + atualizar `membros`/`Election`.
  - `ELECTION` → `self.eleicao.tratar_election(msg)`; `COORDINATOR` → `self.eleicao.tratar_coordinator(msg)`.
- **Cuidados:** este método roda na **thread de conexão** do `Node` (`node.py:86`); nada de tocar tkinter aqui sem `_ui`.

### 1.4 Operações da GUI (com exclusão mútua)

| Método | Base / dependência | Cuidados |
|---|---|---|
| `desenhar(obj)` | DRAW **sem lock** (**D3**); `make_draw(obj, self.node_id)` | `sender_id` evita eco (`coordinator.py:292`). Atualizar réplica+GUI e rotear por papel. |
| `remover(object_id)` | REMOVE **com lock** (**D3**, enunciado §3A); `make_remove` | Sequência: `_solicitar_lock` → operar → `_liberar_lock`. Se negado → `on_error`. |
| `colorir(object_id, color)` | COLOR **com lock**; duas cores (enunciado §1.1) | Idem `remover`. |
| `_solicitar_lock(object_id)` | `LOCK_REQUEST`/`LOCK_RESPONSE` (`coordinator.py:180-196`) | Retorna `(granted, reason)`; rotear por papel. |
| `_liberar_lock(object_id)` | `LOCK_RELEASE` (`coordinator.py:198`) | Fire-and-forget tolerável. |

### 1.5 Virar coordenador + ciclo de vida

| Método | Base / dependência | Cuidados |
|---|---|---|
| `_virar_coordenador(objetos, membros)` | **D1** (delegate sem 2º servidor); REGISTER atualiza SN (enunciado §4) | **Não** chamar `_coord.start()`. Semear estado (`seed()` opcional, senão setar `_objects/_members`). `heartbeat.atualizar_coordenador(host, port)`. |
| `sair()` | **D6** (3 casos) | Não-coord → `LEAVE`. Coord c/ outros → handoff (DECIDIR). Coord sozinho → delegate encerra (`coordinator.py:278`). Sempre `heartbeat.parar()` + `stop()`. |

### 1.6 Wiring + callbacks de Heartbeat e Election

| Método | Base / dependência | Cuidados |
|---|---|---|
| `_setup_heartbeat(anel)` | `Heartbeat.iniciar(send_fn, ring, coord_ip, coord_port)` (`heartbeat.py:89`) | Injetar `self.send`. Setar callbacks **antes** de `iniciar()`. |
| `_setup_election(membros)` | `Election.configurar(send_fn, members)` (`election.py:57`) | Setar `on_tornou_coordenador`/`on_novo_coordenador` antes. |
| `_on_membro_falhou(ip,port)` | callback HB | Coord → `_coord.remover_membro`; senão → `LEAVE` ao coord. |
| `_on_coordenador_falhou()` | callback HB → eleição | `Election.atualizar_membros(vivos)` + `eleicao.iniciar()`. |
| `_on_tornou_coordenador()` | callback eleição (`election.py:177`) | `_virar_coordenador(self.objetos.values(), self.membros)`. |
| `_on_novo_coordenador(ip,port)` | callback eleição (`election.py:215`) | Atualizar `coord_ip/port` + `heartbeat.atualizar_coordenador`. |

> **Decisão pendente (registrar quando decidida):** comportamento do `sair()` quando o
> coordenador sai voluntariamente havendo outros membros (handoff vs. encerrar quadro).
> Decisão de aula diz "sem eleição"; falta definir o mecanismo.

---

## Parte 2 — `telas.py` (GUI tkinter)

Base: contrato de callbacks/métodos já fixado no esqueleto de `client.py`. A GUI **nunca**
fala socket — só chama métodos do `Client` e reage aos callbacks.

- **`TelaInicial`**: botões CRIAR / INGRESSAR. Criar → `simpledialog.askstring` (nome) → `client.criar_quadro`.
- **`TelaListaQuadros`**: `client.listar_quadros()` → `Listbox`/botões → seleção → `client.ingressar_em_quadro`.
- **`TelaQuadro`**: `tk.Canvas` + toolbar (Linha, Quadrado, 2 cores, Remover, Selecionar).
  - Captura de cliques (`<Button-1>`): linha/quadrado = 2 pontos; chamar `client.desenhar(obj)`.
  - Seleção de objeto (feedback visual) antes de colorir/remover → `client.colorir`/`client.remover`.
  - Estado local: `objetos`, `selecionado`, `pontos_temp`, `ferramenta`.
  - Implementar os callbacks: `receber_draw`, `receber_remove`, `receber_color`, `mostrar_erro`,
    `carregar_estado`, e atribuí-los a `client.on_*` — todos disparados via `_ui` (já thread-safe).
- **Correções herdadas** (se reaproveitar esqueleto da Pessoa B): passar `client` entre telas;
  prompt de nome ao criar.

---

## Parte 3 — Integração e testes (3 cenários obrigatórios)

1. **Entrada dinâmica:** SN → coordenador → 3 clientes descobrindo via SN e recebendo `STATE`.
2. **Concorrência:** 2 clientes selecionam/operam o mesmo objeto → exclusão mútua recusa o 2º.
3. **Morte do coordenador:** matar o processo → heartbeat (3 strikes) detecta → Bully → novo
   coordenador assume e **atualiza o SN**.

Recomendado: criar `scripts/` de teste (subir SN + N nós em portas distintas no mesmo host;
porta desempata o Bully — `election.py:234`) e **versioná-los** (hoje não estão no repo).

---

## Divisão do trabalho restante entre as duas pessoas

Princípio: a fronteira é o **contrato de callbacks/métodos** do `Client`. Cada lado programa
contra essa fronteira sem esperar o outro.

### 👤 Pessoa A — Rede & Coordenação (dono do `client.py`)
- **1.1** utilitários (`_ui`, `_aplicar_na_gui`, `_sincronizar_membros_do_coord`).
- **1.2** descoberta (`listar_quadros`, `criar_quadro`, `ingressar_em_quadro`).
- **1.3** `handle_message` completo (roteador).
- **1.5** `_virar_coordenador` + `sair` (+ decidir o handoff com a dupla).
- **1.6** wiring e callbacks de heartbeat/eleição.
- **Cenário 3** (morte do coordenador) — é onde a parte de A é exercitada.
- Manter `DECISOES_PROJETO.md` atualizado (parte do relatório).

### 👤 Pessoa B — Interface & Interação (dono do `telas.py`)
- **Toda a Parte 2** (`telas.py`: TelaInicial, TelaListaQuadros, TelaQuadro, canvas, toolbar, seleção).
- Implementar os **callbacks de GUI** (`receber_draw`/`receber_remove`/`receber_color`/`mostrar_erro`/`carregar_estado`) e ligá-los a `client.on_*`.
- **1.4** operações de quadro (`desenhar`/`remover`/`colorir` + lock) — ficam na fronteira
  GUI↔rede; B implementa a chamada e A garante o roteamento. **Parear** neste item.
- **Cenário 2** (concorrência/exclusão mútua) — exige interação de UI de dois clientes.
- Seção de "fluxo de uso / telas" do relatório.

### 🤝 Conjunto (parear)
- **1.4** (lock) e **Cenário 1** (entrada dinâmica) — tocam GUI e rede ao mesmo tempo.
- Smoke test fim-a-fim antes da entrega.

### Ordem sugerida (paralela)
1. **A** faz 1.1 → 1.2 → 1.3 (cliente já lista/entra e recebe broadcasts).
   **B** faz TelaInicial/TelaListaQuadros + canvas básico contra os callbacks.
2. **A** faz 1.6 (heartbeat/eleição); **B** finaliza toolbar/seleção + callbacks.
3. **Juntos:** 1.4 (lock) e 1.5/handoff; depois os 3 cenários + relatório.

| Frente | Responsável | Bloqueia? |
|---|---|---|
| `client.py` 1.1–1.3, 1.5, 1.6 | A | não (infra pronta) |
| `telas.py` + callbacks | B | não (contrato no esqueleto) |
| `client.py` 1.4 (lock) | A+B | depende de 1.3 |
| Cenários 1–3 + scripts | A+B | depende de tudo acima |
| Relatório | A (protocolo) + B (uso) | incremental |
