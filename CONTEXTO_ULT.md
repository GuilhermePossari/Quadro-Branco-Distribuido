# CONTEXTO_ULT — Quadro Branco Distribuído (SDWB)

> Documento de contexto consolidando o **trabalho** e o **histórico da última sessão de
> desenvolvimento**. Serve de retomada rápida (para a dupla e para o relatório) do que o
> sistema faz, do que foi implementado por último, de como testar (local e entre máquinas)
> e do estado do git.
>
> Complementa — não substitui — o `DECISOES_PROJETO.md` (decisões + protocolo) e o
> `PLANCONI.md` (plano de conclusão).

---

## 1. O que é o projeto

**Shared Distributed Write Board (SDWB)** — disciplina de **Sistemas Distribuídos / UEL**.
Quadro branco colaborativo em tempo real, **sem servidor fixo**, em **Python puro** (só
biblioteca padrão: `socket`, `threading`, `json`, `struct`, `tkinter`).

Três tipos de processo, todos sobre a classe base `Node`:

| Processo | Arquivo | Papel |
|---|---|---|
| **Serviço de Nomes** | `name_service.py` | "Páginas Amarelas": tabela `nome → (ip, porta)` do coordenador. Processo fixo (`0.0.0.0:5000`). |
| **Coordenador** | `coordinator.py` | Gerencia o estado de **um** quadro (objetos, membros, travas) e repassa operações. É **migrante** (roda na máquina de um cliente). |
| **Cliente** | `client.py` + `telas.py` + `main.py` | GUI tkinter + lógica de rede. Qualquer cliente pode virar coordenador. |

**Pilares implementados:** descoberta via SN (sem IP hardcoded), onboarding com
sincronização de estado (`JOIN` → `STATE`), **heartbeat em anel**, **eleição Bully**,
**exclusão mútua por objeto**, comunicação **TCP puro + framing de 4 bytes + JSON**
(`protocol.py`). **2PC foi removido do escopo pelo professor.**

> Filosofia do projeto: a **infra é congelada** (`protocol`, `node`, `coordinator`,
> `heartbeat`, `election`). Mudanças novas evitam tocá-la — o que guiou as decisões abaixo.

---

## 2. O que foi implementado na última sessão

### 2.1. Botão "Sair do quadro" + múltiplos quadros por processo
- Botão na `TelaQuadro` que volta à tela inicial.
- **Cliente comum** → sai de fato (`LEAVE` + para heartbeat), a sessão volta ao "lobby".
- **Coordenador** → **não** abre mão do papel: continua hospedando o quadro **em segundo
  plano**; a GUI abre uma **nova sessão** (nova porta via `porta_livre()`) para o primeiro
  plano. Pode até criar/ingressar em outro quadro sem largar o original.
- O papel de coordenador só é cedido quando o **processo fecha** (`App._ao_fechar` chama
  `sair()` em todas as sessões → handoff/eleição).
- **Abordagem:** **uma sessão `Client` por quadro**, cada uma com seu servidor/porta. Mantém
  o protocolo congelado (cada porta hospeda exatamente um quadro). Detalhes em
  `DECISOES_PROJETO.md` **§2.10**.
- Adicionados: `porta_livre()`, `sair_do_quadro()`, `_resetar_para_lobby()` em `client.py`;
  multiplexador de sessões na `App` (`telas.py`).

### 2.2. Exclusão mútua na SELEÇÃO + cores marrom/verde
- A trava do objeto agora é adquirida **ao selecionar** (não mais só ao colorir/remover) —
  é o que o enunciado §3A pede: o segundo cliente que tentar selecionar o mesmo objeto
  recebe **"Seleção negada"**. A trava é liberada ao trocar de objeto/ferramenta ou sair.
- `client.py`: novos `selecionar()` / `desselecionar()` (envolvem `LOCK_REQUEST`/`RELEASE`);
  `colorir()`/`remover()` deixaram de travar (operam sobre o objeto já travado).
- Cores trocadas: `COR_A = "#8b4513"` (marrom), `COR_B = "#2ca02c"` (verde) em `telas.py`.
- Detalhes em `DECISOES_PROJETO.md` **§2.7** (reescrita) e **§5**.

### 2.3. Correção de quadros órfãos no Serviço de Nomes
**Sintoma observado:** um quadro ficava **registrado no SN apontando para um coordenador
inexistente** — aparecia na lista de "Ingressar" mas o JOIN dava **"coordenador não
disponível"**. (No caso real, o papel havia migrado por handoff até cair numa sessão de
porta aleatória da feature multi-quadro; ao fechar tudo, ninguém assumiu de fato.)

