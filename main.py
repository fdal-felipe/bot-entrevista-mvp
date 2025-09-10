# main.py - Versão completa com fluxo de áudio e feedback final

import os
import json
import redis
import requests
import vertexai
from celery import Celery
from dotenv import load_dotenv
from twilio.rest import Client
from google.cloud import speech
from google.oauth2 import service_account
from fastapi import FastAPI, Form, Response
from vertexai.generative_models import GenerativeModel
from twilio.twiml.messaging_response import MessagingResponse

# --- CONFIGURAÇÃO ---
# Carrega as variáveis do arquivo .env
load_dotenv()

# Credenciais Google Cloud
NOME_ARQUIVO_CHAVE = "google_credentials.json" 
# Obtém as variáveis do arquivo .env
ID_PROJETO = os.getenv("ID_PROJETO")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

# Validação das variáveis obrigatórias
required_vars = {
    "ID_PROJETO": ID_PROJETO,
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_WHATSAPP_NUMBER": TWILIO_WHATSAPP_NUMBER
}

missing_vars = [var_name for var_name, var_value in required_vars.items() if not var_value]
if missing_vars:
    print(f"❌ Erro: Variáveis de ambiente não encontradas: {', '.join(missing_vars)}")
    print("Verifique se o arquivo .env está presente e contém todas as variáveis necessárias.")
    exit()

# Configuração do Celery (usa o Redis como intermediário)
celery = Celery(__name__, broker='redis://localhost:6379/0')

# --- INICIALIZAÇÃO DOS SERVIÇOS ---

try:
    # Autenticação e inicialização dos clientes
    credentials = service_account.Credentials.from_service_account_file(NOME_ARQUIVO_CHAVE)
    vertexai.init(project=ID_PROJETO, credentials=credentials, location="us-central1")
    
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    speech_client = speech.SpeechClient(credentials=credentials)
    
    print("✅ Sucesso: Clientes Vertex AI, Twilio e Speech-to-Text inicializados!")

except Exception as e:
    print(f"❌ Erro na inicialização: {e}")
    # Encerra a aplicação se a inicialização falhar
    exit()

# Conexão com o Redis
try:
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    r.ping()
    print("✅ Sucesso: Conectado ao Redis!")
except Exception as e:
    print(f"❌ Erro ao conectar ao Redis: {e}")
    r = None

# --- FUNÇÃO AUXILIAR DE TRANSCRIÇÃO DE ÁUDIO ---

def transcrever_audio_twilio(media_url):
    """Baixa um áudio de uma URL da Twilio e o transcreve usando a API do Google."""
    try:
        # 1. Baixar o conteúdo do áudio com autenticação da Twilio
        audio_response = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
        audio_content = audio_response.content

        # 2. Configurar a requisição para a API Speech-to-Text
        audio_para_api = speech.RecognitionAudio(content=audio_content)
        config_api = speech.RecognitionConfig(
            # Áudios do WhatsApp geralmente usam o codec OGG_OPUS
            encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
            sample_rate_hertz=16000,
            language_code="pt-BR", # Idioma da transcrição
            model="default" # Modelo padrão é robusto o suficiente
        )

        # 3. Chamar a API e obter a transcrição
        response = speech_client.recognize(config=config_api, audio=audio_para_api)

        if response.results:
            transcricao = response.results[0].alternatives[0].transcript
            print(f"🎤 Áudio transcrito com sucesso: '{transcricao}'")
            return transcricao
        else:
            print("⚠️ Aviso: Não foi possível transcrever o áudio.")
            return ""
    except Exception as e:
        print(f"❌ Erro na transcrição do áudio: {e}")
        return ""
    
def enviar_mensagem_longa(client, destinatario, texto_completo):
    """
    Divide um texto longo em várias mensagens menores que 1600 caracteres
    e as envia via Twilio, tentando quebrar por parágrafos.
    """
    limite = 1550  # Um pouco de margem de segurança
    if len(texto_completo) <= limite:
        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=texto_completo,
            to=destinatario
        )
        return

    print(f"📦 Texto longo detectado. Dividindo em várias mensagens para {destinatario}...")
    
    # Divide o texto em parágrafos (blocos separados por duas quebras de linha)
    paragrafos = texto_completo.split('\n\n')
    mensagem_atual = ""

    for paragrafo in paragrafos:
        # Se o parágrafo atual mais a mensagem que estamos montando ultrapassar o limite
        if len(mensagem_atual) + len(paragrafo) + 2 > limite:
            # Envia o que já montamos
            client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                body=mensagem_atual,
                to=destinatario
            )
            # E começa uma nova mensagem com o parágrafo atual
            mensagem_atual = paragrafo + "\n\n"
        else:
            # Caso contrário, apenas adiciona o parágrafo à mensagem atual
            mensagem_atual += paragrafo + "\n\n"
    
    # Envia a última parte da mensagem que sobrou, se houver
    if mensagem_atual.strip():
        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=mensagem_atual,
            to=destinatario
        )
    print(f"✅ Todas as partes da mensagem longa foram enviadas para {destinatario}.")

