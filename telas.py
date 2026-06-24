"""
telas.py — Interface gráfica (tkinter) do SDWB.

A GUI NUNCA fala socket: só chama métodos do `Client` e reage aos callbacks
(on_draw, on_remove, on_color, on_error, on_state_loaded, on_coord_changed).
Todos os callbacks já chegam na thread do tkinter (Client._ui usa master.after),
então é seguro tocar widgets diretamente neles.

Estrutura:
  App            — controlador: guarda o Client, troca de tela, registra callbacks.
  TelaInicial    — CRIAR / INGRESSAR.
  TelaListaQuadros — lista quadros do Serviço de Nomes e ingressa.
  TelaQuadro     — canvas + toolbar (linha, quadrado, 2 cores, remover, selecionar).
"""

import tkinter as tk
from tkinter import simpledialog, messagebox

# Duas cores disponíveis (enunciado §1.1)
COR_A = "#d62728"   # vermelho
COR_B = "#1f77b4"   # azul
COR_PADRAO = "#000000"


class App(tk.Tk):
    """Janela raiz e controlador de telas. Recebe um Client já instanciado."""

    def __init__(self, client):
        super().__init__()
        self.client = client
        client.master = self          # _ui() passa a enfileirar para esta janela
        self.title(f"SDWB — {client.node_id}")
        self.geometry("900x650")

        self._container = tk.Frame(self)
        self._container.pack(fill="both", expand=True)
        self._tela_atual = None

        # Liga os callbacks de rede aos métodos da tela do quadro.
        # (definidos aqui no controlador; redirecionam para a TelaQuadro ativa)
        client.on_state_loaded  = self._cb_state_loaded
        client.on_draw          = self._cb_draw
        client.on_remove        = self._cb_remove
        client.on_color         = self._cb_color
        client.on_error         = self._cb_error
        client.on_coord_changed = self._cb_coord_changed

        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self.mostrar(TelaInicial)
        self._poll_ui()               # drena callbacks de rede na thread do tkinter

    def _poll_ui(self):
        """Consome a fila de callbacks do Client (thread-safety da GUI, D4)."""
        self.client.drenar_ui()
        self.after(40, self._poll_ui)

    # ── Troca de telas ────────────────────────────────────────────────
    def mostrar(self, classe_tela, **kwargs):
        if self._tela_atual is not None:
            self._tela_atual.destroy()
        self._tela_atual = classe_tela(self._container, self, **kwargs)
        self._tela_atual.pack(fill="both", expand=True)
        return self._tela_atual

    # ── Callbacks de rede → repassam à TelaQuadro se for a tela ativa ──
    def _quadro(self):
        return self._tela_atual if isinstance(self._tela_atual, TelaQuadro) else None

    def _cb_state_loaded(self, objetos):
        q = self._quadro()
        if q: q.carregar_estado(objetos)

    def _cb_draw(self, obj):
        q = self._quadro()
        if q: q.receber_draw(obj)

    def _cb_remove(self, object_id):
        q = self._quadro()
        if q: q.receber_remove(object_id)

    def _cb_color(self, object_id, color):
        q = self._quadro()
        if q: q.receber_color(object_id, color)

    def _cb_error(self, msg):
        messagebox.showwarning("Operação negada", msg)

    def _cb_coord_changed(self, ip, port, sou_coord):
        q = self._quadro()
        if q: q.atualizar_papel(sou_coord, ip, port)

    # ── Encerramento gracioso ─────────────────────────────────────────
    def _ao_fechar(self):
        try:
            self.client.sair()       # LEAVE / handoff / encerra quadro (D6)
        except Exception:
            pass
        self.destroy()


