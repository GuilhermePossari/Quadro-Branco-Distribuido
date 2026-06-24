# Contexto do Projeto SDWB — para continuar no Claude Code

## Sobre o projeto

**SDWB (Shared Distributed Write Board)** — trabalho final da disciplina de Sistemas Distribuídos.
Quadro branco colaborativo onde múltiplos terminais desenham em tempo real.
Sem servidor fixo: usa Serviço de Nomes para descoberta e Coordenador Migrante (eleição via Bully).

**Linguagem:** Python 3, stdlib apenas (proibido Zookeeper/Etcd/frameworks externos).
**Comunicação:** TCP sockets, JSON com framing de 4 bytes (length-prefix).
**Dupla:** Eu sou **Pessoa A** (infraestrutura e coordenação). Parceiro é **Pessoa B** (cliente/GUI).

> **Nota:** o enunciado original tinha uma seção 3B sobre Two-Phase Commit (2PC) para
> transações atômicas. **Essa seção foi removida pelo professor.** O escopo atual NÃO inclui 2PC.

---

## Arquitetura

3 tipos de processo, todos rodando a mesma classe base `Node` (servidor TCP + cliente TCP):

- **Serviço de Nomes** — IP/porta fixos, nunca falha, guarda só `(nome_quadro → ip, porta)` dos coordenadores.
- **Coordenador** — roda na máquina de um dos clientes (não é hardware dedicado). Gerencia estado do quadro (objetos + membros), repassa operações, gerencia travas (exclusão mútua).
- **Cliente** — interface gráfica (tkinter) + lógica de rede. Todo cliente pode virar Coordenador via eleição.

**Modelo híbrido:** cliente-servidor para operações do quadro (cliente → coordenador → broadcast),
P2P para heartbeat e eleição (nó fala direto com nó, sem passar pelo coordenador).

**Conexão por mensagem** (não persistente) — abre socket, manda, recebe resposta, fecha. Suficiente pra escala da demo (3-5 nós).

### Regras de negócio importantes (das anotações de aula)
- Cliente do Coordenador **sai voluntariamente** → Coordenador continua na mesma máquina, sem eleição.
- Máquina do Coordenador **cai/desliga** → dispara eleição.
- Coordenador sozinho no quadro e sai/cai → quadro é encerrado (desregistra do SN).
- Pode haver **múltiplos quadros** simultâneos, cada um com seu Coordenador próprio no SN.
- Heartbeat escolhido: **em anel** (não centralizado, não distribuído todos-para-todos) — um único mecanismo detecta queda de membro comum E queda do coordenador, porque o vizinho de qualquer nó (inclusive o coordenador) detecta sua ausência.

---

## Decisões de design já tomadas e justificadas

1. **TCP socket** (não UDP, não gRPC) — mais direto para sockets manuais em Python.
2. **JSON + framing de 4 bytes** — resolve delimitação de mensagens em stream TCP.
3. **Heartbeat em anel** — único mecanismo resolve os dois casos de falha (membro comum / coordenador). Trade-off: manutenção do anel (entrada/saída) exige reorganização, mas em escala pequena é gerenciável.
4. **Bully Algorithm** para eleição — nó com maior `(ip, porta)` vence. Em rede local com mesmo IP, a porta desempata.
5. **Sem 2PC** — removido do escopo. Exclusão mútua simples (lock por objeto) resolve concorrência de cor/remoção.

---

## Estado atual do código (todos testados e funcionando)

Todos os arquivos abaixo estão completos, testados com scripts de integração (múltiplos cenários cada) e prontos:

### `protocol.py` ✅
Contrato de mensagens compartilhado entre A e B. Contém:
- Constantes de tipo: `REGISTER`, `UNREGISTER`, `LIST`, `LIST_RESPONSE`, `JOIN`, `STATE`, `DRAW`, `REMOVE`, `COLOR`, `LOCK_REQUEST`, `LOCK_RESPONSE`, `LOCK_RELEASE`, `HEARTBEAT`, `HEARTBEAT_OK`, `ELECTION`, `ELECTION_OK`, `COORDINATOR`, `RING_UPDATE`, `LEAVE`, `OK`, `ERROR`.
- `encode(msg)` / `decode(sock)` — serialização com framing de 4 bytes (`struct.pack('>I', len)`).
- Funções `make_*()` para cada tipo de mensagem (ex: `make_join(ip, port)`, `make_draw(obj, sender_id)`, `make_lock_request(object_id, node_id)`).
- **Importante:** `make_draw`, `make_remove`, `make_color` recebem `sender_id` (para o coordinator não repassar a mensagem de volta a quem enviou). `make_lock_request` recebe `node_id` do solicitante.

