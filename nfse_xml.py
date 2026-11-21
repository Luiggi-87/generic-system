"""Leitura de XML de NFS-e (padrão nacional do governo federal e municipais no padrão ABRASF).

Sem chave de API: a cliente envia o arquivo e o sistema extrai número, datas, valor, ISS e tomador.
O leitor ignora namespaces e procura os campos pelo nome, então tolera pequenas diferenças de layout;
o que não for encontrado volta vazio e a tela de conferência deixa a pessoa completar."""
import re
import xml.etree.ElementTree as ET
from datetime import date

TAMANHO_MAX = 1024 * 1024  # 1 MB por arquivo


def _local(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def _acha(raiz, *nomes):
    """Primeiro elemento (em ordem do documento) com algum dos nomes dados."""
    for nome in nomes:
        for el in raiz.iter():
            if _local(el.tag) == nome:
                return el
    return None


def _texto(raiz, *nomes):
    el = _acha(raiz, *nomes)
    return (el.text or '').strip() if el is not None and el.text else ''


def _valor(txt):
    s = (txt or '').strip().replace('R$', '').replace(' ', '')
    if not s:
        return None
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None


def _data(txt):
    try:
        return date.fromisoformat((txt or '').strip()[:10])
    except ValueError:
        return None


def so_digitos(s):
    return re.sub(r'\D', '', s or '')


def ler_nfse(conteudo, nome_arquivo=''):
    """Lê o XML de uma NFS-e. Devolve um dict com os campos; em caso de erro, {'arquivo':..., 'erro': '...'}."""
    base = {'arquivo': nome_arquivo}
    if len(conteudo) > TAMANHO_MAX:
        return {**base, 'erro': 'Arquivo grande demais (máximo 1 MB).'}
    if b'<!DOCTYPE' in conteudo.upper() or b'<!ENTITY' in conteudo.upper():
        return {**base, 'erro': 'XML recusado por segurança (declaração DOCTYPE/ENTITY).'}
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError:
        return {**base, 'erro': 'O arquivo não é um XML válido.'}

    numero = _texto(raiz, 'nNFSe', 'Numero')
    inf = _acha(raiz, 'infNFSe', 'InfNfse', 'InfNFSe')
    chave = ''
    if inf is not None:
        m = re.search(r'(\d{50})', inf.get('Id', '') or '')
        chave = m.group(1) if m else ''
    tomador = _acha(raiz, 'toma', 'TomadorServico', 'Tomador')
    escopo = tomador if tomador is not None else ET.Element('vazio')
    doc = so_digitos(_texto(escopo, 'CPF', 'CNPJ', 'Cpf', 'Cnpj'))
    prestador = _acha(raiz, 'emit', 'PrestadorServico', 'prest', 'Prestador')
    esc_prest = prestador if prestador is not None else ET.Element('vazio')
    bruto = _valor(_texto(raiz, 'vServ', 'ValorServicos'))
    liquido = _valor(_texto(raiz, 'vLiq', 'ValorLiquidoNfse'))
    iss = _valor(_texto(raiz, 'vISSQN', 'ValorIss'))
    aliq = _valor(_texto(raiz, 'pAliqAplic', 'pAliq', 'Aliquota'))
    if aliq is not None and aliq < 1:   # 0,05 -> 5 (%)
        aliq = round(aliq * 100, 4)
    emissao = _data(_texto(raiz, 'dhEmi', 'DataEmissao', 'dhProc'))
    competencia = _data(_texto(raiz, 'dCompet', 'Competencia')) or emissao

    dados = {
        **base, 'numero': numero, 'chave': chave, 'data_emissao': emissao, 'competencia': competencia,
        'valor_bruto': bruto, 'valor_iss': iss, 'aliquota': aliq,
        'tomador_nome': _texto(escopo, 'xNome', 'RazaoSocial', 'Nome'), 'tomador_doc': doc,
        'valor_liquido': liquido,
        'descricao': _texto(raiz, 'xDescServ', 'Discriminacao'),   # nome/CPF da paciente costumam vir aqui (o tomador é a clínica)
        'prestador_nome': _texto(esc_prest, 'xNome', 'RazaoSocial', 'NomeFantasia', 'Nome'),
        'prestador_doc': so_digitos(_texto(esc_prest, 'CNPJ', 'CPF', 'Cnpj', 'Cpf')),
    }
    faltam = [r for r, v in (('número', numero), ('data de emissão', emissao), ('valor', bruto)) if not v]
    if faltam:
        return {**dados, 'erro': 'Não foi possível ler: ' + ', '.join(faltam) + '. Confira se é o XML de uma NFS-e.'}
    return dados
