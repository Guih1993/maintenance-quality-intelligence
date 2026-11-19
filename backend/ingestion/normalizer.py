
import hashlib
import json
import re
from datetime import datetime


def limpar_texto(valor):
    if valor is None:
        return ""
    return str(valor).strip()


def normalizar_relato(valor):
    texto = limpar_texto(valor)
    return re.sub(r"\s+", " ", texto)


def normalizar_data(valor):
    valor = limpar_texto(valor)

    if not valor:
        return None

    formatos = [
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]

    for formato in formatos:
        try:
            data = datetime.strptime(valor, formato)

            if data.year == 1900:
                return None

            return data.date().isoformat()
        except ValueError:
            continue

    raise ValueError(f"Data inválida: {valor}")


def gerar_hash_avaliacao(registro):
    campos = {
        "relato": registro["observacao_normalizada"],
        "bem_codigo": registro["bem_codigo"],
        "bem_nome": registro["bem_nome"],
        "servico_nome": registro["servico_nome"],
    }

    conteudo = json.dumps(
        campos,
        ensure_ascii=False,
        sort_keys=True,
    )

    return hashlib.sha256(
        conteudo.encode("utf-8")
    ).hexdigest()


def separar_tecnicos(valor):
    nomes = [
        limpar_texto(nome)
        for nome in limpar_texto(valor).split("|")
    ]

    return list(dict.fromkeys(
        nome for nome in nomes if nome
    ))
