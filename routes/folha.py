from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Funcionario, PeriodoFolha, ReceitaFolha, EscalaFolha, Cliente, Lancamento, CentroCusto, Atendimento
from datetime import date
from sqlalchemy import and_, or_
import calendar
import json

folha_bp = Blueprint('folha', __name__, url_prefix='/folha')

from marca import MARCA
FATOR_NOTURNO = MARCA['fator_hora_noturna']  # horas noturnas valem este fator das diurnas (marca.json)
RATEIO_CUSTOS_DESDE = tuple(int(x) for x in MARCA['rateio_custos_desde'].split('-'))   # a partir desta folha, as despesas do mês são rateadas entre as prestadoras no lugar do desconto em %


def custos_a_ratear(periodo):
    """Total das despesas do mês (as do 'Descritivo de despesas' do relatório) a ratear entre as prestadoras; None = folha
    antiga, vale o desconto em %. Folha fechada usa o valor gravado no fechamento, para o repasse pago não mudar depois."""
    if (periodo.ano, periodo.mes) < RATEIO_CUSTOS_DESDE:
        return None
    if periodo.custos_rateados is not None:
        return periodo.custos_rateados
    from routes.relatorio_faturamento import custos_do_mes
    return custos_do_mes(periodo.mes, periodo.ano, periodo)[1]


def _calcular(periodo):
    """Calcula todas as métricas derivadas de um período de folha."""
    # Receitas direcionadas a uma prestadora de serviço específica saem do rateio proporcional
    receitas_rateadas     = [r for r in periodo.receitas if not r.funcionario_id]
    receitas_direcionadas = [r for r in periodo.receitas if r.funcionario_id]

    total_receita         = sum(r.total for r in periodo.receitas)
    total_receita_rateada = sum(r.total for r in receitas_rateadas)

    # Monta dicionário de valores direcionados por prestadora de serviço
    direcionado = {}
    for r in receitas_direcionadas:
        direcionado[r.funcionario_id] = direcionado.get(r.funcionario_id, 0) + r.total

    hd   = sum(e.horas_diurnas or 0 for e in periodo.escalas)
    hn   = sum(e.horas_noturnas or 0 for e in periodo.escalas)
    hed  = sum(e.horas_extra or 0 for e in periodo.escalas)
    hen  = sum(e.horas_extra_noturnas or 0 for e in periodo.escalas)
    horas_eq = hd + hn * FATOR_NOTURNO + hed + hen * FATOR_NOTURNO

    # Taxa calculada apenas sobre receitas rateadas
    taxa_diurna  = total_receita_rateada / horas_eq if horas_eq > 0 else 0
    taxa_noturna = taxa_diurna * FATOR_NOTURNO

    resultados = []

    escalas_sorted = sorted(periodo.escalas, key=lambda e: e.funcionario.nome)
    for e in escalas_sorted:
        v_d  = (e.horas_diurnas or 0) * taxa_diurna
        v_n  = (e.horas_noturnas or 0) * taxa_noturna
        v_ed = (e.horas_extra or 0) * taxa_diurna
        v_en = (e.horas_extra_noturnas or 0) * taxa_noturna
        bruto_rateado = v_d + v_n + v_ed + v_en
        bruto_direto  = direcionado.get(e.funcionario_id, 0)
        bruto = bruto_rateado + bruto_direto
        desc_pct = (e.taxa_desconto if e.taxa_desconto is not None else
                    (e.funcionario.taxa_desconto if e.funcionario.taxa_desconto is not None else 0.15))
        desc_val = bruto * desc_pct
        liquido = bruto - desc_val
        resultados.append({
            'funcionario': e.funcionario,
            'escala': e,
            'v_diurnas': v_d,
            'v_noturnas': v_n,
            'v_extra_d': v_ed,
            'v_extra_n': v_en,
            'bruto_rateado': bruto_rateado,
            'bruto_direto': bruto_direto,
            'bruto': bruto,
            'desc_pct': desc_pct,
            'desc_val': desc_val,
            'liquido': liquido,
        })

    # despesas do mês rateadas na proporção do bruto de cada prestadora (mesmo % para todas), no lugar do desconto individual
    custos = custos_a_ratear(periodo)
    if custos is not None:
        bruto_soma = sum(r['bruto'] for r in resultados)
        pct = min(custos / bruto_soma, 1.0) if bruto_soma > 0 else 0.0
        for r in resultados:
            r['desc_pct'], r['desc_val'] = pct, r['bruto'] * pct
            r['liquido'] = r['bruto'] - r['desc_val']
    total_bruto = sum(r['bruto'] for r in resultados)
    total_desconto_val = sum(r['desc_val'] for r in resultados)
    total_liquido = sum(r['liquido'] for r in resultados)

    return {
        'rateio_custos': custos,
        # receita a ratear mas ninguém com horas lançadas: o rateio some sem aviso
        'sem_horas': total_receita_rateada > 0 and horas_eq <= 0,
        'total_receita': total_receita,
        'total_receita_rateada': total_receita_rateada,
        'hd_total': hd,
        'hn_total': hn,
        'hed_total': hed,
        'hen_total': hen,
        'horas_eq': horas_eq,
        'taxa_diurna': taxa_diurna,
        'taxa_noturna': taxa_noturna,
        'resultados': resultados,
        'total_bruto': total_bruto,
        'total_desconto_val': total_desconto_val,
        'total_liquido': total_liquido,
    }


