# main.py - Versão completa com fluxo de áudio, feedback final, logging estruturado, coleta de feedback qualitativo e validação versão Pro

import os
import re
import sys
import json
import redis
import logging
import requests
import vertexai
from celery import Celery
from dotenv import load_dotenv
from twilio.rest import Client
from google.cloud import speech
from pythonjsonlogger import jsonlogger
from google.oauth2 import service_account
from fastapi import FastAPI, Form, Response
from vertexai.generative_models import GenerativeModel
from twilio.twiml.messaging_response import MessagingResponse

log = logging.getLogger()
log.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout) 
formatter = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)

from celery.utils.log import get_task_logger
celery_logger = get_task_logger(__name__)
celery_logger.addHandler(handler)
celery_logger.setLevel(logging.INFO)

load_dotenv()

NOME_ARQUIVO_CHAVE = "google_credentials.json" 
ID_PROJETO = os.getenv("ID_PROJETO")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

required_vars = {
    "ID_PROJETO": ID_PROJETO,
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_WHATSAPP_NUMBER": TWILIO_WHATSAPP_NUMBER
}

missing_vars = [var_name for var_name, var_value in required_vars.items() if not var_value]
if missing_vars:
    log.error("Variáveis de ambiente não encontradas", extra={
        "missing_vars": missing_vars,
        "action": "startup_validation"
    })
    exit()

celery = Celery(__name__, broker='redis://localhost:6379/0')

try:
    credentials = service_account.Credentials.from_service_account_file(NOME_ARQUIVO_CHAVE)
    vertexai.init(project=ID_PROJETO, credentials=credentials, location="us-central1")
    
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    speech_client = speech.SpeechClient(credentials=credentials)
    
    log.info("Clientes inicializados com sucesso", extra={
        "services": ["vertex_ai", "twilio", "speech_to_text"],
        "action": "service_initialization",
        "status": "success"
    })

except Exception as e:
    log.error("Erro na inicialização dos serviços", extra={
        "error": str(e),
        "action": "service_initialization",
        "status": "failed"
    })
    exit()

try:
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    r.ping()
    log.info("Conectado ao Redis com sucesso", extra={
        "service": "redis",
        "action": "redis_connection",
        "status": "success"
    })
except Exception as e:
    log.error("Erro ao conectar ao Redis", extra={
        "error": str(e),
        "service": "redis",
        "action": "redis_connection",
        "status": "failed"
    })
    r = None


def validar_email(email):
    """Valida se o formato do email está correto."""
    padrao = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(padrao, email) is not None


def transcrever_audio_twilio(media_url):
    """Baixa um áudio de uma URL da Twilio e o transcreve usando a API do Google."""
    try:
        audio_response = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
        audio_content = audio_response.content

        audio_para_api = speech.RecognitionAudio(content=audio_content)
        config_api = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
            sample_rate_hertz=16000,
            language_code="pt-BR",
            model="default"
        )

        response = speech_client.recognize(config=config_api, audio=audio_para_api)

        if response.results:
            transcricao = response.results[0].alternatives[0].transcript
            log.info("Áudio transcrito com sucesso", extra={
                "transcription": transcricao,
                "media_url": media_url,
                "action": "audio_transcription",
                "status": "success"
            })
            return transcricao
        else:
            log.warning("Não foi possível transcrever o áudio", extra={
                "media_url": media_url,
                "action": "audio_transcription",
                "status": "no_results"
            })
            return ""
    except Exception as e:
        log.error("Erro na transcrição do áudio", extra={
            "error": str(e),
            "media_url": media_url,
            "action": "audio_transcription",
            "status": "failed"
        })
        return ""
    
