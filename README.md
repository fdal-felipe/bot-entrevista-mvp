# Bot de Entrevista MVP

Um chatbot inteligente para WhatsApp que simula entrevistas de emprego personalizadas, oferecendo feedback detalhado usando IA generativa.

## 🚀 Funcionalidades

- **Entrevistas Personalizadas**: Gera perguntas baseadas no contexto do candidato (vaga, experiência, tecnologias)
- **Suporte a Áudio**: Aceita respostas por texto ou áudio (transcrição automática)
- **Feedback Inteligente**: Análise detalhada das respostas usando metodologia STAR
- **WhatsApp Integration**: Interface familiar via WhatsApp usando Twilio
- **Processamento Assíncrono**: Workers em background para melhor performance

## 🛠️ Tecnologias

- **Backend**: FastAPI + Python
- **IA**: Google Vertex AI (Gemini)
- **Messaging**: Twilio WhatsApp API
- **Speech-to-Text**: Google Cloud Speech API
- **Queue/Cache**: Redis + Celery
- **Tunneling**: ngrok

## 📋 Pré-requisitos

- Python 3.8+
- Docker (para Redis)
- Conta Google Cloud Platform
- Conta Twilio com WhatsApp sandbox
- ngrok instalado

## ⚙️ Configuração

### 1. Variáveis de Ambiente

Copie o arquivo `.env-example` para `.env` e configure suas credenciais:

```bash
cp .env-example .env
```

Edite o arquivo `.env` com suas credenciais reais:

```env
ID_PROJETO=seu-projeto-gcp
TWILIO_ACCOUNT_SID=seu-account-sid
TWILIO_AUTH_TOKEN=seu-auth-token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
```

### 2. Credenciais Google Cloud

1. Crie um projeto no Google Cloud Platform
2. Ative as APIs: Vertex AI, Speech-to-Text
3. Crie uma Service Account e baixe o arquivo JSON
4. Renomeie o arquivo para `google_credentials.json` e coloque na raiz do projeto

### 3. Configuração Twilio

1. Crie uma conta no Twilio
2. Configure o WhatsApp Sandbox
3. Anote o Account SID, Auth Token e número do WhatsApp

## 🚀 Instalação e Execução

### 1. Instalar Dependências

```bash
pip install -r requirements.txt
```

### 2. Iniciar Redis (Docker)

```bash
docker start meu-redis
```

*Se o container não existir, crie primeiro:*
```bash
docker run --name meu-redis -p 6379:6379 -d redis
```

### 3. Iniciar Worker Celery

```bash
celery -A main.celery worker --loglevel=info --pool=solo
```

### 4. Iniciar Servidor FastAPI

```bash
uvicorn main:app --reload
```

### 5. Expor Webhook Publicamente

```bash
ngrok http 8000
```

### 6. Configurar Webhook no Twilio

1. Copie a URL do ngrok (ex: `https://abc123.ngrok.io`)
2. No console Twilio, configure o webhook para: `https://abc123.ngrok.io/webhook/twilio`

## 🔄 Fluxo de Uso

1. **Início**: Usuário envia mensagem para o número WhatsApp
2. **Contexto**: Bot solicita contexto (vaga, experiência, tecnologias)
3. **Perguntas**: IA gera 3 perguntas personalizadas (2 soft skills + 1 hard skill)
4. **Respostas**: Usuário responde via texto ou áudio
5. **Feedback**: IA analisa e fornece feedback detalhado com pontuação

## 📁 Estrutura do Projeto

```
bot-entrevista-mvp/
├── main.py                 # Aplicação principal
├── requirements.txt        # Dependências Python
├── .env                   # Variáveis de ambiente (não versionado)
├── .env-example           # Template das variáveis de ambiente
├── .gitignore            # Arquivos ignorados pelo Git
├── google_credentials.json # Credenciais GCP (não versionado)
└── README.md             # Este arquivo
```

## 🧩 Arquitetura

### Componentes Principais

- **FastAPI Webhook**: Recebe mensagens do Twilio
- **Redis**: Cache de estado do usuário
- **Celery Workers**: Processamento assíncrono de IA
- **Google Vertex AI**: Geração de perguntas e feedback
- **Google Speech-to-Text**: Transcrição de áudio
- **Twilio**: Interface WhatsApp

### Estados do Usuário

- `aguardando_contexto`: Esperando informações do candidato
- `preparando_perguntas`: IA gerando perguntas
- `aguardando_resposta_N`: Coletando respostas (1, 2, 3)
- `gerando_feedback`: IA analisando respostas

## 🔧 Troubleshooting

### Redis não conecta
```bash
# Verificar se o container está rodando
docker ps

# Reiniciar se necessário
docker restart meu-redis
```

### Celery Worker com problemas
```bash
# No Windows, usar pool=solo
celery -A main.celery worker --loglevel=info --pool=solo

# No Linux/Mac, pode usar padrão
celery -A main.celery worker --loglevel=info
```

### Webhook não recebe mensagens
1. Verificar se o ngrok está ativo
2. Confirmar URL no console Twilio
3. Testar endpoint: `curl https://sua-url.ngrok.io/webhook/twilio`

### Problemas com áudio
- Verificar credenciais Google Cloud
- Confirmar APIs habilitadas (Speech-to-Text)
- Testar com mensagem de texto primeiro

## 📝 Comandos Úteis

```bash
# Iniciar tudo em sequência
docker start meu-redis
celery -A main.celery worker --loglevel=info --pool=solo &
uvicorn main:app --reload &
ngrok http 8000

# Verificar logs do Redis
docker logs meu-redis

# Limpar cache Redis
docker exec -it meu-redis redis-cli FLUSHALL

# Testar webhook localmente
curl -X POST http://localhost:8000/webhook/twilio \
  -d "From=whatsapp:+5511999999999&Body=teste"
```

## 🔒 Segurança

- Arquivo `.env` não está versionado
- Credenciais Google Cloud não estão versionadas
- Use HTTPS em produção
- Configure rate limiting se necessário

## 📈 Melhorias Futuras

- [ ] Persistência em banco de dados
- [ ] Métricas e analytics
- [ ] Suporte a mais idiomas
- [ ] Interface web administrativa
- [ ] Integração com calendários
- [ ] Feedback por voz (text-to-speech)

## 🆘 Suporte

Para problemas ou dúvidas:
1. Verificar logs do Celery worker
2. Conferir logs do FastAPI
3. Validar configurações no arquivo `.env`
4. Testar conectividade com Redis e APIs externas