# --- TAREFAS ASSÍNCRONAS (CELERY) ---

@celery.task
def tarefa_gerar_perguntas(user_key, contexto):
    """Worker que gera as perguntas de entrevista em segundo plano."""
    print(f"⚙️ WORKER: Gerando perguntas para {user_key}...")
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
            
            # Envia a primeira pergunta proativamente
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                body=perguntas[0],
                to=user_key
            )
            print(f"✅ WORKER: Primeira pergunta enviada para {user_key}.")
        else:
            # Fallback: resetar o fluxo e pedir novo contexto
            user_state = json.loads(r.get(user_key) or "{}")
            user_state.update({"etapa": "aguardando_contexto"})
            r.set(user_key, json.dumps(user_state))
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                body="Não consegui gerar as perguntas com base no contexto. Pode resumir novamente sua vaga, experiência e tecnologias? 🙏",
                to=user_key
            )
            print(f"⚠️ WORKER: Formato inesperado ao gerar perguntas para {user_key}.")
    except Exception as e:
        print(f"❌ WORKER (Perguntas): Erro ao processar: {e}")
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
            print(f"❌ WORKER (Perguntas): Falha ao notificar usuário: {e2}")


@celery.task
def tarefa_gerar_feedback(user_key):
    """Worker que analisa as respostas e gera o feedback final."""
    print(f"⚙️ WORKER: Gerando feedback para {user_key}...")
    user_state = json.loads(r.get(user_key))
    contexto = user_state.get("contexto", "")
    perguntas = user_state.get("perguntas", [])
    respostas = user_state.get("respostas", [])

    prompt = f"""
    Você é um coach de carreira e especialista em recrutamento.
    Analise a entrevista a seguir e forneça um feedback estruturado para o candidato.

    **Contexto do Candidato:** {contexto}

    **Entrevista Realizada:**
    1. Pergunta: {perguntas[0]}
       Resposta: {respostas[0]}
    
    2. Pergunta: {perguntas[1]}
       Resposta: {respostas[1]}
       
    3. Pergunta: {perguntas[2]}
       Resposta: {respostas[2]}

    **Sua Tarefa:**
    Forneça um feedback detalhado e construtivo mas seja sucinto na quantidade de texto, o usuário não precisa de muitos detalhes apenas os principais de alto impacto. Para cada resposta, analise-a brevemente usando a metodologia STAR (Situação, Tarefa, Ação, Resultado) quando aplicável.
    Comece dando uma porcentagem de clareza entre 0% e 100% para cada resposta, onde 100% significa que a resposta foi clara, direta e completa.
    Em seguida, para cada resposta:
    - Destaque os pontos fortes de cada resposta.
    - Ofereça sugestões claras e práticas de melhoria.
    - Mantenha um tom encorajador e profissional.
    - Formate o texto para boa legibilidade no WhatsApp, usando negrito (*texto*) e itálico (_texto_).
    Finalize com uma mensagem de encerramento positiva.
    Utilize emojis para melhorar a experiência de leitura e considere utilizar textos no padrão do WhatsApp (ex: *negrito* e _itálico_).
    """
    try:
        model = GenerativeModel("gemini-2.5-flash-lite")
        response = model.generate_content(prompt)
        feedback_text = response.text

        enviar_mensagem_longa(twilio_client, user_key, feedback_text)
        print(f"✅ WORKER: Feedback enviado para {user_key}.")
        r.delete(user_key)
    except Exception as e:
        print(f"❌ WORKER (Feedback): Erro ao processar: {e}")

# --- ENDPOINT DO WEBHOOK (FASTAPI) ---

app = FastAPI()

