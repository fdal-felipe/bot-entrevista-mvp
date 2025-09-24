import logging
from app.models import UserState
from app.tasks import tarefa_gerar_perguntas, tarefa_gerar_feedback
from app.services.twilio_service import enviar_mensagem_longa
from app.utils import validar_email # Assumindo que moveremos `validar_email` para app/utils.py

log = logging.getLogger(__name__)

def handle_inicio(user_state: UserState, resposta_usuario: str) -> str:
    """Envia a mensagem de boas-vindas e aguarda o contexto."""
    user_state.etapa = 'aguardando_contexto'
    return (
        "Olá! 👋 Sou o Darwin, seu assistente de entrevistas.\n\n"
        "Para começarmos, me envie seu contexto em uma única mensagem:\n"
        "- A vaga para a qual você está aplicando.\n"
        "- Seu nível de experiência.\n"
        "- As tecnologias que você domina."
    )


def handle_aguardando_contexto(user_state: UserState, resposta_usuario: str) -> str:
    """Processa o contexto inicial do usuário e já inicia a geração das perguntas."""
    if not resposta_usuario:
        return "Por favor, envie seu contexto por texto ou áudio para começarmos."
    
    user_state.contexto = resposta_usuario
    user_state.etapa = 'preparando_perguntas'
    log.info("Contexto recebido; iniciando geração de perguntas imediatamente.", extra={"user_id": user_state.user_key})
    return (
        "Recebi seu contexto! 👍 Preparando 3 perguntas personalizadas...\n\n"
        "Me avise com *'Estou pronto'* ou *'Estou pronta'* quando quiser que eu envie a primeira pergunta.\n\n"
        "Para uma melhor experiência, responda usando *áudios* 🎤."
    )


def handle_preparando_perguntas(user_state: UserState, resposta_usuario: str) -> str:
    """
    Estado enquanto as perguntas estão sendo geradas em background.
    Quando o usuário confirma que está pronto, verifica se as perguntas já estão prontas.
    """
    if not resposta_usuario:
        return "Estou preparando 3 perguntas... Quando estiver pronto, me avise!"

    if user_state.erro_geracao:
        error_message = user_state.erro_geracao
        user_state.etapa = 'aguardando_contexto'
        user_state.contexto = None
        user_state.erro_geracao = None
        log.warning("Erro na geração de perguntas - resetando fluxo", extra={"user_id": user_state.user_key})
        return error_message

    normalized = resposta_usuario.strip().lower()
    ready_keywords = [
        'estou pronto', 'estou pronta', 'Estou pronto', 'Estou pronta', 
        'pronto', 'pronta', 'ready', 'vamos', 'vamos lá', 'pode enviar', 
        'pode mandar', 'manda', 'envia', 'envie', 'bora', 'ok', 'sim', 
        'yes', 'go', 'começar', 'comecar', 'começa', 'começa', 'start',
        'iniciar', 'inicia', 'início', 'inicio', 'let\'s go', 'let us go',
        'let\'s', 'let us', 'vamos começar', 'vamos comecar', 'vamos la', 
        'pode começar', 'pode comecar', 'pode começar', 'pode comecar'
    ]
    
    if any(keyword in normalized for keyword in ready_keywords):
        if user_state.perguntas and len(user_state.perguntas) >= 3:
            user_state.etapa = 'aguardando_resposta_1'
            log.info("Usuário pronto e perguntas disponíveis - enviando primeira pergunta", extra={"user_id": user_state.user_key})
            return (f"*Pergunta 1:*\n{user_state.perguntas[0]}")
        else:
            return "Quase lá! Estou finalizando suas perguntas personalizadas... Mais alguns segundos! ⏰"
    else:
        if len(resposta_usuario.strip()) > 10:
            user_state.contexto = resposta_usuario
            return (
                "Recebi sua atualização! 👍\n\n"
                "Quando estiver pronto para começar, envie 'Estou pronto' ou 'Estou pronta'."
            )
        else:
            return (
                "Estou preparando 3 perguntas personalizadas...\n\n"
                "Quando estiver pronto para começar, envie 'Estou pronto' ou 'Estou pronta'."
            )

def handle_aguardando_resposta_1(user_state: UserState, resposta_usuario: str) -> str:
    """Coleta a primeira resposta e envia a segunda pergunta."""
    if not resposta_usuario.strip():
        return "Por favor, responda à pergunta anterior para continuarmos."
    
    user_state.respostas.append(resposta_usuario)
    user_state.etapa = 'aguardando_resposta_2'
    
    if len(user_state.perguntas) >= 2:
        return f"*Pergunta 2:*\n{user_state.perguntas[1]}"
    else:
        return "Erro: Segunda pergunta não encontrada. Digite 'reiniciar' para começar novamente."

def handle_aguardando_resposta_2(user_state: UserState, resposta_usuario: str) -> str:
    """Coleta a segunda resposta e envia a terceira pergunta."""
    if not resposta_usuario.strip():
        return "Por favor, responda à pergunta anterior para continuarmos."
    
    user_state.respostas.append(resposta_usuario)
    user_state.etapa = 'aguardando_resposta_3'
    
    if len(user_state.perguntas) >= 3:
        return f"*Pergunta 3:*\n{user_state.perguntas[2]}"
    else:
        return "Erro: Terceira pergunta não encontrada. Digite 'reiniciar' para começar novamente."

