import logging
from functools import lru_cache
from google.oauth2 import service_account
from google.cloud import speech
import vertexai
from vertexai.generative_models import GenerativeModel

from app.config import settings

log = logging.getLogger(__name__)


@lru_cache()
def get_gcp_credentials():
    """
    Carrega as credenciais do Google Cloud a partir do arquivo de chave de serviço.
    Usa @lru_cache para garantir que o arquivo seja lido do disco apenas uma vez.
    """
    try:
        credentials = service_account.Credentials.from_service_account_file(settings.NOME_ARQUIVO_CHAVE)
        log.info("Credenciais do Google Cloud carregadas com sucesso.")
        return credentials
    except FileNotFoundError:
        log.critical(f"Arquivo de credenciais '{settings.NOME_ARQUIVO_CHAVE}' não encontrado.")
        return None
    except Exception as e:
        log.critical("Erro ao carregar as credenciais do Google Cloud", extra={"error": str(e)})
        return None


@lru_cache()
def get_speech_client():
    """
    Cria e retorna um cliente para a API Google Cloud Speech-to-Text.
    Reutiliza a instância do cliente para melhor performance.
    """
    credentials = get_gcp_credentials()
    if not credentials:
        return None
    
    try:
        client = speech.SpeechClient(credentials=credentials)
        log.info("Cliente Google Speech-to-Text inicializado com sucesso.")
        return client
    except Exception as e:
        log.critical("Falha ao inicializar o cliente Speech-to-Text", extra={"error": str(e)})
        return None


def initialize_vertexai():
    """
    Inicializa o SDK do Vertex AI com as credenciais e projeto corretos.
    Deve ser chamada uma vez durante o startup da aplicação.
    """
    credentials = get_gcp_credentials()
    if not credentials or not settings.ID_PROJETO:
        log.critical("Não foi possível inicializar o Vertex AI. Credenciais ou ID do projeto ausentes.")
        return False
    
    try:
        vertexai.init(project=settings.ID_PROJETO, credentials=credentials, location="us-central1")
        log.info("Vertex AI SDK inicializado com sucesso.")
        return True
    except Exception as e:
        log.critical("Falha ao inicializar o Vertex AI SDK", extra={"error": str(e)})
        return False


def transcrever_audio_gcp(audio_content: bytes) -> str:
    """
    Transcreve um conteúdo de áudio em bytes usando a API do Google Speech-to-Text.
    
    Args:
        audio_content: O conteúdo do áudio no formato de bytes.

    Returns:
        A transcrição em texto ou uma string vazia em caso de falha.
    """
    speech_client = get_speech_client()
    if not speech_client:
        log.error("Cliente Speech-to-Text não disponível para transcrição.")
        return ""

    try:
        audio_para_api = speech.RecognitionAudio(content=audio_content)
        config_api = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
            sample_rate_hertz=16000,
            language_code="pt-BR",
            model="default"
        )

        response = speech_client.recognize(config=config_api, audio=audio_para_api)

        if response.results and response.results[0].alternatives:
            transcricao = response.results[0].alternatives[0].transcript
            log.info("Áudio transcrito com sucesso", extra={"transcription_length": len(transcricao)})
            return transcricao
        else:
            log.warning("Transcrição de áudio não retornou resultados.")
            return ""
    except Exception as e:
        log.error("Erro na chamada da API de transcrição do Google", extra={"error": str(e)})
        return ""
