"""Relatório de Faturamento de Vendas (divisão de lucros) e relatório individual por prestadora de serviço.

Segue a estrutura do demonstrativo em PDF usado com as sócias:
  entradas do mês (por gestante) -> despesas de X% sobre o lucro bruto -> lucro líquido
  -> rateio pela escala (hora noturna vale 25% a mais) -> repasse por prestadora de serviço.
"""
import calendar
from collections import OrderedDict
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from sqlalchemy import and_, or_

from models import Cliente, Lancamento, NotaFiscal, PeriodoFolha
from servicos_financeiros import nomes_formas

MARCA_FORA_DO_RATEIO = '[fora-rateio]'   # nas observações do ISS de uma nota: a despesa não entra no rateio das prestadoras

faturamento_bp = Blueprint('faturamento', __name__, url_prefix='/financeiro/relatorio-faturamento')

FATOR_NOTURNO = 1.25
MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
         'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
CATEGORIAS = ['parto', 'amamentacao', 'laser', 'curso', 'outros']


def _categoria(l):
    if l.atendimento_id is None:
        return 'parto'  # contrato da gestante
    d = (l.descricao or '').lower()
    if 'amament' in d:
        return 'amamentacao'
    if 'laser' in d:
        return 'laser'
    if 'curso' in d:
        return 'curso'
    return 'outros'


def _parametros():
    hoje = date.today()
    mes = request.args.get('mes', hoje.month, type=int)
    ano = request.args.get('ano', hoje.year, type=int)
    pct = request.args.get('despesa_pct', 12.0, type=float)
    if not 1 <= mes <= 12:
        mes = hoje.month
    if not 2000 <= ano <= 2100:
        ano = hoje.year
    pct = min(max(pct, 0.0), 100.0)
    return mes, ano, pct


def _criterio():
    return 'pagamento' if request.args.get('criterio') == 'pagamento' else 'parto'


def _a_receber():
    return request.args.get('a_receber') == '1'


def _modelo():
    return 'despesas' if request.args.get('modelo') == 'despesas' else 'folha'