### `name_service.py` ✅
Processo separado, IP/porta fixos (padrão `0.0.0.0:5000`). Dict em memória `{nome: {ip, port}}`. Trata `REGISTER`, `UNREGISTER`, `LIST`. Thread por conexão.

### `node.py` ✅
Classe base `Node(host, port)`. Toda subclasse herda:
- `start_server()` — abre socket TCP, thread de accept loop com timeout de 1s (para checar `_running`).
- `handle_message(msg, addr)` — **deve ser sobrescrito pela subclasse**. Retorna dict de resposta ou `None`.
- `send(ip, port, msg, timeout=5)` — conecta, envia, espera resposta, fecha. Retorna `None` se falhar (nó fora do ar) — **chamador sempre deve checar `None`**.
- `send_sem_resposta(...)` — fire-and-forget, usado em broadcasts.
- `node_id` = `"ip:porta"`, usado como identificador em todo o sistema.

### `coordinator.py` ✅
Classe `Coordinator(board_name, host, port, ns_host, ns_port)`, herda `Node`.
- `start(initial_objects=None, initial_members=None)` — sobe servidor, registra no SN. Aceita estado inicial para o caso pós-eleição.
- Trata: `JOIN` (onboarding, envia STATE + avisa RING_UPDATE), `DRAW`/`REMOVE`/`COLOR` (atualiza estado + broadcast para outros membros, exclui o `sender_id`), `LOCK_REQUEST`/`LOCK_RELEASE` (exclusão mútua via dict `{object_id: node_id}`), `LEAVE` (saída voluntária), `HEARTBEAT` (responde OK).
- `remover_membro(ip, port)` — API pública chamada pelo heartbeat quando detecta falha. Libera travas do membro, broadcast RING_UPDATE, e se ficar 0 membros desregistra do SN e encerra.
- `get_state()` — retorna `{"objects": [...], "members": [...]}`, usado pela eleição para transferir estado ao vencedor.
- Internamente usa `_state_lock` (threading.Lock) protegendo `_objects`, `_members`, `_locks`.

### `heartbeat.py` ✅
- `construir_anel(members, coord_ip, coord_port)` — função pura, produz lista ordenada `sorted by (ip, port)` incluindo o coordenador. Todo nó que chamar com os mesmos dados chega no mesmo anel.
- Classe `Heartbeat(own_ip, own_port, intervalo=2.0)`:
  - `iniciar(send_fn, ring, coord_ip, coord_port)` — injeta `Node.send`, começa loop em thread.
  - Pinga o **próximo nó no anel** a cada `intervalo` segundos, timeout de `2*intervalo`.
  - Callbacks: `on_membro_falhou(ip, port)` e `on_coordenador_falhou()` — setar antes de `iniciar()`.
  - `atualizar_anel(novo_ring)` — chamar ao receber `RING_UPDATE`.
  - `atualizar_coordenador(ip, port)` — chamar quando eleição terminar (evita pingar coordenador morto).
  - `parar()` — para o loop (usado em saída voluntária).

### `election.py` ✅
Classe `Election(own_ip, own_port)` — Algoritmo do Valentão.
- `configurar(send_fn, members)` — injeta dependências.
- `iniciar()` — dispara eleição (thread-safe, chamadas duplicadas são ignoradas via `_em_eleicao` flag).
  - Sem nós superiores → vence imediatamente.
  - Envia `ELECTION` para todos com ID maior em paralelo, espera `ELECTION_OK` (timeout `timeout_ok=3.0s`).
  - Se nenhum responder → vence.
  - Se algum responder OK → espera `COORDINATOR` (timeout `timeout_coord=6.0s`). Se não chegar, reinicia eleição.
- `tratar_election(msg)` / `tratar_coordinator(msg)` — handlers a integrar no `handle_message` da subclasse.
- Callbacks: `on_tornou_coordenador()` e `on_novo_coordenador(ip, port)`.
- Comparação de ID: tupla `(ip, port)` — maior vence.

---

## O que falta — `client.py` (responsabilidade de Pessoa B, mas pode precisar de ajuda)

**Não implementado ainda.** É o maior bloco restante, ~45% do código total do projeto por volume.

