from flask import Blueprint, render_template, request
from models import db, Lancamento, CentroCusto
from sqlalchemy import func, or_
from datetime import date, datetime
from collections import defaultdict

# Regime de caixa usa valor bruto — a taxa de cartão é registrada como despesa separada (CC005)
_valor_caixa = Lancamento.valor

relatorios_bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _meses_entre(inicio, fim):
    meses = []
    y, m = inicio.year, inicio.month
    while (y, m) <= (fim.year, fim.month):
        meses.append(f'{y:04d}-{m:02d}')
        m += 1
        if m > 12:
            m = 1
            y += 1
    return meses


@relatorios_bp.route('/dre')
def dre():
    hoje = date.today()
    data_de = _parse_date(request.args.get('data_de')) or date(hoje.year, 1, 1)
    data_ate = _parse_date(request.args.get('data_ate')) or hoje

    meses = _meses_entre(data_de, data_ate)
    centros = CentroCusto.query.filter_by(ativo=True).order_by(CentroCusto.nome).all()

    # ─── REGIME DE COMPETÊNCIA ───────────────────────────────────────────────
    def _query_competencia(tipo):
        return db.session.query(
            func.strftime('%Y-%m', Lancamento.data_competencia).label('mes'),
            CentroCusto.nome.label('centro'),
            func.sum(Lancamento.valor).label('total'),
        ).join(CentroCusto, Lancamento.centro_custo_id == CentroCusto.id, isouter=True).filter(
            Lancamento.tipo == tipo,
            Lancamento.status != 'cancelado',
            Lancamento.data_competencia >= data_de,
            Lancamento.data_competencia <= data_ate,
        ).group_by(
            func.strftime('%Y-%m', Lancamento.data_competencia),
            CentroCusto.nome,
        ).all()

    rec_comp_rows = _query_competencia('receita')
    desp_comp_rows = _query_competencia('despesa')

    rec_comp = defaultdict(lambda: defaultdict(float))
    for row in rec_comp_rows:
        rec_comp[row.centro or 'Sem Centro'][row.mes] += row.total

    desp_comp = defaultdict(lambda: defaultdict(float))
    for row in desp_comp_rows:
        desp_comp[row.centro or 'Sem Centro'][row.mes] += row.total

    # Totais por mês — competência
    totais_rec_comp = {m: sum(rec_comp[c][m] for c in rec_comp) for m in meses}
    totais_desp_comp = {m: sum(desp_comp[c][m] for c in desp_comp) for m in meses}
    resultado_comp = {m: totais_rec_comp[m] - totais_desp_comp[m] for m in meses}

    # ─── REGIME DE CAIXA ─────────────────────────────────────────────────────
    def _query_caixa(tipo, status):
        return db.session.query(
            func.strftime('%Y-%m', Lancamento.data_pagamento).label('mes'),
            CentroCusto.nome.label('centro'),
            func.sum(_valor_caixa).label('total'),
        ).join(CentroCusto, Lancamento.centro_custo_id == CentroCusto.id, isouter=True).filter(
            Lancamento.tipo == tipo,
            Lancamento.status == status,
            Lancamento.data_pagamento >= data_de,
            Lancamento.data_pagamento <= data_ate,
        ).group_by(
            func.strftime('%Y-%m', Lancamento.data_pagamento),
            CentroCusto.nome,
        ).all()

    rec_caixa_rows = _query_caixa('receita', 'recebido')
    desp_caixa_rows = _query_caixa('despesa', 'pago')

    rec_caixa = defaultdict(lambda: defaultdict(float))
    for row in rec_caixa_rows:
        rec_caixa[row.centro or 'Sem Centro'][row.mes] += row.total

    desp_caixa = defaultdict(lambda: defaultdict(float))
    for row in desp_caixa_rows:
        desp_caixa[row.centro or 'Sem Centro'][row.mes] += row.total

    totais_rec_caixa = {m: sum(rec_caixa[c][m] for c in rec_caixa) for m in meses}
    totais_desp_caixa = {m: sum(desp_caixa[c][m] for c in desp_caixa) for m in meses}
    resultado_caixa = {m: totais_rec_caixa[m] - totais_desp_caixa[m] for m in meses}

    # Totais gerais
    total_rec_comp = sum(totais_rec_comp.values())
    total_desp_comp = sum(totais_desp_comp.values())
    total_rec_caixa = sum(totais_rec_caixa.values())
    total_desp_caixa = sum(totais_desp_caixa.values())

    return render_template('relatorios/dre.html',
        data_de=data_de, data_ate=data_ate, meses=meses,
        # Competência
        rec_comp=dict(rec_comp), desp_comp=dict(desp_comp),
        totais_rec_comp=totais_rec_comp, totais_desp_comp=totais_desp_comp,
        resultado_comp=resultado_comp,
        total_rec_comp=total_rec_comp, total_desp_comp=total_desp_comp,
        resultado_comp_total=total_rec_comp - total_desp_comp,
        # Caixa
        rec_caixa=dict(rec_caixa), desp_caixa=dict(desp_caixa),
        totais_rec_caixa=totais_rec_caixa, totais_desp_caixa=totais_desp_caixa,
        resultado_caixa=resultado_caixa,
        total_rec_caixa=total_rec_caixa, total_desp_caixa=total_desp_caixa,
        resultado_caixa_total=total_rec_caixa - total_desp_caixa,
    )