def _congelar(d, periodo):
    """O repasse às prestadoras de serviço sai da FOLHA, então o relatório e o demonstrativo usam os valores dela
    (receitas da folha e rateio de _calcular), e não os lançamentos do mês. Folha fechada: o repasse já foi pago e os
    valores não mudam com edições posteriores nos contratos. Folha aberta: vale o que está lançado nela agora. A
    diferença para os lançamentos atuais vira um aviso."""
    from routes.folha import _calcular
    calc = _calcular(periodo)
    aberta = periodo.status != 'fechado'
    linhas, totais = [], dict.fromkeys(CATEGORIAS, 0.0)
    for r in sorted(periodo.receitas, key=lambda x: (x.data or date.min, x.id)):
        linha = dict.fromkeys(CATEGORIAS, 0.0)
        linha.update({'parto': r.parto or 0.0, 'amamentacao': r.amamentacao or 0.0, 'laser': r.laser or 0.0,
                      'curso': r.curso or 0.0, 'outros': (r.aeo or 0.0) + (r.brinco or 0.0)})
        for k in CATEGORIAS:
            totais[k] += linha[k]
        linhas.append({'data': r.data, 'nome': r.cliente_nome, 'total': r.total, **linha})
    total_entradas = round(sum(totais.values()), 2)
    funcionarias = []
    for x in calc['resultados']:
        funcionarias.append({
            'id': x['funcionario'].id, 'nome': x['funcionario'].nome, 'cargo': x['funcionario'].cargo,
            'horas_diurnas': x['escala'].horas_diurnas or 0, 'horas_noturnas': x['escala'].horas_noturnas or 0,
            'horas_extra_d': x['escala'].horas_extra or 0, 'horas_extra_n': x['escala'].horas_extra_noturnas or 0,
            'valor_diurnas': round(x['v_diurnas'], 2), 'valor_noturnas': round(x['v_noturnas'], 2),
            'valor_extras': round(x['v_extra_d'] + x['v_extra_n'], 2),
            'bruto': round(x['bruto'], 2), 'direcionado': round(x['bruto_direto'], 2),
            'desc_pct': x['desc_pct'], 'desc_val': round(x['desc_val'], 2), 'repasse': round(x['liquido'], 2)})
    horas_d, horas_n = calc['hd_total'] + calc['hed_total'], calc['hn_total'] + calc['hen_total']
    vivo = d['total_entradas']
    d.update({
        'linhas': linhas, 'totais': totais, 'total_entradas': total_entradas, 'lucro_liquido': total_entradas,
        'total_pago': round(sum(l['total'] for l in linhas if l['data']), 2), 'taxas_cartao': 0.0,
        'a_receber': False, 'tem_outros': totais['outros'] > 0, 'rec_folha': total_entradas, 'congelado': not aberta,
        'rateio_custos': calc['rateio_custos'],
        'horas_diurnas': horas_d, 'horas_noturnas': horas_n, 'horas_total': horas_d + horas_n,
        'taxa_dia': round(calc['taxa_diurna'], 2), 'taxa_noite': round(calc['taxa_noturna'], 2),
        'valor_periodo_noturno': round(horas_n * calc['taxa_noturna'], 2), 'valor_periodo_diurno': round(horas_d * calc['taxa_diurna'], 2),
        'extras_d': calc['hed_total'], 'extras_n': calc['hen_total'], 'horas_equivalentes': round(horas_n * FATOR_NOTURNO, 2),
        'funcionarias': funcionarias, 'total_repasse': round(sum(f['repasse'] for f in funcionarias), 2),
        'total_bruto_func': round(sum(f['bruto'] for f in funcionarias), 2), 'total_descontos': round(sum(f['desc_val'] for f in funcionarias), 2),
    })
    avisos = ['Folha em aberto: valores conforme as receitas lançadas na Folha, que são a base do repasse às prestadoras de serviço '
              '(mudam se a Folha mudar).' if aberta else
              'Folha fechada: valores conforme o pagamento já realizado (não mudam com edições posteriores nos contratos).']
    from routes.folha import _nomes_em_receitas, _partos_sem_receita
    tardios = _partos_sem_receita(periodo, _nomes_em_receitas(periodo))   # parto registrado depois do fechamento (com ou sem complemento já lançado)
    inicio = (periodo.ano, periodo.mes)
    complementos = [r for r in periodo.receitas if r.data and (r.data.year, r.data.month) < inicio]   # partos de meses já fechados
    if tardios:
        avisos.append(('Partos do mês ainda sem receita na Folha (entram neste relatório quando forem importados na Folha): ' if aberta else
                       'Partos registrados depois do fechamento da folha (o repasse sai como complemento na folha do mês seguinte): ')
                      + ', '.join(f'{t["cliente"].nome} (parto {t["cliente"].data_parto:%d/%m})' for t in tardios) + '.')
    if complementos:
        avisos.append('Esta folha inclui o complemento de partos de meses anteriores, registrados depois do fechamento daquela folha: '
                      + ', '.join(f'{r.cliente_nome} (parto {r.data:%d/%m/%Y})' for r in complementos) + '.')
    if abs(vivo - total_entradas) > 0.01 and not tardios and not complementos:
        from app import format_brl
        if aberta:
            avisos.append(f'Os lançamentos dos contratos deste mês somam {format_brl(vivo)} e a Folha tem {format_brl(total_entradas)} '
                          f'(diferença de {format_brl(abs(vivo - total_entradas))}). O repasse segue a Folha: contrato sem parto registrado '
                          f'ou ainda não importado na Folha fica de fora.')
        else:
            avisos.append(f'Os lançamentos atuais dos contratos deste mês somam {format_brl(vivo)}, diferente dos {format_brl(total_entradas)} '
                          f'usados na Folha (diferença de {format_brl(abs(vivo - total_entradas))}): contrato ou taxa foram editados depois do '
                          f'fechamento. O pagamento seguiu a Folha.')
    if not aberta and calc['rateio_custos'] is not None and abs(d['total_custos'] - calc['rateio_custos']) > 0.01:
        from app import format_brl
        avisos.append(f'As despesas do mês somam hoje {format_brl(d["total_custos"])}, mas o repasse pago rateou {format_brl(calc["rateio_custos"])} '
                      f'(valor do fechamento da Folha): despesa lançada ou alterada depois do fechamento não entra no repasse já pago.')
    d['avisos'] = avisos
    return d