def enviar_mensagem_longa(client, destinatario, texto_completo):
    """
    Divide um texto longo em várias mensagens menores que 1600 caracteres
    e as envia via Twilio, tentando quebrar por parágrafos.
    """
    limite = 1500
    if len(texto_completo) <= limite:
        try:
            client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                body=texto_completo,
                to=destinatario
            )
        except Exception as e:
            log.error("Erro ao enviar mensagem", extra={
                "error": str(e),
                "recipient": destinatario,
                "action": "send_message",
                "status": "failed"
            })
        return

    log.info("Texto longo detectado, dividindo em várias mensagens", extra={
        "recipient": destinatario,
        "text_length": len(texto_completo),
        "action": "send_long_message"
    })
    
    paragrafos = texto_completo.split('\n\n')
    mensagem_atual = ""

    for paragrafo in paragrafos:
        if len(paragrafo) > limite:
            if mensagem_atual.strip():
                try:
                    client.messages.create(
                        from_=TWILIO_WHATSAPP_NUMBER,
                        body=mensagem_atual.strip(),
                        to=destinatario
                    )
                except Exception as e:
                    log.error("Erro ao enviar parte da mensagem", extra={
                        "error": str(e),
                        "recipient": destinatario,
                        "action": "send_message_part",
                        "status": "failed"
                    })
                mensagem_atual = ""
            
            palavras = paragrafo.split(' ')
            chunk_atual = ""
            for palavra in palavras:
                if len(chunk_atual) + len(palavra) + 1 <= limite:
                    chunk_atual += " " + palavra if chunk_atual else palavra
                else:
                    if chunk_atual.strip():
                        try:
                            client.messages.create(
                                from_=TWILIO_WHATSAPP_NUMBER,
                                body=chunk_atual.strip(),
                                to=destinatario
                            )
                        except Exception as e:
                            log.error("Erro ao enviar chunk", extra={
                                "error": str(e),
                                "recipient": destinatario,
                                "action": "send_chunk",
                                "status": "failed"
                            })
                    chunk_atual = palavra
            
            if chunk_atual.strip():
                try:
                    client.messages.create(
                        from_=TWILIO_WHATSAPP_NUMBER,
                        body=chunk_atual.strip(),
                        to=destinatario
                    )
                except Exception as e:
                    log.error("Erro ao enviar último chunk", extra={
                        "error": str(e),
                        "recipient": destinatario,
                        "action": "send_last_chunk",
                        "status": "failed"
                    })
                    
        elif len(mensagem_atual) + len(paragrafo) + 2 > limite:
            if mensagem_atual.strip():
                try:
                    client.messages.create(
                        from_=TWILIO_WHATSAPP_NUMBER,
                        body=mensagem_atual.strip(),
                        to=destinatario
                    )
                except Exception as e:
                    log.error("Erro ao enviar mensagem acumulada", extra={
                        "error": str(e),
                        "recipient": destinatario,
                        "action": "send_accumulated_message",
                        "status": "failed"
                    })
            mensagem_atual = paragrafo + "\n\n"
        else:
            mensagem_atual += paragrafo + "\n\n"
    
    if mensagem_atual.strip():
        try:
            client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                body=mensagem_atual.strip(),
                to=destinatario
            )
        except Exception as e:
            log.error("Erro ao enviar última parte", extra={
                "error": str(e),
                "recipient": destinatario,
                "action": "send_final_part",
                "status": "failed"
            })
    
    log.info("Todas as partes da mensagem longa foram enviadas", extra={
        "recipient": destinatario,
        "action": "send_long_message",
        "status": "completed"
    })


