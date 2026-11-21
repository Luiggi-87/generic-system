"""Regras financeiras compartilhadas (taxa de cartão como despesa, vencimento de contratos)."""
import calendar
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from models import db, Cliente, Lancamento, CentroCusto, FormaPagamento, TaxaOperadora, Operadora, schema_pronto

_TAG_RE = re.compile(r'\[taxa_de:(\d+)\]')


def _despesas_de_taxa(receita_id):
    return Lancamento.query.filter(
        Lancamento.tipo == 'despesa',
        Lancamento.observacoes.like(f'%[taxa_de:{receita_id}]%'),
    ).all()


def sincronizar_taxa(lanc):
    """Mantém UMA despesa de taxa (CC005) coerente com a receita `lanc`.

    Existe se e somente se a receita está recebida, com taxa > 0 e data de pagamento.
    Cria, atualiza ou remove conforme necessário — não faz commit.
    """
    if lanc.id is None:
        db.session.flush()
    existentes = _despesas_de_taxa(lanc.id)

    deve_ter = (lanc.tipo == 'receita' and lanc.status == 'recebido'
                and (lanc.taxa_operadora_valor or 0) > 0 and lanc.data_pagamento)
    if not deve_ter:
        for e in existentes:
            db.session.delete(e)
        return

    for extra in existentes[1:]:  # duplicadas
        db.session.delete(extra)
    taxa = existentes[0] if existentes else Lancamento(tipo='despesa', status='pago')

    pct = lanc.taxa_operadora_pct or 0
    forma = nomes_formas().get(lanc.forma_pagamento, lanc.forma_pagamento or '')
    cc = CentroCusto.query.filter_by(codigo='CC005').first()
    taxa.descricao = f'Taxa {forma} {pct:.2f}% — {lanc.descricao}'
    taxa.valor = lanc.taxa_operadora_valor
    taxa.data_competencia = lanc.data_pagamento
    taxa.data_pagamento = lanc.data_pagamento
    taxa.status = 'pago'
    taxa.centro_custo_id = cc.id if cc else None
    taxa.forma_pagamento = lanc.forma_pagamento
    taxa.observacoes = (f'[taxa_de:{lanc.id}] Dedução automática de {pct:.2f}% '
                        f'sobre recebimento de {lanc.valor:.2f}')
    db.session.add(taxa)


def sincronizar_todas():
    """Reconcilia as despesas de taxa de TODAS as receitas. Retorna (receitas_verificadas, orfãs_removidas)."""
    receitas = Lancamento.query.filter(Lancamento.tipo == 'receita').all()
    ids = {r.id for r in receitas}
    verificadas = 0
    for r in receitas:
        if (r.taxa_operadora_valor or 0) > 0 or _despesas_de_taxa(r.id):
            sincronizar_taxa(r)
            verificadas += 1

    orfas = 0
    for d in Lancamento.query.filter(Lancamento.tipo == 'despesa',
                                     Lancamento.observacoes.like('%[taxa_de:%')).all():
        m = _TAG_RE.search(d.observacoes or '')
        if m and int(m.group(1)) not in ids:  # receita de origem não existe mais
            db.session.delete(d)
            orfas += 1
    return verificadas, orfas


def preencher_vencimentos():
    """Contratos pendentes sem vencimento passam a vencer na data de competência (parto/DPP)."""
    n = 0
    for l in Lancamento.query.filter(
            Lancamento.tipo == 'receita', Lancamento.status == 'pendente',
            Lancamento.data_vencimento.is_(None), Lancamento.atendimento_id.is_(None),
            Lancamento.periodo_folha_id.is_(None)).all():
        l.data_vencimento = l.data_competencia
        n += 1
    return n


def partos_sem_pagamento(hoje=None):
    """Clientes que já pariram (data do parto até hoje) e têm contrato pendente de pagamento:
    {cliente_id: valor pendente}. Pagamento parcial também conta (o que falta pagar)."""
    hoje = hoje or date.today()
    rows = (db.session.query(Lancamento.cliente_id, db.func.sum(Lancamento.valor))
            .join(Cliente, Cliente.id == Lancamento.cliente_id)
            .filter(Cliente.data_parto.isnot(None), Cliente.data_parto <= hoje,
                    Lancamento.tipo == 'receita', Lancamento.status == 'pendente', Lancamento.atendimento_id.is_(None))
            .group_by(Lancamento.cliente_id).all())
    return {cid: round(v, 2) for cid, v in rows if v and v > 0}


