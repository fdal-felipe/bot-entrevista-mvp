import logging
import time
from fastapi import APIRouter, Form, Response, Depends, Request
from twilio.twiml.messaging_response import MessagingResponse
from app.models import UserState
from app.state_machine import STATE_HANDLERS
from app.services.redis_service import get_redis_client
from app.services.twilio_service import get_twilio_client, download_twilio_media, enviar_mensagem_longa
from app.services.gcp_service import transcrever_audio_gcp
from app.tasks import tarefa_gerar_perguntas

log = logging.getLogger(__name__)
router = APIRouter()

@router.post("/twilio")
async def handle_twilio_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(None),
    NumMedia: int = Form(0),
    MediaUrl0: str = Form(None),
    r: object = Depends(get_redis_client),
    twilio_client: object = Depends(get_twilio_client)
):
    """
    Recebe, processa e orquestra as mensagens do WhatsApp.
    Este endpoint agora atua como um controlador, delegando a lógica
    de negócio para a máquina de estados.
    """
    user_key = From
    response_twiml = MessagingResponse()

    log.info("Webhook recebido", extra={
        "user_id": user_key, 
        "body": Body, 
        "num_media": NumMedia, 
        "media_url": MediaUrl0,
        "body_length": len(Body) if Body else 0
    })

    resposta_usuario = Body.strip() if Body else ""
    
    if NumMedia > 0 and MediaUrl0:
        log.info("Processando mídia recebida", extra={"user_id": user_key, "media_url": MediaUrl0})
        response_twiml.message("Recebi seu áudio, um momento enquanto o transcrevo... 🎙️")
        audio_content = download_twilio_media(MediaUrl0)
        if audio_content:
            log.info("Mídia baixada com sucesso", extra={"user_id": user_key, "content_size": len(audio_content)})
            transcricao = transcrever_audio_gcp(audio_content)
            if transcricao and transcricao.strip():
                resposta_usuario = transcricao.strip()
                log.info("Áudio transcrito com sucesso", extra={"user_id": user_key, "transcription_length": len(resposta_usuario), "transcription": resposta_usuario})
            else:
                log.warning("Transcrição vazia ou falhou", extra={"user_id": user_key, "transcription": transcricao})
                response_twiml.message("Não consegui entender seu áudio. Por favor, tente falar mais claramente ou envie uma mensagem de texto.")
                return Response(content=str(response_twiml), media_type="application/xml")
        else:
            log.error("Falha no download da mídia", extra={"user_id": user_key})
            response_twiml.message("Não consegui processar seu áudio. Por favor, tente novamente.")
            return Response(content=str(response_twiml), media_type="application/xml")

    log.info("Resposta do usuário recebida", extra={"user_id": user_key, "response_type": "audio" if NumMedia > 0 else "text", "response_preview": resposta_usuario[:100]})

    user_state_json = r.get(user_key)
    if user_state_json:
        user_state = UserState.model_validate_json(user_state_json)
        log.info("Estado do usuário carregado", extra={"user_id": user_key, "current_state": user_state.etapa, "responses_count": len(user_state.respostas)})
    else:
        log.info("Novo usuário detectado", extra={
            "action": "new_user_detected",
            "user_id": user_key
        })
        user_state = UserState()

    prev_etapa = user_state.etapa

    user_state.user_key = user_key

    user_state.last_user_ts = int(time.time())

    if resposta_usuario.lower() in ['reiniciar', 'recomeçar', 'restart']:
        user_state = UserState(user_key=user_key)
        handler = STATE_HANDLERS.get(user_state.etapa)
        response_text = handler(user_state, resposta_usuario)
        log.info("Usuário reiniciou a conversa", extra={"user_id": user_key})
    else:
        handler = STATE_HANDLERS.get(user_state.etapa)
        if handler:
            log.info("Processando etapa do usuário", extra={"user_id": user_key, "etapa": user_state.etapa})
            
            if user_state.etapa == 'preparando_perguntas' and prev_etapa == 'aguardando_contexto':
                log.info("Entrevista iniciada", extra={
                    "action": "interview_started",
                    "user_id": user_key
                })
            
            if user_state.etapa == 'gerando_feedback':
                 response_text = handler(user_state, resposta_usuario, twilio_client)
            else:
                 response_text = handler(user_state, resposta_usuario)
        else:
            log.warning("Estado desconhecido encontrado, resetando usuário", extra={"user_id": user_key, "etapa": user_state.etapa})
            user_state = UserState(user_key=user_key)
            response_text = "Me perdi aqui. Vamos recomeçar para garantir que tudo corra bem. Me conte sua vaga, experiência e tecnologias."

    if user_state.etapa == 'finalizado':
        log.info("Ciclo do usuário finalizado. Removendo estado do Redis.", extra={"user_id": user_key})
        r.delete(user_key)
    else:
        r.set(user_key, user_state.model_dump_json())

    if user_state.etapa == 'preparando_perguntas' and prev_etapa == 'aguardando_contexto':
        try:
            tarefa_gerar_perguntas.delay(user_state.user_key, user_state.contexto, user_state.last_user_ts)
            log.info("Task tarefa_gerar_perguntas disparada", extra={"user_id": user_key})
        except Exception as e:
            log.error("Falha ao disparar tarefa de geração de perguntas", extra={"user_id": user_key, "error": str(e)})
            user_state.erro_geracao = "Erro ao iniciar geração de perguntas. Tente novamente."
            r.set(user_key, user_state.model_dump_json())

    if (getattr(user_state, "perguntas_prontas", False) and 
        user_state.etapa == "aguardando_resposta_1" and 
        twilio_client):
        try:
            texto = f"*Pergunta 1:*\n{user_state.perguntas[0]}"
            enviar_mensagem_longa(twilio_client, user_key, texto)
            user_state.perguntas_prontas = False
            r.set(user_key, user_state.model_dump_json())
        except Exception as e:
            log.error("Erro ao enviar pergunta pronta via Twilio", extra={"user_id": user_key, "error": str(e)})

    if response_text:
        response_twiml.message(response_text)
        log.info("Resposta enviada ao usuário", extra={"user_id": user_key, "response_preview": response_text[:100]})

    return Response(content=str(response_twiml), media_type="application/xml")
