import json
import sys
from collections import Counter

def analisar_logs(arquivo_logs):
    """Analisa o arquivo de logs e gera métricas."""
    
    try:
        with open(arquivo_logs, 'r', encoding='utf-8') as f:
            linhas = f.readlines()
    except FileNotFoundError:
        print(f"❌ Arquivo {arquivo_logs} não encontrado!")
        return
    
    metricas = Counter()
    usuarios_unicos_entrevista = set()
    depoimentos = []
    emails = []
    
    print("🔍 Analisando logs...\n")
    
    for linha in linhas:
        try:
            evento = json.loads(linha.strip())
            action = evento.get('action', '')
            user_id = evento.get('user_id', '')
            
            if action:
                metricas[action] += 1
            
            if action == 'interview_started' and user_id:
                usuarios_unicos_entrevista.add(user_id)
            
            if action == 'user_feedback_received':
                depoimento = evento.get('depoimento', '')
                if depoimento:
                    depoimentos.append(depoimento)
            
            if action == 'pro_email_collected':
                email = evento.get('email', '')
                if email:
                    emails.append(email)
                    
        except json.JSONDecodeError:
            continue
    
    print("📊 MÉTRICAS DO BOT DE ENTREVISTAS")
    print("=" * 50)
    
    print(f"👥 Novos usuários: {metricas['new_user_detected']}")
    print(f"🎯 Entrevistas iniciadas: {metricas['interview_started']}")
    print(f"✅ Entrevistas concluídas: {metricas['interview_completed']}")
    print(f"📝 Feedbacks da IA enviados: {metricas['feedback_generation_success']}")
    print(f"💬 Usuários que deram depoimento: {metricas['user_feedback_received']}")
    print(f"🏁 Ciclos completos: {metricas['user_cycle_completed']}")
    
    print("\n🚀 MÉTRICAS DA VERSÃO PRO")
    print("=" * 30)
    print(f"📢 Ofertas da versão PRO: {metricas['pro_version_offer']}")
    print(f"📧 Emails coletados: {metricas['pro_email_collected']}")
    print(f"❌ Recusas da versão PRO: {metricas['pro_version_declined']}")
    
    if metricas['new_user_detected'] > 0:
        taxa_inicio = (metricas['interview_started'] / metricas['new_user_detected']) * 100
        print(f"\n📈 Taxa de conversão (usuário → entrevista): {taxa_inicio:.1f}%")
    
    if metricas['interview_started'] > 0:
        taxa_conclusao = (metricas['interview_completed'] / metricas['interview_started']) * 100
        print(f"📈 Taxa de conclusão (entrevista → feedback): {taxa_conclusao:.1f}%")
    
    if metricas['pro_version_offer'] > 0:
        taxa_pro = (metricas['pro_email_collected'] / metricas['pro_version_offer']) * 100
        print(f"📈 Taxa de interesse na versão PRO: {taxa_pro:.1f}%")
    
    print(f"\n👤 Usuários únicos que fizeram entrevistas: {len(usuarios_unicos_entrevista)}")
    
    if depoimentos:
        print("\n💭 DEPOIMENTOS DOS USUÁRIOS:")
        print("=" * 35)
        for i, depoimento in enumerate(depoimentos, 1):
            print(f"{i}. {depoimento}\n")
    
    if emails:
        print("📧 EMAILS COLETADOS PARA VERSÃO PRO:")
        print("=" * 40)
        for i, email in enumerate(emails, 1):
            print(f"{i}. {email}")
    
    print(f"\n✅ Análise concluída! Total de eventos processados: {sum(metricas.values())}")

if __name__ == "__main__":
    arquivo = "logs.jsonl"
    if len(sys.argv) > 1:
        arquivo = sys.argv[1]
    
    analisar_logs(arquivo)
    