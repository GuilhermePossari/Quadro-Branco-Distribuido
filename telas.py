#import tkinter as tk
#
#class TelaInicial(tk.Frame):
#    def __init__(self, master=None):
#        super().__init__(master)
#        self.master = master
#        self.pack(fill="both", expand=True) 
#        self.create_widgets()
#
#    def create_widgets(self):
#        self.label = tk.Label(self, text="Museu histórico da CompArte", font=("Arial", 12, "bold"))
#        self.label.pack(pady=20)
#
#        self.button1 = tk.Button(self, text="CRIAR NOVO QUADRO", command=self.ir_para_quadro)
#        self.button1.pack(side=tk.LEFT, padx=20, pady=5)
#
#        self.button2 = tk.Button(self, text="INGRESSAR EM QUADRO EXISTENTE", command=self.ir_para_lista)
#        self.button2.pack(side=tk.RIGHT, padx=20, pady=5)
#        
#    def ir_para_quadro(self):
#
#        self.destroy()
#        TelaQuadro(self.master)
#        
#    def ir_para_lista(self):
#
#        self.destroy()
#        TelaListaQuadros(self.master)
#
#
#class TelaQuadro(tk.Frame):
#    def __init__(self, master=None):
#        super().__init__(master)
#        self.master = master
#        self.pack(fill="both", expand=True)
#        self.create_widgets()
#
#    def create_widgets(self):
#        self.label = tk.Label(self, text="Aqui vai ficar o seu quadro", font=("Arial", 10))
#        self.label.pack(pady=30)
#        
#        self.btn_voltar = tk.Button(self, text="Voltar ao Menu", command=self.voltar)
#        self.btn_voltar.pack(pady=10)
#
#    def voltar(self):
#        self.destroy()
#        TelaInicial(self.master)
#
#
#class TelaListaQuadros(tk.Frame):
#    def __init__(self, master=None):
#        super().__init__(master)
#        self.master = master
#        self.pack(fill="both", expand=True)
#        self.create_widgets()
#
#    def create_widgets(self):
#        self.label = tk.Label(self, text="Aqui vai ficar a lista de quadros disponíveis para ingressar", font=("Arial", 10))
#        self.label.pack(pady=30)
#        
#        self.btn_voltar = tk.Button(self, text="Voltar ao Menu", command=self.voltar)
#        self.btn_voltar.pack(pady=10)
#
#    def voltar(self):
#        self.destroy()
#        TelaInicial(self.master)
#
#
#if __name__ == "__main__":
#    root = tk.Tk()
#    root.title("App - CompArte")
#
#    root.geometry("600x200") 
#    app = TelaInicial(master=root)
#    app.mainloop()

import tkinter as tk
from tkinter import simpledialog, messagebox
import uuid

# Importe o seu cliente (mesmo que ele ainda esteja com partes não implementadas)
from client import Client 

class TelaInicial(tk.Frame):
    def __init__(self, master=None, client=None):
        super().__init__(master)
        self.master = master
        self.client = client # Recebemos o cliente aqui
        self.pack(fill="both", expand=True) 
        self.create_widgets()

    def create_widgets(self):
        self.label = tk.Label(self, text="Museu histórico da CompArte", font=("Arial", 14, "bold"))
        self.label.pack(pady=30)

        self.button1 = tk.Button(self, text="CRIAR NOVO QUADRO", command=self.criar_quadro, width=30)
        self.button1.pack(pady=10)

        self.button2 = tk.Button(self, text="INGRESSAR EM QUADRO EXISTENTE", command=self.ir_para_lista, width=30)
        self.button2.pack(pady=10)
        
    def criar_quadro(self):
        # Abre um popup perguntando o nome
        nome = simpledialog.askstring("Novo Quadro", "Digite o nome do quadro:")
        if nome:
            sucesso = self.client.criar_quadro(nome)
            if sucesso:
                self.destroy()
                TelaQuadro(self.master, self.client)
            else:
                messagebox.showerror("Erro", "Não foi possível criar o quadro.")
        
    def ir_para_lista(self):
        self.destroy()
        TelaListaQuadros(self.master, self.client)