def handle_aguardando_resposta_3(user_state: UserState, resposta_usuario: str) -> str:
    """Coleta a última resposta e inicia a geração do feedback."""
    if not resposta_usuario.strip():
        return "Por favor, responda à pergunta anterior para continuarmos."
    
    user_state.respostas.append(resposta_usuario)
    user_state.etapa = 'gerando_feedback'
    tarefa_gerar_feedback.delay(user_state.user_key)
    
    log.info("Entrevista concluída", extra={
        "action": "interview_completed",
        "user_id": user_state.user_key
    })
    
    log.info("Todas as respostas recebidas, task de feedback iniciada.", extra={"user_id": user_state.user_key})
    return "Excelente! Recebi todas as suas respostas. ✅ Estou preparando um feedback curto e direto.\n\nAssim que estiver pronto para receber seu feedback, me avise com *'Pode enviar'*."

def handle_gerando_feedback(user_state: UserState, resposta_usuario: str, twilio_client) -> str:
    """Verifica se o feedback está pronto e o envia imediatamente via TwiML Response."""
    if user_state.erro_feedback:
        user_state.etapa = 'aguardando_contexto'
        return f"Houve um problema ao gerar seu feedback: {user_state.erro_feedback}. Digite 'reiniciar' para começar uma nova entrevista."
    
    if user_state.feedback_gerado:
        mensagem_pedido_feedback = (
            "\n\nEspero que este feedback tenha ajudado! 🙏\n\n"
            "Sua opinião é ouro para nós. O que você achou da experiência? "
        )
        mensagem_completa = user_state.feedback_gerado
        
        user_state.etapa = 'aguardando_feedback_usuario'
        user_state.feedback_gerado = None
        
        return mensagem_completa
    else:
        return "Estou finalizando seu feedback. Já te envio em instantes... 📊"

def handle_aguardando_feedback_usuario(user_state: UserState, resposta_usuario: str) -> str:
    """Coleta o depoimento do usuário e oferece a versão PRO."""
    user_state.depoimento = resposta_usuario
    user_state.etapa = 'aguardando_email_pro'
    
    log.info("Depoimento do usuário recebido", extra={
        "action": "user_feedback_received",
        "user_id": user_state.user_key,
        "depoimento": resposta_usuario
    })
    
    log.info("Oferecendo versão PRO", extra={
        "action": "pro_version_offer",
        "user_id": user_state.user_key
    })
    
    return (
        "Muito obrigado pelo seu feedback! 🙏\n\n"
        "🚀 *VERSÃO PRO EM DESENVOLVIMENTO* 🚀\n\n"
        "Estamos criando uma versão PRO com *análise de vídeo* para avaliar sua comunicação não-verbal, "
        "postura e confiança durante as entrevistas!\n\n"
        "Para ser o *primeiro a saber* e ganhar um *desconto especial de lançamento*, "
        "envie seu e-mail abaixo.\n\n"
        "Caso não tenha interesse, digite *'finalizar'*."
    )

def handle_aguardando_email_pro(user_state: UserState, resposta_usuario: str) -> str:
    """Processa a resposta sobre a versão PRO e finaliza ou coleta o email."""
    if resposta_usuario.lower() in ['finalizar', 'finalizar.', 'nao', 'não', 'no', 'skip', 'pular']:
        user_state.etapa = 'finalizado'
        
        log.info("Versão PRO recusada", extra={
            "action": "pro_version_declined",
            "user_id": user_state.user_key
        })
        log.info("Ciclo do usuário completo", extra={
            "action": "user_cycle_completed",
            "user_id": user_state.user_key
        })
        
        return "Sem problemas! Obrigado por usar nosso bot. Para uma nova simulação, digite 'reiniciar'. 🚀"
    
    if validar_email(resposta_usuario):
        email = resposta_usuario.strip()
        
        log.info("Email para versão PRO coletado", extra={
            "action": "pro_email_collected",
            "user_id": user_state.user_key,
            "email": email
        })
        log.info("Ciclo do usuário completo", extra={
            "action": "user_cycle_completed", 
            "user_id": user_state.user_key
        })
        
        user_state.etapa = 'finalizado'
        return (
            f"Perfeito! ✅ Seu email *{email}* foi salvo na nossa lista de espera.\n\n"
            "Você receberá em primeira mão as novidades e um desconto especial de lançamento.\n\n"
            "Para uma nova simulação, digite 'reiniciar'. Obrigado! 🎉"
        )
    else:
        return (
            "O formato do email não parece estar correto. 😅\n\n"
            "Pode tentar novamente? (Ex: seuemail@dominio.com)\n\n"
            "Ou digite 'finalizar' se não quiser cadastrar."
        )

STATE_HANDLERS = {
    "inicio": handle_inicio,
    "aguardando_contexto": handle_aguardando_contexto,
    "preparando_perguntas": handle_preparando_perguntas,
    "aguardando_resposta_1": handle_aguardando_resposta_1,
    "aguardando_resposta_2": handle_aguardando_resposta_2,
    "aguardando_resposta_3": handle_aguardando_resposta_3,
    "gerando_feedback": handle_gerando_feedback,
    "aguardando_feedback_usuario": handle_aguardando_feedback_usuario,
    "aguardando_email_pro": handle_aguardando_email_pro,
}
