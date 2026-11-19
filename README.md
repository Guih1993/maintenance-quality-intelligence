# Maintenance Quality Intelligence

Painel local para avaliar a documentação de ordens de serviço de manutenção. Permite acompanhar cobertura, evolução das notas, encerramento e desempenho por critério. A demonstração reúne 60 ordens fictícias, três técnicos simulados e 54 avaliações ilustrativas. As seis ordens restantes permitem experimentar a classificação local com IA.

## Executar a demonstração no Windows

Em uma cópia nova do projeto, abra o PowerShell na pasta deste README. Com Python 3.12 instalado, execute:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
New-Item -ItemType Directory -Force data/incoming
Copy-Item examples/ordens_demo.csv data/incoming/DADOS_EXPORTADOS.csv
Copy-Item examples/avaliacoes_demo.csv data/incoming/HISTORICO_AVALIACOES.csv
.\.venv\Scripts\python -m scripts.init_database
.\.venv\Scripts\python -m backend.ingestion.importer
.\.venv\Scripts\python -m scripts.importar_historico_unificado --aplicar
.\.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Abra http://127.0.0.1:8000/dashboard. Na consulta por período, selecione as datas da coluna OS_DATA_ORIGINAL dos exemplos.

## Usar dados próprios

Comece em uma instalação separada e inicialize o banco com scripts.init_database. Exporte uma linha por combinação de FILIAL e ORDEM_SERVICO para data/incoming/DADOS_EXPORTADOS.csv. Siga o cabeçalho de examples/ordens_demo.csv, em UTF-8, com vírgula como delimitador. Use datas no formato AAAA-MM-DD, SIM ou NAO no encerramento e uma barra vertical entre técnicos. QTD_TECNICOS deve refletir o número de nomes distintos. OS_USUARIO_INICIO é opcional.

Mapeie as corretivas emergenciais para C01 e as corretivas não programadas para C05. O classificador seleciona essas duas categorias. Use a aba Classificar para atualizar o CSV após cada exportação. Para incorporar avaliações anteriores, siga o exemplo de histórico separado por ponto e vírgula. Execute o importador histórico sem --aplicar para simular a carga.

A rubrica em prompts/avaliacao_os_v1.txt atribui de 0 a 2 pontos a componente, anomalia, causa/evidência, intervenção, teste e clareza. O score corresponde à soma dividida por 12, multiplicada por 100. Para gerar novas avaliações, execute Ollama localmente na porta 11434, instale o modelo com `ollama pull qwen3:4b` e use a aba Classificar. A consulta aos exemplos funciona sem o modelo.

## Visualizador de consulta

Na aplicação principal, a publicação cria uma cópia SQLite em data/publicado. Para escolher outro destino, configure MQI_PUBLICACAO_DIR com o caminho absoluto da pasta antes de iniciar a aplicação e o visualizador. Depois da primeira publicação, execute `.\.venv\Scripts\python viewer_launcher.py` para abrir o visualizador. O visualizador usa uma cópia local e pode consultar a última publicação recebida quando estiver offline.

## Verificação

Execute `.\.venv\Scripts\python -m unittest discover -s tests`. O repositório inclui apenas os CSVs sintéticos em examples. Os arquivos de trabalho, bancos, publicações, logs e ambientes locais estão no .gitignore.