class TelaListaQuadros(tk.Frame):
    def __init__(self, master=None, client=None):
        super().__init__(master)
        self.master = master
        self.client = client
        self.quadros_disponiveis = []
        self.pack(fill="both", expand=True)
        self.create_widgets()
        self.carregar_lista()

    def create_widgets(self):
        self.label = tk.Label(self, text="Selecione um quadro para ingressar:", font=("Arial", 12))
        self.label.pack(pady=10)
        
        # Lista visual do Tkinter
        self.listbox = tk.Listbox(self, width=50, height=10)
        self.listbox.pack(pady=10)

        self.btn_entrar = tk.Button(self, text="Entrar no Quadro", command=self.entrar_quadro)
        self.btn_entrar.pack(pady=5)

        self.btn_voltar = tk.Button(self, text="Voltar ao Menu", command=self.voltar)
        self.btn_voltar.pack(pady=5)

    def carregar_lista(self):
        self.quadros_disponiveis = self.client.listar_quadros()
        self.listbox.delete(0, tk.END)
        for q in self.quadros_disponiveis:
            self.listbox.insert(tk.END, f"{q['name']} ({q['ip']}:{q['port']})")

    def entrar_quadro(self):
        selecao = self.listbox.curselection()
        if not selecao:
            messagebox.showwarning("Aviso", "Selecione um quadro primeiro.")
            return
        
        quadro_selecionado = self.quadros_disponiveis[selecao[0]]
        sucesso = self.client.ingressar_em_quadro(quadro_selecionado)
        
        if sucesso:
            self.destroy()
            TelaQuadro(self.master, self.client)
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
        
        # Variáveis de estado do desenho
        self.ferramenta_atual = tk.StringVar(value="line")
        self.cor_atual = tk.StringVar(value="black")
        self.pontos_temp = []
        self.objetos_canvas = {} # Mapeia o ID do protocolo para o ID visual do Tkinter

        # Ligar os callbacks do cliente aos métodos desta tela
        self.client.on_draw = self.receber_draw
        self.client.on_error = self.mostrar_erro
        # self.client.on_remove = self.receber_remove  # (Para quando for implementar a exclusão mútua)
        
        self.create_widgets()

    def create_widgets(self):
        # --- Barra de Ferramentas (Topo) ---
        toolbar = tk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=5)

        tk.Radiobutton(toolbar, text="Linha", variable=self.ferramenta_atual, value="line").pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(toolbar, text="Quadrado", variable=self.ferramenta_atual, value="square").pack(side=tk.LEFT, padx=5)
        
        tk.Label(toolbar, text="| Cor:").pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(toolbar, text="Preto", variable=self.cor_atual, value="black").pack(side=tk.LEFT)
        tk.Radiobutton(toolbar, text="Vermelho", variable=self.cor_atual, value="red").pack(side=tk.LEFT)

        self.btn_voltar = tk.Button(toolbar, text="Sair do Quadro", command=self.voltar)
        self.btn_voltar.pack(side=tk.RIGHT, padx=10)

        # --- Área de Desenho ---
        self.canvas = tk.Canvas(self, bg="white", cursor="cross")
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Captura cliques no canvas
        self.canvas.bind("<Button-1>", self.on_click)

    def on_click(self, event):
        # Salva o ponto clicado
        self.pontos_temp.append([event.x, event.y])
        
        # Se temos 2 pontos, formamos uma figura
        if len(self.pontos_temp) == 2:
            novo_objeto = {
                "id": str(uuid.uuid4()), # Gera um ID único para o objeto
                "shape": self.ferramenta_atual.get(),
                "points": self.pontos_temp.copy(),
                "color": self.cor_atual.get()
            }
            # Envia para a rede
            self.client.desenhar(novo_objeto)
            # Limpa para o próximo desenho
            self.pontos_temp = []

    # --- Callbacks da Rede ---
    def receber_draw(self, obj):
        # Esta função é chamada pelo client.py quando chega um desenho da rede
        shape = obj.get("shape")
        pts = obj.get("points")
        color = obj.get("color")
        obj_id = obj.get("id")

        if shape == "line":
            item = self.canvas.create_line(pts[0][0], pts[0][1], pts[1][0], pts[1][1], fill=color, width=2)
        elif shape == "square":
            item = self.canvas.create_rectangle(pts[0][0], pts[0][1], pts[1][0], pts[1][1], outline=color, width=2)
            
        self.objetos_canvas[obj_id] = item

    def mostrar_erro(self, mensagem):
        messagebox.showerror("Erro na Rede", mensagem)

    def voltar(self):
        self.client.sair() # Avisa a rede que está saindo
        self.destroy()
        TelaInicial(self.master, self.client)


if __name__ == "__main__":
    root = tk.Tk()
    root.title("App - CompArte")
    root.geometry("500x300") 

    # 1. Instanciar o cliente ANTES das telas
    # Atenção: Ajuste os IPs/Portas conforme a sua máquina/serviço de nomes
    meu_cliente = Client(host="127.0.0.1", port=6001, ns_host="127.0.0.1", ns_port=5000, master=root)
    # meu_cliente.start() # Você precisará iniciar o cliente para habilitar o servidor TCP interno dele

    # 2. Passar o cliente para a tela inicial
    app = TelaInicial(master=root, client=meu_cliente)
    app.mainloop()