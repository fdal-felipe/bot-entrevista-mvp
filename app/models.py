from pydantic import BaseModel, Field
from typing import List, Optional

class UserState(BaseModel):
    """
    Representa o estado completo da conversa de um usuário no bot.
    Este modelo é usado para validar, serializar e desserializar
    os dados armazenados no Redis.
    """
    
    user_key: Optional[str] = Field(default=None, description="Chave única do usuário (número do WhatsApp)")
    
    etapa: str = Field(default="inicio", description="A etapa atual na máquina de estados da conversa.")

    contexto: Optional[str] = Field(default=None, description="O contexto da entrevista fornecido pelo usuário.")

    perguntas: List[str] = Field(default_factory=list, description="Lista de perguntas geradas pela IA.")

    respostas: List[str] = Field(default_factory=list, description="Lista de respostas fornecidas pelo usuário.")

    perguntas_prontas: bool = Field(default=False, description="Flag que indica se as perguntas estão prontas para serem enviadas.")

    erro_geracao: Optional[str] = Field(default=None, description="Mensagem de erro da geração de perguntas.")

    feedback_gerado: Optional[str] = Field(default=None, description="O texto do feedback gerado pela IA.")
    
    erro_feedback: Optional[str] = Field(default=None, description="Mensagem de erro da geração de feedback.")

    depoimento: Optional[str] = Field(default=None, description="O depoimento do usuário sobre a experiência.")

    last_user_ts: Optional[int] = Field(default=None, description="Timestamp (epoch) da última mensagem do usuário.")

    class Config:
        exclude_none = True