def tirar_inativas_sem_horas(periodo):
    """Folha aberta: prestadora que foi inativada depois de a folha ser criada e não tem horas nem receita direcionada
    neste mês não fica na folha (se trabalhou no mês, continua). Devolve quantas saíram; quem chama faz o commit."""
    if periodo.status == 'fechado':
        return 0
    direcionadas = {r.funcionario_id for r in periodo.receitas if r.funcionario_id}
    n = 0
    for e in list(periodo.escalas):
        if (not e.funcionario.ativo and e.funcionario_id not in direcionadas
                and not any([e.horas_diurnas, e.horas_noturnas, e.horas_extra, e.horas_extra_noturnas])):
            db.session.delete(e)
            n += 1
    return n


def _funcionarios_sem_escala(periodo):
    ids_com_escala = {e.funcionario_id for e in periodo.escalas}
    q = Funcionario.query.filter_by(ativo=True)
    if ids_com_escala:
        q = q.filter(~Funcionario.id.in_(ids_com_escala))
    return q.order_by(Funcionario.nome).all()


def _nomes_em_receitas(periodo=None):
    """Nomes (minúsculos) das clientes que já estão nas receitas de uma folha (ou de todas, se não informar)."""
    q = ReceitaFolha.query
    if periodo is not None:
        q = q.filter_by(periodo_id=periodo.id)
    return {(r.cliente_nome or '').strip().lower() for r in q.all()}


def _partos_sem_receita(periodo, ja, ate=None):
    """Clientes com parto registrado no mês da folha cujo nome não está em `ja` (receitas já lançadas).
    `valor_sugerido`: líquido de todos os lançamentos do contrato; `valor_recebido`: só o que já entrou (até `ate`)."""
    mes_ini = date(periodo.ano, periodo.mes, 1)
    mes_fim = date(periodo.ano, periodo.mes, calendar.monthrange(periodo.ano, periodo.mes)[1])
    # só depois de o parto ser registrado: a DPP pode cair neste mês e o parto acontecer no seguinte
    clientes_parto = Cliente.query.filter(
        Cliente.data_parto >= mes_ini, Cliente.data_parto <= mes_fim
    ).order_by(Cliente.data_parto).all()
    itens = []
    for c in clientes_parto:
        if c.nome.strip().lower() in ja:
            continue
        lancs = Lancamento.query.filter_by(cliente_id=c.id, tipo='receita').order_by(Lancamento.id).all()
        if not lancs:
            continue  # sem contrato lançado não há o que sugerir
        liq = lambda l: l.valor_liquido if l.valor_liquido else l.valor
        recebidos = [l for l in lancs if l.status in ('recebido', 'pago') and (ate is None or (l.data_pagamento and l.data_pagamento <= ate))]
        itens.append({
            'cliente': c,
            'lancamento': lancs[0],
            'valor_sugerido': sum(liq(l) for l in lancs) or 0.0,
            'valor_recebido': sum(liq(l) for l in recebidos),
        })
    return itens