def custos_do_mes(mes, ano, folha=None):
    """Despesas pagas no mês (sem taxas automáticas de cartão, sem repasses e sem a folha), por centro de custo:
    (OrderedDict {centro: {'total', 'itens'}}, total). São as despesas rateadas entre as prestadoras a partir de nov/2026.
    Com a `folha` ABERTA, entram também, como 'previsto', as despesas de % do lucro bruto ainda pendentes (calculadas sobre
    o lucro bruto da Folha): elas são lançadas como pagas quando a Folha fecha, então a prévia já mostra o rateio final.
    ISS das notas fiscais (nov/2026 em diante): entra no mês da EMISSÃO da nota, esteja pago ou a pagar (o pagamento sai do
    caixa no mês seguinte); por isso o ISS pago neste mês de nota emitida em outro mês não entra aqui."""
    from routes.folha import RATEIO_CUSTOS_DESDE
    inicio = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    iss_por_emissao = (ano, mes) >= RATEIO_CUSTOS_DESDE
    notas_iss = {}   # id do lançamento de ISS -> nota
    if iss_por_emissao:
        notas_iss = {n.lancamento_iss_id: n for n in NotaFiscal.query.filter(NotaFiscal.lancamento_iss_id.isnot(None)).all()}
    custos = {}  # centro de custo -> {'total', 'itens'} (cada item é uma despesa paga)
    for l in (Lancamento.query
              .filter(Lancamento.tipo == 'despesa', Lancamento.status == 'pago',
                      Lancamento.data_pagamento >= inicio, Lancamento.data_pagamento <= fim,
                      Lancamento.periodo_folha_id.is_(None))
              .order_by(Lancamento.data_pagamento, Lancamento.id).all()):
        if '[taxa_de:' in (l.observacoes or '') or '[repasse-pdf:' in (l.observacoes or ''):
            continue   # taxa de cartão e repasses às prestadoras de serviço não são custos da empresa
        if l.id in notas_iss:
            continue   # ISS de nota: conta no mês da emissão (abaixo)
        c = custos.setdefault(l.centro_custo.nome if l.centro_custo else 'Sem centro de custo',
                              {'total': 0.0, 'itens': []})
        c['total'] = round(c['total'] + l.valor, 2)
        c['itens'].append({'data': l.data_pagamento, 'descricao': l.descricao, 'valor': l.valor,
                           'forma': nomes_formas().get(l.forma_pagamento, l.forma_pagamento or ''),
                           'recorrente': bool(l.recorrente or l.recorrencia_origem_id)})
    if iss_por_emissao:
        for n in NotaFiscal.query.filter(NotaFiscal.data_emissao >= inicio, NotaFiscal.data_emissao <= fim,
                                         NotaFiscal.status != 'anulada').all():
            l = n.lancamento_iss
            if l is not None and (l.status == 'cancelado' or MARCA_FORA_DO_RATEIO in (l.observacoes or '')):
                continue   # cancelado, ou ISS de nota atrasada que a empresa assume (sai do caixa, mas não é descontado das prestadoras)
            valor = l.valor if l is not None else (n.valor_iss or 0)
            if valor <= 0:
                continue
            c = custos.setdefault(l.centro_custo.nome if l is not None and l.centro_custo else 'Imposto sobre Nota Fiscal',
                                  {'total': 0.0, 'itens': []})
            c['total'] = round(c['total'] + valor, 2)
            c['itens'].append({'data': n.data_emissao, 'descricao': l.descricao if l is not None else f'ISS — Nota Fiscal {n.numero}',
                               'valor': valor, 'forma': '', 'recorrente': False, 'iss': True})
    if folha is not None and folha.status != 'fechado' and (ano, mes) >= RATEIO_CUSTOS_DESDE:
        from servicos_financeiros import lancamentos_percentuais
        bruto = sum(r.total for r in folha.receitas)
        for m, x in lancamentos_percentuais(ano, mes):
            valor = round(m.percentual_lucro / 100 * bruto, 2)
            if (x is not None and x.status != 'pendente') or valor <= 0:
                continue
            c = custos.setdefault(m.centro_custo.nome if m.centro_custo else 'Sem centro de custo', {'total': 0.0, 'itens': []})
            c['total'] = round(c['total'] + valor, 2)
            c['itens'].append({'data': fim, 'descricao': m.descricao, 'valor': valor, 'forma': '', 'recorrente': True, 'previsto': True})
    for c in custos.values():
        c['itens'].sort(key=lambda i: i['data'])
    custos = OrderedDict(sorted(custos.items()))
    return custos, round(sum(c['total'] for c in custos.values()), 2)