FORMAS_LABEL = {
    'pix': 'PIX', 'dinheiro': 'Dinheiro', 'transferencia': 'Transferência',
    'cartao_debito': 'Débito', 'cartao_credito': 'Crédito',
    'boleto': 'Boleto', 'convenio': 'Convênio', 'cheque': 'Cheque',
}

@relatorios_bp.route('/fluxo-caixa')
def fluxo_caixa():
    hoje = date.today()
    data_de  = _parse_date(request.args.get('data_de'))  or date(hoje.year, hoje.month, 1)
    data_ate = _parse_date(request.args.get('data_ate')) or hoje
    forma_filtro = request.args.get('forma_pagamento', '')
    from servicos_financeiros import nomes_formas
    labels = {**FORMAS_LABEL, **{c: n for c, n in nomes_formas().items() if c not in FORMAS_LABEL}}

    from models import Cliente
    q_receita = Lancamento.query.filter(
        Lancamento.tipo == 'receita',
        Lancamento.status == 'recebido',
        Lancamento.data_pagamento >= data_de,
        Lancamento.data_pagamento <= data_ate,
    )
    q_despesa = Lancamento.query.filter(
        Lancamento.tipo == 'despesa',
        Lancamento.status == 'pago',
        Lancamento.data_pagamento >= data_de,
        Lancamento.data_pagamento <= data_ate,
        # a taxa de cartão já está descontada no valor líquido da entrada; listar a despesa
        # de taxa (CC005) aqui descontaria duas vezes
        or_(Lancamento.observacoes.is_(None), ~Lancamento.observacoes.like('%[taxa_de:%')),
    )
    if forma_filtro:
        q_receita = q_receita.filter(Lancamento.forma_pagamento == forma_filtro)
        q_despesa = q_despesa.filter(Lancamento.forma_pagamento == forma_filtro)

    lancs_receita = q_receita.order_by(Lancamento.data_pagamento, Lancamento.id).all()
    lancs_despesa = q_despesa.order_by(Lancamento.data_pagamento, Lancamento.id).all()

    # Agrupa por dia com detalhes individuais
    from collections import defaultdict
    dias_dados = defaultdict(lambda: {'entradas': [], 'saidas': []})

    for l in lancs_receita:
        dia = l.data_pagamento.strftime('%Y-%m-%d')
        valor_liq = l.valor_liquido if l.valor_liquido is not None else l.valor
        cliente_nome = l.cliente.nome if l.cliente else '—'
        dias_dados[dia]['entradas'].append({
            'descricao': l.descricao,
            'cliente': cliente_nome,
            'forma': labels.get(l.forma_pagamento or '', l.forma_pagamento or '—'),
            'parcelas': l.parcelas or 1,
            'valor_bruto': l.valor,
            'valor_liquido': valor_liq,
            'tem_taxa': (l.taxa_operadora_pct or 0) > 0,
            'taxa_pct': l.taxa_operadora_pct or 0,
        })

    for l in lancs_despesa:
        dia = l.data_pagamento.strftime('%Y-%m-%d')
        valor_liq = l.valor_liquido if l.valor_liquido is not None else l.valor
        dias_dados[dia]['saidas'].append({
            'descricao': l.descricao,
            'cliente': l.cliente.nome if l.cliente else None,
            'forma': labels.get(l.forma_pagamento or '', l.forma_pagamento or '—'),
            'parcelas': l.parcelas or 1,
            'valor_bruto': l.valor,
            'valor_liquido': valor_liq,
            'tem_taxa': (l.taxa_operadora_pct or 0) > 0,
            'taxa_pct': l.taxa_operadora_pct or 0,
        })

    dias = sorted(dias_dados.keys())
    saldo_acumulado = 0.0
    linhas = []
    for dia in dias:
        e_items = dias_dados[dia]['entradas']
        s_items = dias_dados[dia]['saidas']
        total_e = sum(it['valor_liquido'] for it in e_items)
        total_s = sum(it['valor_liquido'] for it in s_items)
        saldo_dia = total_e - total_s
        saldo_acumulado += saldo_dia
        linhas.append({
            'dia': dia,
            'entradas': total_e,
            'saidas': total_s,
            'saldo_dia': saldo_dia,
            'saldo_acumulado': saldo_acumulado,
            'itens_entrada': e_items,
            'itens_saida': s_items,
        })

    # Previsão — pendentes com vencimento no período
    previsao_receber = Lancamento.query.filter(
        Lancamento.tipo == 'receita',
        Lancamento.status == 'pendente',
        Lancamento.data_vencimento >= data_de,
        Lancamento.data_vencimento <= data_ate,
    ).order_by(Lancamento.data_vencimento).all()

    previsao_pagar = Lancamento.query.filter(
        Lancamento.tipo == 'despesa',
        Lancamento.status == 'pendente',
        Lancamento.data_vencimento >= data_de,
        Lancamento.data_vencimento <= data_ate,
    ).order_by(Lancamento.data_vencimento).all()

    # Pendentes SEM vencimento definido (ficam fora da previsão — aviso ao usuário)
    sem_venc_rec = Lancamento.query.filter(
        Lancamento.tipo == 'receita',
        Lancamento.status == 'pendente',
        Lancamento.data_vencimento.is_(None),
    ).all()
    sem_venc_desp = Lancamento.query.filter(
        Lancamento.tipo == 'despesa',
        Lancamento.status == 'pendente',
        Lancamento.data_vencimento.is_(None),
    ).all()

    total_entradas = sum(l['entradas'] for l in linhas)
    total_saidas = sum(l['saidas'] for l in linhas)
    total_prev_receber = sum(l.valor for l in previsao_receber)
    total_prev_pagar = sum(l.valor for l in previsao_pagar)

    # repasses de folhas de meses ANTERIORES ao período (o dinheiro correspondente entrou antes)
    from models import PeriodoFolha
    periodos = {p.id: (p.ano, p.mes) for p in PeriodoFolha.query.all()}
    repasses_anteriores = round(sum(
        l.valor for l in lancs_despesa
        if l.periodo_folha_id and periodos.get(l.periodo_folha_id, (9999, 12)) < (data_de.year, data_de.month)), 2)

    return render_template('relatorios/fluxo_caixa.html',
        repasses_anteriores=repasses_anteriores,
        data_de=data_de, data_ate=data_ate,
        forma_filtro=forma_filtro,
        formas_label=labels,
        linhas=linhas, total_entradas=total_entradas, total_saidas=total_saidas,
        saldo_final=saldo_acumulado,
        previsao_receber=previsao_receber, previsao_pagar=previsao_pagar,
        total_prev_receber=total_prev_receber, total_prev_pagar=total_prev_pagar,
        sem_venc_rec=sem_venc_rec, sem_venc_desp=sem_venc_desp,
        total_sem_venc_rec=sum(l.valor for l in sem_venc_rec),
        total_sem_venc_desp=sum(l.valor for l in sem_venc_desp),
    )


