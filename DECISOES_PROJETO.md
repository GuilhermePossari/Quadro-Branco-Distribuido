# Decisões de Projeto — SDWB (Shared Distributed Write Board)

> Documento vivo. Registra **o que foi decidido, por quê, e como está implementado**
> até o momento. Serve tanto de guia para a dupla quanto de base para o relatório
> (que vale 10% da nota, exigindo "documentação dos protocolos de mensagens criados").

**Disciplina:** Sistemas Distribuídos — UEL
**Trabalho:** Quadro Branco Distribuído colaborativo, sem servidor fixo.
**Dupla:** Pessoa A (infraestrutura/coordenação) · Pessoa B (cliente/GUI).
**Linguagem:** Python 3 (apenas biblioteca padrão — `socket`, `threading`, `json`, `struct`, `tkinter`).

---

## 1. Visão geral da arquitetura

O sistema é composto por **três tipos de processo**, todos construídos sobre uma mesma
classe base de rede (`Node`):

| Processo | Papel | Quantidade | Endereço |
|---|---|---|---|
| **Serviço de Nomes** (`name_service.py`) | "Páginas Amarelas": guarda `(nome_quadro → ip, porta)` do coordenador de cada quadro | 1, fixo | IP/porta fixos (`0.0.0.0:5000`) |
| **Coordenador** (`coordinator.py`) | Gerencia o estado de **um** quadro: objetos, membros e travas. Repassa operações. | 1 por quadro | Roda na máquina de um dos clientes |
| **Cliente** (`client.py`) | Interface gráfica + lógica de rede. Qualquer cliente pode virar coordenador. | N por quadro | Cada um na sua máquina/porta |

### Modelo híbrido de comunicação

- **Cliente-servidor** para operações do quadro: cliente → coordenador → broadcast aos demais.
- **P2P** para heartbeat e eleição: nó fala direto com nó, sem passar pelo coordenador.

Essa divisão é deliberada: o coordenador é o ponto central da **consistência** (estado e
travas), mas a **detecção de falha** precisa funcionar mesmo quando o coordenador é justamente
quem caiu — por isso ela é descentralizada (anel).

---

## 2. Decisões de design e justificativas

### 2.1. Transporte: TCP sockets (não UDP, não gRPC)
- **Por quê:** O enunciado permite Sockets (TCP/UDP) ou gRPC. TCP dá entrega confiável e
  ordenada "de graça", o que simplifica a lógica de aplicação. gRPC traria dependência
  externa e complexidade de build desnecessárias para a escala da demo (3–5 nós).
- **Trade-off aceito:** abrir/fechar conexões tem custo, mas é irrelevante nesta escala.

### 2.2. Serialização: JSON + framing de 4 bytes (length-prefix)
- **Problema:** TCP é um *stream* de bytes — sem delimitação, não há como saber onde uma
  mensagem termina e a próxima começa.
- **Solução:** cada mensagem é prefixada por 4 bytes big-endian (`struct.pack('>I', len)`)
  com o tamanho do payload JSON. O receptor lê primeiro os 4 bytes, depois exatamente
  esse número de bytes (`protocol._recv_exato`).
- JSON foi escolhido por ser legível (facilita depuração e o relatório) e nativo em Python.

### 2.3. Conexão por mensagem (não persistente)
- Cada interação = abrir socket → enviar → receber resposta → fechar.
- **Por quê:** elimina o gerenciamento de pools de conexões e estados de socket meio-abertos.
  Suficiente para a escala da demo.
- **Trade-off:** mais syscalls; aceitável aqui.

### 2.4. Identificador de nó: `"ip:porta"`
- Todo nó é identificado pela string `node_id = f"{ip}:{port}"` (definido em `Node.__init__`).
- Usado de forma uniforme em heartbeat, eleição, travas e remetente de operações.

### 2.5. Heartbeat **em anel** (não centralizado nem todos-para-todos)
- **Decisão central do projeto.** O anel é a lista de todos os nós (coordenador incluído),
  ordenada por `(ip, porta)`. Cada nó pinga **apenas o próximo** no anel.
