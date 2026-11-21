from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from models import db, Lancamento, NotaFiscal, PeriodoFolha, Funcionario, CentroCusto, SaldoBancario, ContaBancaria
from sqlalchemy import func
from datetime import date
import calendar
from config import ALIQUOTA_ISS

gerencial_bp = Blueprint('gerencial', __name__, url_prefix='/gerencial')
MESES_NOMES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
               'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

def _calcular_folha(periodo):
    """Mesmo cálculo da tela de folha (fonte única em routes/folha.py)."""
    from routes.folha import _calcular
    return _calcular(periodo)['resultados']


def _build_data(mes, ano, funcionario_id=None):
    inicio = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])

    # ── Saldo acumulado em caixa (histórico até o fim do período) ───────────
    total_rec_acum = db.session.query(func.sum(Lancamento.valor)).filter(
        Lancamento.tipo == 'receita',
        Lancamento.status.in_(['recebido', 'pago']),
        Lancamento.data_pagamento <= fim,
    ).scalar() or 0.0
    total_desp_acum = db.session.query(func.sum(Lancamento.valor)).filter(
        Lancamento.tipo == 'despesa',
        Lancamento.status == 'pago',
        Lancamento.data_pagamento <= fim,
    ).scalar() or 0.0
    saldo_caixa_acumulado = total_rec_acum - total_desp_acum

    # ── Receitas do período ─────────────────────────────────────────────────
    q_rec = Lancamento.query.filter(
        Lancamento.tipo == 'receita',
        Lancamento.status.in_(['recebido', 'pago']),
        Lancamento.data_pagamento >= inicio,
        Lancamento.data_pagamento <= fim,
    )
    lancamentos_receita = q_rec.order_by(Lancamento.data_pagamento).all()
    total_receitas = sum(l.valor for l in lancamentos_receita)

    # Receitas por centro de custo (categoria)
    rec_por_cc = {}
    for l in lancamentos_receita:
        nome_cc = l.centro_custo.nome if l.centro_custo else 'Sem categoria'
        if nome_cc not in rec_por_cc:
            rec_por_cc[nome_cc] = {'qtd': 0, 'valor': 0.0}
        rec_por_cc[nome_cc]['qtd'] += 1
        rec_por_cc[nome_cc]['valor'] += l.valor

    # ── Despesas do período ─────────────────────────────────────────────────
    q_desp = Lancamento.query.filter(
        Lancamento.tipo == 'despesa',
        Lancamento.status == 'pago',
        Lancamento.data_pagamento >= inicio,
        Lancamento.data_pagamento <= fim,
    )
    lancamentos_despesa = q_desp.order_by(Lancamento.data_pagamento).all()
    total_despesas = sum(l.valor for l in lancamentos_despesa)

    # Despesas por centro de custo
    desp_por_cc = {}
    for l in lancamentos_despesa:
        nome_cc = l.centro_custo.nome if l.centro_custo else 'Sem centro'
        if nome_cc not in desp_por_cc:
            desp_por_cc[nome_cc] = 0.0
        desp_por_cc[nome_cc] += l.valor

    # ── Folha do período ────────────────────────────────────────────────────
    periodo_folha = PeriodoFolha.query.filter_by(mes=mes, ano=ano).first()
    folha_resultados = []
    total_folha_bruto = 0.0
    total_folha_liquido = 0.0
    total_folha_desconto = 0.0

    if periodo_folha:
        todos = _calcular_folha(periodo_folha)
        if funcionario_id:
            todos = [r for r in todos if r['funcionario'].id == funcionario_id]
        folha_resultados = todos
        # soma os valores já arredondados por prestadora: é assim que o repasse é pago e aparece no Relatório de Faturamento
        total_folha_bruto = round(sum(round(r['bruto'], 2) for r in todos), 2)
        total_folha_desconto = round(sum(round(r['desc_val'], 2) for r in todos), 2)
        total_folha_liquido = round(sum(round(r['liquido'], 2) for r in todos), 2)

    # ── Notas Fiscais — período ─────────────────────────────────────────────
    notas_periodo = NotaFiscal.query.filter(
        NotaFiscal.competencia_mes == mes,
        NotaFiscal.competencia_ano == ano,
        NotaFiscal.status != 'anulada',
    ).all()
    total_nf_bruto = sum(n.valor_bruto for n in notas_periodo)
    total_iss_emitido = sum(n.valor_iss for n in notas_periodo)

    # ── Notas Fiscais — histórico completo (para acumulado) ─────────────────
    todas_notas = NotaFiscal.query.filter(NotaFiscal.status != 'anulada').all()
    nf_cliente_ids_acum = {n.cliente_id for n in todas_notas}

    # ISS histórico: pago / a pagar / estimado
    iss_pago_itens = [
        {'numero': n.numero, 'cliente': n.cliente.nome if n.cliente else '—', 'iss': n.valor_iss}
        for n in todas_notas if n.status_iss == 'pago'
    ]
    iss_a_pagar_itens = [
        {'numero': n.numero, 'cliente': n.cliente.nome if n.cliente else '—', 'iss': n.valor_iss}
        for n in todas_notas if n.status_iss in ('a_pagar', 'nao_lancado')
    ]
    total_iss_pago = sum(i['iss'] for i in iss_pago_itens)
    total_iss_a_pagar = sum(i['iss'] for i in iss_a_pagar_itens)

    # ISS estimado — receitas acumuladas sem NF emitida (soma TODOS os lançamentos por cliente)
    sem_nf_acum_lancs = (
        Lancamento.query
        .filter(
            Lancamento.tipo == 'receita',
            Lancamento.status.in_(['recebido', 'pago']),
            Lancamento.cliente_id.isnot(None),
            Lancamento.data_pagamento <= fim,
        )
        .order_by(Lancamento.data_pagamento.desc())
        .all()
    )
    sem_nf_acum_map = {}
    for l in sem_nf_acum_lancs:
        if l.cliente_id in nf_cliente_ids_acum:
            continue
        if l.cliente_id not in sem_nf_acum_map:
            sem_nf_acum_map[l.cliente_id] = {'cliente': l.cliente, 'valor': 0.0}
        sem_nf_acum_map[l.cliente_id]['valor'] += l.valor

    # sem_nf_acum exposto ao template como lista de objetos com .cliente e .valor
    from types import SimpleNamespace
    sem_nf_acum = [
        SimpleNamespace(cliente=info['cliente'], valor=info['valor'],
                        cliente_id=cid)
        for cid, info in sem_nf_acum_map.items()
    ]

    iss_estimado_itens = [
        {'cliente': e.cliente.nome if e.cliente else '—', 'valor': e.valor, 'iss': round(e.valor * ALIQUOTA_ISS, 2)}
        for e in sem_nf_acum
    ]
    total_iss_estimado = sum(i['iss'] for i in iss_estimado_itens)
    total_sem_nf = sum(i['valor'] for i in iss_estimado_itens)

    # sem_nf do período (para relatório sintético — soma TODOS os lançamentos do mês por cliente)
    nf_cliente_ids_periodo = {n.cliente_id for n in notas_periodo}
    sem_nf_periodo_map = {}
    for l in lancamentos_receita:
        if not l.cliente_id or l.cliente_id in nf_cliente_ids_periodo:
            continue
        if l.cliente_id not in sem_nf_periodo_map:
            sem_nf_periodo_map[l.cliente_id] = {'cliente': l.cliente, 'valor': 0.0}
        sem_nf_periodo_map[l.cliente_id]['valor'] += l.valor
    sem_nf_periodo = [
        SimpleNamespace(cliente=info['cliente'], valor=info['valor'],
                        cliente_id=cid)
        for cid, info in sem_nf_periodo_map.items()
    ]

    # ── Apuração saldo real ─────────────────────────────────────────────────
    # Repasses já lançados (folha fechada) de meses até o fim do período, mas pagos só DEPOIS dele (pagamento no 1º dia
    # do mês seguinte): em 31/10 o dinheiro ainda estava no caixa, porém já era dívida da empresa.
    repasses_a_pagar_itens = {}
    for l in (Lancamento.query.filter(Lancamento.tipo == 'despesa', Lancamento.status == 'pago', Lancamento.data_pagamento > fim,
                                      Lancamento.data_competencia <= fim,
                                      db.or_(Lancamento.periodo_folha_id.isnot(None), Lancamento.observacoes.like('%[repasse-pdf:%')))
              .order_by(Lancamento.data_competencia).all()):
        chave = (l.data_competencia, l.data_pagamento)
        repasses_a_pagar_itens[chave] = repasses_a_pagar_itens.get(chave, 0.0) + l.valor
    repasses_a_pagar_itens = [{'competencia': MESES_NOMES[c.month - 1][:3] + '/' + str(c.year), 'pagamento': p, 'valor': round(v, 2)}
                              for (c, p), v in repasses_a_pagar_itens.items()]
    # partos registrados depois de a folha do mês fechar: o repasse ainda não foi lançado (vai como complemento na folha
    # seguinte), mas o dinheiro já entrou e é dívida com as prestadoras — estimativa pelo rateio daquela folha
    from routes.folha import repasses_apos_fechamento
    tardios = {}
    for t in repasses_apos_fechamento(fim):
        tardios[t['periodo']] = tardios.get(t['periodo'], 0.0) + t['repasse']
    repasses_a_pagar_itens += [{'competencia': q.titulo, 'pagamento': None, 'valor': round(v, 2), 'estimado': True}
                               for q, v in tardios.items() if v > 0]
    total_repasses_a_pagar = round(sum(i['valor'] for i in repasses_a_pagar_itens), 2)
    saldo_real = saldo_caixa_acumulado - total_iss_a_pagar - total_iss_estimado - total_repasses_a_pagar

    # Adiantamentos: contratos já pagos (líquido, até o fim do período) de clientes cujo parto — ou a data prevista,
    # se ainda não ocorreu — é DEPOIS do período. O dinheiro está no caixa, mas será repassado quando o parto acontecer.
    adiantamentos = 0.0
    for l in (Lancamento.query.filter(Lancamento.tipo == 'receita', Lancamento.status == 'recebido', Lancamento.atendimento_id.is_(None),
                                      Lancamento.cliente_id.isnot(None), Lancamento.data_pagamento <= fim).all()):
        c = l.cliente
        ref = (c.data_parto or c.data_prevista_parto) if c else None
        if ref and ref > fim:
            adiantamentos += l.valor_liquido if l.valor_liquido is not None else l.valor
    adiantamentos = round(adiantamentos, 2)

    return {
        'mes': mes,
        'ano': ano,
        'mes_nome': MESES_NOMES[mes - 1],
        'inicio': inicio,
        'fim': fim,
        'saldo_caixa_acumulado': saldo_caixa_acumulado,
        'total_rec_acum': total_rec_acum,
        'total_desp_acum': total_desp_acum,
        'lancamentos_receita': lancamentos_receita,
        'lancamentos_despesa': lancamentos_despesa,
        'total_receitas': total_receitas,
        'total_despesas': total_despesas,
        'rec_por_cc': rec_por_cc,
        'desp_por_cc': desp_por_cc,
        'folha_resultados': folha_resultados,
        'total_folha_bruto': total_folha_bruto,
        'total_folha_desconto': total_folha_desconto,
        'total_folha_liquido': total_folha_liquido,
        'notas': notas_periodo,
        'todas_notas': todas_notas,
        'total_nf_bruto': total_nf_bruto,
        'total_iss_emitido': total_iss_emitido,
        'iss_pago_itens': iss_pago_itens,
        'iss_a_pagar_itens': iss_a_pagar_itens,
        'total_iss_pago': total_iss_pago,
        'total_iss_a_pagar': total_iss_a_pagar,
        'sem_nf': sem_nf_periodo,
        'sem_nf_acum': sem_nf_acum,
        'iss_estimado_itens': iss_estimado_itens,
        'total_iss_estimado': total_iss_estimado,
        'total_sem_nf': total_sem_nf,
        'repasses_a_pagar_itens': repasses_a_pagar_itens,
        'total_repasses_a_pagar': total_repasses_a_pagar,
        'saldo_real': saldo_real,
        'adiantamentos': adiantamentos,
        'saldo_livre': round(saldo_real - adiantamentos, 2),
        'periodo_folha': periodo_folha,
        'funcionarios': Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all(),
    }