class TelaInicial(tk.Frame):
    """Primeira tela: criar um quadro novo ou ingressar num existente."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app

        tk.Label(self, text="Quadro Branco Distribuído",
                 font=("Arial", 22, "bold")).pack(pady=(80, 10))
        tk.Label(self, text=f"Este nó: {app.client.node_id}",
                 font=("Arial", 11), fg="#666").pack(pady=(0, 40))

        tk.Button(self, text="CRIAR NOVO QUADRO", width=28, height=2,
                  command=self._criar).pack(pady=8)
        tk.Button(self, text="INGRESSAR EM QUADRO EXISTENTE", width=28, height=2,
                  command=self._ingressar).pack(pady=8)

    def _criar(self):
        nome = simpledialog.askstring("Criar quadro", "Nome do novo quadro:", parent=self)
        if not nome:
            return
        if self.app.client.criar_quadro(nome):
            self.app.mostrar(TelaQuadro, nome=nome)
        else:
            messagebox.showerror("Erro", f"Já existe um quadro chamado '{nome}'.")

    def _ingressar(self):
        self.app.mostrar(TelaListaQuadros)


class TelaListaQuadros(tk.Frame):
    """Lista os quadros registrados no Serviço de Nomes e permite ingressar."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self._boards = []

        tk.Label(self, text="Quadros disponíveis",
                 font=("Arial", 18, "bold")).pack(pady=(30, 15))

        self._listbox = tk.Listbox(self, width=50, height=12, font=("Arial", 12))
        self._listbox.pack(pady=10)

        barra = tk.Frame(self)
        barra.pack(pady=10)
        tk.Button(barra, text="Atualizar", width=12, command=self._atualizar).pack(side="left", padx=5)
        tk.Button(barra, text="Ingressar", width=12, command=self._ingressar).pack(side="left", padx=5)
        tk.Button(barra, text="Voltar", width=12,
                  command=lambda: app.mostrar(TelaInicial)).pack(side="left", padx=5)

        self._atualizar()

    def _atualizar(self):
        self._boards = self.app.client.listar_quadros()
        self._listbox.delete(0, tk.END)
        for b in self._boards:
            self._listbox.insert(tk.END, f"{b['name']}  ({b['ip']}:{b['port']})")
        if not self._boards:
            self._listbox.insert(tk.END, "(nenhum quadro ativo)")

    def _ingressar(self):
        sel = self._listbox.curselection()
        if not sel or not self._boards:
            return
        board = self._boards[sel[0]]
        if self.app.client.ingressar_em_quadro(board):
            self.app.mostrar(TelaQuadro, nome=board["name"])
        else:
            messagebox.showerror("Erro", "Não foi possível ingressar (coordenador indisponível).")
            self._atualizar()


