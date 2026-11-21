# taxas.py — Tabela de taxas das operadoras de cartão
from datetime import date

# Operadora assumida quando nenhuma é informada: a partir desta data, 'infinite'; antes dela, 'tom'.
# As taxas abaixo são EXEMPLOS: ajuste em Gerência > Formas de Pagamento (operadoras e taxas) antes de usar em produção.
INFINITE_PADRAO_DESDE = date(2000, 1, 1)


def operadora_padrao(data=None):
    """Operadora assumida quando nenhuma é informada, conforme a data do pagamento (hoje, se omitida)."""
    return 'infinite' if (data or date.today()) >= INFINITE_PADRAO_DESDE else 'tom'


TAXAS_POR_OPERADORA = {
    'tom': {
        'debito': 1.39,
        'credito': {
            1: 3.34, 2: 7.29, 3: 8.35, 4: 9.23, 5: 10.10,
            6: 10.85, 7: 10.90, 8: 10.95, 9: 11.00, 10: 11.05,
            11: 11.73, 12: 12.38, 13: 13.02, 14: 13.66, 15: 14.30,
            16: 14.94, 17: 15.58, 18: 16.22,
        },
    },
    'infinite': {
        'debito': 1.37,
        'credito': {
            1: 3.15, 2: 5.39, 3: 6.12, 4: 6.85, 5: 7.57,
            6: 8.28, 7: 8.99, 8: 9.69, 9: 10.38, 10: 11.06,
            11: 11.74, 12: 12.40,
        },
    },
}

# Aliases backward-compat (Tom)
TAXAS_DEBITO  = TAXAS_POR_OPERADORA['tom']['debito']
TAXAS_CREDITO = TAXAS_POR_OPERADORA['tom']['credito']

SEM_TAXA = {'pix', 'dinheiro'}


def tabela_operadoras() -> dict:
    """Tabela vigente: valores do banco (editáveis na tela) sobre as constantes acima."""
    tab = {k: {'debito': v['debito'], 'credito': dict(v['credito'])}
           for k, v in TAXAS_POR_OPERADORA.items()}
    from models import TaxaOperadora, schema_pronto
    if schema_pronto('taxas_operadora'):  # senão (migração pendente) vale a constante
        for r in TaxaOperadora.query.all():
            op = tab.setdefault(r.operadora, {'debito': 0.0, 'credito': {}})
            if r.modalidade == 'debito':
                op['debito'] = r.taxa_pct
            else:
                op['credito'][r.parcelas] = r.taxa_pct
    for op in tab.values():
        op['credito'] = dict(sorted(op['credito'].items()))
    return tab


def get_taxa_pct(forma_pagamento: str, parcelas: int = 1, operadora: str = 'tom') -> float:
    if not forma_pagamento:
        return 0.0
    from servicos_financeiros import tipo_taxa_forma  # import tardio: evita ciclo com models
    tipo = tipo_taxa_forma(forma_pagamento)
    if tipo == 'nenhuma':
        return 0.0
    tabela = tabela_operadoras()
    op = tabela.get(operadora) or tabela['tom']
    if tipo == 'debito':
        return op['debito']
    if tipo == 'credito':
        p = max(1, int(parcelas) if parcelas else 1)
        tabela = op['credito']
        p = min(p, max(tabela))
        return tabela.get(p, tabela[1])
    return 0.0


def calcular(valor_bruto: float, forma_pagamento: str, parcelas: int = 1, operadora: str = 'tom'):
    """Retorna (taxa_pct, taxa_valor, valor_liquido)."""
    taxa_pct = get_taxa_pct(forma_pagamento, parcelas, operadora)
    taxa_valor = round(valor_bruto * taxa_pct / 100, 2)
    valor_liquido = round(valor_bruto - taxa_valor, 2)
    return taxa_pct, taxa_valor, valor_liquido


def taxas_js_dict() -> dict:
    return tabela_operadoras()