def _fator_repasse(periodo):
    """Quanto de cada R$ 1 de receita rateada vira repasse (já sem o desconto da prestadora) na folha deste período."""
    calc = _calcular(periodo)
    if calc['total_receita_rateada'] <= 0:
        return 0.0
    return sum(x['bruto_rateado'] * (1 - x['desc_pct']) for x in calc['resultados']) / calc['total_receita_rateada']


def _periodos_fechados():
    return PeriodoFolha.query.filter_by(status='fechado').order_by(PeriodoFolha.ano, PeriodoFolha.mes).all()


def repasses_apos_fechamento(ate):
    """Partos registrados depois de a folha do mês fechar e já recebidos até `ate`: o repasse não saiu naquela folha e continua
    devido até o complemento ser pago (na folha seguinte, no 1º dia do mês depois dela). Devolve
    [{'periodo', 'cliente', 'valor_recebido', 'repasse'}] com o repasse estimado pelo rateio da folha do parto."""
    em_folhas = {}                        # nome -> períodos em que a cliente já está nas receitas
    for r in ReceitaFolha.query.all():
        em_folhas.setdefault((r.cliente_nome or '').strip().lower(), set()).add(r.periodo_id)
    quitada = {}

    def paga_ate_data(pid):
        if pid not in quitada:
            pgs = [l.data_pagamento for l in Lancamento.query.filter_by(periodo_folha_id=pid, tipo='despesa').all() if l.data_pagamento]
            quitada[pid] = bool(pgs) and min(pgs) <= ate
        return quitada[pid]

    itens = []
    for q in _periodos_fechados():
        if date(q.ano, q.mes, 1) > ate:
            break
        fator = None
        ja_q = {n for n, pids in em_folhas.items() if q.id in pids}
        for t in _partos_sem_receita(q, ja_q, ate):
            if t['cliente'].data_parto > ate or t['valor_recebido'] <= 0:
                continue
            if any(pid != q.id and paga_ate_data(pid) for pid in em_folhas.get(t['cliente'].nome.strip().lower(), ())):
                continue                  # o complemento já foi pago
            fator = _fator_repasse(q) if fator is None else fator
            itens.append({'periodo': q, 'cliente': t['cliente'], 'valor_recebido': t['valor_recebido'],
                          'repasse': round(t['valor_recebido'] * fator, 2)})
    return itens


def _folha_fechada(id):
    """Folha fechada não aceita mais mudanças que alterem o repasse já pago; devolve o redirecionamento, ou None."""
    p = PeriodoFolha.query.get_or_404(id)
    if p.status != 'fechado':
        return None
    flash('Folha fechada: o repasse já foi pago e não pode mais mudar. Parto registrado depois do fechamento entra como '
          'complemento na folha do mês seguinte.', 'danger')
    return redirect(url_for('folha.periodo', id=id))


# ── Períodos ────────────────────────────────────────────────────────────────

@folha_bp.route('/')
def index():
    periodos = PeriodoFolha.query.order_by(PeriodoFolha.ano.desc(), PeriodoFolha.mes.desc()).all()
    return render_template('folha/index.html', periodos=periodos)


@folha_bp.route('/novo', methods=['GET', 'POST'])
def novo_periodo():
    if request.method == 'POST':
        mes = int(request.form['mes'])
        ano = int(request.form['ano'])

        existing = PeriodoFolha.query.filter_by(mes=mes, ano=ano).first()
        if existing:
            flash('Já existe uma folha para este mês/ano.', 'warning')
            return redirect(url_for('folha.periodo', id=existing.id))

        total_dias = calendar.monthrange(ano, mes)[1]
        periodo = PeriodoFolha(mes=mes, ano=ano, total_dias=total_dias)
        db.session.add(periodo)
        db.session.flush()

        for f in Funcionario.query.filter_by(ativo=True).all():
            db.session.add(EscalaFolha(
                periodo_id=periodo.id,
                funcionario_id=f.id,
                taxa_desconto=f.taxa_desconto
            ))

        db.session.commit()
        flash(f'Folha {periodo.titulo} criada com sucesso.', 'success')
        return redirect(url_for('folha.periodo', id=periodo.id))

    hoje = date.today()
    funcionarios_ativos = Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()
    return render_template('folha/novo_periodo.html', mes_atual=hoje.month, ano_atual=hoje.year,
                           funcionarios_ativos=funcionarios_ativos)


