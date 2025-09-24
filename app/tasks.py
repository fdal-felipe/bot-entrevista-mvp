import json
import logging
import time
from celery import Celery
from celery.utils.log import get_task_logger
from vertexai.generative_models import GenerativeModel

from app.config import settings
from app.services.redis_service import get_redis_client
from app.models import UserState
from app.services.twilio_service import get_twilio_client, enviar_mensagem_longa
from app.services.gcp_service import initialize_vertexai

celery_app = Celery('tasks', broker=settings.CELERY_BROKER_URL, backend=settings.CELERY_BROKER_URL)
log = get_task_logger(__name__)

@celery_app.task
def tarefa_gerar_perguntas(user_key, contexto, last_user_ts=None):
    """
    Worker que gera as perguntas da entrevista em segundo plano.
    Agora recebe last_user_ts para decidir se pode enviar a pergunta imediatamente
    (janela de 24h). Caso contrário, marca perguntas_prontas para que o webhook
    envie quando o usuário voltar.
    """
    log.info("Iniciando task: gerar perguntas", extra={"user_id": user_key, "contexto_length": len(contexto)})
    r = get_redis_client()
    if not r:
        log.error("Task falhou: Redis não disponível.", extra={"user_id": user_key})
        return

    user_state_json = r.get(user_key)
    if user_state_json:
        try:
            user_state = UserState.model_validate_json(user_state_json)
        except Exception as e:
            log.error("Erro ao deserializar estado do usuário", extra={"user_id": user_key, "error": str(e)})
            user_state = UserState(user_key=user_key, contexto=contexto, etapa='preparando_perguntas')
    else:
        user_state = UserState(user_key=user_key, contexto=contexto, etapa='preparando_perguntas')

    if last_user_ts:
        user_state.last_user_ts = last_user_ts

    twilio_client = get_twilio_client()
    if not initialize_vertexai() or not twilio_client:
        log.error("Falha ao inicializar serviços (Vertex AI ou Twilio)", extra={"user_id": user_key})
        user_state.erro_geracao = "Erro de configuração interna."
        r.set(user_key, user_state.model_dump_json())
        return

    try:
        model = GenerativeModel("gemini-2.5-flash-lite")
        prompt = f"""
        Você é um recrutador técnico sênior. Baseado no seguinte contexto de um candidato: '{contexto}'.
        Gere exatamente 3 perguntas de entrevista (2 de soft skill e 1 de hard skill) no formato JSON array:
        {{"perguntas": ["pergunta1", "pergunta2", "pergunta3"]}}
        """
        response = model.generate_content(prompt)
        json_response_text = response.text.strip().replace("```json", "").replace("```", "")
        perguntas_dict = json.loads(json_response_text)
        perguntas = perguntas_dict.get("perguntas", [])

        if perguntas and len(perguntas) == 3:
            user_state.perguntas = perguntas
            user_state.respostas = []
            log.info("Perguntas geradas com sucesso", extra={"user_id": user_key, "questions_count": len(perguntas)})

            user_state.perguntas_prontas = True
        else:
            raise ValueError("Formato de resposta inesperado da IA.")
    except Exception as e:
        log.error(
            "Erro na task de geração de perguntas", 
            exc_info=True, 
            extra={"user_id": user_key, "error": str(e), "error_type": type(e).__name__}
        )
        user_state.etapa = 'aguardando_contexto'
        user_state.contexto = None
        user_state.erro_geracao = "Não consegui gerar as perguntas com base no seu contexto. Poderia tentar descrevê-lo de outra forma?"

    try:
        r.set(user_key, user_state.model_dump_json())
        log.info("Estado do usuário salvo no Redis", extra={"user_id": user_key, "etapa": user_state.etapa})
    except Exception as e:
        log.error("Erro ao salvar estado no Redis", extra={"user_id": user_key, "error": str(e)})


@celery_app.task
def tarefa_gerar_feedback(user_key):
    """
    Worker que analisa as respostas e gera o feedback final.
    Utiliza o modelo UserState para carregar e salvar os dados de forma segura.
    """
    log.info("Iniciando task: gerar feedback", extra={"user_id": user_key})
    r = get_redis_client()
    if not r:
        log.error("Task falhou: Redis não disponível.", extra={"user_id": user_key})
        return

    user_state_json = r.get(user_key)
    if not user_state_json:
        log.error("Estado do usuário não encontrado no Redis para a task.", extra={"user_id": user_key})
        return
    user_state = UserState.model_validate_json(user_state_json)

    if not all([user_state.contexto, user_state.perguntas, user_state.respostas]):
        log.error("Dados insuficientes para gerar feedback.", extra={"user_id": user_key})
        user_state.erro_feedback = "Dados da entrevista estavam incompletos."
        r.set(user_key, user_state.model_dump_json())
        return

    from app.services.gcp_service import initialize_vertexai
    initialize_vertexai()

    prompt = f"""
    Você é um coach de carreira especialista em recrutamento.
    
    **IMPORTANTE: Sua resposta deve ter NO MÁXIMO 1200 caracteres total.**
    
    Analise a entrevista e forneça feedback CONCISO e Realista para cada resposta:
    
    Contexto: {user_state.contexto}
    
    Entrevista:
    1. {user_state.perguntas[0]}
       → {user_state.respostas[0]}
    
    2. {user_state.perguntas[1]}
       → {user_state.respostas[1]}
       
    3. {user_state.perguntas[2]}
       → {user_state.respostas[2]}

    Para cada resposta: clareza% + 1 ponto forte + 1 melhoria (máximo 2 linhas cada).
    Use *negrito* e emojis, mas poucos.
    Termine pedindo feedback, sendo educado, sobre a experiência (exemplo: Espero que este feedback tenha ajudado!🙏 Sua opinião é ouro para nós. O que você achou da experiência?).
    
    LIMITE: 1200 caracteres no total.
    """
    try:
        model = GenerativeModel("gemini-2.5-flash-lite")
        response = model.generate_content(prompt)
        
        user_state.feedback_gerado = response.text
        
        log.info("Feedback gerado com sucesso", extra={
            "action": "feedback_generation_success",
            "user_id": user_key,
            "feedback_length": len(response.text)
        })

    except Exception as e:
        log.error("Erro na task de geração de feedback", extra={"user_id": user_key, "error": str(e)})
        user_state.erro_feedback = "Erro técnico ao gerar feedback."
    
    r.set(user_key, user_state.model_dump_json())