@gerencial_bp.route('/')
def index():
    hoje = date.today()
    mes = request.args.get('mes', hoje.month, type=int)
    ano = request.args.get('ano', hoje.year, type=int)
    if not (1 <= mes <= 12 and 2000 <= ano <= 2100):   # parâmetro inválido na URL: usa o mês atual
        mes, ano = hoje.month, hoje.year
    tipo = request.args.get('tipo', 'sintetico')  # 'sintetico' | 'analitico'
    escopo = request.args.get('escopo', 'geral')   # 'geral' | 'individual'
    funcionario_id = request.args.get('funcionario_id', type=int)

    dados = None
    funcionario_sel = None
    if request.args.get('gerar'):
        if escopo == 'individual' and funcionario_id:
            funcionario_sel = Funcionario.query.get(funcionario_id)
        dados = _build_data(mes, ano, funcionario_id if escopo == 'individual' else None)

    funcionarios = Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()

    return render_template('relatorios/gerencial.html',
        mes=mes, ano=ano, tipo=tipo, escopo=escopo,
        funcionario_id=funcionario_id,
        funcionario_sel=funcionario_sel,
        funcionarios=funcionarios,
        dados=dados,
        hoje=hoje,
        meses_nomes=MESES_NOMES,
    )


# ── Conta bancária: saldo real do extrato x saldo em caixa do sistema ────────────────────────────────
def saldo_sistema_ate(data):
    """Saldo em caixa do sistema até a data (receitas recebidas - despesas pagas), a mesma conta do Relatório Gerencial.
    O caixa do sistema começa em 2026: a diferença para o banco inclui o que havia antes disso."""
    rec = db.session.query(func.sum(Lancamento.valor)).filter(
        Lancamento.tipo == 'receita', Lancamento.status.in_(['recebido', 'pago']), Lancamento.data_pagamento <= data).scalar() or 0.0
    desp = db.session.query(func.sum(Lancamento.valor)).filter(
        Lancamento.tipo == 'despesa', Lancamento.status == 'pago', Lancamento.data_pagamento <= data).scalar() or 0.0
    return round(rec - desp, 2)