@folha_bp.route('/<int:id>')
def periodo(id):
    periodo = PeriodoFolha.query.get_or_404(id)
    if tirar_inativas_sem_horas(periodo):
        db.session.commit()
    calc = _calcular(periodo)
    if calc['sem_horas']:
        flash('Há receita a ratear, mas nenhuma hora foi lançada na escala: ninguém receberá o rateio.', 'warning')
    sem_escala = _funcionarios_sem_escala(periodo)
    receitas_sorted = sorted(periodo.receitas, key=lambda r: (r.data or date.min))

    # Clientes que deram à luz neste mês e ainda não estão nas receitas da folha
    todos_nomes = _nomes_em_receitas()
    partos_pendentes, partos_tardios = [], []
    if periodo.status == 'fechado':
        # parto registrado depois do fechamento: não entra mais nesta folha, vai de complemento para a seguinte
        fator = _fator_repasse(periodo)
        for t in _partos_sem_receita(periodo, todos_nomes):
            t['repasse'] = round(t['valor_sugerido'] * fator, 2)
            partos_tardios.append(t)
    else:
        partos_pendentes = _partos_sem_receita(periodo, _nomes_em_receitas(periodo))
        # complemento: partos de meses anteriores já fechados que ficaram sem repasse
        for q in _periodos_fechados():
            if (q.ano, q.mes) < (periodo.ano, periodo.mes):
                for t in _partos_sem_receita(q, todos_nomes):
                    t['tardio_de'] = q.titulo
                    partos_pendentes.append(t)

    mes_ini = date(periodo.ano, periodo.mes, 1)
    mes_fim = date(periodo.ano, periodo.mes, calendar.monthrange(periodo.ano, periodo.mes)[1])
    # atendimentos realizados no mês, com valor, que ainda não viraram receita da folha
    ja = {r.atendimento_id for r in periodo.receitas if r.atendimento_id}
    atendimentos_pendentes = [
        {'atendimento': a, 'categoria': _categoria_folha(a)}
        for a in (Atendimento.query
                  .filter(Atendimento.status == 'realizado', Atendimento.valor_total > 0,
                          Atendimento.data_atendimento >= mes_ini, Atendimento.data_atendimento <= mes_fim)
                  .order_by(Atendimento.data_atendimento).all())
        if a.id not in ja]

    previsao_existente = Lancamento.query.filter(
        Lancamento.observacoes.like(f'%[previsao_folha:{periodo.id}]%')
    ).first()

    return render_template('folha/periodo.html', periodo=periodo, calc=calc,
                           atendimentos_pendentes=atendimentos_pendentes, categorias_folha=CATEGORIAS_FOLHA,
                           sem_escala=sem_escala, receitas_sorted=receitas_sorted,
                           partos_pendentes=partos_pendentes, partos_tardios=partos_tardios,
                           previsao_existente=previsao_existente)


@folha_bp.route('/<int:id>/parametros', methods=['POST'])
def salvar_parametros(id):
    if (bloqueio := _folha_fechada(id)):
        return bloqueio
    p = PeriodoFolha.query.get_or_404(id)
    p.total_dias = int(request.form.get('total_dias', 30) or 30)
    # Horas agora são auto-calculadas da escala — não precisam de input manual
    db.session.commit()
    flash('Parâmetros salvos.', 'success')
    return redirect(url_for('folha.periodo', id=id) + '#parametros')


@folha_bp.route('/<int:id>/escala', methods=['POST'])
def salvar_escala(id):
    if (bloqueio := _folha_fechada(id)):
        return bloqueio
    p = PeriodoFolha.query.get_or_404(id)
    for e in p.escalas:
        e.horas_diurnas        = float(request.form.get(f'hd_{e.id}',  0) or 0)
        e.horas_noturnas       = float(request.form.get(f'hn_{e.id}',  0) or 0)
        e.horas_extra          = float(request.form.get(f'hed_{e.id}', 0) or 0)
        e.horas_extra_noturnas = float(request.form.get(f'hen_{e.id}', 0) or 0)
        desc_raw = request.form.get(f'desc_{e.id}')
        if desc_raw is not None:   # a partir de nov/2026 a tela não tem mais o campo (despesas rateadas): não mexe no que já está gravado
            e.taxa_desconto = float(desc_raw) / 100 if desc_raw else None
    db.session.commit()
    flash('Escala salva com sucesso.', 'success')
    return redirect(url_for('folha.periodo', id=id) + '#escala')