# Meses sem Folha com valor retido conhecido: {(ano, mes): valor}. Vazio por padrão.
RETIDO_PDF = {}


@relatorios_bp.route('/caixa-empresa')
def caixa_empresa():
    """Quanto fica na empresa: por mês do parto (como o PDF), entradas líquidas - repasses às prestadoras de serviço
    - despesas pagas. Meses com Folha usam o repasse calculado; fev-mai, o valor do PDF; outros sem Folha, X% de reserva."""
    from routes.relatorio_faturamento import montar_faturamento
    hoje = date.today()
    pct = request.args.get('despesa_pct', 12.0, type=float)
    pct = min(max(pct, 0.0), 100.0)
    primeiro = db.session.query(func.min(Lancamento.data_pagamento)).filter(
        Lancamento.tipo == 'receita', Lancamento.status == 'recebido').scalar() or hoje
    meses, a, m = [], primeiro.year, primeiro.month
    while (a, m) <= (hoje.year, hoje.month):
        meses.append((a, m))
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    linhas, avisos = [], []
    for a, m in meses:
        d = montar_faturamento(m, a, pct, 'parto', False, 'folha')
        if d['total_entradas'] <= 0 and d['total_custos'] <= 0:
            continue
        if d['tem_folha']:
            repasses, origem = d['total_repasse'], 'Folha'
            if d['horas_total'] <= 0:
                avisos.append(f"{d['mes_nome']}/{a}: a escala da Folha está sem horas, então nenhum repasse foi descontado.")
        elif (a, m) in RETIDO_PDF:
            repasses, origem = round(d['total_entradas'] - RETIDO_PDF[(a, m)], 2), 'conforme PDF'
        else:
            repasses, origem = round(d['total_entradas'] * (1 - pct / 100), 2), f'estimado ({pct:g}% fica como reserva)'
        retido = round(d['total_entradas'] - repasses, 2)
        linhas.append({'mes': f"{d['mes_nome'][:3]}/{a}", 'entradas': d['total_entradas'], 'repasses': repasses,
                       'origem': origem, 'retido': retido, 'custos': d['total_custos'],
                       'resultado': round(retido - d['total_custos'], 2)})
    total = {k: round(sum(l[k] for l in linhas), 2) for k in ('entradas', 'repasses', 'retido', 'custos', 'resultado')}
    # ISS (6%) das notas que ainda não foram emitidas: já é dívida da empresa, então sai do que fica no caixa
    from routes.contratos_iss import _build_contratos
    iss = _build_contratos()
    iss_nao_emitidas = round(iss['total_iss_estimado'], 2)
    return render_template('relatorios/caixa_empresa.html', linhas=linhas, total=total, avisos=avisos, pct=pct,
                           iss_nao_emitidas=iss_nao_emitidas, qtd_sem_nf=iss['count_sem_nf'],
                           iss_emitidas_a_pagar=round(iss['total_iss_a_pagar'], 2),
                           caixa_apos_iss=round(total['resultado'] - iss_nao_emitidas, 2))
