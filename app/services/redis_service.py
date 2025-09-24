import logging
import redis
from functools import lru_cache

from app.config import settings

log = logging.getLogger(__name__)

@lru_cache()
def get_redis_client():
    """
    Cria e retorna uma conexão com o servidor Redis.
    
    A anotação @lru_cache garante que a conexão seja estabelecida apenas uma vez
    (padrão singleton), sendo reutilizada em todas as chamadas subsequentes dentro
    da aplicação, o que é essencial para a performance.
    
    Retorna o cliente Redis conectado ou None em caso de falha.
    """
    if not settings or not settings.REDIS_HOST:
        log.critical("Configurações do Redis não foram carregadas. Não é possível conectar.")
        return None

    try:
        r = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=0,
            decode_responses=True
        )
        r.ping()
        log.info(f"Conectado ao Redis com sucesso em {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        return r
    except redis.exceptions.ConnectionError as e:
        log.critical(
            "Não foi possível conectar ao Redis. Verifique se o serviço está em execução.",
            extra={"host": settings.REDIS_HOST, "port": settings.REDIS_PORT, "error": str(e)}
        )
        return None
    except Exception as e:
        log.critical(
            "Ocorreu um erro inesperado ao conectar ao Redis.",
            extra={"error": str(e)}
        )
        return None
