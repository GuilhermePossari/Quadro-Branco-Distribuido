# Quadro Branco Distribuído (SDWB)

O sistema foi escrito em Python e utiliza exclusivamente a biblioteca padrão da linguagem (`socket`, `threading`, `json`, `struct` e `tkinter`). Não há nenhuma dependência externa a instalar, e nenhum coordenador ou serviço de consenso pronto (como Zookeeper ou Etcd) é utilizado: toda a lógica de descoberta, detecção de falhas, eleição e exclusão mútua é implementada diretamente sobre sockets TCP.

### Autores

- Guilherme Possari
- Rafael Lançoni Santos

### Divisão de responsabilidades

O desenvolvimento foi dividido em duas frentes principais. Uma frente cuidou da infraestrutura de rede e da coordenação: a classe base de comunicação, o Serviço de Nomes, o coordenador de quadro, o mecanismo de heartbeat em anel e o algoritmo de eleição. A outra frente cuidou do cliente e da interface gráfica: a lógica de rede do terminal, a integração com a infraestrutura de coordenação e toda a interface de usuário em que o quadro é desenhado e manipulado.

## Como executar

### Pré-requisitos

O sistema roda em qualquer máquina com Python 3 instalado. O único componente que pode não estar presente por padrão é o `tkinter`, usado pela interface gráfica. Em distribuições baseadas em Debian ou Ubuntu, ele é instalado com:

```bash
sudo apt install python3-tk
```

### Ordem de inicialização

O sistema é composto por dois programas que são iniciados separadamente. O primeiro é o Serviço de Nomes (`name_service.py`), que precisa estar no ar antes de tudo, pois é ele que os clientes consultam para descobrir e registrar quadros. O segundo são os clientes (`main.py`), um por terminal participante, cada um abrindo a sua própria janela gráfica. A regra prática é: primeiro sobe o Serviço de Nomes, depois sobem os clientes.

### Passo 1: subir o Serviço de Nomes

Em uma máquina cujo endereço seja alcançável por todos os participantes, execute:

```bash
python name_service.py
```

Por padrão, o Serviço de Nomes escuta em todas as interfaces, na porta 5000 (`0.0.0.0:5000`). Caso seja necessário usar outro endereço ou porta, há os parâmetros opcionais:

```bash
python name_service.py --host 0.0.0.0 --port 5000
```

O Serviço de Nomes permanece em execução exibindo no terminal cada registro, remoção e consulta de quadro que recebe. Ele deve continuar rodando durante toda a sessão de uso.

### Passo 2: subir os clientes

Cada terminal participante é iniciado com:

```bash
python main.py [porta] [ip_proprio] [--ns IP:PORTA]
```

Os três argumentos são opcionais e têm o seguinte significado:

- `porta`: a porta TCP em que este cliente vai escutar. O padrão é 6001. Ao rodar vários clientes na mesma máquina, cada um precisa de uma porta diferente (6001, 6002, 6003 e assim por diante).
- `ip_proprio`: o endereço IP com que este cliente se anuncia aos demais. Se for omitido, o programa detecta automaticamente o IP da interface de saída da máquina. Em testes na mesma máquina, pode ser omitido. Em testes entre máquinas diferentes, deve ser o IP real pelo qual os outros nós conseguem alcançar este, e nunca `127.0.0.1`.
- `--ns IP:PORTA`: o endereço do Serviço de Nomes. O padrão é `127.0.0.1:5000`, adequado quando o Serviço de Nomes roda na mesma máquina do cliente.

### Exemplo na mesma máquina

Em três terminais distintos, com o Serviço de Nomes já rodando localmente:

```bash
python main.py 6001
python main.py 6002
python main.py 6003
```

Cada comando abre uma janela. A partir dela, um cliente pode criar um quadro novo (e se tornar o coordenador dele) ou ingressar em um quadro já existente, escolhido na lista obtida do Serviço de Nomes.

### Exemplo entre máquinas diferentes

Suponha o Serviço de Nomes rodando na máquina de endereço `192.168.0.5`. Em uma segunda máquina, de endereço `192.168.0.10`, um cliente é iniciado assim:

```bash
python main.py 6001 192.168.0.10 --ns 192.168.0.5:5000
```

O importante é que todos os participantes consigam alcançar, pela rede, tanto o Serviço de Nomes quanto os demais clientes nas portas anunciadas.


## Arquitetura

### Modelo de comunicação híbrido

A comunicação acontece em dois modos, escolhidos conforme a finalidade.

Para as operações do quadro, o modelo é cliente-servidor, com o coordenador no centro. Um participante que desenha, colore ou remove envia a operação ao coordenador. O coordenador a aplica ao seu estado autoritativo e a retransmite a todos os outros participantes. 

