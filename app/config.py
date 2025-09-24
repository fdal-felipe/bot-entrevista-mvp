import logging
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

class Settings(BaseSettings):
    """
    Carrega e valida as variáveis de ambiente da aplicação a partir de um arquivo .env.
    """
    
    ID_PROJETO: str
    NOME_ARQUIVO_CHAVE: str = "google_credentials.json"

    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_WHATSAPP_NUMBER: str

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    @property
    def CELERY_BROKER_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')

try:
    settings = Settings()
    log.info("Configurações da aplicação carregadas com sucesso.")
except Exception as e:
    log.critical(f"Erro fatal ao carregar as configurações (.env): {e}. A aplicação não pode iniciar.")
    settings = None
