import tkinter as tk

class TelaInicial(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.pack(fill="both", expand=True) 
        self.create_widgets()

    def create_widgets(self):
        self.label = tk.Label(self, text="Museu histórico da CompArte", font=("Arial", 12, "bold"))
        self.label.pack(pady=20)

        self.button1 = tk.Button(self, text="CRIAR NOVO QUADRO", command=self.ir_para_quadro)
        self.button1.pack(side=tk.LEFT, padx=20, pady=5)

        self.button2 = tk.Button(self, text="INGRESSAR EM QUADRO EXISTENTE", command=self.ir_para_lista)
        self.button2.pack(side=tk.RIGHT, padx=20, pady=5)
        
    def ir_para_quadro(self):

        self.destroy()
        TelaQuadro(self.master)
        
    def ir_para_lista(self):

        self.destroy()
        TelaListaQuadros(self.master)


class TelaQuadro(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.pack(fill="both", expand=True)
        self.create_widgets()

    def create_widgets(self):
        self.label = tk.Label(self, text="Aqui vai ficar o seu quadro", font=("Arial", 10))
        self.label.pack(pady=30)
        
        self.btn_voltar = tk.Button(self, text="Voltar ao Menu", command=self.voltar)
        self.btn_voltar.pack(pady=10)

    def voltar(self):
        self.destroy()
        TelaInicial(self.master)


class TelaListaQuadros(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.pack(fill="both", expand=True)
        self.create_widgets()

    def create_widgets(self):
        self.label = tk.Label(self, text="Aqui vai ficar a lista de quadros disponíveis para ingressar", font=("Arial", 10))
        self.label.pack(pady=30)
        
        self.btn_voltar = tk.Button(self, text="Voltar ao Menu", command=self.voltar)
        self.btn_voltar.pack(pady=10)

    def voltar(self):
        self.destroy()
        TelaInicial(self.master)


# --- INÍCIO DO PROGRAMA ---
if __name__ == "__main__":
    root = tk.Tk()
    root.title("App - CompArte")
    # Aumentei um pouco a janela para os botões caberem confortavelmente
    root.geometry("600x200") 
    app = TelaInicial(master=root)
    app.mainloop()