Para a detecção de falhas e a eleição, o modelo é ponto a ponto: os nós conversam diretamente entre si, sem passar pelo coordenador. Essa separação é deliberada e necessária. A detecção de falhas precisa continuar funcionando exatamente na situação em que o coordenador é quem falhou. Se ela dependesse do coordenador, a queda dele cegaria todo o mecanismo. Por isso a vigilância é distribuída entre os nós.

### Detecção de falhas em anel

A detecção de falhas é organizada em anel. Todos os nós de um quadro, incluindo o coordenador, são dispostos em uma sequência ordenada de forma determinística pelo endereço de cada um. Cada nó tem a tarefa de vigiar apenas o seu sucessor imediato no anel, enviando-lhe mensagens periódicas de verificação. Enquanto o sucessor responde, ele é considerado vivo. Quando ele deixa de responder por algumas tentativas seguidas, é declarado fora do ar.

### Eleição de um novo coordenador

Quando a falha do coordenador é detectada, os nós sobreviventes realizam uma eleição pelo Algoritmo do Valentão. A regra de prioridade é simples: vence o nó de maior endereço. Em uma rede local em que os participantes compartilham o mesmo IP, a porta funciona como critério de desempate, de modo que o nó de porta mais alta prevalece.


### Infraestrutura de rede e coordenação

#### protocol.py

Define o contrato de comunicação do sistema. Reúne, em um só lugar, os identificadores de todos os tipos de mensagem trocados entre os processos e as funções construtoras que montam cada mensagem. Também contém a rotina de empacotamento e desempacotamento das mensagens no fluxo TCP. Por ser o vocabulário comum, é importado por todos os demais processos, o que garante que todos falem exatamente a mesma língua.

#### node.py

Contém a classe base de rede, da qual o coordenador e o cliente herdam. Ela cuida de toda a mecânica de socket: abre o servidor TCP em uma porta, aceita conexões em segundo plano usando uma thread por conexão, decodifica a mensagem recebida e a entrega para tratamento. Oferece também os dois métodos de envio usados em todo o sistema: um que aguarda resposta e devolve uma indicação de falha quando o destino está inacessível, e outro que apenas dispara a mensagem sem esperar retorno, usado nas retransmissões. As subclasses só precisam definir como tratar cada mensagem.

#### name_service.py

Implementa o Serviço de Nomes. É um processo autônomo, com endereço fixo, que mantém a tabela de quadros ativos e atende aos pedidos de registro, remoção e listagem. Pode ser iniciado diretamente pela linha de comando, com parâmetros opcionais de endereço e porta.

#### coordinator.py

Implementa o coordenador de quadro. Guarda os objetos desenhados, a lista de participantes e as travas de exclusão mútua, todos protegidos contra acesso concorrente das várias threads. Trata o ingresso de novos participantes respondendo com o estado completo, processa as operações de desenho, cor e remoção retransmitindo-as aos demais, gerencia a concessão e a liberação de travas e trata a saída de participantes. Oferece ainda os pontos de apoio usados pela detecção de falhas e pela eleição: a remoção de um membro que caiu e a consulta ao estado atual do quadro. Quando o último participante sai, encerra o quadro e o remove do Serviço de Nomes.

#### heartbeat.py

Implementa a detecção de falhas em anel. Contém a função que monta o anel de forma determinística a partir da lista de nós e a classe que executa a vigília: periodicamente envia a verificação ao sucessor, contabiliza as tentativas sem resposta e, ao confirmar uma falha, aciona o tratamento adequado conforme o nó perdido fosse um participante comum ou o coordenador. Permite também atualizar o anel e o coordenador conhecidos quando a composição do quadro muda.

#### election.py

Implementa a eleição pelo Algoritmo do Valentão. Conduz a rodada de eleição em segundo plano, envia e responde às mensagens de eleição, aguarda o anúncio do vencedor com tempo limite e reinício quando necessário, e avisa o restante do sistema sobre quem passou a ser o coordenador. É escrita para tolerar disparos simultâneos, ignorando rodadas redundantes.

### Cliente e interface

#### client.py

É o cérebro de rede de cada terminal. Reúne tudo o que um cliente faz: consultar o Serviço de Nomes para listar, criar ou ingressar em quadros; receber e armazenar o estado no momento do ingresso; encaminhar ao coordenador as operações originadas na interface; receber as operações retransmitidas e repassá-las à tela; integrar a detecção de falhas e a eleição; e assumir o papel de coordenador quando cria um quadro ou vence uma eleição. A interface gráfica nunca conversa diretamente por socket: ela chama métodos do cliente e é avisada por meio de funções de retorno, sempre de maneira segura para o uso com a interface.

#### telas.py