@celery.task
def tarefa_gerar_perguntas(user_key, contexto):
    """Worker que gera as perguntas de entrevista em segundo plano."""
    log.info("Iniciando geração de perguntas", extra={
        "user_id": user_key,
        "task": "tarefa_gerar_perguntas",
        "action": "start_question_generation"
    })
    
    model = GenerativeModel("gemini-2.5-flash-lite")
    prompt = f"""
    Você é um recrutador técnico sênior. Baseado no seguinte contexto de um candidato: '{contexto}'.
    Gere exatamente 3 perguntas de entrevista (2 de soft skill e 1 de hard skill) no formato JSON array:
    {{"perguntas": ["pergunta1", "pergunta2", "pergunta3"]}}
    """
    try:
        response = model.generate_content(prompt)
        json_response_text = response.text.strip().replace("```json", "").replace("```", "")
        try:
            perguntas_dict = json.loads(json_response_text)
        except Exception:
            perguntas_dict = {}
        perguntas = perguntas_dict.get("perguntas", [])

        if perguntas and len(perguntas) == 3:
            user_state = json.loads(r.get(user_key))
            user_state.update({
                "etapa": "aguardando_resposta_1",
                "perguntas": perguntas,
                "respostas": []
            })
            r.set(user_key, json.dumps(user_state))
            
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                body=perguntas[0],
                to=user_key
            )
            
            log.info("Perguntas geradas e primeira pergunta enviada", extra={
                "user_id": user_key,
                "task": "tarefa_gerar_perguntas",
                "questions_count": len(perguntas),
                "action": "question_generation_success",
                "status": "completed"
            })
        else:
            user_state = json.loads(r.get(user_key) or "{}")
            user_state.update({"etapa": "aguardando_contexto"})
            r.set(user_key, json.dumps(user_state))
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                body="Não consegui gerar as perguntas com base no contexto. Pode resumir novamente sua vaga, experiência e tecnologias? 🙏",
                to=user_key
            )
            
            log.warning("Formato inesperado ao gerar perguntas", extra={
                "user_id": user_key,
                "task": "tarefa_gerar_perguntas",
                "questions_received": len(perguntas),
                "action": "question_generation_format_error",
                "status": "failed"
            })
    except Exception as e:
        log.error("Erro ao processar geração de perguntas", extra={
            "user_id": user_key,
            "task": "tarefa_gerar_perguntas",
            "error": str(e),
            "action": "question_generation_error",
            "status": "failed"
        })
        try:
            user_state = json.loads(r.get(user_key) or "{}")
            user_state.update({"etapa": "aguardando_contexto"})
            r.set(user_key, json.dumps(user_state))
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                body="Tive um problema ao preparar suas perguntas. Vamos recomeçar? Envie seu contexto (vaga, experiência, tecnologias).",
                to=user_key
            )
        except Exception as e2:
            log.error("Falha ao notificar usuário sobre erro", extra={
                "user_id": user_key,
                "task": "tarefa_gerar_perguntas",
                "error": str(e2),
                "action": "error_notification_failed",
                "status": "critical"
            })


