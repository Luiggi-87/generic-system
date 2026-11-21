"""Leitura do PDF da NFS-e do padrão nacional (DANFSe v2.0, portal do governo federal).

O PDF gerado pelo emissor traz o texto dentro do arquivo, cada campo logo abaixo do seu título; aqui o texto é
extraído (pypdf) e os campos são localizados pelos títulos. PDF escaneado/foto (sem texto) não é lido: nesse caso
use o XML da nota. Os campos devolvidos seguem os de nfse_xml.ler_nfse, mais 'descricao' (descrição do serviço,
onde costuma estar o nome da paciente)."""
import io
import re
from datetime import date

from nfse_xml import so_digitos

TAMANHO_MAX = 2 * 1024 * 1024  # 2 MB
PAGINAS_MAX = 3


def _data(txt):
    m = re.match(r'\s*(\d{2})/(\d{2})/(\d{4})', txt or '')
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
    except ValueError:
        return None


def _valor(txt):
    m = re.search(r'R\$\s*([\d.]+,\d{2})', txt or '')
    return float(m.group(1).replace('.', '').replace(',', '.')) if m else None


def _apos(texto, titulo, padrao=r'([^\n]+)'):
    """Texto da linha seguinte ao título (primeira ocorrência)."""
    m = re.search(re.escape(titulo) + r'[ \t]*\n[ \t]*' + padrao, texto)
    return m.group(1).strip() if m else ''


def _bloco(texto, ini, fim):
    a = texto.find(ini)
    if a < 0:
        return ''
    b = texto.find(fim, a + len(ini))
    return texto[a:b if b > 0 else len(texto)]


def ler_texto_danfse(texto, nome_arquivo=''):
    """Extrai os campos do texto de um DANFSe. Devolve dict (com 'erro' se não reconhecer o layout)."""
    base = {'arquivo': nome_arquivo}
    texto = texto.replace('\r', '')
    numero = _apos(texto, 'NÚMERO DA NFS-e', r'(\d+)')
    chave = _apos(texto, 'CHAVE DE ACESSO DA NFS-e', r'(\d{50})')
    emissao = _data(_apos(texto, 'DATA E HORA DA EMISSÃO DA NFS-e'))
    competencia = _data(_apos(texto, 'COMPETÊNCIA DA NFS-e')) or emissao
    prest = _bloco(texto, 'PRESTADOR / FORNECEDOR', 'TOMADOR / ADQUIRENTE')
    toma = _bloco(texto, 'TOMADOR / ADQUIRENTE', 'SERVIÇO PRESTADO')
    desc = _bloco(texto, 'Descrição do Serviço', 'TRIBUTAÇÃO MUNICIPAL')
    desc = re.sub(r'^Descrição do Serviço\s*', '', desc).strip()
    bruto = _valor(_apos(texto, 'VALOR TOTAL DA NFS-e VALOR DA OPERAÇÃO / SERVIÇO'))
    liquido = _valor(_apos(texto, 'VALOR LÍQUIDO DA NFS-e'))
    iss = _valor(_apos(texto, 'ISSQN Apurado'))   # "-" no Simples Nacional (imposto na guia mensal)
    aliq_txt = _apos(texto, 'Alíquota Aplicada')
    m = re.search(r'([\d.,]+)\s*%?', aliq_txt)
    aliq = float(m.group(1).replace('.', '').replace(',', '.')) if m and re.search(r'\d', aliq_txt) else None
    dados = {
        **base, 'numero': numero, 'chave': chave, 'data_emissao': emissao, 'competencia': competencia,
        'valor_bruto': bruto, 'valor_liquido': liquido, 'valor_iss': iss, 'aliquota': aliq,
        'tomador_nome': _apos(toma, 'Nome / Nome Empresarial'), 'tomador_doc': so_digitos(_apos(toma, 'TOMADOR / ADQUIRENTE CNPJ / CPF / NIF')),
        'prestador_nome': _apos(prest, 'Nome / Nome Empresarial'), 'prestador_doc': so_digitos(_apos(prest, 'PRESTADOR / FORNECEDOR CNPJ / CPF / NIF')),
        'descricao': re.sub(r'\s+', ' ', desc),
    }
    faltam = [r for r, v in (('número', numero), ('data de emissão', emissao), ('valor', bruto)) if not v]
    if faltam:
        return {**dados, 'erro': 'Não foi possível ler: ' + ', '.join(faltam) + '. Confira se é o PDF (DANFSe) de uma NFS-e nacional ou use o XML.'}
    return dados


def ler_nfse_pdf(conteudo, nome_arquivo=''):
    """Lê o PDF (bytes) de uma NFS-e nacional."""
    base = {'arquivo': nome_arquivo}
    if len(conteudo) > TAMANHO_MAX:
        return {**base, 'erro': 'PDF grande demais (máximo 2 MB).'}
    try:
        from pypdf import PdfReader
    except ImportError:
        return {**base, 'erro': 'A leitura de PDF ainda não está instalada no servidor (pacote pypdf). Use o XML da nota.'}
    try:
        leitor = PdfReader(io.BytesIO(conteudo))
        if len(leitor.pages) > PAGINAS_MAX:
            return {**base, 'erro': f'PDF com muitas páginas (máximo {PAGINAS_MAX}): não parece uma NFS-e.'}
        texto = '\n'.join((p.extract_text() or '') for p in leitor.pages)
    except Exception:
        return {**base, 'erro': 'Não foi possível abrir o PDF.'}
    if len(texto.strip()) < 50:
        return {**base, 'erro': 'O PDF não tem texto (imagem escaneada). Use o PDF/XML original gerado pelo emissor.'}
    return ler_texto_danfse(texto, nome_arquivo)