Contém toda a interface gráfica, construída com a biblioteca padrão de janelas do Python. Define a janela principal, que controla a navegação entre telas e cuida das múltiplas sessões abertas, e as telas de uso: a tela inicial, com as opções de criar e ingressar; a tela de listagem dos quadros disponíveis obtidos do Serviço de Nomes; e a tela do quadro em si, com a área de desenho e a barra de ferramentas, que oferece as ferramentas de linha, quadrado, as duas cores, a seleção, a remoção e a saída do quadro.

#### main.py

É o ponto de entrada do cliente. Interpreta os argumentos de linha de comando (porta, endereço próprio e endereço do Serviço de Nomes), detecta o IP da máquina quando não informado, instancia o cliente e abre a interface gráfica.

## Protocolo de mensagens

Toda a comunicação entre os processos acontece por troca de mensagens em formato JSON. Cada mensagem é um objeto que sempre carrega um campo de tipo, indicando a sua natureza, além dos campos específicos daquele tipo. As mensagens são sempre montadas por funções construtoras dedicadas, e nunca escritas manualmente espalhadas pelo código, o que evita divergências de formato entre quem envia e quem recebe.

### Delimitação das mensagens no fluxo TCP

O TCP entrega um fluxo contínuo de bytes, sem marcar onde termina uma mensagem e começa a próxima. Se duas mensagens forem enviadas em sequência, elas podem chegar grudadas ou partidas, e o receptor não teria como separá-las apenas olhando os bytes.

Para resolver isso, cada mensagem é transmitida com um cabeçalho de quatro bytes que informa o tamanho do conteúdo que vem logo a seguir. O receptor lê primeiro esses quatro bytes, descobre o tamanho exato da mensagem e então lê precisamente essa quantidade de bytes, remontando o conteúdo completo. Esse esquema de prefixo de tamanho garante que cada mensagem seja lida inteira e isolada das demais, independentemente de como o TCP fragmentou ou juntou os dados no caminho. Caso a conexão se feche no meio da leitura, o receptor percebe e trata como ausência de mensagem.

### Catálogo de tipos de mensagem

As mensagens estão agrupadas abaixo por finalidade. Para cada uma, indica-se a função construtora correspondente e os campos que ela carrega.

| Finalidade | Tipo | Construtor | Campos e significado |
|---|---|---|---|
| Serviço de Nomes | `REGISTER` | `make_register(name, ip, port)` | Registra ou atualiza um quadro: nome do quadro e endereço do seu coordenador. |
| | `UNREGISTER` | `make_unregister(name)` | Remove um quadro da tabela, quando ele é encerrado. |
| | `LIST` | `make_list()` | Pedido de listagem dos quadros disponíveis. |
| | `LIST_RESPONSE` | `make_list_response(boards)` | Resposta com a lista de quadros, cada um com nome, IP e porta. |
| Ingresso | `JOIN` | `make_join(ip, port)` | Pedido de um cliente para entrar em um quadro, informando o próprio endereço. |
| | `STATE` | `make_state(objects, members)` | Estado completo enviado ao recém-chegado: todos os objetos e a lista de participantes. |
| Operações | `DRAW` | `make_draw(obj, sender_id)` | Desenho de um objeto, mais a identificação de quem o originou. |
| | `REMOVE` | `make_remove(object_id, sender_id)` | Remoção de um objeto pelo seu identificador, mais quem originou. |
| | `COLOR` | `make_color(object_id, color, sender_id)` | Alteração da cor de um objeto, mais quem originou. |
| Exclusão mútua | `LOCK_REQUEST` | `make_lock_request(object_id, node_id)` | Pedido de trava sobre um objeto, identificando quem pede. |
| | `LOCK_RESPONSE` | `make_lock_response(object_id, granted, reason)` | Resposta ao pedido: concedida ou negada, com o motivo. |
| | `LOCK_RELEASE` | `make_lock_release(object_id)` | Liberação da trava de um objeto. |
| Detecção de falhas | `HEARTBEAT` | `make_heartbeat(node_id)` | Verificação periódica enviada ao sucessor no anel. |
| | `HEARTBEAT_OK` | `make_heartbeat_ok(node_id)` | Resposta confirmando que o nó está ativo. |
| Eleição | `ELECTION` | `make_election(candidate_id)` | Início de eleição, enviado aos nós de prioridade superior. |
| | `ELECTION_OK` | `make_election_ok()` | Resposta de um superior, confirmando que está ativo. |
| | `COORDINATOR` | `make_coordinator(ip, port)` | Anúncio do vencedor como novo coordenador. |
| Composição do quadro | `RING_UPDATE` | `make_ring_update(members)` | Aviso de mudança no anel, com a nova composição já ordenada. |
| Saída | `LEAVE` | `make_leave(node_id)` | Aviso de saída voluntária de um participante. |
| Utilitárias | `OK` | `make_ok()` | Confirmação genérica de sucesso. |
| | `ERROR` | `make_error(reason)` | Indicação de erro, com o motivo. |