class TelaQuadro(tk.Frame):
    """
    Canvas colaborativo + toolbar. Mantém um espelho local dos objetos para
    redesenhar; cada item do canvas leva o object_id como tag para hit-test.
    """

    def __init__(self, master, app, nome=""):
        super().__init__(master)
        self.app = app
        self.client = app.client
        self.nome = nome

        self.objetos = {}          # object_id -> {id, shape, points, color}
        self.ferramenta = "linha"  # 'linha' | 'quadrado' | 'selecionar'
        self.cor_atual = COR_A
        self.pontos_temp = []      # cliques acumulados para linha/quadrado
        self.selecionado = None    # object_id selecionado
        self._contador = 0         # para gerar ids únicos por nó

        self._montar_toolbar()
        self._montar_canvas()
        self._montar_status()
        self._redesenhar()

    # ── Layout ────────────────────────────────────────────────────────
    def _montar_toolbar(self):
        tb = tk.Frame(self, bd=1, relief="raised")
        tb.pack(side="top", fill="x")

        tk.Button(tb, text="Linha", width=8,
                  command=lambda: self._set_ferramenta("linha")).pack(side="left", padx=2, pady=4)
        tk.Button(tb, text="Quadrado", width=8,
                  command=lambda: self._set_ferramenta("quadrado")).pack(side="left", padx=2)
        tk.Button(tb, text="Selecionar", width=10,
                  command=lambda: self._set_ferramenta("selecionar")).pack(side="left", padx=2)

        tk.Label(tb, text="  Cor:").pack(side="left")
        tk.Button(tb, bg=COR_A, width=3, command=lambda: self._set_cor(COR_A)).pack(side="left", padx=2)
        tk.Button(tb, bg=COR_B, width=3, command=lambda: self._set_cor(COR_B)).pack(side="left", padx=2)

        tk.Button(tb, text="Remover", width=8, command=self._remover).pack(side="left", padx=12)

    def _montar_canvas(self):
        self.canvas = tk.Canvas(self, bg="white", cursor="cross")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._clique)

    def _montar_status(self):
        self.status = tk.Label(self, anchor="w", relief="sunken", bd=1)
        self.status.pack(side="bottom", fill="x")
        self._atualizar_status()

    def _atualizar_status(self):
        papel = "COORDENADOR" if self.client.sou_coordenador else "cliente"
        sel = f" | sel: {self.selecionado}" if self.selecionado else ""
        self.status.config(
            text=f"Quadro: {self.nome}  [{papel}]  | ferramenta: {self.ferramenta}"
                 f"  | cor: {self.cor_atual}{sel}")

    # ── Toolbar handlers ──────────────────────────────────────────────
    def _set_ferramenta(self, f):
        self.ferramenta = f
        self.pontos_temp = []
        self._atualizar_status()

    def _set_cor(self, cor):
        self.cor_atual = cor
        # Se há objeto selecionado, aplicar a cor a ele (exclusão mútua via Client)
        if self.selecionado:
            self.client.colorir(self.selecionado, cor)
        self._atualizar_status()

    def _remover(self):
        if not self.selecionado:
            messagebox.showinfo("Remover", "Selecione um objeto primeiro.")
            return
        oid = self.selecionado
        if self.client.remover(oid):
            self.selecionado = None
        self._atualizar_status()

    # ── Interação no canvas ───────────────────────────────────────────
    def _clique(self, event):
        if self.ferramenta == "selecionar":
            self._selecionar_em(event.x, event.y)
            return

        self.pontos_temp.append([event.x, event.y])
        if len(self.pontos_temp) == 2:
            obj = {
                "id": self._novo_id(),
                "shape": "line" if self.ferramenta == "linha" else "square",
                "points": list(self.pontos_temp),
                "color": self.cor_atual,
            }
            self.pontos_temp = []
            self.client.desenhar(obj)   # atualiza réplica + broadcast; eco volta via _aplicar_na_gui

    def _selecionar_em(self, x, y):
        itens = self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3)
        for item in reversed(itens):
            tags = self.canvas.gettags(item)
            if tags:
                self.selecionado = tags[0]
                self._redesenhar()
                self._atualizar_status()
                return
        self.selecionado = None
        self._redesenhar()
        self._atualizar_status()

    def _novo_id(self):
        self._contador += 1
        return f"{self.client.node_id}-{self._contador}"

    # ── Renderização ──────────────────────────────────────────────────
    def _redesenhar(self):
        self.canvas.delete("all")
        for oid, obj in self.objetos.items():
            self._desenhar_obj(obj, destaque=(oid == self.selecionado))

    def _desenhar_obj(self, obj, destaque=False):
        (x1, y1), (x2, y2) = obj["points"]
        cor = obj["color"]
        largura = 4 if destaque else 2
        if obj["shape"] == "line":
            self.canvas.create_line(x1, y1, x2, y2, fill=cor, width=largura, tags=(obj["id"],))
        else:
            self.canvas.create_rectangle(x1, y1, x2, y2, outline=cor, width=largura, tags=(obj["id"],))
        if destaque:
            self.canvas.create_rectangle(
                min(x1, x2) - 5, min(y1, y2) - 5, max(x1, x2) + 5, max(y1, y2) + 5,
                outline="#888", dash=(3, 3))

    # ── Callbacks de rede (chamados via App, já na thread do tkinter) ──
    def carregar_estado(self, objetos):
        self.objetos = {o["id"]: o for o in objetos}
        self._redesenhar()

    def receber_draw(self, obj):
        self.objetos[obj["id"]] = obj
        self._redesenhar()

    def receber_remove(self, object_id):
        self.objetos.pop(object_id, None)
        if self.selecionado == object_id:
            self.selecionado = None
        self._redesenhar()

    def receber_color(self, object_id, color):
        if object_id in self.objetos:
            self.objetos[object_id]["color"] = color
        self._redesenhar()

    def atualizar_papel(self, sou_coord, ip, port):
        self._atualizar_status()