def gestantes_36_sem_pagamento(hoje=None):
    """Gestantes que entraram na 36ª semana (DPP em até 28 dias, ou já passada) sem parto registrado e com
    contrato pendente de pagamento: [(cliente, valor pendente)], da gestação mais avançada para a menos."""
    hoje = hoje or date.today()
    pend = dict(db.session.query(Lancamento.cliente_id, db.func.sum(Lancamento.valor))
                .filter(Lancamento.tipo == 'receita', Lancamento.status == 'pendente', Lancamento.atendimento_id.is_(None),
                        Lancamento.cliente_id.isnot(None))
                .group_by(Lancamento.cliente_id).all())
    clientes = (Cliente.query.filter(Cliente.status == 'ativa', Cliente.data_parto.is_(None),
                                     Cliente.data_prevista_parto.isnot(None),
                                     Cliente.data_prevista_parto <= hoje + timedelta(days=28))
                .order_by(Cliente.data_prevista_parto).all())
    return [(c, round(pend[c.id], 2)) for c in clientes if pend.get(c.id, 0) > 0]


def valor_percentual(pct, ano, mes):
    """pct% do lucro bruto do mês. Folha de nov/2026 em diante (aberta ou fechada): o lucro bruto da Folha (soma das receitas
    dela), a mesma base usada ao fechar a Folha. Sem Folha: contratos dos partos do mês (já recebidos + a receber), como no
    relatório de faturamento com 'incluir contratos a receber'."""
    from models import PeriodoFolha
    from routes.folha import RATEIO_CUSTOS_DESDE
    folha = PeriodoFolha.query.filter_by(mes=mes, ano=ano).first() if (ano, mes) >= RATEIO_CUSTOS_DESDE else None
    if folha is not None:
        base = sum(r.total for r in folha.receitas)
    else:
        from routes.relatorio_faturamento import montar_faturamento
        base = montar_faturamento(mes, ano, 12.0, 'parto', True)['total_entradas']
    return round((pct or 0) / 100 * base, 2)


def lancamentos_percentuais(ano, mes):
    """Despesas recorrentes por % do lucro bruto: [(modelo, lançamento do mês ou None)]."""
    if not schema_pronto('lancamentos', 'percentual_lucro'):
        return []
    saida = []
    for m in Lancamento.query.filter(Lancamento.recorrente.is_(True), Lancamento.tipo == 'despesa',
                                     Lancamento.percentual_lucro.isnot(None), Lancamento.status != 'cancelado').all():
        comp = (m.data_competencia.year, m.data_competencia.month)
        if comp > (ano, mes):
            continue
        x = m if comp == (ano, mes) else next(
            (c for c in Lancamento.query.filter_by(recorrencia_origem_id=m.id)
             if (c.data_competencia.year, c.data_competencia.month) == (ano, mes) and c.status != 'cancelado'), None)
        saida.append((m, x))
    return saida


def baixar_percentuais_da_folha(ano, mes, lucro_bruto):
    """Ao fechar a Folha: lança como PAGA, no último dia do mês, a despesa recorrente de % do lucro bruto, calculada sobre o
    lucro bruto da Folha (para não depender de lembrar a data nem de dar a baixa). Não faz commit; devolve [(descrição, valor)]."""
    ultimo = date(ano, mes, calendar.monthrange(ano, mes)[1])
    gerar_recorrentes(ultimo, commit=False)   # garante a cópia do mês (sem commit: tudo vai junto com o fechamento)
    feitas = []
    for m, x in lancamentos_percentuais(ano, mes):
        if x is None or x.status != 'pendente':
            continue   # já paga (ou cancelada): fica como está
        valor = round(m.percentual_lucro / 100 * lucro_bruto, 2)
        if valor <= 0:
            continue
        x.valor, x.status, x.data_pagamento = valor, 'pago', ultimo
        x.forma_pagamento = x.forma_pagamento or m.forma_pagamento or 'pix'
        x.updated_at = datetime.utcnow()
        feitas.append((x.descricao, valor))
    return feitas