def montar_faturamento(mes, ano, pct=12.0, criterio='parto', a_receber=False, modelo='folha'):
    inicio = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])

    # ── Entradas (valor líquido, já sem a taxa do cartão) ──
    base = Lancamento.query.filter(Lancamento.tipo == 'receita', Lancamento.status == 'recebido')
    if criterio == 'parto':
        # como no PDF: contratos cujo parto (ou DPP, se ainda sem parto) cai no mês, com TODOS os
        # recebimentos deles, mesmo pagos em outro mês; mais os serviços avulsos pagos no mês.
        ids = [c.id for c in Cliente.query.filter(or_(
            and_(Cliente.data_parto >= inicio, Cliente.data_parto <= fim),
            and_(Cliente.data_parto.is_(None), Cliente.data_prevista_parto >= inicio,
                 Cliente.data_prevista_parto <= fim))).all()]
        filtro = or_(
            and_(Lancamento.atendimento_id.is_(None), Lancamento.cliente_id.in_(ids or [-1])),
            and_(Lancamento.atendimento_id.isnot(None),
                 Lancamento.data_pagamento >= inicio, Lancamento.data_pagamento <= fim))
    else:
        filtro = and_(Lancamento.data_pagamento >= inicio, Lancamento.data_pagamento <= fim)
    lancs = base.filter(filtro).order_by(Lancamento.data_pagamento, Lancamento.id).all()
    periodo = PeriodoFolha.query.filter_by(mes=mes, ano=ano).first()
    # contratos pendentes: os que a Folha do mês já inclui entram sempre (o repasse é calculado sobre eles);
    # os demais só com "incluir contratos a receber"
    nomes_folha = {(r.cliente_nome or '').strip().lower() for r in periodo.receitas} if periodo else set()
    pendentes = []
    if criterio == 'parto' and (a_receber or nomes_folha):
        # como no PDF, que lista o valor do contrato mesmo sem pagamento ("Total pagamento" = 0)
        pendentes = [l for l in (Lancamento.query
                     .filter(Lancamento.tipo == 'receita', Lancamento.status == 'pendente',
                             Lancamento.atendimento_id.is_(None), Lancamento.cliente_id.in_(ids or [-1]))
                     .order_by(Lancamento.data_vencimento, Lancamento.id).all())
                     if a_receber or (l.cliente and l.cliente.nome.strip().lower() in nomes_folha)]
    linhas, totais, taxas_cartao = [], dict.fromkeys(CATEGORIAS, 0.0), 0.0
    for l in lancs:
        liquido = l.valor_liquido if l.valor_liquido is not None else l.valor
        taxas_cartao += l.valor - liquido
        cat = _categoria(l)
        linha = dict.fromkeys(CATEGORIAS, 0.0)
        linha[cat] = liquido
        totais[cat] += liquido
        linhas.append({'data': l.data_pagamento, 'nome': l.cliente.nome if l.cliente else l.descricao,
                       'total': liquido, **linha})
    total_pago = round(sum(l['total'] for l in linhas), 2)
    for l in pendentes:
        linha = dict.fromkeys(CATEGORIAS, 0.0)
        linha['parto'] = l.valor
        totais['parto'] += l.valor
        linhas.append({'data': None, 'nome': (l.cliente.nome if l.cliente else l.descricao) + ' (a receber)',
                       'total': 0.0, **linha})
    total_entradas = round(sum(totais.values()), 2)
    # atendimentos direcionados a uma prestadora de serviço ficam fora do rateio (como na Folha) e vão só para ela
    direcionado = {}
    for l in lancs:
        if l.atendimento is not None and l.atendimento.funcionario_id:
            liquido = l.valor_liquido if l.valor_liquido is not None else l.valor
            direcionado[l.atendimento.funcionario_id] = direcionado.get(l.atendimento.funcionario_id, 0.0) + liquido
    # modelo "folha" (PDF de jun/2026 em diante): rateia o lucro BRUTO pelas horas da Folha e aplica o
    # desconto individual de cada prestadora de serviço; modelo "despesas" (PDF de fev/mar): tira X% antes.
    usa_folha = modelo == 'folha' and periodo is not None
    despesas_pct = 0.0 if usa_folha else round(total_entradas * pct / 100, 2)
    lucro_liquido = round(total_entradas - despesas_pct, 2)

    # ── Escala e rateio ──
    funcionarias, avisos = [], []
    horas_d = horas_n = 0.0
    if periodo is None:
        avisos.append(f'Não há folha/escala cadastrada para {MESES[mes - 1]}/{ano}: '
                      'o rateio por prestadora de serviço não pôde ser calculado.')
    else:
        for e in periodo.escalas:
            horas_d += (e.horas_diurnas or 0) + (e.horas_extra or 0)
            horas_n += (e.horas_noturnas or 0) + (e.horas_extra_noturnas or 0)
    base = horas_d + FATOR_NOTURNO * horas_n
    taxa_dia = (lucro_liquido - (sum(direcionado.values()) if usa_folha else 0.0)) / base if base > 0 else 0.0
    taxa_noite = taxa_dia * FATOR_NOTURNO
    if periodo is not None and base <= 0:
        avisos.append('Nenhuma hora lançada na escala deste mês.')

    extras_d = extras_n = 0.0
    rec_folha = None
    a_ratear = None
    if usa_folha:
        for e in periodo.escalas:
            extras_d += e.horas_extra or 0
            extras_n += e.horas_extra_noturnas or 0
        rec_folha = round(sum(r.total for r in periodo.receitas), 2)
        if abs(rec_folha - total_entradas) > 0.01:   # só aparece quando a Folha não manda (critério por pagamento / com contratos a receber)
            avisos.append(f'A Folha tem receitas de R$ {rec_folha:,.2f} neste mês, diferente do lucro bruto dos '
                          f'lançamentos (R$ {total_entradas:,.2f}). Este relatório usa os lançamentos.'
                          .replace(',', '_').replace('.', ',').replace('_', '.'))

    if usa_folha:
        for e in sorted(periodo.escalas, key=lambda x: x.funcionario.nome):
            hd, hn = e.horas_diurnas or 0, e.horas_noturnas or 0
            hed, hen = e.horas_extra or 0, e.horas_extra_noturnas or 0
            v_d, v_n = round(hd * taxa_dia, 2), round(hn * taxa_noite, 2)
            v_ex = round(hed * taxa_dia + hen * taxa_noite, 2)
            bruto = round(v_d + v_n + v_ex + (direcionado.get(e.funcionario_id, 0.0)), 2)
            desc_pct = (e.taxa_desconto if e.taxa_desconto is not None else
                        (e.funcionario.taxa_desconto if e.funcionario.taxa_desconto is not None else 0.15))
            desc_val = round(bruto * desc_pct, 2)
            funcionarias.append({
                'id': e.funcionario_id, 'nome': e.funcionario.nome, 'cargo': e.funcionario.cargo,
                'horas_diurnas': hd, 'horas_noturnas': hn, 'horas_extra_d': hed, 'horas_extra_n': hen,
                'valor_diurnas': v_d, 'valor_noturnas': v_n, 'valor_extras': v_ex,
                'bruto': bruto, 'direcionado': round(direcionado.get(e.funcionario_id, 0.0), 2), 'desc_pct': desc_pct, 'desc_val': desc_val,
                'repasse': round(bruto - desc_val, 2),
            })
        from routes.folha import custos_a_ratear
        a_ratear = custos_a_ratear(periodo)
        if a_ratear is not None and funcionarias:   # despesas do mês no lugar do desconto individual (mesmo % para todas)
            soma = sum(f['bruto'] for f in funcionarias)
            pct = min(a_ratear / soma, 1.0) if soma > 0 else 0.0
            for f in funcionarias:
                f['desc_pct'], f['desc_val'] = pct, round(f['bruto'] * pct, 2)
                f['repasse'] = round(f['bruto'] - f['desc_val'], 2)
    elif periodo is not None:
        for e in sorted(periodo.escalas, key=lambda x: x.funcionario.nome):
            hd = (e.horas_diurnas or 0) + (e.horas_extra or 0)
            hn = (e.horas_noturnas or 0) + (e.horas_extra_noturnas or 0)
            v_n, v_d = round(hn * taxa_noite, 2), round(hd * taxa_dia, 2)
            atribuido = round(v_n + v_d, 2)
            adicionais = round(sum(r.total for r in periodo.receitas
                                   if r.funcionario_id == e.funcionario_id), 2)
            funcionarias.append({
                'id': e.funcionario_id, 'nome': e.funcionario.nome, 'cargo': e.funcionario.cargo,
                'horas_noturnas': hn, 'horas_diurnas': hd,
                'valor_noturnas': v_n, 'valor_diurnas': v_d, 'atribuido': atribuido,
                'adicionais': adicionais, 'repasse': round(atribuido + adicionais, 2),
            })

    custos, total_custos = custos_do_mes(mes, ano, periodo if usa_folha else None)

    resultado = {
        'mes': mes, 'ano': ano, 'mes_nome': MESES[mes - 1], 'pct': pct, 'criterio': criterio,
        'inicio': inicio, 'fim': fim, 'total_dias': calendar.monthrange(ano, mes)[1],
        'linhas': linhas, 'totais': totais, 'total_entradas': total_entradas, 'total_pago': total_pago,
        'a_receber': a_receber and criterio == 'parto',
        'taxas_cartao': round(taxas_cartao, 2),
        'despesas_pct': despesas_pct, 'lucro_liquido': lucro_liquido,
        'horas_diurnas': horas_d, 'horas_noturnas': horas_n, 'horas_total': horas_d + horas_n,
        'taxa_dia': round(taxa_dia, 2), 'taxa_noite': round(taxa_noite, 2),
        'valor_periodo_noturno': round(horas_n * taxa_noite, 2),
        'valor_periodo_diurno': round(horas_d * taxa_dia, 2),
        'funcionarias': funcionarias, 'total_repasse': round(sum(f['repasse'] for f in funcionarias), 2),
        'modelo': 'folha' if usa_folha else 'despesas', 'extras_d': extras_d, 'extras_n': extras_n,
        'total_bruto_func': round(sum(f.get('bruto', f['atribuido'] if 'atribuido' in f else 0) for f in funcionarias), 2),
        'total_descontos': round(sum(f.get('desc_val', 0) for f in funcionarias), 2),
        'horas_equivalentes': round(horas_n * FATOR_NOTURNO, 2), 'rec_folha': rec_folha,
        'custos': custos, 'total_custos': total_custos,
        'diferenca': round(despesas_pct - total_custos, 2),
        'tem_outros': totais['outros'] > 0, 'avisos': avisos, 'tem_folha': periodo is not None, 'congelado': False, 'rateio_custos': a_ratear,
        'folha_aberta': periodo is not None and periodo.status != 'fechado',   # repasse ainda provisório: pode mudar até fechar
    }
    # a Folha (aberta ou fechada) manda no relatório; só a previsão 'com contratos a receber' continua nos lançamentos
    if usa_folha and criterio == 'parto' and (periodo.status == 'fechado' or not a_receber):
        resultado = _congelar(resultado, periodo)
    return resultado