# ── Receitas ─────────────────────────────────────────────────────────────────

@folha_bp.route('/<int:id>/receita/nova', methods=['POST'])
def nova_receita(id):
    if (bloqueio := _folha_fechada(id)):
        return bloqueio
    data_str = request.form.get('data')
    try:
        dt = date.fromisoformat(data_str) if data_str else None
    except ValueError:
        dt = None
    func_id_raw = request.form.get('funcionario_id', '').strip()
    func_id = int(func_id_raw) if func_id_raw else None
    r = ReceitaFolha(
        periodo_id=id,
        data=dt,
        cliente_nome=request.form.get('cliente_nome', '').strip(),
        parto=float(request.form.get('parto', 0) or 0),
        aeo=float(request.form.get('aeo', 0) or 0),
        amamentacao=float(request.form.get('amamentacao', 0) or 0),
        laser=float(request.form.get('laser', 0) or 0),
        curso=float(request.form.get('curso', 0) or 0),
        brinco=float(request.form.get('brinco', 0) or 0),
        funcionario_id=func_id,
    )
    db.session.add(r)
    db.session.commit()
    return redirect(url_for('folha.periodo', id=id) + '#receitas')


CATEGORIAS_FOLHA = [('aeo', 'AEO'), ('amamentacao', 'Amamentação'), ('laser', 'Laser'), ('curso', 'Curso'),
                    ('brinco', 'Brinco'), ('parto', 'Parto')]


def _categoria_folha(a):
    """Coluna da receita da folha sugerida pelo nome dos procedimentos do atendimento."""
    nomes = ' '.join((i.procedimento.nome if i.procedimento else '') for i in a.itens).lower()
    for chave, cat in (('amament', 'amamentacao'), ('laser', 'laser'), ('curso', 'curso'), ('brinco', 'brinco')):
        if chave in nomes:
            return cat
    return 'aeo'


@folha_bp.route('/<int:id>/importar-atendimento', methods=['POST'])
def importar_atendimento(id):
    """Lança na folha a receita de um atendimento realizado; se o atendimento foi direcionado a uma
    prestadora de serviço, a receita fica só com ela (fora do rateio)."""
    p = PeriodoFolha.query.get_or_404(id)
    if p.status == 'fechado':
        flash('Folha fechada: não é possível incluir receitas.', 'danger')
        return redirect(url_for('folha.periodo', id=id) + '#receitas')
    a = Atendimento.query.get_or_404(int(request.form['atendimento_id']))
    categoria = request.form.get('categoria')
    if categoria not in dict(CATEGORIAS_FOLHA):
        categoria = 'aeo'
    if any(r.atendimento_id == a.id for r in p.receitas):
        flash('Este atendimento já está nas receitas da folha.', 'warning')
        return redirect(url_for('folha.periodo', id=id) + '#receitas')
    try:
        valor = float(request.form.get('valor') or a.valor_total or 0)
    except ValueError:
        valor = a.valor_total or 0
    db.session.add(ReceitaFolha(
        periodo_id=id, data=a.data_atendimento, cliente_nome=a.cliente.nome if a.cliente else '',
        funcionario_id=a.funcionario_id, atendimento_id=a.id, **{categoria: valor}))
    db.session.commit()
    flash(f'Atendimento de {a.cliente.nome} incluído na folha'
          + (f' (somente {a.funcionario.nome}).' if a.funcionario else ' (rateio).'), 'success')
    return redirect(url_for('folha.periodo', id=id) + '#receitas')


