import tkinter as tk 
from tkinter import simpledialog, messagebox
import uuid 
from client import Client # Importa a classe Client que cuida da rede (o esqueleto do seu parceiro).

class TelaInicial(tk.Frame): # Herda de tk.Frame, ou seja, esta classe É um "recipiente" visual.
    def __init__(self, master=None, client=None):
        super().__init__(master) # Inicializa o Frame passando a janela principal (master).
        self.master = master # Guarda a referência da janela principal (a raiz do app).
        self.client = client # Guarda a instância do cliente de rede (Injeção de Dependência).
        self.pack(fill="both", expand=True) # Diz para este Frame ocupar todo o espaço da janela.
        self.create_widgets() # Chama a função que desenha os botões e textos na tela.

    def create_widgets(self):
        # Cria um rótulo (texto) e o coloca na tela com um espaçamento vertical (pady).
        self.label = tk.Label(self, text="Museu histórico da CompArte", font=("Arial", 14, "bold"))
        self.label.pack(pady=30) 

        # Cria os botões, atrelando a ação (command) às funções específicas da classe.
        self.button1 = tk.Button(self, text="CRIAR NOVO QUADRO", command=self.criar_quadro, width=30)
        self.button1.pack(pady=10)

        self.button2 = tk.Button(self, text="INGRESSAR EM QUADRO EXISTENTE", command=self.ir_para_lista, width=30)
        self.button2.pack(pady=10)
        
    def criar_quadro(self):
        # Abre um pop-up pedindo o nome. O programa pausa aqui até o usuário digitar e dar OK.
        nome = simpledialog.askstring("Novo Quadro", "Digite o nome do quadro:")
        if nome: # Se o usuário não cancelou...
            sucesso = self.client.criar_quadro(nome) # ...pede para a rede criar o quadro.
            if sucesso:
                self.destroy() # Destrói a tela inicial atual (limpa a janela).
                TelaQuadro(self.master, self.client) # Instancia a tela de desenho, passando a janela e o cliente.
            else:
                messagebox.showerror("Erro", "Não foi possível criar o quadro.") # Pop-up de erro se a rede falhar.
        
    def ir_para_lista(self):
        self.destroy() # Limpa a tela atual.
        TelaListaQuadros(self.master, self.client) # Abre a tela de listar quadros.


class TelaListaQuadros(tk.Frame):
    def __init__(self, master=None, client=None):
        super().__init__(master)
        self.master = master
        self.client = client
        self.quadros_disponiveis = [] # Lista local para guardar os quadros que vierem da rede.
        self.pack(fill="both", expand=True)
        self.create_widgets()
        self.carregar_lista() # Assim que a tela nasce, já pede a lista para a rede.

    def create_widgets(self):
        self.label = tk.Label(self, text="Selecione um quadro para ingressar:", font=("Arial", 12))
        self.label.pack(pady=10)
        
        # Listbox é um componente visual do Tkinter para listas selecionáveis.
        self.listbox = tk.Listbox(self, width=50, height=10)
        self.listbox.pack(pady=10)

        self.btn_entrar = tk.Button(self, text="Entrar no Quadro", command=self.entrar_quadro)
        self.btn_entrar.pack(pady=5)

        self.btn_voltar = tk.Button(self, text="Voltar ao Menu", command=self.voltar)
        self.btn_voltar.pack(pady=5)

    def carregar_lista(self):
        # Pede os quadros para o client.py. Ele vai falar com o Serviço de Nomes.
        self.quadros_disponiveis = self.client.listar_quadros() 
        self.listbox.delete(0, tk.END) # Limpa a lista visual antes de preencher.
        for q in self.quadros_disponiveis:
            # Insere cada quadro na interface visual (mostra nome, IP e porta).
            self.listbox.insert(tk.END, f"{q['name']} ({q['ip']}:{q['port']})")

    def entrar_quadro(self):
        selecao = self.listbox.curselection() # Retorna uma tupla com os índices selecionados (ex: (0,)).
        if not selecao:
            messagebox.showwarning("Aviso", "Selecione um quadro primeiro.")
            return # Aborta a função se nada foi selecionado.
        
        # Pega o dicionário do quadro usando o índice que o usuário clicou.
        quadro_selecionado = self.quadros_disponiveis[selecao[0]] 
        # Tenta ingressar via rede.
        sucesso = self.client.ingressar_em_quadro(quadro_selecionado)
        
        if sucesso:
            self.destroy()
            TelaQuadro(self.master, self.client) # Vai para o canvas!
        else:
            messagebox.showerror("Erro", "Falha ao ingressar no quadro.")

    def voltar(self):
        self.destroy()
        TelaInicial(self.master, self.client)