def despesas_da_prestadora(d, f):
    """Parte da prestadora em cada grupo de despesa do mês (centro de custo), sem o analítico: [(grupo, valor)].
    Proporcional ao total de cada grupo; o arredondamento sobra no último, para a soma bater com o rateio dela."""
    total = sum(c['total'] for c in d['custos'].values())
    if d.get('rateio_custos') is None or total <= 0 or f['desc_val'] <= 0:
        return []
    partes = [[nome, round(f['desc_val'] * c['total'] / total, 2)] for nome, c in d['custos'].items()]
    partes[-1][1] = round(f['desc_val'] - sum(p[1] for p in partes[:-1]), 2)
    return [tuple(p) for p in partes]


def _propria_fid():
    """Prestadora de serviço (sem perfil de administradora) só vê o próprio demonstrativo.
    None = sem restrição; -1 = acesso ainda não vinculado a uma prestadora de serviço."""
    if current_user.eh_admin or current_user.perfil == 'contabilidade':   # contador vê o relatório completo, se a área for liberada
        return None
    return current_user.funcionario_id or -1


def _sem_vinculo():
    return render_template('sem_permissao.html', mensagem='Seu acesso ainda não está vinculado a uma prestadora de serviço. '
                           'Peça à administradora para vincular.'), 403