@folha_bp.route('/<int:id>/importar-parto', methods=['POST'])
def importar_parto(id):
    """Importa o contrato de uma paciente que pariu neste mês (ou, como complemento, num mês já fechado) para as receitas da folha."""
    if (bloqueio := _folha_fechada(id)):
        return bloqueio
    cliente_id = int(request.form['cliente_id'])
    cliente = Cliente.query.get_or_404(cliente_id)
    try:
        valor = float(request.form.get('valor', 0) or 0)
    except ValueError:
        valor = 0.0

    # Busca todos os lançamentos de receita da cliente para documentar as parcelas
    lancs = Lancamento.query.filter_by(cliente_id=cliente_id, tipo='receita').order_by(Lancamento.data_competencia).all()
    detalhes = []
    for l in lancs:
        detalhes.append({
            'data': l.data_competencia.isoformat() if l.data_competencia else l.data_pagamento.isoformat() if l.data_pagamento else '',
            'valor': l.valor
        })

    pagos = [l.data_pagamento for l in lancs if l.data_pagamento]
    r = ReceitaFolha(
        periodo_id=id,
        data=cliente.data_parto or (max(pagos) if pagos else cliente.data_prevista_parto),
        cliente_nome=cliente.nome,
        parto=valor,
        detalhes_pagamentos=json.dumps(detalhes),
    )
    db.session.add(r)
    db.session.commit()
    flash(f'{cliente.nome} adicionada às receitas da folha.', 'success')
    return redirect(url_for('folha.periodo', id=id) + '#receitas')


def sincronizar_receitas_periodo(p):
    """Refaz a cópia das receitas da folha a partir dos lançamentos atuais (valor líquido, como na importação).
    Devolve (alteradas, ignoradas); quem chama faz o commit."""
    por_nome = {}
    for r in p.receitas:
        por_nome.setdefault((r.cliente_nome or '').strip().lower(), []).append(r)

    alteradas, ignoradas = [], []
    for nome, itens in por_nome.items():
        cliente = Cliente.query.filter(db.func.lower(Cliente.nome) == nome).first() if nome else None
        if not cliente:
            continue
        if len(itens) > 1:
            ignoradas.append(itens[0].cliente_nome)  # várias linhas da mesma cliente: não divide sozinho
            continue
        r = itens[0]
        if not r.parto:
            continue
        lancs = (Lancamento.query
                 .filter(Lancamento.cliente_id == cliente.id, Lancamento.tipo == 'receita',
                         Lancamento.atendimento_id.is_(None), Lancamento.status != 'cancelado')
                 .order_by(Lancamento.data_competencia).all())
        if not lancs:
            continue
        novo = round(sum(l.valor_liquido if l.valor_liquido is not None else l.valor for l in lancs), 2)
        if abs(novo - (r.parto or 0)) < 0.005:
            continue
        alteradas.append(f'{cliente.nome}: {r.parto:.2f} -> {novo:.2f}')
        r.parto = novo
        r.detalhes_pagamentos = json.dumps([
            {'data': (l.data_pagamento or l.data_competencia).isoformat() if (l.data_pagamento or l.data_competencia) else '',
             'valor': l.valor_liquido if l.valor_liquido is not None else l.valor}
            for l in lancs])
    return alteradas, ignoradas


@folha_bp.route('/<int:id>/sincronizar-receitas', methods=['POST'])
def sincronizar_receitas(id):
    """Atualiza o valor de parto das receitas da folha a partir dos lançamentos atuais da cliente.

    A receita da folha é uma CÓPIA do valor no momento da importação; corrigir o lançamento
    depois não altera a folha. Aqui a cópia é refeita (valor líquido, como na importação).
    """
    p = PeriodoFolha.query.get_or_404(id)
    if p.status == 'fechado':
        flash('Folha fechada: os pagamentos já foram registrados no caixa, valores não podem mudar.', 'danger')
        return redirect(url_for('folha.periodo', id=id) + '#receitas')

    alteradas, ignoradas = sincronizar_receitas_periodo(p)
    db.session.commit()

    if alteradas:
        flash(f'{len(alteradas)} receita(s) atualizada(s): ' + '; '.join(alteradas), 'success')
    else:
        flash('Nenhuma receita precisou de atualização.', 'info')
    if ignoradas:
        flash('Não atualizadas por terem mais de uma linha na folha: ' + ', '.join(ignoradas), 'warning')
    return redirect(url_for('folha.periodo', id=id) + '#receitas')


@folha_bp.route('/receita/<int:rid>/excluir', methods=['POST'])
def excluir_receita(rid):
    r = ReceitaFolha.query.get_or_404(rid)
    pid = r.periodo_id
    if r.periodo.status == 'fechado':
        flash('Esta folha está fechada. Não é possível excluir receitas após o registro dos pagamentos.', 'danger')
        return redirect(url_for('folha.periodo', id=pid) + '#receitas')
    db.session.delete(r)
    db.session.commit()
    return redirect(url_for('folha.periodo', id=pid) + '#receitas')