def _contas_com_saldos():
    """Contas cadastradas. A 1ª vez cria a 'Conta principal' e passa para ela os saldos registrados antes de existir cadastro de contas."""
    contas = ContaBancaria.query.order_by(ContaBancaria.nome).all()
    orfaos = SaldoBancario.query.filter(SaldoBancario.conta_id.is_(None)).all()
    if orfaos or not contas:
        principal = next((c for c in contas if c.nome == 'Conta principal'), None) or ContaBancaria(nome='Conta principal')
        db.session.add(principal)
        db.session.flush()
        for r in orfaos:
            r.conta_id = principal.id
        db.session.commit()
        contas = ContaBancaria.query.order_by(ContaBancaria.nome).all()
    return contas


@gerencial_bp.route('/conta-bancaria')
def conta_bancaria():
    contas = _contas_com_saldos()
    filtro = request.args.get('conta', type=int)
    registros = SaldoBancario.query.order_by(SaldoBancario.data, SaldoBancario.id).all()
    ultimo = {}   # conta -> último saldo registrado (pela data)
    anterior = {}
    linhas = []
    for r in registros:
        ant = anterior.get(r.conta_id)
        linhas.append({'r': r, 'var': round(r.saldo - ant.saldo, 2) if ant is not None else None})
        anterior[r.conta_id] = ultimo[r.conta_id] = r
    if filtro:
        linhas = [l for l in linhas if l['r'].conta_id == filtro]
    nomes = {c.id: c.nome for c in contas}
    total_contas = round(sum(r.saldo for r in ultimo.values()), 2)
    hoje = date.today()
    saldo_hoje = saldo_sistema_ate(hoje)
    return render_template('relatorios/conta_bancaria.html', contas=contas, ultimo=ultimo, nomes=nomes, filtro=filtro,
                           linhas=list(reversed(linhas)), hoje=hoje, saldo_hoje=saldo_hoje, total_contas=total_contas,
                           diferenca=round(total_contas - saldo_hoje, 2), tem_saldo=bool(ultimo))


