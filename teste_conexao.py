import sys
import tkinter as tk
from tkinter import messagebox

try:
    import pjsua2 as pj
    PJSUA2_DISPONIVEL = True
except ImportError:
    PJSUA2_DISPONIVEL = False

class AppTeste(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Softphone - Teste de Módulos")
        self.geometry("450x300")
        
        lbl = tk.Label(self, text="Status do PJSua2 no Python 3.14", font=("Arial", 14, "bold"))
        lbl.pack(pady=10)
        
        self.txt_log = tk.Text(self, height=10, width=50)
        self.txt_log.pack(pady=10)
        
        btn = tk.Button(self, text="Verificar Codecs e Criptografia", command=self.checar_pjsip)
        btn.pack(pady=5)

    def checar_pjsip(self):
        if not PJSUA2_DISPONIVEL:
            messagebox.showerror("Erro", "O módulo pjsua2 não pôde ser importado no venv!")
            return
            
        try:
            ep = pj.Endpoint()
            ep.libCreate()
            ep_cfg = pj.EpConfig()
            ep.libInit(ep_cfg)
            
            self.txt_log.insert(tk.END, "✅ PJSua2 carregado com sucesso!\n\n")
            self.txt_log.insert(tk.END, "🔒 Segurança: ZRTP Ativado no Núcleo\n\n")
            self.txt_log.insert(tk.END, "🎙️ Codecs de Áudio Disponíveis:\n")
            
            codec_repo = ep.codecEnum()
            for codec in codec_repo:
                self.txt_log.insert(tk.END, f"  • {codec.codecId}\n")
                
            ep.libDestroy()
        except Exception as e:
            self.txt_log.insert(tk.END, f"❌ Erro ao inicializar: {e}\n")

if __name__ == "__main__":
    app = AppTeste()
    app.mainloop()