@folha_bp.route('/<int:id>/adicionar-funcionario', methods=['POST'])
def adicionar_funcionario_periodo(id):
    if (bloqueio := _folha_fechada(id)):
        return bloqueio
    fid = int(request.form['funcionario_id'])
    if not EscalaFolha.query.filter_by(periodo_id=id, funcionario_id=fid).first():
        f = Funcionario.query.get(fid)
        db.session.add(EscalaFolha(periodo_id=id, funcionario_id=fid, taxa_desconto=f.taxa_desconto))
        db.session.commit()
    return redirect(url_for('folha.periodo', id=id) + '#escala')


# ── Relatório da folha ────────────────────────────────────────────────────────

@folha_bp.route('/<int:id>/relatorio')
def relatorio(id):
    periodo = PeriodoFolha.query.get_or_404(id)
    calc    = _calcular(periodo)
    receitas_sorted = sorted(periodo.receitas, key=lambda r: (r.data or date.min))

    # Busca info de pagamento (primeiro lançamento gerado pela folha)
    pagamento_ref = Lancamento.query.filter_by(periodo_folha_id=id).first()

    return render_template('folha/relatorio.html',
        periodo=periodo,
        calc=calc,
        receitas_sorted=receitas_sorted,
        pagamento_ref=pagamento_ref,
        gerado_em=date.today(),
    )


# ── Registrar pagamentos no caixa ─────────────────────────────────────────────

def registrar_pagamentos_periodo(p, data_pg, forma='pix'):
    """Cria uma despesa paga por prestadora de serviço com o líquido da folha. Quem chama fecha o período e faz o commit."""
    cc = CentroCusto.query.filter_by(codigo='CC006').first()
    for r in _calcular(p)['resultados']:
        db.session.add(Lancamento(
            descricao=f'Folha {p.titulo} — {r["funcionario"].nome}',
            tipo='despesa',
            valor=round(r['liquido'], 2),
            data_competencia=date(p.ano, p.mes, 1),
            data_vencimento=data_pg,
            data_pagamento=data_pg,
            status='pago',
            forma_pagamento=forma,
            centro_custo_id=cc.id if cc else None,
            observacoes=f'Pagamento automático — Folha {p.titulo}',
            periodo_folha_id=p.id,
        ))


@folha_bp.route('/<int:id>/registrar-pagamentos', methods=['POST'])
def registrar_pagamentos(id):
    p = PeriodoFolha.query.get_or_404(id)

    if p.status == 'fechado':
        flash('Os pagamentos desta folha já foram registrados no caixa.', 'warning')
        return redirect(url_for('folha.periodo', id=id))

    tirar_inativas_sem_horas(p)
    # Remove previsão pendente desta folha antes de criar os pagamentos reais
    Lancamento.query.filter(
        Lancamento.observacoes.like(f'%[previsao_folha:{p.id}]%')
    ).delete(synchronize_session=False)

    padrao = date(p.ano + (p.mes == 12), p.mes % 12 + 1, 1)   # o repasse é pago no 1º dia do mês seguinte
    data_pg_str = request.form.get('data_pagamento')
    try:
        data_pg = date.fromisoformat(data_pg_str) if data_pg_str else padrao
    except ValueError:
        data_pg = padrao

    forma = request.form.get('forma_pagamento', 'pix')

    baixadas = []
    if (p.ano, p.mes) >= RATEIO_CUSTOS_DESDE:   # despesa de % do lucro bruto (ex.: Administração 10%): lançada como paga ao fechar
        from servicos_financeiros import baixar_percentuais_da_folha
        baixadas = baixar_percentuais_da_folha(p.ano, p.mes, sum(r.total for r in p.receitas))
    p.custos_rateados = custos_a_ratear(p)   # congela as despesas rateadas: o repasse pago não muda se entrar outra despesa depois
    registrar_pagamentos_periodo(p, data_pg, forma)

    p.status = 'fechado'
    db.session.commit()
    flash(f'Pagamentos da folha {p.titulo} registrados no caixa com sucesso!', 'success')
    from app import format_brl
    for descricao, valor in baixadas:
        flash(f'{descricao}: {format_brl(valor)} lançado como pago em {date(p.ano, p.mes, calendar.monthrange(p.ano, p.mes)[1]):%d/%m/%Y} '
              f'(% do lucro bruto da folha).', 'info')
    return redirect(url_for('folha.periodo', id=id) + '#resultado')