def gerar_recorrentes(hoje=None, commit=True):
    """Cria, como PENDENTES, as despesas recorrentes dos meses que faltam (do mês seguinte ao do modelo
    até o mês atual). Idempotente. `commit=False`: só prepara na sessão, quem chama faz o commit. Para parar: desmarcar 'recorrente' no modelo (ou cancelá-lo).
    Recorrente por % do lucro bruto: o valor das pendentes é recalculado a cada chamada (o lucro do mês muda
    até o fim do mês); depois de paga, a despesa fica com o valor pago."""
    if not (schema_pronto('lancamentos', 'recorrencia_origem_id') and schema_pronto('lancamentos', 'percentual_lucro')):
        return 0
    hoje = hoje or date.today()
    criadas, mudou = 0, False
    for m in Lancamento.query.filter(Lancamento.recorrente.is_(True), Lancamento.tipo == 'despesa',
                                     Lancamento.status != 'cancelado').all():
        existentes = {(x.data_competencia.year, x.data_competencia.month): x
                      for x in Lancamento.query.filter_by(recorrencia_origem_id=m.id)}
        existentes[(m.data_competencia.year, m.data_competencia.month)] = m
        ano, mes = m.data_competencia.year, m.data_competencia.month
        while (ano, mes) <= (hoje.year, hoje.month):
            valor = valor_percentual(m.percentual_lucro, ano, mes) if m.percentual_lucro else m.valor
            x = existentes.get((ano, mes))
            dia = min(m.dia_recorrencia or m.data_competencia.day, calendar.monthrange(ano, mes)[1])
            if x is None:
                db.session.add(Lancamento(
                    descricao=m.descricao, tipo='despesa', valor=valor, status='pendente',
                    data_competencia=date(ano, mes, dia), data_vencimento=date(ano, mes, dia),
                    centro_custo_id=m.centro_custo_id, forma_pagamento=m.forma_pagamento,
                    observacoes=m.observacoes, recorrencia_origem_id=m.id))
                criadas += 1
            else:
                if m.percentual_lucro and x.status == 'pendente' and abs(x.valor - valor) > 0.004:
                    x.valor, mudou = valor, True
                if x.status == 'pendente' and x.data_vencimento is None:   # sem vencimento: vence no dia da recorrência
                    x.data_vencimento, mudou = date(ano, mes, dia), True
            ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    if (criadas or mudou) and commit:
        db.session.commit()
    return criadas


def backup_banco():
    """Cópia consistente do banco em instance/backups/. Retorna o caminho."""
    origem = Path(db.engine.url.database)
    destino_dir = origem.parent / 'backups'
    destino_dir.mkdir(exist_ok=True)
    destino = destino_dir / f'gestao_clinica_{datetime.now():%Y%m%d_%H%M%S}.db'
    src, dst = sqlite3.connect(origem), sqlite3.connect(destino)
    with dst:
        src.backup(dst)
    src.close(); dst.close()
    return destino


# ── Formas de pagamento ──────────────────────────────────────────────────────

FORMAS_BASE = [
    ('pix', 'PIX'),
    ('dinheiro', 'Dinheiro'),
    ('cartao_debito', 'Cartão Débito'),
    ('cartao_credito', 'Cartão Crédito'),
    ('transferencia', 'Transferência'),
    ('link_pagamento', 'Link de Pagamento'),
]
# Como cada forma do sistema calcula taxa (a cliente define as formas novas na tela)
TIPO_TAXA_BASE = {'cartao_debito': 'debito', 'cartao_credito': 'credito', 'link_pagamento': 'credito'}
TRAVADAS = ('cartao_debito', 'cartao_credito')  # o tipo de taxa destas não pode ser alterado
OPERADORAS_BASE = [('tom', 'Tom'), ('infinite', 'Infinite Pay')]
# Prazo preenchido na primeira carga; o prazo de cartão/link depende do contrato com a operadora
PRAZOS_PADRAO = {'pix': 'Imediato', 'dinheiro': 'Imediato', 'transferencia': 'Imediato'}


def seed_formas_pagamento():
    """Cadastra as formas do sistema, sem sobrescrever o que o usuário já alterou."""
    existentes = {f.codigo for f in FormaPagamento.query.all()}
    for codigo, nome in FORMAS_BASE:
        if codigo not in existentes:
            db.session.add(FormaPagamento(codigo=codigo, nome=nome, padrao=True, ativo=True))
    db.session.flush()
    seed_taxas_operadora()
    seed_operadoras()
    for f in FormaPagamento.query.all():
        if f.codigo in TRAVADAS:
            f.tipo_taxa = TIPO_TAXA_BASE[f.codigo]
        elif f.tipo_taxa is None:
            f.tipo_taxa = TIPO_TAXA_BASE.get(f.codigo, 'nenhuma')
    for f in FormaPagamento.query.filter(FormaPagamento.prazo.is_(None)).all():
        if f.codigo in PRAZOS_PADRAO:
            f.prazo = PRAZOS_PADRAO[f.codigo]
    db.session.commit()