Duas frentes (ambas implementadas):
- **Fix A — poda no `LIST` (`name_service.py`):** antes de responder o `LIST`, o SN faz um
  *probe* paralelo (`connect` + `HEARTBEAT`, ~1s) em cada coordenador e **remove os que não
  respondem**. Cobre handoff perdido **e** crash (kill -9). Remoção condicional ao endereço
  ainda registrado (não apaga quadro re-registrado após eleição). Torna o SN levemente
  ativo (decisão consciente).
- **Fix B — handoff confirmado (`client.py::sair`):** ao sair como coordenador, tenta os
  sucessores do maior para o menor `ip:porta`; só transfere se o sucessor **responder**.
  Se **nenhum** sucessor vivo responder, **desregistra** o quadro em vez de orfanar.
- Detalhes em `DECISOES_PROJETO.md` **§2.11**.

---

## 3. Mapa de arquivos

```
name_service.py   Serviço de Nomes. + Fix A (probe de vivacidade no LIST).
node.py           Classe base Node (servidor TCP + send/recv). CONGELADO.
protocol.py       Mensagens + framing. CONGELADO.
coordinator.py    Coordinator(Node): motor de estado + broadcast. CONGELADO.
heartbeat.py      Heartbeat em anel (construir_anel + classe). CONGELADO.
election.py       Election (Bully). CONGELADO.
client.py         Lógica de rede do cliente. + porta_livre, sair_do_quadro,
                  selecionar/desselecionar, Fix B no sair().
telas.py          GUI tkinter. App multi-sessão, botão "Sair do quadro",
                  seleção com trava, cores marrom/verde.
main.py           Entrada: python main.py [porta] [ip] [--ns IP:PORTA].

scripts/
  _comum.py             Infra de teste (sobe SN + clientes com timeouts curtos).
  teste_cenario_1_2.py  Entrada dinâmica + concorrência/exclusão mútua.
  teste_cenario_3.py    Morte do coordenador → Bully → recuperação.
  teste_multiquadro.py  Múltiplos quadros + "Sair do quadro".
  teste_orfaos.py       Fix A (poda no LIST) + Fix B (handoff/desregistro).
  teste_gui.py          Smoke test GUI ↔ rede (exclusão mútua na seleção).

Docs: DECISOES_PROJETO.md, PLANCONI.md, PLANO_IMPLEMENTACAO.md,
      contexto_SDWB.md, Trabalho_2026_SD_SharedWriteBoard.md, este CONTEXTO_ULT.md.
```

---

## 4. Como testar

### 4.1. Testes automatizados (rápido, sem GUI)
Da raiz, com a porta 5000 **livre** (sem SN antigo rodando):
```bash
source .venv/bin/activate
python scripts/teste_orfaos.py
python scripts/teste_cenario_1_2.py
python scripts/teste_cenario_3.py
python scripts/teste_multiquadro.py
python scripts/teste_gui.py        # precisa de display (WSLg/X)
```
Estado: **os 5 passam**. Cada teste sobe seu próprio SN numa thread; se sobrar um
`name_service.py` standalone na 5000, ele "vence" o bind e os testes colidem com o estado
antigo — encerre-o antes (`pkill -f name_service.py` ou `lsof -i:5000`).

### 4.2. Demo local interativa (1 máquina, vários terminais)
```bash
# Terminal 1 — SN
python name_service.py
# Terminais 2,3,... — clientes (passe 127.0.0.1 p/ manter tudo local)
python main.py 6001 127.0.0.1
python main.py 6002 127.0.0.1
```

### 4.3. Demo entre máquinas: Ubuntu ↔ WSL via **Tailscale**
O WSL2 fica atrás de NAT (IP `172.x` não alcançável de fora). A **Tailscale** dá a cada
máquina um IP `100.x` diretamente alcançável, contornando isso (e o isolamento de Wi-Fi de
campus). Os dois devem estar **na mesma tailnet** (mesma conta).

**Tailnet usada nesta sessão** (conta `langossaripeerrilherme@gmail.com`):

| Máquina | Papel | IP Tailscale |
|---|---|---|
| `guilherme-possari-ideapad...` | Ubuntu (você) | `100.90.10.11` |
| `delldorafa` | WSL (amigo) | `100.110.113.124` |

> Os IPs podem mudar se trocar de conta/tailnet — confira sempre com `tailscale ip -4` e
> `tailscale status` (deve listar as duas máquinas). O `tailscale ping <ip>` confirma a rota.

**Regras de ouro:**
- Cada nó **deve** passar o próprio IP Tailscale como `ip_proprio` (não deixe autodetectar,
  senão o WSL anuncia o `172.x` interno e ninguém o alcança).
