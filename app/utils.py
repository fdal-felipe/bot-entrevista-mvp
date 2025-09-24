import re

def validar_email(email: str) -> bool:
    """
    Valida se o formato de uma string corresponde a um e-mail válido.
    """
    if not email:
        return False
    padrao = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(padrao, email) is not None