@app.post("/webhook/twilio")
def handle_twilio_webhook(From: str = Form(...), Body: str = Form(None), NumMedia: int = Form(0), MediaUrl0: str = Form(None)):
    """Recebe e processa as mensagens do WhatsApp via Twilio."""
    
    response_twiml = MessagingResponse()
    response_text = None  # evita mensagem de erro genérica
    user_key = From
    # Log básico da requisição e do estado salvo
    print(f"[WEBHOOK] From={user_key} NumMedia={NumMedia} Body='{Body}'")

    if not r:
        response_twiml.message("Serviço indisponível (não conectado ao Redis).")
        return Response(content=str(response_twiml), media_type="application/xml")

    # Prioriza o áudio. Se houver mídia, transcreve. Senão, usa o texto.
    resposta_usuario = ""
    if NumMedia > 0 and MediaUrl0:
        response_twiml.message("Recebi seu áudio, um momento enquanto o transcrevo...")
        resposta_usuario = transcrever_audio_twilio(MediaUrl0)
    elif Body:
        resposta_usuario = Body.strip()

    # Se é a primeira interação, apresente-se e peça o contexto
    user_state_json = r.get(user_key)
    print(f"[WEBHOOK] Estado atual no Redis: {user_state_json}")
    if not user_state_json:
        r.set(user_key, json.dumps({"etapa": "aguardando_contexto"}))
        response_text = (
            "Olá! Eu sou seu coach de entrevistas por WhatsApp. 👋\n\n"
            "Para personalizar sua simulação, me conte seu contexto:\n"
            "- Vaga desejada\n- Experiência relevante\n- Principais tecnologias\n\n"
            "Pode enviar por texto ou áudio."
        )
        response_twiml.message(response_text)
        return Response(content=str(response_twiml), media_type="application/xml")

    # Lógica de máquina de estados
    if resposta_usuario and resposta_usuario.lower() == 'reiniciar':
        r.set(user_key, json.dumps({"etapa": "aguardando_contexto"}))
        response_text = "Vamos recomeçar! Me conte seu contexto (vaga desejada, experiência e tecnologias)."
    else:
        try:
            user_state = json.loads(user_state_json)
        except Exception:
            # Estado corrompido -> reset
            r.set(user_key, json.dumps({"etapa": "aguardando_contexto"}))
            response_text = "Detectei um problema no seu histórico. Vamos recomeçar. Me conte sua vaga, experiência e tecnologias."
            user_state = {"etapa": "aguardando_contexto"}

        etapa_atual = user_state.get("etapa", "aguardando_contexto")
        print(f"[WEBHOOK] Etapa: {etapa_atual} | Resposta='{resposta_usuario}'")

        if etapa_atual == "aguardando_contexto":
            if not resposta_usuario:
                response_text = "Pode me enviar seu contexto por texto ou áudio?"
            else:
                user_state['contexto'] = resposta_usuario
                user_state['etapa'] = 'preparando_perguntas'
                r.set(user_key, json.dumps(user_state))
                tarefa_gerar_perguntas.delay(user_key, resposta_usuario)
                response_text = "Ótimo, recebi seu contexto! 👍 Estou preparando suas perguntas personalizadas. Envio a primeira em instantes...\n\n*Responda as perguntas em áudio.*"

        elif etapa_atual == "preparando_perguntas":
            response_text = "Estou preparando suas perguntas agora. Aguarde um instante, por favor. Se preferir recomeçar, digite 'reiniciar'."

        elif etapa_atual == "aguardando_resposta_1":
            user_state.setdefault('respostas', []).append(resposta_usuario)
            user_state['etapa'] = 'aguardando_resposta_2'
            r.set(user_key, json.dumps(user_state))
            response_text = user_state['perguntas'][1]

        elif etapa_atual == "aguardando_resposta_2":
            user_state.setdefault('respostas', []).append(resposta_usuario)
            user_state['etapa'] = 'aguardando_resposta_3'
            r.set(user_key, json.dumps(user_state))
            response_text = user_state['perguntas'][2]

        elif etapa_atual == "aguardando_resposta_3":
            user_state.setdefault('respostas', []).append(resposta_usuario)
            user_state['etapa'] = 'gerando_feedback'
            r.set(user_key, json.dumps(user_state))
            tarefa_gerar_feedback.delay(user_key)
            response_text = "Excelente! Recebi todas as suas respostas. ✅ Estou preparando um feedback curto e direto. Isso pode levar um minuto."

        elif etapa_atual == "gerando_feedback":
            response_text = "Estou finalizando seu feedback. Já te envio em instantes. Para recomeçar, digite 'reiniciar'."

        else:
            # Estado desconhecido -> reset amigável
            r.set(user_key, json.dumps({"etapa": "aguardando_contexto"}))
            response_text = "Vamos recomeçar para garantir tudo certo. Me conte sua vaga, experiência e tecnologias."

    # Fallback seguro
    if not response_text:
        response_text = "Não entendi bem. Se quiser recomeçar, digite 'reiniciar'."

    response_twiml.message(response_text)
    return Response(content=str(response_twiml), media_type="application/xml")
