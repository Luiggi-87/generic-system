"""
Licença offline do sistema.

A licença é um texto "dados.assinatura" emitido pelo fornecedor (ferramentas_fornecedor/gerar_licenca.py).
Aqui só se VERIFICA a assinatura com a chave pública abaixo. A chave privada não está neste projeto,
então ninguém consegue fabricar uma licença só com o código entregue.
"""

import base64
import binascii
import json
import os
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Chave pública do fornecedor (pode ser divulgada).
CHAVE_PUBLICA_B64 = 'uRLyLexPwW4lIBf7QFOm2WpnR+QnnZ4i9AtHgpd+w4g='

ARQUIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'licenca.txt')


def _decodificar(parte: str) -> bytes:
    return base64.urlsafe_b64decode(parte + '=' * (-len(parte) % 4))


def verificar(texto: str):
    """Retorna (True, dados) se a licença é válida e vigente; senão (False, motivo)."""
    try:
        parte_dados, parte_assinatura = texto.strip().split('.')
        dados_bytes = _decodificar(parte_dados)
        assinatura = _decodificar(parte_assinatura)
        chave = Ed25519PublicKey.from_public_bytes(base64.b64decode(CHAVE_PUBLICA_B64))
        chave.verify(assinatura, dados_bytes)
        dados = json.loads(dados_bytes.decode('utf-8'))
        validade = date.fromisoformat(dados['validade'])
    except (ValueError, KeyError, binascii.Error, InvalidSignature):
        return False, 'Licença inválida.'
    if validade < date.today():
        return False, f"Licença vencida em {validade.strftime('%d/%m/%Y')}."
    return True, dados


def licenca_instalada():
    """Verifica a licença salva nesta instalação. Retorna (ok, dados_ou_motivo)."""
    if not os.path.exists(ARQUIVO):
        return False, 'Nenhuma licença instalada.'
    with open(ARQUIVO, encoding='utf-8') as f:
        return verificar(f.read())


def instalar(texto: str):
    """Valida a licença colada pelo cliente e a grava na instalação. Retorna (ok, dados_ou_motivo)."""
    ok, resultado = verificar(texto)
    if ok:
        os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
        with open(ARQUIVO, 'w', encoding='utf-8') as f:
            f.write(texto.strip())
    return ok, resultado
