import requests
import time
from concurrent.futures import ThreadPoolExecutor

def simular_usuario(usuario_id):
    """Simula um usuário fazendo requisições."""
    webhook_url = "https://78a24a089a6f.ngrok-free.app/webhook/twilio"
    
    try:
        data = {
            "From": f"whatsapp:+5511{usuario_id:08d}",
            "Body": "Olá",
            "NumMedia": 0
        }
        
        start_time = time.time()
        response = requests.post(webhook_url, data=data, timeout=30)
        end_time = time.time()
        
        print(f"Usuário {usuario_id}: {response.status_code} - {end_time-start_time:.2f}s")
        return end_time - start_time
        
    except Exception as e:
        print(f"Usuário {usuario_id}: ERRO - {str(e)}")
        return None

def teste_concorrencia(num_usuarios=5):
    """Testa múltiplos usuários simultâneos."""
    print(f"🧪 Testando {num_usuarios} usuários simultâneos...")
    
    with ThreadPoolExecutor(max_workers=num_usuarios) as executor:
        futures = [executor.submit(simular_usuario, i) for i in range(1, num_usuarios+1)]
        tempos = [f.result() for f in futures if f.result()]
    
    if tempos:
        print(f"✅ Tempo médio: {sum(tempos)/len(tempos):.2f}s")
        print(f"✅ Tempo máximo: {max(tempos):.2f}s")
    else:
        print("❌ Todos os testes falharam")

if __name__ == "__main__":
    teste_concorrencia(5)