def seed_taxas_operadora():
    """Carrega as taxas atuais (taxas.py) para o banco, sem sobrescrever o que a cliente editou."""
    from taxas import TAXAS_POR_OPERADORA
    existentes = {(t.operadora, t.modalidade, t.parcelas) for t in TaxaOperadora.query.all()}
    for operadora, tab in TAXAS_POR_OPERADORA.items():
        linhas = [('debito', 1, tab['debito'])] + [('credito', p, v) for p, v in tab['credito'].items()]
        for modalidade, parcelas, pct in linhas:
            if (operadora, modalidade, parcelas) not in existentes:
                db.session.add(TaxaOperadora(operadora=operadora, modalidade=modalidade,
                                             parcelas=parcelas, taxa_pct=pct))


def formas_ativas(incluir=None):
    """[(codigo, nome)] das formas liberadas. `incluir` mantém uma forma já usada, mesmo bloqueada."""
    if not schema_pronto('formas_pagamento', 'tipo_taxa'):  # migração pendente
        return list(FORMAS_BASE)
    formas = FormaPagamento.query.order_by(FormaPagamento.padrao.desc(), FormaPagamento.nome).all()
    if not formas:
        return list(FORMAS_BASE)
    return [(f.codigo, f.nome) for f in formas if f.ativo or f.codigo == incluir]


def nomes_formas():
    """{codigo: nome} de todas as formas (inclusive bloqueadas), para exibir histórico."""
    d = {}
    if schema_pronto('formas_pagamento', 'tipo_taxa'):
        d = {f.codigo: f.nome for f in FormaPagamento.query.all()}
    return {**dict(FORMAS_BASE), **d}


def forma_liberada(codigo):
    """True se a forma pode ser usada em novos pagamentos (vazio/desconhecido = liberado)."""
    if not codigo:
        return True
    if not schema_pronto('formas_pagamento', 'tipo_taxa'):
        return True
    f = FormaPagamento.query.filter_by(codigo=codigo).first()
    return f is None or f.ativo


# ── Operadoras (maquininhas / link) e tipo de taxa das formas ──────────────

def seed_operadoras():
    """Cadastra Tom e Infinite Pay (e qualquer operadora que já tenha taxas) sem sobrescrever edições."""
    existentes = {o.codigo for o in Operadora.query.all()}
    nomes = dict(OPERADORAS_BASE)
    codigos = list(nomes) + [c for (c,) in db.session.query(TaxaOperadora.operadora).distinct() if c not in nomes]
    for codigo in codigos:
        if codigo not in existentes:
            db.session.add(Operadora(codigo=codigo, nome=nomes.get(codigo, codigo), ativo=True))


def operadoras_ativas(incluir=None):
    """[(codigo, nome)] das operadoras liberadas (mantém `incluir` mesmo bloqueada)."""
    if not schema_pronto('operadoras'):
        return list(OPERADORAS_BASE)
    ops = Operadora.query.order_by(Operadora.id).all()
    if not ops:
        return list(OPERADORAS_BASE)
    return [(o.codigo, o.nome) for o in ops if o.ativo or o.codigo == incluir]


def nomes_operadoras():
    d = {}
    if schema_pronto('operadoras'):
        d = {o.codigo: o.nome for o in Operadora.query.all()}
    return {**dict(OPERADORAS_BASE), **d}


def tipos_taxa():
    """{codigo da forma: 'nenhuma' | 'debito' | 'credito'}."""
    d = {}
    if schema_pronto('formas_pagamento', 'tipo_taxa'):
        d = {f.codigo: (f.tipo_taxa or TIPO_TAXA_BASE.get(f.codigo, 'nenhuma'))
             for f in FormaPagamento.query.all()}
    d.update({c: TIPO_TAXA_BASE[c] for c in TRAVADAS})
    return {**TIPO_TAXA_BASE, **d}


def tipo_taxa_forma(codigo):
    return tipos_taxa().get(codigo, 'nenhuma') if codigo else 'nenhuma'