@folha_bp.route('/<int:id>/reservar-previsao', methods=['POST'])
def reservar_previsao(id):
    """Cria lançamento pendente no fluxo de caixa com o total estimado da folha."""
    p = PeriodoFolha.query.get_or_404(id)
    if p.status == 'fechado':
        flash('Folha já fechada — previsão não necessária.', 'warning')
        return redirect(url_for('folha.periodo', id=id))

    calc = _calcular(p)
    total = calc.get('total_liquido', 0)
    if total <= 0:
        flash('Lance as receitas e horas antes de reservar a previsão.', 'warning')
        return redirect(url_for('folha.periodo', id=id))

    # Remove previsão anterior desta folha, se existir
    Lancamento.query.filter(
        Lancamento.observacoes.like(f'%[previsao_folha:{p.id}]%')
    ).delete(synchronize_session=False)

    data_prev_str = request.form.get('data_previsao')
    try:
        data_venc = date.fromisoformat(data_prev_str) if data_prev_str else \
                    date(p.ano, p.mes, calendar.monthrange(p.ano, p.mes)[1])
    except ValueError:
        data_venc = date(p.ano, p.mes, calendar.monthrange(p.ano, p.mes)[1])

    cc = CentroCusto.query.filter_by(codigo='CC006').first()
    lanc = Lancamento(
        descricao=f'Previsão Folha {p.titulo} ({len(calc.get("resultados", []))} prestadora de serviço(s))',
        tipo='despesa',
        valor=round(total, 2),
        data_competencia=date(p.ano, p.mes, 1),
        data_vencimento=data_venc,
        status='pendente',
        centro_custo_id=cc.id if cc else None,
        observacoes=f'[previsao_folha:{p.id}] Estimativa de repasse — {len(calc.get("resultados", []))} prestadora de serviço(s)',
    )
    db.session.add(lanc)
    db.session.commit()
    flash(
        f'Previsão de {total:_.2f} reservada no fluxo de caixa para {data_venc.strftime("%d/%m/%Y")}.'.replace('.', ',').replace('_', '.'),
        'success'
    )
    return redirect(url_for('folha.periodo', id=id) + '#resultado')


# ── Prestadores de serviço ──────────────────────────────────────────────────────────────

@folha_bp.route('/funcionarios')
def funcionarios():
    todos = Funcionario.query.order_by(Funcionario.nome).all()
    return render_template('folha/funcionarios.html', funcionarios=todos)


@folha_bp.route('/funcionarios/novo', methods=['GET', 'POST'])
def novo_funcionario():
    if request.method == 'POST':
        f = Funcionario(
            nome=request.form['nome'].strip(),
            cpf=request.form.get('cpf', '').strip() or None,
            cargo=request.form.get('cargo', '').strip() or None,
            taxa_desconto=float(request.form.get('taxa_desconto', 15)) / 100,
        )
        db.session.add(f)
        db.session.commit()
        flash(f'{f.nome} cadastrado com sucesso.', 'success')
        return redirect(url_for('folha.funcionarios'))
    return render_template('folha/funcionario_form.html', funcionario=None)


@folha_bp.route('/funcionarios/<int:fid>/editar', methods=['GET', 'POST'])
def editar_funcionario(fid):
    f = Funcionario.query.get_or_404(fid)
    if request.method == 'POST':
        f.nome = request.form['nome'].strip()
        f.cpf = request.form.get('cpf', '').strip() or None
        f.cargo = request.form.get('cargo', '').strip() or None
        f.taxa_desconto = float(request.form.get('taxa_desconto', 15)) / 100
        f.ativo = 'ativo' in request.form
        db.session.commit()
        flash('Prestador de serviço atualizado.', 'success')
        return redirect(url_for('folha.funcionarios'))
    return render_template('folha/funcionario_form.html', funcionario=f)