@celery.task
def tarefa_gerar_feedback(user_key):
    """Worker que analisa as respostas e gera o feedback final."""
    log.info("Iniciando geração de feedback", extra={
        "user_id": user_key,
        "task": "tarefa_gerar_feedback",
        "action": "start_feedback_generation"
    })
    
    user_state = json.loads(r.get(user_key))
    contexto = user_state.get("contexto", "")
    perguntas = user_state.get("perguntas", [])
    respostas = user_state.get("respostas", [])

    log.info("Simulação de entrevista concluída", extra={
        "user_id": user_key,
        "contexto": contexto,
        "perguntas": perguntas,
        "respostas": respostas,
        "action": "interview_completed"
    })

    prompt = f"""
    Você é um coach de carreira e especialista em recrutamento.
    Analise a entrevista a seguir e forneça um feedback CONCISO e objetivo para o candidato.

    **Contexto do Candidato:** {contexto}

    **Entrevista Realizada:**
    1. Pergunta: {perguntas[0]}
       Resposta: {respostas[0]}
    
    2. Pergunta: {perguntas[1]}
       Resposta: {respostas[1]}
       
    3. Pergunta: {perguntas[2]}
       Resposta: {respostas[2]}

    **Sua Tarefa:**
    Forneça um feedback BREVE e direto (máximo 1000 caracteres). Para cada resposta:
    - Dê uma % de clareza (0-100%)
    - 1 ponto forte principal
    - 1 sugestão de melhoria específica
    - Considere a metodologia STAR (Situação, Tarefa, Ação, Resultado)
    
    Use formatação WhatsApp (*negrito* e _itálico_) e emojis.
    Seja objetivo e encorajador.
    Termine com uma mensagem motivacional curta.
    """
    try:
        model = GenerativeModel("gemini-2.5-flash-lite")
        response = model.generate_content(prompt)
        feedback_text = response.text

        enviar_mensagem_longa(twilio_client, user_key, feedback_text)
        log.info("Feedback da IA enviado com sucesso", extra={
            "user_id": user_key,
            "task": "tarefa_gerar_feedback",
            "feedback_length": len(feedback_text),
            "action": "feedback_generation_success",
            "status": "completed"
        })

        mensagem_pedido_feedback = (
            "Espero que este feedback tenha ajudado! 🙏\n\n"
            "Sua opinião é ouro para nós. O que você achou da experiência? "
        )
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=mensagem_pedido_feedback,
            to=user_key
        )

        user_state['etapa'] = 'aguardando_feedback_usuario'
        r.set(user_key, json.dumps(user_state))
        log.info("Solicitando feedback do usuário", extra={
            "user_id": user_key,
            "action": "requesting_user_feedback"
        })
        
    except Exception as e:
        log.error("Erro ao processar geração de feedback", extra={
            "user_id": user_key,
            "task": "tarefa_gerar_feedback",
            "error": str(e),
            "action": "feedback_generation_error",
            "status": "failed"
        })

        try:
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                body="Houve um problema ao gerar seu feedback. Digite 'reiniciar' para começar uma nova entrevista.",
                to=user_key
            )
            # r.delete(user_key)
        except Exception as e2:
            log.error("Falha ao notificar erro de feedback", extra={
                "user_id": user_key,
                "task": "tarefa_gerar_feedback",
                "error": str(e2),
                "action": "feedback_error_notification_failed",
                "status": "critical"
            })

app = FastAPI()

