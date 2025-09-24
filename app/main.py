import logging
import sys
import os
from datetime import datetime
from fastapi import FastAPI
from pythonjsonlogger import jsonlogger

from app.webhook import router as webhook_router
from app.services.gcp_service import initialize_vertexai

log = logging.getLogger()
log.setLevel(logging.INFO)

if not log.handlers:
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')
    console_handler.setFormatter(console_formatter)
    log.addHandler(console_handler)
    
    logs_dir = "logs"
    os.makedirs(logs_dir, exist_ok=True)
    
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(logs_dir, f"bot_metrics_{today}.jsonl")
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_formatter = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')
    file_handler.setFormatter(file_formatter)
    log.addHandler(file_handler)
    
    print(f"📁 Logs sendo salvos em: {log_file}")

app = FastAPI(
    title="Darwin Interview Bot",
    description="Um bot de WhatsApp para simulação de entrevistas com feedback via IA.",
    version="1.0.0"
)

@app.on_event("startup")
def on_startup():
    """
    Executa ações quando a aplicação inicia.
    Aqui, garantimos que o SDK do Vertex AI seja inicializado.
    """
    log.info("Aplicação iniciando...")
    if not initialize_vertexai():
        log.critical("A APLICAÇÃO NÃO PODE INICIAR: Falha ao inicializar o Vertex AI.")
    else:
        log.info("Inicialização completa. Aplicação pronta.")


app.include_router(webhook_router, prefix="/webhook", tags=["Twilio Webhook"])

@app.get("/", tags=["Health Check"])
def read_root():
    """Endpoint raiz para verificar se a aplicação está no ar."""
    return {"status": "ok", "message": "Darwin Interview Bot is running"}