### Parte 1 — Lógica de rede (`Client` herda `Node`)
- Conecta no SN, lista quadros (`LIST`/`LIST_RESPONSE`), permite criar (`REGISTER` direto, sobe `Coordinator` local) ou ingressar (`JOIN` no coordinator escolhido).
- Recebe `STATE` no JOIN, popula estado local.
- `handle_message` deve rotear: `DRAW`/`REMOVE`/`COLOR` (atualiza UI via `master.after(0, ...)` — thread-safety obrigatória), `HEARTBEAT` (responde OK), `RING_UPDATE` (chama `heartbeat.atualizar_anel`), `ELECTION`/`COORDINATOR` (delega para `Election`).
- Antes de colorir/remover: `LOCK_REQUEST` → se negado, mostra erro na UI; se concedido, faz a operação e `LOCK_RELEASE`.
- Ao vencer eleição (`on_tornou_coordenador`): instancia `Coordinator` com `get_state()` que tinha guardado localmente, chama `.start(initial_objects=..., initial_members=...)`.
- Ao sair: envia `LEAVE`, chama `heartbeat.parar()`.

### Parte 2 — Interface gráfica (tkinter)
Parceiro já começou em `telas.py` (enviado para revisão). Estrutura: `TelaInicial`, `TelaListaQuadros`, `TelaQuadro` (cada uma `tk.Frame`).

**Problemas identificados no `telas.py` atual (ainda não corrigidos):**
1. Telas não recebem referência ao objeto `Client` — estão desconectadas da rede. Precisa passar `client` no `__init__` de cada tela e propagar nas transições (`TelaQuadro(self.master, self.client)`).
2. "Criar Novo Quadro" pula direto para o canvas sem pedir nome — precisa de `simpledialog.askstring(...)` antes de criar.

**`TelaQuadro` ainda precisa:**
- Canvas (`tk.Canvas`) + toolbar com botões: Linha, Quadrado, 2 cores, Remover, Selecionar.
- Captura de cliques no canvas (`<Button-1>`) para marcar pontos (linha/quadrado = 2 pontos cada).
- Seleção de objeto por clique antes de colorir/remover (com feedback visual).
- Estado local: `self.objetos = {}`, `self.selecionado`, `self.pontos_temp`, `self.ferramenta`.
- Método `receber_draw(obj)` chamado pela thread de rede via `master.after(0, ...)` para atualizar canvas sem violar thread-safety do tkinter.

**`TelaListaQuadros` precisa:**
- Buscar lista do SN via `client.send(...)` com `make_list()`.
- Mostrar em `Listbox` ou botões, permitir seleção e `JOIN`.

---

## Estrutura de arquivos final

```
sdwb/
├── name_service.py    ✅ completo
├── coordinator.py     ✅ completo
├── client.py          ❌ não iniciado
├── telas.py            🟡 esqueleto criado por Pessoa B, precisa integração + canvas
├── node.py             ✅ completo
├── protocol.py         ✅ completo
├── election.py         ✅ completo
└── heartbeat.py         ✅ completo
```

---

## Estimativa de conclusão

~45% do código pronto por volume, mas a infraestrutura mais difícil (heartbeat em anel + eleição Bully + exclusão mútua) já está implementada e testada. Falta majoritariamente `client.py` + integração da GUI.

| Tarefa restante | Estimativa |
|---|---|
| `client.py` — lógica de rede | 4-6h |
| `telas.py` / GUI — canvas, toolbar, seleção | 4-6h |
| Integração + testes dos 3 cenários obrigatórios | 3-4h |
| Documentação do protocolo (10% da nota) | 1-2h |

### Os 3 cenários obrigatórios de demonstração
1. **Entrada dinâmica** — SN sobe, depois Coordenador, depois 3 clientes entrando e descobrindo o quadro.
2. **Concorrência** — dois usuários tentam selecionar/operar o mesmo objeto ao mesmo tempo; exclusão mútua deve ordenar.
3. **Morte do Coordenador** — matar o processo; heartbeat em anel detecta, eleição Bully ocorre, novo Coordenador assume e atualiza o SN.

---

## Próximo passo sugerido
Construir `client.py` integrando os módulos já prontos (`node.py`, `heartbeat.py`, `election.py`, `protocol.py`) com a GUI de `telas.py`, corrigindo primeiro os dois problemas identificados nela (referência ao client ausente, falta do prompt de nome ao criar quadro).