@app.post("/webhook/twilio")
def handle_twilio_webhook(From: str = Form(...), Body: str = Form(None), NumMedia: int = Form(0), MediaUrl0: str = Form(None)):
    """Recebe e processa as mensagens do WhatsApp via Twilio."""
    
    response_twiml = MessagingResponse()
    response_text = None
    user_key = From
    
    if not r:
        response_twiml.message("Serviço indisponível (não conectado ao Redis).")
        log.error("Redis não disponível para webhook", extra={
            "user_id": user_key,
            "action": "webhook_redis_unavailable",
            "status": "failed"
        })
        return Response(content=str(response_twiml), media_type="application/xml")

    resposta_usuario = ""
    if NumMedia > 0 and MediaUrl0:
        response_twiml.message("Recebi seu áudio, um momento enquanto o transcrevo...")
        resposta_usuario = transcrever_audio_twilio(MediaUrl0)
    elif Body:
        resposta_usuario = Body.strip()

    user_state_json = r.get(user_key)
    
    log.info("Webhook recebido", extra={
        "user_id": user_key,
        "body": Body,
        "num_media": NumMedia,
        "current_state": user_state_json,
        "has_media": NumMedia > 0,
        "has_text": bool(Body),
        "action": "webhook_received"
    })
    
    if not user_state_json:
        log.info("Novo usuário detectado", extra={"user_id": user_key, "action": "new_user_detected"})
        r.set(user_key, json.dumps({"etapa": "aguardando_contexto"}))
        response_text = (
            "Olá! Eu sou seu coach de entrevistas por WhatsApp. 👋\n\n"
            "Para personalizar sua simulação, me conte seu contexto:\n"
            "- Vaga desejada\n- Experiência relevante\n- Principais tecnologias\n\n"
            "Pode enviar por texto ou áudio."
        )
        response_twiml.message(response_text)
        
        log.info("Novo usuário iniciado", extra={
            "user_id": user_key,
            "action": "new_user_started"
        })
        
        return Response(content=str(response_twiml), media_type="application/xml")

    if resposta_usuario and resposta_usuario.lower() in ['reiniciar', 'recomeçar', 'restart']:
        r.set(user_key, json.dumps({"etapa": "aguardando_contexto"}))
        response_text = "Vamos recomeçar! Me conte seu contexto (vaga desejada, experiência e tecnologias)."
        
        log.info("Usuário reiniciou conversa", extra={
            "user_id": user_key,
            "action": "user_restart"
        })
    else:
        try:
            user_state = json.loads(user_state_json)
        except Exception:
            r.set(user_key, json.dumps({"etapa": "aguardando_contexto"}))
            response_text = "Detectei um problema no seu histórico. Vamos recomeçar. Me conte sua vaga, experiência e tecnologias."
            user_state = {"etapa": "aguardando_contexto"}
            
            log.warning("Estado corrompido, resetando usuário", extra={
                "user_id": user_key,
                "action": "state_corruption_reset"
            })

        etapa_atual = user_state.get("etapa", "aguardando_contexto")
        
        log.info("Processando etapa do usuário", extra={
            "user_id": user_key,
            "current_stage": etapa_atual,
            "user_response": resposta_usuario[:100] if resposta_usuario else None,
            "action": "process_user_stage"
        })

        if etapa_atual == "aguardando_contexto":
            if not resposta_usuario:
                response_text = "Pode me enviar seu contexto por texto ou áudio?"
            else:
                log.info("Início de simulação de entrevista", extra={
                    "user_id": user_key,
                    "contexto": resposta_usuario,
                    "action": "interview_started"
                })
                user_state['contexto'] = resposta_usuario
                user_state['etapa'] = 'preparando_perguntas'
                r.set(user_key, json.dumps(user_state))
                tarefa_gerar_perguntas.delay(user_key, resposta_usuario)
                response_text = "Ótimo, recebi seu contexto! 👍 Estou preparando suas perguntas personalizadas. Envio a primeira em instantes...\n\n*Responda as perguntas em áudio.*"
                
                log.info("Contexto recebido, iniciando geração de perguntas", extra={
                    "user_id": user_key,
                    "context_length": len(resposta_usuario),
                    "action": "context_received"
                })

        elif etapa_atual == "preparando_perguntas":
            response_text = "Estou preparando suas perguntas agora. Aguarde um instante, por favor. Se preferir recomeçar, digite 'reiniciar'."

        elif etapa_atual == "aguardando_resposta_1":
            user_state.setdefault('respostas', []).append(resposta_usuario)
            user_state['etapa'] = 'aguardando_resposta_2'
            r.set(user_key, json.dumps(user_state))
            response_text = user_state['perguntas'][1]
            
            log.info("Resposta 1 recebida", extra={
                "user_id": user_key,
                "response_length": len(resposta_usuario) if resposta_usuario else 0,
                "action": "response_1_received"
            })

        elif etapa_atual == "aguardando_resposta_2":
            user_state.setdefault('respostas', []).append(resposta_usuario)
            user_state['etapa'] = 'aguardando_resposta_3'
            r.set(user_key, json.dumps(user_state))
            response_text = user_state['perguntas'][2]
            
            log.info("Resposta 2 recebida", extra={
                "user_id": user_key,
                "response_length": len(resposta_usuario) if resposta_usuario else 0,
                "action": "response_2_received"
            })

        elif etapa_atual == "aguardando_resposta_3":
            user_state.setdefault('respostas', []).append(resposta_usuario)
            user_state['etapa'] = 'gerando_feedback'
            r.set(user_key, json.dumps(user_state))
            tarefa_gerar_feedback.delay(user_key)
            response_text = "Excelente! Recebi todas as suas respostas. ✅ Estou preparando um feedback curto e direto. Isso pode levar um minuto."
            
            log.info("Todas as respostas recebidas, iniciando geração de feedback", extra={
                "user_id": user_key,
                "response_length": len(resposta_usuario) if resposta_usuario else 0,
                "action": "all_responses_received"
            })

        elif etapa_atual == "gerando_feedback":
            response_text = "Estou finalizando seu feedback. Já te envio em instantes. Para recomeçar, digite 'reiniciar'."

        elif etapa_atual == "aguardando_feedback_usuario":
            depoimento = resposta_usuario
            log.info("Depoimento do usuário recebido", extra={
                "user_id": user_key,
                "depoimento": depoimento,
                "action": "user_feedback_received"
            })
            
            user_state['depoimento'] = depoimento
            user_state['etapa'] = 'aguardando_email_pro'
            r.set(user_key, json.dumps(user_state))
            
            response_text = (
                "Muito obrigado pelo seu feedback! 🙏\n\n"
                "🚀 *VERSÃO PRO EM DESENVOLVIMENTO* 🚀\n\n"
                "Estamos criando uma versão PRO com *análise de vídeo* para avaliar sua comunicação não-verbal, "
                "postura e confiança durante as entrevistas!\n\n"
                "Para ser o *primeiro a saber* e ganhar um *desconto especial de lançamento*, "
                "envie seu e-mail abaixo.\n\n"
                "Caso não tenha interesse, digite *'finalizar'* ou *'reiniciar'*."
            )
            
            log.info("Oferecendo versão PRO ao usuário", extra={
                "user_id": user_key,
                "action": "pro_version_offer"
            })

        elif etapa_atual == "aguardando_email_pro":
            if resposta_usuario.lower() in ['finalizar', 'finalizar.', 'nao', 'não', 'no', 'skip', 'pular']:
                log.info("Usuário recusou versão PRO", extra={
                    "user_id": user_key,
                    "action": "pro_version_declined"
                })
                response_text = "Sem problemas! Obrigado por usar nosso bot. Para uma nova simulação, digite 'reiniciar'. 🚀"
                r.delete(user_key)
                log.info("Fim do ciclo completo do usuário", extra={
                    "user_id": user_key,
                    "action": "user_cycle_completed"
                })
            
            elif validar_email(resposta_usuario):
                email = resposta_usuario.strip()
                log.info("Email para versão PRO coletado", extra={
                    "user_id": user_key,
                    "email": email,
                    "action": "pro_email_collected"
                })
                response_text = (
                    f"Perfeito! ✅ Seu email *{email}* foi salvo na nossa lista de espera.\n\n"
                    "Você receberá em primeira mão:\n"
                    "• Acesso antecipado à versão PRO\n"
                    "• Desconto especial de lançamento\n"
                    "• Updates sobre novas funcionalidades\n\n"
                    "Para uma nova simulação, digite 'reiniciar'. Obrigado! 🎉"
                )
                r.delete(user_key)
                log.info("Fim do ciclo completo do usuário", extra={
                    "user_id": user_key,
                    "action": "user_cycle_completed"
                })
            
            else:
                response_text = (
                    "O formato do email não parece estar correto. 😅\n\n"
                    "Pode tentar novamente? Ex: seuemail@gmail.com\n\n"
                    "Ou digite 'finalizar' se não quiser cadastrar."
                )
                log.info("Email inválido fornecido", extra={
                    "user_id": user_key,
                    "invalid_email": resposta_usuario,
                    "action": "invalid_email_provided"
                })

        else:
            r.set(user_key, json.dumps({"etapa": "aguardando_contexto"}))
            response_text = "Vamos recomeçar para garantir tudo certo. Me conte sua vaga, experiência e tecnologias."
            
            log.warning("Estado desconhecido, resetando usuário", extra={
                "user_id": user_key,
                "unknown_stage": etapa_atual,
                "action": "unknown_state_reset"
            })

    if not response_text:
        response_text = "Não entendi bem. Se quiser recomeçar, digite 'reiniciar'."

    response_twiml.message(response_text)
    
    log.info("Resposta enviada ao usuário", extra={
        "user_id": user_key,
        "response_length": len(response_text),
        "action": "response_sent"
    })
    
    return Response(content=str(response_twiml), media_type="application/xml")
