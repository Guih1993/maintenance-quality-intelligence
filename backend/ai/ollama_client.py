
import httpx


OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3:4b"


def verificar_ollama():
    with httpx.Client(timeout=10.0) as client:
        resposta = client.get(
            f"{OLLAMA_URL}/api/tags"
        )
        resposta.raise_for_status()

        modelos = resposta.json().get("models", [])
        nomes = [m["name"] for m in modelos]

        if OLLAMA_MODEL not in nomes:
            raise RuntimeError(
                f"Modelo {OLLAMA_MODEL} não encontrado. "
                f"Disponíveis: {nomes}"
            )

        return True


def gerar_resposta(prompt, formato=None):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_ctx": 4096,
            "num_predict": 1024,
        },
    }

    if formato is not None:
        payload["format"] = formato

    with httpx.Client(timeout=300.0) as client:
        resposta = client.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
        )
        resposta.raise_for_status()

        dados = resposta.json()

        return {
            "resposta": dados.get("response", ""),
            "modelo": dados.get("model"),
            "tempo_total_ns": dados.get("total_duration"),
            "tokens_entrada": dados.get("prompt_eval_count"),
            "tokens_saida": dados.get("eval_count"),
        }
