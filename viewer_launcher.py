
import json
import os
import re
import shutil
import socket
import sqlite3
import sys
import threading
import time
import tkinter as tk
import webbrowser

from contextlib import closing
from pathlib import Path
from tkinter import messagebox, ttk


# Compatibilidade com executaveis PyInstaller --windowed.
# Nesse modo, stdout e stderr podem estar indisponiveis.

PASTA_LOG = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    / "MaintenanceQualityViewer"
)

PASTA_LOG.mkdir(parents=True, exist_ok=True)

ARQUIVO_LOG = PASTA_LOG / "viewer.log"

if sys.stdout is None:
    sys.stdout = open(
        os.devnull,
        "w",
        encoding="utf-8",
    )

if sys.stderr is None:
    sys.stderr = open(
        ARQUIVO_LOG,
        "a",
        encoding="utf-8",
        buffering=1,
    )


import uvicorn


BASE_PUBLICACAO = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
PASTA_DADOS_REDE = Path(os.environ.get("MQI_PUBLICACAO_DIR", BASE_PUBLICACAO / "data" / "publicado")).resolve()
MANIFESTO_REDE = PASTA_DADOS_REDE / "versao.json"

CACHE = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    / "MaintenanceQualityViewer"
)

PASTA_CACHE = CACHE / "data"
ARQUIVO_CACHE = CACHE / "ultimo_banco.json"

PADRAO_BANCO = re.compile(
    r"quality_[0-9a-f]{12}\.db"
)

servidor = None


def validar_nome(nome):
    if (
        not isinstance(nome, str)
        or not PADRAO_BANCO.fullmatch(nome)
    ):
        raise ValueError(
            "Nome de banco invalido no manifesto."
        )

    return nome


def verificar_banco(caminho):
    if not caminho.is_file():
        raise FileNotFoundError(caminho)

    # A verificacao ocorre em arquivo local.
    with closing(
        sqlite3.connect(
            caminho.as_uri() + "?mode=ro",
            uri=True,
            timeout=15,
        )
    ) as conn:

        resultado = conn.execute(
            "PRAGMA quick_check"
        ).fetchone()[0]

        if resultado != "ok":
            raise RuntimeError(
                "Falha de integridade do SQLite."
            )

        conn.execute(
            "SELECT COUNT(*) FROM avaliacoes"
        ).fetchone()

    return True


def obter_banco():
    PASTA_CACHE.mkdir(
        parents=True,
        exist_ok=True
    )

    # Tenta obter a publicacao mais recente.
    try:
        manifesto = json.loads(
            MANIFESTO_REDE.read_text(
                encoding="utf-8"
            )
        )

        nome = validar_nome(
            manifesto["arquivo"]
        )

        origem = PASTA_DADOS_REDE / nome
        destino = PASTA_CACHE / nome

        if not destino.is_file():
            temporario = (
                PASTA_CACHE
                / f"{nome}.{os.getpid()}.tmp"
            )

            try:
                shutil.copyfile(
                    origem,
                    temporario
                )

                verificar_banco(temporario)

                os.replace(
                    temporario,
                    destino
                )

            finally:
                if temporario.exists():
                    temporario.unlink()

        else:
            verificar_banco(destino)

        ARQUIVO_CACHE.write_text(
            json.dumps(
                {
                    "arquivo": nome,
                    "publicado_em": manifesto.get(
                        "publicado_em"
                    )
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return destino, False, manifesto

    except Exception as erro:
        # Se a rede falhar, utiliza a ultima
        # copia local previamente validada.
        if not ARQUIVO_CACHE.is_file():
            raise RuntimeError(
                "Nao foi possivel acessar a rede "
                "e nao existe banco local salvo."
            ) from erro

        info = json.loads(
            ARQUIVO_CACHE.read_text(
                encoding="utf-8"
            )
        )

        nome = validar_nome(info["arquivo"])
        destino = PASTA_CACHE / nome

        verificar_banco(destino)

        return destino, True, info


def preparar_socket():
    # Solicita ao Windows uma porta local livre.
    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    sock.bind(("127.0.0.1", 0))
    sock.listen(128)

    return sock


def iniciar_api(sock):
    global servidor

    from viewer_api import app

    
    configuracao = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        loop="asyncio",
        http="h11",
        log_level="warning",
        access_log=False,
        lifespan="off",
        log_config=None,
    )


    servidor = uvicorn.Server(configuracao)

    servidor.run(sockets=[sock])


def main():
    global servidor

    try:
        banco, offline, info = obter_banco()
    except Exception as erro:
        janela_erro = tk.Tk()
        janela_erro.withdraw()

        messagebox.showerror(
            "Maintenance Quality Viewer",
            str(erro)
        )

        janela_erro.destroy()
        return

    # O viewer_api le esta variavel
    # ao abrir as conexoes SQLite.
    os.environ["MQI_VIEWER_DB"] = str(banco)

    sock = preparar_socket()
    porta = sock.getsockname()[1]

    thread = threading.Thread(
        target=iniciar_api,
        args=(sock,),
        daemon=True,
        name="mqi-viewer-api",
    )

    thread.start()

    # Aguarda a inicializacao da API.
    for _ in range(100):
        if servidor is not None and servidor.started:
            break

        if not thread.is_alive():
            break

        time.sleep(0.1)

    if servidor is None or not servidor.started:
        sock.close()
        janela_erro = tk.Tk()
        janela_erro.withdraw()

        messagebox.showerror(
            "Maintenance Quality Viewer",
            "Nao foi possivel iniciar o dashboard."
        )

        janela_erro.destroy()
        return

    endereco = (
        f"http://127.0.0.1:{porta}/dashboard"
    )

    janela = tk.Tk()
    janela.title("Maintenance Quality Viewer")
    janela.geometry("480x260")
    janela.resizable(False, False)

    quadro = ttk.Frame(
        janela,
        padding=24
    )
    quadro.pack(
        fill="both",
        expand=True
    )

    ttk.Label(
        quadro,
        text="Maintenance Quality Intelligence",
        font=("Segoe UI", 12, "bold"),
        wraplength=420,
    ).pack(pady=(0, 12))

    situacao = (
        "Modo offline: ultima copia local"
        if offline
        else "Dados atualizados pela rede"
    )

    ttk.Label(
        quadro,
        text=situacao
    ).pack(pady=5)

    ttk.Label(
        quadro,
        text=(
            "Publicacao: "
            + str(info.get("publicado_em", "Nao informado"))
        )
    ).pack(pady=5)

    ttk.Label(
        quadro,
        text="Acesso somente leitura",
    ).pack(pady=5)

    ttk.Button(
        quadro,
        text="Abrir dashboard",
        command=lambda: webbrowser.open(endereco),
    ).pack(
        fill="x",
        pady=(12, 6),
    )

    def encerrar():
        if servidor is not None:
            servidor.should_exit = True

        janela.destroy()

    ttk.Button(
        quadro,
        text="Encerrar visualizador",
        command=encerrar,
    ).pack(fill="x")

    janela.protocol(
        "WM_DELETE_WINDOW",
        encerrar
    )

    janela.after(
        500,
        lambda: webbrowser.open(endereco)
    )

    janela.mainloop()


if __name__ == "__main__":
    main()