- O `--ns` aponta para o IP Tailscale de **quem roda o SN** (pode ser qualquer das duas;
  só não pode desligar/`wsl --shutdown` no meio).
- Atualizem o código nas duas antes: `git pull origin main`.

**Setup com SN no Ubuntu (âncora):**
```bash
# Ubuntu — SN
python name_service.py                                  # 100.90.10.11:5000
# Ubuntu — cliente
python main.py 6001 100.90.10.11 --ns 100.90.10.11:5000
# WSL do amigo — cliente
python3 main.py 6001 100.110.113.124 --ns 100.90.10.11:5000
```
(O SN também pode rodar no WSL: `python3 name_service.py` lá, e os dois usam
`--ns 100.110.113.124:5000`.)

### 4.4. Roteiro: os 3 cenários obrigatórios (entre máquinas)
1. **Entrada dinâmica:** SN → você cria quadro (coordenador) → amigo "Ingressar" → vê pelo
   SN, entra e recebe os desenhos atuais.
2. **Concorrência/seleção:** um seleciona um objeto (trava); o outro tenta o mesmo → "Seleção
   negada". Testem cores marrom/verde e remoção.
3. **Morte do coordenador:** mate o coordenador → o outro detecta por heartbeat → Bully
   elege novo → SN reapontado → quadro segue operante.

### 4.5. Roteiro: testar os fixes de órfãos (WSL participando)
SN no seu Ubuntu (âncora; o terminal do SN é onde a **prova** aparece).

**Teste Fix B — handoff confirmado, o WSL assume:**
1. Você cria "Sala" (coordenador); amigo (WSL) ingressa.
2. Você fecha pela **janela (X)** → handoff. O WSL vira **COORDENADOR** (status na GUI dele)
   e o SN re-registra: `Registrado: 'Sala' -> 100.110.113.124:6001`.
3. Suba um cliente novo no Ubuntu → "Ingressar" → "Sala" aparece (apontando pro WSL) → entra
   e vê os desenhos. **Sobreviveu, sem fantasma.**
   - (Se o amigo também fechasse junto → `Removido: 'Sala'`, desregistrado em vez de órfão.)

**Teste Fix A — coordenador (WSL) sozinho crasha → some da lista:**
1. Amigo (WSL) cria "X" e **ninguém entra** (órfão por crash só sobra com coordenador
   sozinho; com outros, a eleição cura).
2. Amigo mata abrupto (crash, NÃO o X da janela): `pkill -9 -f "main.py 6001"`.
3. Você abre "Ingressar" → "X" **não aparece**; terminal do SN mostra:
   `[SN] Podado (coordenador não responde): 'X' -> 100.110.113.124:6001`.

**Prova em ambos:** terminal do SN — `Registrado/Removido` (Fix B) e `Podado` (Fix A).

---

## 5. Estado do git (fim da sessão)

- Trabalho desenvolvido na branch **`feature`**; integrado também em **`main`** a pedido.
- **`origin/main`** e **`origin/feature`** sincronizados no commit
  **`17b409d "Corrige quadros órfãos no Serviço de Nomes"`**.
- Commits relevantes da sessão: `v5` (cores/seleção/multi-quadro/"Sair do quadro") e
  `17b409d` (fixes A+B de órfãos). Merge limpo com o trabalho do colega (`servico_nomes.py`),
  sem conflitos.
- **Preferência de fluxo:** trabalhar/push em `feature`; só mexer em `main` quando pedido
  explicitamente; nunca `push --force`; integrar (merge limpo) em vez de forçar quando
  `origin/feature` divergir (o colega também faz push lá).

---

## 6. Pontos de atenção / pegadinhas conhecidas

- **SN standalone sobrando na 5000:** repetidas vezes um `python name_service.py` deixado
  aberto (com estado antigo) atrapalhou os testes e a demo (bind falha → clientes falam com
  o SN velho). Sempre garanta que **só o SN da rodada atual** esteja na 5000.
- **GUI no WSL:** precisa de WSLg (Win11) ou X server; senão as janelas tkinter não abrem
  (problema de display, não da aplicação). Instalar `python3-tk` no WSL.
- **Multi-quadro usa portas aleatórias** (`porta_livre()`) — funcionam direto sobre Tailscale
  (sem NAT); sob NAT comum, não seriam alcançáveis.
- **Fix A poda no próximo LIST** — após matar um coordenador, basta abrir/atualizar a lista
  para o quadro sumir.
- **Órfão por crash só sobra quando o coordenador está sozinho** — com outros membros, a
  eleição Bully cura a queda (cenário 3), então não há órfão a podar.
</content>
