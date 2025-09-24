import logging
from functools import lru_cache
from twilio.rest import Client
import requests

# Importa o objeto 'settings' que conterá todas as nossas variáveis de ambiente.
# Este será nosso ponto central de configuração.
from app.config import settings

log = logging.getLogger(__name__)


@lru_cache()
def get_twilio_client():
    """
    Cria e retorna um cliente Twilio.
    Usa @lru_cache para garantir que o cliente seja instanciado apenas uma vez (singleton),
    melhorando a performance. Isso é fundamental para a injeção de dependências do FastAPI.
    """
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        log.critical("Credenciais da Twilio (SID ou Auth Token) não encontradas nas variáveis de ambiente.")
        return None
    
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        log.info("Cliente Twilio inicializado com sucesso.")
        return client
    except Exception as e:
        log.critical("Falha ao inicializar o cliente Twilio", extra={"error": str(e)})
        return None


def enviar_mensagem_longa(twilio_client, destinatario: str, texto_completo: str):
    """
    Divide um texto longo em várias mensagens menores que 1600 caracteres
    e as envia via Twilio, tentando quebrar por parágrafos.
    """
    if not twilio_client:
        log.error("Não foi possível enviar mensagem pois o cliente Twilio não está disponível.")
        return

    limite = 1500
    
    if len(texto_completo) <= limite:
        try:
            twilio_client.messages.create(
                from_=settings.TWILIO_WHATSAPP_NUMBER,
                body=texto_completo,
                to=destinatario
            )
        except Exception as e:
            log.error("Erro ao enviar mensagem simples via Twilio", extra={"error": str(e), "recipient": destinatario})
        return

    log.info("Texto longo detectado, dividindo em várias mensagens", extra={"recipient": destinatario, "text_length": len(texto_completo)})
    
    paragrafos = texto_completo.split('\n\n')
    mensagem_atual = ""

    for i, paragrafo in enumerate(paragrafos):
        if len(paragrafo) > limite:
            if mensagem_atual.strip():
                twilio_client.messages.create(from_=settings.TWILIO_WHATSAPP_NUMBER, body=mensagem_atual.strip(), to=destinatario)
                mensagem_atual = ""

            palavras = paragrafo.split(' ')
            chunk_atual = ""
            for palavra in palavras:
                if len(chunk_atual) + len(palavra) + 1 <= limite:
                    chunk_atual += f" {palavra}" if chunk_atual else palavra
                else:
                    twilio_client.messages.create(from_=settings.TWILIO_WHATSAPP_NUMBER, body=chunk_atual, to=destinatario)
                    chunk_atual = palavra
            if chunk_atual:
                twilio_client.messages.create(from_=settings.TWILIO_WHATSAPP_NUMBER, body=chunk_atual, to=destinatario)

        elif len(mensagem_atual) + len(paragrafo) + 2 > limite:
            if mensagem_atual.strip():
                twilio_client.messages.create(from_=settings.TWILIO_WHATSAPP_NUMBER, body=mensagem_atual.strip(), to=destinatario)
            mensagem_atual = paragrafo + "\n\n"
        
        else:
            mensagem_atual += paragrafo + "\n\n"

    if mensagem_atual.strip():
        try:
            twilio_client.messages.create(
                from_=settings.TWILIO_WHATSAPP_NUMBER,
                body=mensagem_atual.strip(),
                to=destinatario
            )
        except Exception as e:
            log.error("Erro ao enviar parte final da mensagem longa", extra={"error": str(e), "recipient": destinatario})

    log.info("Envio de mensagem longa concluído", extra={"recipient": destinatario})


def download_twilio_media(media_url: str) -> bytes | None:
    """
    Baixa o conteúdo de uma mídia (áudio) da Twilio usando as credenciais da conta.
    Retorna o conteúdo em bytes ou None em caso de erro.
    """
    try:
        auth = (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        response = requests.get(media_url, auth=auth, timeout=10)
        response.raise_for_status()
        log.info("Mídia da Twilio baixada com sucesso", extra={"media_url": media_url})
        return response.content
    except requests.exceptions.RequestException as e:
        log.error("Erro ao baixar mídia da Twilio", extra={"error": str(e), "media_url": media_url})
        return None
