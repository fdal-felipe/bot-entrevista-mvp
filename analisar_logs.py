import json
import sys
import os
import glob
from collections import Counter

def analisar_logs(arquivos_ou_pasta):
    """Analisa arquivos de log e gera métricas."""
    
    arquivos_log = []
    
    if os.path.isdir(arquivos_ou_pasta):
        arquivos_log = glob.glob(os.path.join(arquivos_ou_pasta, "*.jsonl"))
        print(f"📁 Analisando pasta: {arquivos_ou_pasta}")
        print(f"📄 Arquivos encontrados: {len(arquivos_log)}")
    elif os.path.isfile(arquivos_ou_pasta):
        arquivos_log = [arquivos_ou_pasta]
        print(f"📄 Analisando arquivo: {arquivos_ou_pasta}")
    else:
        print(f"❌ {arquivos_ou_pasta} não encontrado!")
        return
    
    if not arquivos_log:
        print("❌ Nenhum arquivo .jsonl encontrado!")
        return
    
    metricas = Counter()
    usuarios_unicos_entrevista = set()
    depoimentos = []
    emails = []
    
    print("🔍 Processando logs...\n")
    
    for arquivo in arquivos_log:
        print(f"📖 Lendo: {os.path.basename(arquivo)}")
        try:
            with open(arquivo, 'r', encoding='utf-8') as f:
                for linha in f:
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
        except FileNotFoundError:
            print(f"⚠️  Arquivo {arquivo} não encontrado, pulando...")
    
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
    caminho = "logs" if len(sys.argv) == 1 else sys.argv[1]
    analisar_logs(caminho)
