import tkinter as tk
from tkinter import scrolledtext
import subprocess
import threading
import sys
import os
import shutil

# --- KONFIGURATION ---
SOURCE_FOLDER = r"I:\01_Listen"  # Quelle deiner Excel-Dateien
FILES_TO_SYNC = [
    "Filme_Rosi_2025_DE.xlsx",
    "Serien_Rosi_2025.xlsx"
]
# ---------------------

class GitUploaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CouchPilot Cloud Sync")
        self.root.geometry("600x450")
        
        tk.Label(root, text="CouchPilot Cloud Upload", font=("Arial", 14, "bold")).pack(pady=10)
        
        self.txt_log = scrolledtext.ScrolledText(root, state='disabled', height=15)
        self.txt_log.pack(padx=10, pady=5, fill="both", expand=True)

        self.btn_start = tk.Button(root, text="1. Daten holen & 2. Hochladen", command=self.start_update_thread, 
                                   bg="#4CAF50", fg="white", font=("Arial", 12, "bold"))
        self.btn_start.pack(pady=10, fill="x", padx=50)

        self.lbl_status = tk.Label(root, text="Bereit.", fg="gray")
        self.lbl_status.pack(pady=5)

    def log(self, message):
        self.txt_log.config(state='normal')
        self.txt_log.insert(tk.END, message + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state='disabled')

    def copy_files(self):
        self.log("--- SCHRITT 1: Kopiere Excel-Dateien ---")
        if not os.path.exists(SOURCE_FOLDER):
            self.log(f"❌ Quelle nicht gefunden: {SOURCE_FOLDER}")
            return False
            
        count = 0
        for f in FILES_TO_SYNC:
            src = os.path.join(SOURCE_FOLDER, f)
            if os.path.exists(src):
                try:
                    shutil.copy2(src, f)
                    self.log(f"✅ Kopiert: {f}")
                    count += 1
                except Exception as e:
                    self.log(f"❌ Fehler bei {f}: {e}")
            else:
                self.log(f"⚠️ Datei fehlt in Quelle: {f}")
        return count > 0

    def git_cmd(self, args, desc):
        self.log(f"--- {desc} ---")
        try:
            # Creationflags verhindern aufpoppende Fenster
            flags = 0x08000000 if sys.platform == "win32" else 0
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=flags)
            out, err = p.communicate()
            if out: self.log(out.strip())
            if err: self.log(err.strip())
            return p.returncode
        except Exception as e:
            self.log(f"❌ Systemfehler: {e}")
            return -1

    def run_process(self):
        if not self.copy_files():
            self.lbl_status.config(text="Fehler beim Kopieren", fg="red")
            self.btn_start.config(state="normal")
            return

        # Git Workflow
        self.git_cmd(["git", "pull"], "Git Pull (Aktualisieren)")
        self.git_cmd(["git", "add", "."], "Git Add (Vorbereiten)")
        self.git_cmd(["git", "commit", "-m", "Auto-Update Excel Lists"], "Git Commit (Bestätigen)")
        
        code = self.git_cmd(["git", "push"], "Git Push (Hochladen)")
        
        if code == 0:
            self.log("\n✅ ERFOLGREICH! Daten sind online.")
            self.lbl_status.config(text="Upload fertig!", fg="green")
        else:
            self.log("\n⚠️ Warnung: Push hatte Probleme (oder nichts Neues).")
            self.lbl_status.config(text="Fertig (mit Hinweisen)", fg="orange")
            
        self.btn_start.config(state="normal")

    def start_update_thread(self):
        self.btn_start.config(state="disabled")
        self.lbl_status.config(text="Arbeite...", fg="blue")
        threading.Thread(target=self.run_process, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    GitUploaderApp(root)
    root.mainloop()