- **Por que anel:** um único mecanismo resolve os **dois** casos de falha exigidos pelo
  enunciado:
  - queda de um **membro comum** → seu antecessor no anel detecta e avisa o coordenador;
  - queda do **coordenador** → seu antecessor no anel detecta e dispara eleição.
  Como o coordenador também está no anel, ele é monitorado igual a qualquer outro nó.
- **Determinismo:** `construir_anel()` é uma função pura ordenada — qualquer nó que a chame
  com os mesmos dados obtém exatamente o mesmo anel, então todos concordam sobre "quem pinga quem".
- **Trade-off:** entrada/saída de nós exige reorganizar o anel (via `RING_UPDATE`); em escala
  pequena é gerenciável.

### 2.6. Eleição: Algoritmo do Valentão (Bully)
- **Critério de vitória:** maior `(ip, porta)` vence. Em rede local com IP compartilhado, a
  **porta** desempata (cliente de porta mais alta vence).
- **Fluxo:** nó detecta queda → envia `ELECTION` a todos com ID maior → se ninguém responder
  `ELECTION_OK`, ele vence e anuncia `COORDINATOR`; se alguém responder, aguarda o `COORDINATOR`
  desse superior (com timeout e reinício se não chegar).
- **Recuperação de estado:** o vencedor sobe um `Coordinator` usando o último estado conhecido
  (objetos + membros) que mantinha localmente, atende ao requisito "novo coordenador recupera
  a lista de integrantes".
- Atende explicitamente o enunciado, que cita o "Algoritmo do Valentão" como exemplo.