class TelaQuadro(tk.Frame):
    def __init__(self, master=None, client=None):
        super().__init__(master)
        self.master = master
        self.client = client
        self.pack(fill="both", expand=True)
        
        # Variáveis do Tkinter que atualizam a interface automaticamente quando mudam.
        self.ferramenta_atual = tk.StringVar(value="line") 
        self.cor_atual = tk.StringVar(value="black")
        
        self.pontos_temp = [] # Guarda os cliques (1º clique inicia a reta, 2º finaliza).
        self.objetos_canvas = {} # Dicionário para relacionar o ID da rede com o ID da linha desenhada na tela.

        # A MÁGICA: Ligamos as funções desta tela aos "gatilhos" (callbacks) do cliente de rede.
        self.client.on_draw = self.receber_draw 
        self.client.on_error = self.mostrar_erro
        
        self.create_widgets()

    def create_widgets(self):
        toolbar = tk.Frame(self) # Um sub-container só para os botões do topo.
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=5)

        # Radiobuttons são botões de múltipla escolha. Eles mudam o valor da variável "ferramenta_atual".
        tk.Radiobutton(toolbar, text="Linha", variable=self.ferramenta_atual, value="line").pack(side=tk.LEFT)
        tk.Radiobutton(toolbar, text="Quadrado", variable=self.ferramenta_atual, value="square").pack(side=tk.LEFT)
        
        tk.Label(toolbar, text="| Cor:").pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(toolbar, text="Preto", variable=self.cor_atual, value="black").pack(side=tk.LEFT)
        tk.Radiobutton(toolbar, text="Vermelho", variable=self.cor_atual, value="red").pack(side=tk.LEFT)

        self.btn_voltar = tk.Button(toolbar, text="Sair do Quadro", command=self.voltar)
        self.btn_voltar.pack(side=tk.RIGHT, padx=10)

        # Cria a área desenhável.
        self.canvas = tk.Canvas(self, bg="white", cursor="cross")
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Diz ao Tkinter: "Toda vez que o botão esquerdo do mouse (<Button-1>) for clicado aqui, chame 'on_click'".
        self.canvas.bind("<Button-1>", self.on_click)

    def on_click(self, event):
        # O 'event' traz as coordenadas (x e y) de onde o mouse clicou.
        self.pontos_temp.append([event.x, event.y]) 
        
        # Um desenho (linha ou quadrado) precisa de 2 pontos (início e fim).
        if len(self.pontos_temp) == 2:
            # Monta o pacote no formato esperado pelo protocolo da rede.
            novo_objeto = {
                "id": str(uuid.uuid4()), # Gera um ID aleatório tipo "123e4567-e89b-12d3-a456-426614174000".
                "shape": self.ferramenta_atual.get(),
                "points": self.pontos_temp.copy(),
                "color": self.cor_atual.get()
            }
            # ATENÇÃO: Nós NÃO desenhamos aqui. Apenas enviamos para a rede.
            self.client.desenhar(novo_objeto) 
            self.pontos_temp = [] # Limpa a lista para o próximo desenho.

    def receber_draw(self, obj):
        # Esta função só roda quando chega uma mensagem da rede (seja a sua que voltou, ou a de um amigo).
        shape = obj.get("shape")
        pts = obj.get("points")
        color = obj.get("color")
        obj_id = obj.get("id")

        if shape == "line":
            # Cria a linha visualmente e guarda o ID interno que o Tkinter gera.
            item = self.canvas.create_line(pts[0][0], pts[0][1], pts[1][0], pts[1][1], fill=color, width=2)
        elif shape == "square":
            item = self.canvas.create_rectangle(pts[0][0], pts[0][1], pts[1][0], pts[1][1], outline=color, width=2)
            
        self.objetos_canvas[obj_id] = item # Guarda no dicionário: ID_da_rede -> ID_do_Tkinter.

    def mostrar_erro(self, mensagem):
        messagebox.showerror("Erro na Rede", mensagem)

    def voltar(self):
        self.client.sair() # Avisa a infraestrutura de rede que estamos vazando.
        self.destroy()
        TelaInicial(self.master, self.client)


if __name__ == "__main__":
    root = tk.Tk() # Criando a janela principal 
    root.title("App - CompArte")
    root.geometry("800x600") 

    # Instanciamos O MOTOR DE REDE primeiro.
    meu_cliente = Client(host="127.0.0.1", port=6001, ns_host="127.0.0.1", ns_port=5000, master=root)
    # Passamos a janela raiz (root) e o motor (meu_cliente) para a primeira tela.
    app = TelaInicial(master=root, client=meu_cliente)
    
    # Entrega o controle do programa para o loop infinito do Tkinter.
    app.mainloop()