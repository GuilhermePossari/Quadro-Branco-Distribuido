# Anotações de aula — esclarecimentos do professor (SDWB)

Pontos ditos em aula que **complementam ou esclarecem** o enunciado escrito
(`Trabalho_2026_SD_SharedWriteBoard.md`). São requisitos/regras de negócio, não
escolhas de implementação de nenhuma dupla específica.

## Mudança de escopo
- O enunciado original tinha uma seção sobre **Two-Phase Commit (2PC)** para transações
  atômicas. **Essa seção foi removida pelo professor.** O escopo atual **NÃO inclui 2PC**.

## Regras de negócio do ciclo de vida (coordenador / quadro)
- Cliente que é o **coordenador sai voluntariamente** → o coordenador **continua na mesma
  máquina**, **sem disparar eleição** (saída controlada não é falha).
- Máquina do **coordenador cai/desliga** → **dispara eleição** para escolher novo coordenador.
- Coordenador **sozinho** no quadro sai/cai → o quadro é **encerrado** (deve ser desregistrado
  do Serviço de Nomes).
- Podem existir **múltiplos quadros simultâneos**, cada um com seu próprio coordenador
  registrado no Serviço de Nomes.

## Observações gerais
- O coordenador **não é hardware dedicado**: roda na máquina de um dos clientes, e qualquer
  cliente pode se tornar coordenador via eleição.

## Impacto da remoção do 2PC nos requisitos do professor

Dois pontos do enunciado escrito ficaram "no limbo" depois que o professor removeu o 2PC.
Registro aqui o que continua valendo e **como o trabalho resolveu**.

### 1. Cenário de Teste Obrigatório #2 — "Concorrência Transacional"

O enunciado (§5, Cenários) ainda pede: *"Dois usuários tentam iniciar transações conflitantes
ao mesmo tempo; o sistema deve ordenar via exclusão mútua."* Como o 2PC saiu, **não há mais
"transações"** de múltiplos objetos. O requisito que sobrevive é a parte final — **ordenar via
exclusão mútua** — e ele agora é atendido pela exclusão mútua **na seleção de um único objeto**
(enunciado §3A).

**O trabalho do seu pai(possari)** resolveu assim: a exclusão mútua acontece no **momento da
seleção**, não no da operação. Quando um nó seleciona um objeto, o cliente envia um
`LOCK_REQUEST` ao coordenador (`client.py::selecionar` → `_solicitar_lock`); o coordenador é o
**ponto único de serialização** — ele concede a trava ao primeiro que pedir e **nega aos demais**,
devolvendo `LOCK_RESPONSE(granted=False)`, que a GUI mostra como "Seleção negada". Enquanto o nó
mantém o objeto selecionado, **nenhum outro consegue selecioná-lo** e, como só se opera sobre o
objeto selecionado, ninguém mais consegue colori-lo nem removê-lo. A trava é liberada com
`LOCK_RELEASE` ao desselecionar (`desselecionar`), e o coordenador também a libera
automaticamente quando o objeto é removido. Resultado: dois usuários clicando no mesmo objeto ao
mesmo tempo são **ordenados pelo coordenador** — exatamente o que o cenário #2 pede, sem precisar
de 2PC.

### 3. Falha do Coordenador (#3) e resiliência do Serviço de Nomes

O enunciado pede o cenário *"Morte do Coordenador"* (§5, #3: "matar o processo do Coordenador") e
afirma que **o Serviço de Nomes não será afetado por falhas** (§4) — ou seja, pode-se assumir o
SN sempre no ar; só os coordenadores caem.

**O trabalho do seu pai(possari)** resolveu em três frentes:
- **Detecção:** um **heartbeat em anel** monitora os vizinhos. Quando o vizinho que cai é o
  coordenador, dispara o callback `_on_coordenador_falhou` (`client.py`).
- **Eleição:** inicia-se o **Algoritmo do Valentão (Bully)** entre os nós vivos
  (`eleicao.iniciar()`); o vencedor vira coordenador, **assume a réplica local do estado** (os
  objetos recebidos por broadcast + a lista de membros) e **reatualiza o SN** com o próprio
  endereço via `REGISTER` (`_virar_coordenador`). Assim o quadro continua operando e os novos nós
  já descobrem o coordenador novo no SN — atende §3A/§4.
- **SN resiliente / sem órfãos:** o SN é um processo separado e fixo, tratado como sempre
  disponível. Para os casos em que um coordenador morre sem conseguir reapontar o SN (crash
  abrupto, ou handoff de saída sem sucessor vivo), o SN **poda quadros fantasma**: antes de
  responder o `LIST`, ele faz um probe de vivacidade em cada coordenador e remove da tabela os
  que não respondem (`name_service.py::_separar_vivos_e_mortos`). Na saída voluntária do
  coordenador, o handoff só é dado como feito se o sucessor **responder**; se ninguém vivo
  assumir, o quadro é **desregistrado** em vez de ficar órfão (`client.py::sair`, caso 2/3). Com
  isso, "matar o coordenador" nunca deixa um quadro inacessível listado no SN.