### 2.7. Exclusão mútua: trava adquirida na SELEÇÃO (lock por objeto no coordenador)
- O coordenador mantém `_locks = { object_id → node_id }`.
- **A trava é adquirida no momento da SELEÇÃO**, não no momento da operação — é o que o
  enunciado §3A descreve ("selecionar objeto e selecionar operação, nessa sequência...
  se o mesmo objeto foi selecionado por outro cliente, enviar mensagem de erro ao segundo").
  - `client.selecionar(oid)` → `LOCK_REQUEST`. Se o objeto já está travado por outro nó,
    `LOCK_RESPONSE(granted=False)` → a GUI mostra **"Seleção negada"** e o objeto **não** é
    selecionado pelo segundo cliente.
  - `client.desselecionar(oid)` → `LOCK_RELEASE`. A trava é solta quando o nó **deixa de
    selecionar**: clica em outro objeto, clica no vazio, troca de ferramenta ou sai do quadro.
- **Consequência:** enquanto um nó mantém um objeto selecionado, nenhum outro consegue
  selecioná-lo — e, como só se opera sobre o objeto selecionado, ninguém mais consegue
  **colori-lo nem removê-lo**. `COLOR`/`REMOVE` apenas operam sobre o objeto já travado por
  este nó (não re-adquirem trava). `REMOVE` faz o coordenador liberar a trava automaticamente
  (o objeto deixa de existir); após `COLOR` a trava permanece (o objeto segue selecionado).
- **Histórico:** numa versão anterior a trava era transitória, só em volta de cada operação
  (`LOCK_REQUEST` → opera → `LOCK_RELEASE`). Foi movida para a seleção para refletir o §3A —
  o erro de concorrência aparece já na seleção do segundo cliente.
- Travas de um membro são liberadas automaticamente quando ele sai ou cai
  (`coordinator._remover_membro_interno`). Em handoff/eleição as travas não são transferidas
  (o novo coordenador começa sem travas), o que é seguro: o nó que as detinha está saindo.
- `DRAW` não usa trava (qualquer um desenha).

### 2.8. **Fora de escopo: 2PC (Two-Phase Commit)**
- A seção 3B do enunciado original (transações atômicas via 2PC) foi **removida pelo professor**.
- Consequentemente, **não há 2PC** no projeto. A concorrência de cor/remoção é resolvida
  apenas pela exclusão mútua por objeto (2.7).
- ⚠️ Nota: a **tabela de critérios de avaliação** do enunciado ainda lista "Transações (2PC) —
  25%". Isso é inconsistente com a remoção da seção 3B; **confirmar com o professor** se esse
  peso foi redistribuído.

### 2.9. Regras de negócio do ciclo de vida (anotações de aula)
- Cliente que é coordenador **sai voluntariamente** → coordenador **continua na mesma máquina**,
  sem eleição (a saída é controlada, não uma falha).
- Máquina do coordenador **cai/desliga** → **dispara eleição**.
- Coordenador **sozinho** no quadro sai/cai → o quadro é **encerrado** (desregistra do SN via
  `UNREGISTER`).
- Pode haver **múltiplos quadros simultâneos**, cada um com seu coordenador registrado no SN.

### 2.10. "Sair do quadro" e coordenador persistente — uma sessão por quadro
- **Requisito:** a tela do quadro tem um botão **"Sair do quadro"** que volta à tela
  inicial. Regra de negócio pedida: o nó **só deixa de ser coordenador quando o
  processo é encerrado** — ao voltar para a tela inicial, um coordenador **continua
  hospedando** o quadro; e pode inclusive **criar/ingressar em outro quadro** sem
  largar o original.
- **Decisão:** modelar **uma sessão `Client` por quadro**, cada uma com seu próprio
  servidor TCP/porta. Um processo pode manter N sessões: a de **primeiro plano**
  (refletida na tela atual) e as de **segundo plano** (quadros que ele continua
  coordenando). Porta extra obtida via `client.porta_livre()` (bind em `:0`).
- **Por que sessão-por-porta (e não discriminador de quadro no protocolo):** o
  protocolo está **congelado** e as mensagens **não carregam o nome do quadro**; o SN
  mapeia `nome → (ip, porta)`. Dar a cada quadro uma porta própria faz o protocolo
  mono-quadro existente funcionar **sem nenhuma alteração na infra testada** — menor
  risco. A alternativa (campo `board` em JOIN/DRAW/REMOVE/COLOR/LOCK_*/RING_UPDATE/
  ELECTION/COORDINATOR) reescreveria o protocolo e o `coordinator.py`.
- **Comportamento do botão (em `Client.sair_do_quadro()` + `App`):**
  - **Cliente comum** → sai de fato: `LEAVE` ao coordenador, `heartbeat.parar()` e
    reset ao "lobby". A **mesma sessão/porta é reaproveitada**. Retorna `True`.
  - **Coordenador** → **não** abre mão do papel: a sessão segue ativa (servidor,
    delegate, heartbeat, eleição) **em segundo plano**; a `App` move-a para
    `self._fundo`, **desliga seus callbacks de GUI** (o estado interno continua
    atualizando, só não toca a tela) e abre uma **nova sessão de primeiro plano**
    (`App._nova_sessao()`) para o lobby. Retorna `False`.
- **Encerramento do programa** = único momento em que o papel é cedido: `App._ao_fechar`
  chama `sair()` em **todas** as sessões (primeiro plano + fundo), disparando o
  handoff/eleição já existente (D6, §2.6). Coerente com "passa para outro nó".
- **Isolamento entre quadros:** como cada sessão tem porta própria, broadcasts/heartbeats
  de um quadro nunca chegam ao handler de outro — sem vazamento de estado. Custo: um
  servidor TCP por quadro hospedado; irrelevante na escala da demo.
- **Infra tocada:** **nenhuma.** Só foram *adicionados* `porta_livre()` e
  `sair_do_quadro()`/`_resetar_para_lobby()` em `client.py` e o multiplexador de
  sessões na `App` (`telas.py`). Coberto por `scripts/teste_multiquadro.py`.

---

## 3. Protocolo de mensagens

Todas as mensagens são dicts JSON com a chave `"type"`. Os construtores ficam em `protocol.py`
— **nunca montar dicts na mão** em outros arquivos.

### Framing
`encode(msg)` → `struct.pack('>I', len) + payload_utf8`. `decode(sock)` lê o cabeçalho de 4
bytes e o payload exato. Ambos retornam `None` se a conexão fechar.

### Catálogo de tipos

| Categoria | Tipo | Construtor | Campos principais |
|---|---|---|---|
| **Serviço de Nomes** | `REGISTER` | `make_register(name, ip, port)` | quadro registra/atualiza endereço |
| | `UNREGISTER` | `make_unregister(name)` | quadro encerrado |
| | `LIST` | `make_list()` | cliente pede lista de quadros |
| | `LIST_RESPONSE` | `make_list_response(boards)` | `boards: [{name, ip, port}]` |
| **Onboarding** | `JOIN` | `make_join(ip, port)` | cliente pede para entrar |
| | `STATE` | `make_state(objects, members)` | estado completo enviado ao novo cliente |
| **Operações** | `DRAW` | `make_draw(obj, sender_id)` | `obj = {id, shape, points, color}` |
| | `REMOVE` | `make_remove(object_id, sender_id)` | |
| | `COLOR` | `make_color(object_id, color, sender_id)` | |
| **Exclusão mútua** | `LOCK_REQUEST` | `make_lock_request(object_id, node_id)` | |
| | `LOCK_RESPONSE` | `make_lock_response(object_id, granted, reason)` | |
| | `LOCK_RELEASE` | `make_lock_release(object_id)` | |
| **Heartbeat** | `HEARTBEAT` | `make_heartbeat(node_id)` | ping ao vizinho |
| | `HEARTBEAT_OK` | `make_heartbeat_ok(node_id)` | resposta |
| **Eleição (Bully)** | `ELECTION` | `make_election(candidate_id)` | |
| | `ELECTION_OK` | `make_election_ok()` | superior responde que está vivo |
| | `COORDINATOR` | `make_coordinator(ip, port)` | vencedor se anuncia |
| **Anel** | `RING_UPDATE` | `make_ring_update(members)` | anel completo já ordenado |
| **Saída** | `LEAVE` | `make_leave(node_id)` | saída voluntária |
| **Utilitários** | `OK` / `ERROR` | `make_ok()` / `make_error(reason)` | |

### Convenções importantes
- `sender_id` (em `DRAW`/`REMOVE`/`COLOR`): `"ip:porta"` do autor, para o coordenador **não
  reenviar a operação de volta a quem a originou** (evita eco).
- `node_id` em `LOCK_REQUEST`: identifica o dono da trava.
- O **formato de um objeto** do quadro é fixo: `{"id": str, "shape": "line"|"square",
  "points": [[x,y],[x,y]], "color": str}`.

---

## 4. Estado atual da implementação

### ✅ Pronto, testado e funcionando (Pessoa A)

| Arquivo | Conteúdo |
|---|---|
| `protocol.py` | Contrato de mensagens + framing. Compartilhado por A e B. |
| `node.py` | Classe base `Node`: servidor TCP (thread por conexão, accept com timeout de 1s para checar `_running`), `send` (com resposta, retorna `None` em falha), `send_sem_resposta` (fire-and-forget para broadcast). `handle_message` é sobrescrito pelas subclasses. |
| `name_service.py` | Processo independente, IP/porta fixos. Dict `{nome → {ip, port}}`. Trata `REGISTER`/`UNREGISTER`/`LIST`. Thread por conexão. CLI `--host/--port`. |
| `coordinator.py` | `Coordinator(Node)`. `start(initial_objects, initial_members)` sobe servidor e registra no SN (aceita estado inicial para o caso pós-eleição). Trata `JOIN`, `DRAW`/`REMOVE`/`COLOR`, `LOCK_REQUEST`/`LOCK_RELEASE`, `LEAVE`, `HEARTBEAT`. `remover_membro()` (chamado pelo heartbeat), `get_state()` (para a eleição). Estado protegido por `_state_lock`. Encerra o quadro quando fica com 0 membros. |
| `heartbeat.py` | `construir_anel()` (pura, ordenada) + classe `Heartbeat`. Pinga o próximo no anel a cada `intervalo` (2s), timeout `2*intervalo`. Callbacks `on_membro_falhou` / `on_coordenador_falhou`. `atualizar_anel()`, `atualizar_coordenador()`, `parar()`. |
| `election.py` | `Election` (Bully). `iniciar()` (idempotente via flag `_em_eleicao`), handlers `tratar_election`/`tratar_coordinator`, callbacks `on_tornou_coordenador`/`on_novo_coordenador`. Timeouts ajustáveis (`timeout_ok=3s`, `timeout_coord=6s`). |

### ❌ A fazer (responsabilidade de Pessoa B, A pode apoiar)

| Arquivo | Estado |
|---|---|
| `client.py` | **Não iniciado.** Lógica de rede do cliente (`Client(Node)`): conectar ao SN, listar/criar/ingressar em quadro, receber `STATE`, rotear operações para a GUI via `master.after(0, ...)`, fluxo de lock antes de colorir/remover, integrar `Heartbeat` e `Election`, virar coordenador ao vencer eleição. |
| `telas.py` | **Esqueleto criado** (`TelaInicial`, `TelaListaQuadros`, `TelaQuadro`). Faltam: passar a referência `client` entre telas; prompt de nome ao criar quadro; canvas + toolbar (linha, quadrado, 2 cores, remover, selecionar); captura de cliques; seleção visual; método `receber_draw()` thread-safe. |

> Estimativa: infraestrutura difícil (heartbeat em anel + Bully + exclusão mútua) está pronta.
> Resta majoritariamente `client.py` + GUI + integração e testes dos 3 cenários.

---

## 5. Cobertura dos requisitos do enunciado

| Requisito | Como é atendido | Status |
|---|---|---|
| Serviço de Nomes (descoberta sem IP hardcoded) | `name_service.py`; coordenador faz `REGISTER`, cliente faz `LIST` | ✅ infra pronta |
| Entrada dinâmica + sincronização de estado | `JOIN` → coordenador responde `STATE` com todos os objetos | ✅ no coordenador / falta cliente |
| Coordenador armazena membros e repassa ações | `_members` + broadcast em `DRAW`/`REMOVE`/`COLOR` | ✅ |
| Exclusão mútua (cor/remoção) | trava por objeto adquirida na **seleção** via `LOCK_REQUEST`/`RESPONSE`/`RELEASE` (§2.7) | ✅ coordenador + UI |
| Detecção de falha + eleição | heartbeat em anel + Bully; vencedor atualiza o SN | ✅ infra pronta |
| Recuperação do coordenador (recupera membros) | vencedor sobe `Coordinator` com `get_state()` local | ✅ infra pronta |
| Resiliência do SN | processo isolado, fixo, sem dependência dos demais | ✅ |
| Comunicação por Sockets, sem middleware pronto | TCP puro + lógica própria de eleição/consenso | ✅ |
| ~~Transações 2PC~~ | **removido do escopo pelo professor** | ➖ N/A |

### Cenários de demonstração obrigatórios
1. **Entrada dinâmica** — subir SN → coordenador → 3 clientes descobrindo o quadro.
2. **Concorrência** — dois clientes operam o mesmo objeto; exclusão mútua ordena/recusa.
3. **Morte do coordenador** — matar o processo; anel detecta, Bully elege novo, SN atualizado.

---

## 6. Pontos em aberto / a confirmar

1. **Peso de "Transações (2PC)" na avaliação** — a seção 3B foi removida, mas a tabela de
   critérios ainda atribui 25% a 2PC. Confirmar redistribuição com o professor.
2. **`client.py` + `telas.py`** — maior bloco restante; integração com a infra já pronta.
3. **Relatório final (10%)** — este documento + o catálogo de protocolo da seção 3 já cobrem
   boa parte da exigência de "documentação dos protocolos de mensagens".