@faturamento_bp.route('/')
def index():
    propria = _propria_fid()
    if propria is not None:   # prestadora de serviço: vai direto ao demonstrativo dela
        if propria < 0:
            return _sem_vinculo()
        return redirect(url_for('faturamento.funcionaria', fid=propria, mes=request.args.get('mes'), ano=request.args.get('ano')))
    mes, ano, pct = _parametros()
    dados = montar_faturamento(mes, ano, pct, _criterio(), _a_receber(), _modelo())
    return render_template('relatorios/faturamento.html', d=dados, meses=MESES,
                           anos=range(date.today().year - 2, date.today().year + 2), gerado_em=date.today())


@faturamento_bp.route('/funcionaria/<int:fid>')
def funcionaria(fid):
    propria = _propria_fid()
    if propria is not None and fid != propria:
        if propria < 0:
            return _sem_vinculo()
        return redirect(url_for('faturamento.funcionaria', fid=propria, mes=request.args.get('mes'), ano=request.args.get('ano')))
    mes, ano, pct = _parametros()
    if propria is not None:   # a prestadora de serviço não altera os critérios do relatório: vale o padrão (o que foi pago)
        dados = montar_faturamento(mes, ano)
    else:
        dados = montar_faturamento(mes, ano, pct, _criterio(), _a_receber(), _modelo())
    f = next((x for x in dados['funcionarias'] if x['id'] == fid), None)
    ctx = dict(d=dados, meses=MESES, anos=range(date.today().year - 2, date.today().year + 2),
               so_propria=propria is not None, gerado_em=date.today())
    if propria is not None and dados['folha_aberta']:   # a prestadora só vê o repasse definitivo (Folha fechada)
        return render_template('relatorios/faturamento_funcionaria_vazio.html', aguardando=True, **ctx)
    if f is None:
        if propria is None:
            abort(404)
        return render_template('relatorios/faturamento_funcionaria_vazio.html', **ctx)
    return render_template('relatorios/faturamento_funcionaria.html', f=f, despesas=despesas_da_prestadora(dados, f), **ctx)