@gerencial_bp.route('/conta-bancaria/conta/nova', methods=['POST'])
def conta_bancaria_conta_nova():
    nome = ' '.join(request.form.get('nome', '').split())
    if not nome:
        flash('Informe o nome da conta.', 'warning')
    elif ContaBancaria.query.filter(func.lower(ContaBancaria.nome) == nome.lower()).first():
        flash('Já existe uma conta com esse nome.', 'warning')
    else:
        db.session.add(ContaBancaria(nome=nome))
        db.session.commit()
        flash(f'Conta "{nome}" cadastrada.', 'success')
    return redirect(url_for('gerencial.conta_bancaria'))


@gerencial_bp.route('/conta-bancaria/conta/<int:id>/excluir', methods=['POST'])
def conta_bancaria_conta_excluir(id):
    conta = ContaBancaria.query.get_or_404(id)
    if SaldoBancario.query.filter_by(conta_id=id).first():
        flash('Esta conta tem saldos registrados e não pode ser excluída. Exclua os registros dela antes, se for o caso.', 'warning')
    else:
        db.session.delete(conta)
        db.session.commit()
        flash('Conta excluída.', 'info')
    return redirect(url_for('gerencial.conta_bancaria'))


@gerencial_bp.route('/conta-bancaria/novo', methods=['POST'])
def conta_bancaria_novo():
    from routes.financeiro import _valor_br, _parse_date
    data, saldo = _parse_date(request.form.get('data')), _valor_br(request.form.get('saldo'))
    conta = ContaBancaria.query.get(request.form.get('conta_id', type=int) or 0)
    if data is None or saldo is None or conta is None:
        flash('Informe a conta, a data e o saldo.', 'warning')
        return redirect(url_for('gerencial.conta_bancaria'))
    db.session.add(SaldoBancario(data=data, saldo=saldo, conta_id=conta.id, observacao=request.form.get('observacao', '').strip() or None,
                                 registrado_por=current_user.nome))
    db.session.commit()
    flash(f'Saldo de "{conta.nome}" registrado.', 'success')
    return redirect(url_for('gerencial.conta_bancaria', conta=request.form.get('filtro', type=int)))


@gerencial_bp.route('/conta-bancaria/<int:id>/excluir', methods=['POST'])
def conta_bancaria_excluir(id):
    db.session.delete(SaldoBancario.query.get_or_404(id))
    db.session.commit()
    flash('Registro excluído.', 'info')
    return redirect(url_for('gerencial.conta_bancaria'))
