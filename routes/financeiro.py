from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Lancamento, CentroCusto, Cliente, FormaPagamento, TaxaOperadora, Operadora
import calendar
import re
import unicodedata
from datetime import date, datetime
from taxas import calcular as calcular_taxa, operadora_padrao
from servicos_financeiros import (sincronizar_taxa, sincronizar_todas, formas_ativas, forma_liberada,
                                  nomes_operadoras, TRAVADAS, gerar_recorrentes, valor_percentual)

financeiro_bp = Blueprint('financeiro', __name__, url_prefix='/financeiro')




@financeiro_bp.route('/lancamentos')
def lancamentos():
    tipo = request.args.get('tipo', '')
    status = request.args.get('status', '')
    mes = request.args.get('mes', '')
    regime = request.args.get('regime', 'competencia')
    centro_id = request.args.get('centro_id', '')

    gerar_recorrentes()
    query = Lancamento.query.filter(Lancamento.status != 'cancelado')

    if tipo:
        query = query.filter_by(tipo=tipo)
    if status:
        query = query.filter_by(status=status)
    if centro_id:
        if centro_id.isdigit():
            query = query.filter_by(centro_custo_id=int(centro_id))
        else:
            centro_id = ''

    if mes and not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', mes):
        mes = ''  # filtro inválido na URL: ignora em vez de dar erro
    if mes:
        ano, m = mes.split('-')
        inicio = date(int(ano), int(m), 1)
        if int(m) == 12:
            fim = date(int(ano) + 1, 1, 1)
        else:
            fim = date(int(ano), int(m) + 1, 1)
        if regime == 'caixa':
            query = query.filter(
                Lancamento.data_pagamento >= inicio,
                Lancamento.data_pagamento < fim,
            )
        else:
            query = query.filter(
                Lancamento.data_competencia >= inicio,
                Lancamento.data_competencia < fim,
            )

    if regime == 'caixa':
        lancamentos_list = query.order_by(Lancamento.data_pagamento.desc()).all()
    else:
        lancamentos_list = query.order_by(Lancamento.data_competencia.desc()).all()

    centros = CentroCusto.query.filter_by(ativo=True).order_by(CentroCusto.nome).all()
    total_receitas = sum(l.valor for l in lancamentos_list if l.tipo == 'receita')
    total_despesas = sum(l.valor for l in lancamentos_list if l.tipo == 'despesa')

    # Verifica se há taxas históricas sem lançamento de despesa correspondente
    ids_com_taxa = {i for (i,) in db.session.query(Lancamento.id).filter(
        Lancamento.tipo == 'receita',
        Lancamento.status == 'recebido',
        Lancamento.taxa_operadora_valor > 0,
    )}
    ids_com_despesa = set()
    if ids_com_taxa:
        for (obs,) in db.session.query(Lancamento.observacoes).filter(
                Lancamento.tipo == 'despesa', Lancamento.observacoes.like('%[taxa_de:%')):
            ids_com_despesa.update(int(i) for i in re.findall(r'\[taxa_de:(\d+)\]', obs or ''))
    tem_taxas_sem_lancamento = bool(ids_com_taxa - ids_com_despesa)

    return render_template('financeiro/lancamentos.html',
        lancamentos=lancamentos_list, centros=centros,
        tipo=tipo, status=status, mes=mes, regime=regime, centro_id=centro_id,
        total_receitas=total_receitas, total_despesas=total_despesas,
        formas=formas_ativas(),
        tem_taxas_sem_lancamento=tem_taxas_sem_lancamento)


@financeiro_bp.route('/lancamentos/novo', methods=['GET', 'POST'])
def novo_lancamento():
    centros = CentroCusto.query.filter_by(ativo=True).order_by(CentroCusto.nome).all()
    clientes = Cliente.query.filter(Cliente.status != 'inativa').order_by(Cliente.nome).all()

    if request.method == 'POST':
        cc_id = _int_or_none(request.form.get('centro_custo_id'))
        if not forma_liberada(request.form.get('forma_pagamento')):
            flash('Esta forma de pagamento está bloqueada. Escolha outra.', 'danger')
            return redirect(url_for('financeiro.novo_lancamento'))
        if not cc_id:
            flash('Atenção: lançamento sem Centro de Custo. Recomendamos sempre classificar.', 'warning')
        data_comp = _parse_date(request.form.get('data_competencia'))
        recorrente, dia, pct = _recorrencia(request.form, data_comp)
        valor = _valor_br(request.form.get('valor'))
        if pct and data_comp:
            valor = valor_percentual(pct, data_comp.year, data_comp.month)   # recorrente por % do lucro bruto
        if valor is None or (valor <= 0 and not pct):
            flash('Informe um valor válido, maior que zero (ex.: 1.234,56).', 'danger')
            return redirect(url_for('financeiro.novo_lancamento'))
        if not data_comp:
            flash('Informe a data de competência.', 'danger')
            return redirect(url_for('financeiro.novo_lancamento'))
        lanc = Lancamento(
            recorrente=recorrente, dia_recorrencia=dia, percentual_lucro=pct,
            descricao=request.form['descricao'].strip(),
            tipo=request.form['tipo'],
            valor=valor,
            data_competencia=_parse_date(request.form.get('data_competencia')),
            data_vencimento=_parse_date(request.form.get('data_vencimento')),
            data_pagamento=_parse_date(request.form.get('data_pagamento')),
            status=request.form.get('status', 'pendente'),
            centro_custo_id=cc_id,
            cliente_id=_int_or_none(request.form.get('cliente_id')),
            forma_pagamento=request.form.get('forma_pagamento') or None,
            numero_documento=request.form.get('numero_documento', '').strip() or None,
            observacoes=request.form.get('observacoes', '').strip() or None,
        )
        # Ajusta status conforme pagamento informado
        if lanc.data_pagamento and lanc.status == 'pendente':
            lanc.status = 'recebido' if lanc.tipo == 'receita' else 'pago'
        _vencimento_recorrente(lanc)

        db.session.add(lanc)
        db.session.commit()
        if lanc.recorrente:
            gerar_recorrentes()
        flash('Lançamento criado com sucesso!' + (
            (f' Despesa recorrente: {lanc.percentual_lucro:g}% do lucro bruto do mês, ' if lanc.percentual_lucro else ' Despesa recorrente: ') +
            f'lançada todo dia {lanc.dia_recorrencia}.' if lanc.recorrente else ''), 'success')
        return redirect(url_for('financeiro.lancamentos'))

    return render_template('financeiro/form_lancamento.html',
        lancamento=None, centros=centros, clientes=clientes,
        formas=formas_ativas(), form_data={})


@financeiro_bp.route('/lancamentos/<int:id>/editar', methods=['GET', 'POST'])
def editar_lancamento(id):
    lanc = Lancamento.query.get_or_404(id)
    if lanc.bloqueado:
        flash('Este lançamento foi gerado por uma folha de pagamento fechada e não pode ser editado.', 'danger')
        return redirect(url_for('financeiro.lancamentos'))

    centros = CentroCusto.query.filter_by(ativo=True).order_by(CentroCusto.nome).all()
    clientes = Cliente.query.order_by(Cliente.nome).all()
    liquidado = lanc.status in ('recebido', 'pago')

    if request.method == 'POST':
        if liquidado:
            # Lançamento liquidado: apenas descrição, observações e CC são editáveis
            lanc.descricao = request.form['descricao'].strip()
            obs_antiga = lanc.observacoes or ''
            lanc.observacoes = request.form.get('observacoes', '').strip() or None
            # a marca [taxa_de:ID] liga a despesa de taxa ao recebimento; não pode se perder
            marca = re.search(r'\[taxa_de:\d+\]', obs_antiga)
            if marca and marca.group(0) not in (lanc.observacoes or ''):
                lanc.observacoes = f'{marca.group(0)} {lanc.observacoes or ""}'.strip()
            lanc.centro_custo_id = _int_or_none(request.form.get('centro_custo_id'))
            if lanc.tipo == 'despesa' and not lanc.recorrencia_origem_id:
                lanc.recorrente, lanc.dia_recorrencia, lanc.percentual_lucro = _recorrencia(request.form, lanc.data_competencia)
        else:
            cc_id = _int_or_none(request.form.get('centro_custo_id'))
            if not cc_id:
                flash('Atenção: lançamento sem Centro de Custo. Recomendamos sempre classificar.', 'warning')
            valor = _valor_br(request.form.get('valor'))
            data_comp = _parse_date(request.form.get('data_competencia'))
            pct = _recorrencia(request.form, data_comp)[2] if request.form.get('tipo') == 'despesa' and not lanc.recorrencia_origem_id else None
            if pct and data_comp:
                valor = valor_percentual(pct, data_comp.year, data_comp.month)
            if valor is None or (valor <= 0 and not pct) or not data_comp:
                db.session.rollback()
                flash('Informe um valor válido (maior que zero) e a data de competência.', 'danger')
                return redirect(url_for('financeiro.editar_lancamento', id=id))
            lanc.descricao = request.form['descricao'].strip()
            lanc.tipo = request.form['tipo']
            lanc.valor = valor
            lanc.data_competencia = _parse_date(request.form.get('data_competencia'))
            lanc.data_vencimento = _parse_date(request.form.get('data_vencimento'))
            lanc.data_pagamento = _parse_date(request.form.get('data_pagamento'))
            lanc.status = request.form.get('status', 'pendente')
            lanc.centro_custo_id = cc_id
            lanc.cliente_id = _int_or_none(request.form.get('cliente_id'))
            nova_forma = request.form.get('forma_pagamento') or None
            if nova_forma != lanc.forma_pagamento and not forma_liberada(nova_forma):
                flash('Esta forma de pagamento está bloqueada. Escolha outra.', 'danger')
                return redirect(url_for('financeiro.editar_lancamento', id=id))
            lanc.forma_pagamento = nova_forma
            lanc.numero_documento = request.form.get('numero_documento', '').strip() or None
            lanc.observacoes = request.form.get('observacoes', '').strip() or None
            if lanc.tipo == 'despesa' and not lanc.recorrencia_origem_id:
                lanc.recorrente, lanc.dia_recorrencia, lanc.percentual_lucro = _recorrencia(request.form, lanc.data_competencia)
            else:
                lanc.recorrente, lanc.dia_recorrencia, lanc.percentual_lucro = False, None, None

            _vencimento_recorrente(lanc)

            # status e data de pagamento precisam andar juntos (relatórios de caixa filtram pela data)
            pago = 'recebido' if lanc.tipo == 'receita' else 'pago'
            if lanc.status in ('recebido', 'pago'):
                lanc.status = pago
                if not lanc.data_pagamento:
                    db.session.rollback()
                    flash('Informe a data de pagamento para marcar como pago/recebido.', 'danger')
                    return redirect(url_for('financeiro.editar_lancamento', id=id))
            elif lanc.status == 'pendente' and lanc.data_pagamento:
                lanc.status = pago

            # recebimento marcado pela edição: calcula taxa e mantém a despesa de taxa em dia
            if lanc.tipo == 'receita' and lanc.status == 'recebido':
                op = lanc.operadora or operadora_padrao(lanc.data_pagamento)
                taxa_pct, taxa_valor, liq = calcular_taxa(lanc.valor, lanc.forma_pagamento or 'pix',
                                                          lanc.parcelas or 1, op)
                lanc.operadora = op
                lanc.taxa_operadora_pct, lanc.taxa_operadora_valor = taxa_pct, taxa_valor
                lanc.valor_liquido = liq if taxa_pct > 0 else None
            sincronizar_taxa(lanc)

        lanc.updated_at = datetime.utcnow()
        db.session.commit()
        if lanc.recorrente:
            gerar_recorrentes()
        flash('Lançamento atualizado!', 'success')
        return redirect(url_for('financeiro.lancamentos'))

    return render_template('financeiro/form_lancamento.html',
        lancamento=lanc, centros=centros, clientes=clientes,
        formas=formas_ativas(incluir=lanc.forma_pagamento), form_data={}, liquidado=liquidado)


@financeiro_bp.route('/lancamentos/<int:id>/desfazer-pagamento', methods=['POST'])
def desfazer_pagamento(id):
    """Volta uma DESPESA paga (ex.: ISS de nota fiscal com baixa por engano) para pendente, sem data de pagamento.
    Não vale para despesa de folha fechada nem para taxa de cartão (geradas pelo sistema)."""
    lanc = Lancamento.query.get_or_404(id)
    obs = lanc.observacoes or ''
    if lanc.tipo != 'despesa' or lanc.status != 'pago':
        flash('Só é possível desfazer o pagamento de uma despesa paga.', 'warning')
    elif lanc.bloqueado or '[taxa_de:' in obs or '[repasse-pdf:' in obs:
        flash('Este lançamento é gerado pelo sistema (folha ou taxa) e não pode ter o pagamento desfeito.', 'danger')
    else:
        lanc.status, lanc.data_pagamento = 'pendente', None
        lanc.updated_at = datetime.utcnow()
        db.session.commit()
        flash(f'Pagamento desfeito: "{lanc.descricao}" voltou para Contas a Pagar como pendente.', 'success')
        return redirect(url_for('financeiro.pagar'))
    return redirect(url_for('financeiro.editar_lancamento', id=id))


@financeiro_bp.route('/lancamentos/<int:id>/pagar', methods=['POST'])
def registrar_pagamento(id):
    lanc = Lancamento.query.get_or_404(id)
    if lanc.status == 'cancelado':
        flash('Lançamento cancelado não pode receber pagamento.', 'danger')
        return redirect(request.referrer or url_for('financeiro.lancamentos'))
    if lanc.bloqueado:
        flash('Este lançamento foi gerado por uma folha de pagamento fechada.', 'danger')
        return redirect(request.referrer or url_for('financeiro.lancamentos'))

    data_pag = _parse_date(request.form.get('data_pagamento')) or date.today()
    forma = request.form.get('forma_pagamento') or lanc.forma_pagamento or 'pix'
    if forma != lanc.forma_pagamento and not forma_liberada(forma):
        flash('Esta forma de pagamento está bloqueada. Escolha outra.', 'danger')
        return redirect(request.referrer or url_for('financeiro.lancamentos'))
    try:
        parcelas = max(1, int(request.form.get('parcelas') or 1))
    except ValueError:
        parcelas = 1
    operadora = request.form.get('operadora') or operadora_padrao(data_pag)

    if lanc.tipo == 'receita':
        taxa_pct, taxa_valor, valor_liquido = calcular_taxa(lanc.valor, forma, parcelas, operadora)
    else:
        # taxa de operadora só existe em recebimentos; despesa paga é sempre pelo valor cheio
        taxa_pct, taxa_valor, valor_liquido = 0.0, 0.0, None

    lanc.data_pagamento = data_pag
    lanc.forma_pagamento = forma
    lanc.parcelas = parcelas
    lanc.operadora = operadora
    lanc.taxa_operadora_pct = taxa_pct
    lanc.taxa_operadora_valor = taxa_valor
    lanc.valor_liquido = valor_liquido
    lanc.status = 'recebido' if lanc.tipo == 'receita' else 'pago'

    # Cria/atualiza/remove a despesa de taxa de cartão (CC005) conforme o recebimento
    sincronizar_taxa(lanc)

    db.session.commit()

    if taxa_pct > 0:
        flash(
            f'Pagamento registrado! Taxa {taxa_pct:.2f}% = {taxa_valor:_.2f} → Líquido: {valor_liquido:_.2f}'.replace('.', ',').replace('_', '.'),
            'success'
        )
    else:
        flash('Pagamento registrado!', 'success')
    return redirect(request.referrer or url_for('financeiro.lancamentos'))


@financeiro_bp.route('/backfill-taxas', methods=['POST'])
def backfill_taxas():
    """Reconcilia as despesas de taxa de cartão (CC005) com os recebimentos."""
    verificadas, orfas = sincronizar_todas()
    db.session.commit()
    flash(f'Taxas reconciliadas: {verificadas} recebimento(s) verificado(s), {orfas} taxa(s) órfã(s) removida(s).', 'success')
    return redirect(url_for('financeiro.lancamentos'))


@financeiro_bp.route('/lancamentos/<int:id>/cancelar', methods=['POST'])
def cancelar_lancamento(id):
    lanc = Lancamento.query.get_or_404(id)
    if lanc.bloqueado:
        flash('Este lançamento foi gerado por uma folha de pagamento fechada e não pode ser cancelado.', 'danger')
        return redirect(url_for('financeiro.lancamentos'))
    lanc.status = 'cancelado'
    sincronizar_taxa(lanc)  # remove a despesa de taxa, se houver
    db.session.commit()
    flash('Lançamento cancelado.', 'warning')
    return redirect(url_for('financeiro.lancamentos'))


@financeiro_bp.route('/receber')
def receber():
    hoje = date.today()
    status = request.args.get('status', 'pendente')
    query = Lancamento.query.filter_by(tipo='receita')
    if status:
        query = query.filter_by(status=status)
    else:
        query = query.filter(Lancamento.status != 'cancelado')
    lancamentos_list = query.order_by(Lancamento.data_vencimento).all()

    vencidas = [l for l in lancamentos_list if l.status == 'pendente' and l.data_vencimento and l.data_vencimento < hoje]

    total = sum(l.valor for l in lancamentos_list)
    return render_template('financeiro/receber.html',
        lancamentos=lancamentos_list, status=status, total=total,
        hoje=hoje, vencidas=len(vencidas), formas=formas_ativas())


@financeiro_bp.route('/pagar')
def pagar():
    hoje = date.today()
    status = request.args.get('status', 'pendente')
    query = Lancamento.query.filter_by(tipo='despesa')
    if status:
        query = query.filter_by(status=status)
    else:
        query = query.filter(Lancamento.status != 'cancelado')
    lancamentos_list = query.order_by(Lancamento.data_vencimento).all()

    total = sum(l.valor for l in lancamentos_list)
    return render_template('financeiro/pagar.html',
        lancamentos=lancamentos_list, status=status, total=total,
        hoje=hoje, formas=formas_ativas())


# ── Formas de pagamento ─────────────────────────────────────────────────────

@financeiro_bp.route('/formas-pagamento')
def formas_pagamento():
    from taxas import tabela_operadoras
    formas = FormaPagamento.query.order_by(FormaPagamento.padrao.desc(), FormaPagamento.nome).all()
    usos = dict(db.session.query(Lancamento.forma_pagamento, db.func.count(Lancamento.id))
                .group_by(Lancamento.forma_pagamento).all())
    tabela = tabela_operadoras()
    cadastradas = {o.codigo: o for o in Operadora.query.order_by(Operadora.id).all()}
    ordem = list(cadastradas) + [c for c in tabela if c not in cadastradas]
    operadoras = [{'codigo': c,
                   'nome': cadastradas[c].nome if c in cadastradas else c,
                   'ativo': cadastradas[c].ativo if c in cadastradas else True,
                   'id': cadastradas[c].id if c in cadastradas else None,
                   'tabela': tabela[c]} for c in ordem if c in tabela]
    return render_template('financeiro/formas_pagamento.html',
        formas=formas, usos=usos, operadoras=operadoras)


@financeiro_bp.route('/formas-pagamento/operadoras/<operadora>/taxas', methods=['POST'])
def salvar_taxas_operadora(operadora):
    """Atualiza as taxas de uma maquininha. Vale para novos pagamentos; os já registrados não mudam."""
    from taxas import tabela_operadoras
    tabela = tabela_operadoras()
    if operadora not in tabela:
        flash('Operadora desconhecida.', 'danger')
        return redirect(url_for('financeiro.formas_pagamento'))

    novos = {}  # (modalidade, parcelas) -> pct
    campos = [('debito', 'debito', 1)] + [(f'credito_{p}', 'credito', p) for p in tabela[operadora]['credito']]
    for campo, modalidade, parcelas in campos:
        bruto = (request.form.get(campo) or '').strip().replace('%', '').replace(',', '.')
        try:
            pct = float(bruto)
        except ValueError:
            pct = -1
        if not 0 <= pct <= 100:
            nome = 'Débito' if modalidade == 'debito' else f'Crédito {parcelas}x'
            flash(f'Taxa inválida em "{nome}". Use um número entre 0 e 100 (ex.: 3,34). Nada foi salvo.', 'danger')
            return redirect(url_for('financeiro.formas_pagamento'))
        novos[(modalidade, parcelas)] = round(pct, 2)

    existentes = {(t.modalidade, t.parcelas): t
                  for t in TaxaOperadora.query.filter_by(operadora=operadora).all()}
    alteradas = 0
    for (modalidade, parcelas), pct in novos.items():
        t = existentes.get((modalidade, parcelas))
        if t is None:
            db.session.add(TaxaOperadora(operadora=operadora, modalidade=modalidade,
                                         parcelas=parcelas, taxa_pct=pct))
            alteradas += 1
        elif t.taxa_pct != pct:
            t.taxa_pct = pct
            alteradas += 1
    db.session.commit()
    nome_novo = ' '.join(request.form.get('nome', '').split())
    op = Operadora.query.filter_by(codigo=operadora).first()
    if nome_novo:
        if op is None:
            op = Operadora(codigo=operadora, nome=nome_novo, ativo=True)
            db.session.add(op)
        else:
            op.nome = nome_novo
        db.session.commit()
    nome_op = nomes_operadoras().get(operadora, operadora)
    flash(f'Taxas da {nome_op} salvas ({alteradas} alterada(s)). Valem para novos pagamentos.', 'success')
    return redirect(url_for('financeiro.formas_pagamento') + '#tabela-taxas')


@financeiro_bp.route('/formas-pagamento/operadoras/nova', methods=['POST'])
def nova_operadora():
    """Cadastra uma maquininha/operadora (ou conta de link) com a tabela de taxas zerada para preencher."""
    nome = ' '.join(request.form.get('nome', '').split())
    try:
        max_parc = max(1, min(18, int(request.form.get('parcelas_max') or 12)))
    except ValueError:
        max_parc = 12
    if not nome:
        flash('Informe o nome da operadora.', 'danger')
        return redirect(url_for('financeiro.formas_pagamento'))
    codigo = unicodedata.normalize('NFKD', nome).encode('ascii', 'ignore').decode().lower()
    codigo = re.sub(r'[^a-z0-9]+', '_', codigo).strip('_')[:50] or 'operadora'
    if Operadora.query.filter(
            (Operadora.codigo == codigo) | (db.func.lower(Operadora.nome) == nome.lower())).first():
        flash('Já existe uma operadora com esse nome.', 'warning')
        return redirect(url_for('financeiro.formas_pagamento'))
    db.session.add(Operadora(codigo=codigo, nome=nome, ativo=True))
    db.session.add(TaxaOperadora(operadora=codigo, modalidade='debito', parcelas=1, taxa_pct=0.0))
    for p in range(1, max_parc + 1):
        db.session.add(TaxaOperadora(operadora=codigo, modalidade='credito', parcelas=p, taxa_pct=0.0))
    db.session.commit()
    flash(f'Operadora "{nome}" cadastrada com taxas zeradas. Preencha as taxas abaixo e salve.', 'success')
    return redirect(url_for('financeiro.formas_pagamento') + '#tabela-taxas')


@financeiro_bp.route('/formas-pagamento/operadoras/<int:id>/alternar', methods=['POST'])
def alternar_operadora(id):
    o = Operadora.query.get_or_404(id)
    if o.ativo and Operadora.query.filter_by(ativo=True).count() <= 1:
        flash('Pelo menos uma operadora precisa ficar liberada.', 'danger')
    else:
        o.ativo = not o.ativo
        db.session.commit()
        flash(f'"{o.nome}" {"liberada" if o.ativo else "bloqueada"}. Lançamentos antigos não mudam.', 'success')
    return redirect(url_for('financeiro.formas_pagamento') + '#tabela-taxas')


@financeiro_bp.route('/formas-pagamento/nova', methods=['POST'])
def nova_forma_pagamento():
    nome = ' '.join(request.form.get('nome', '').split())
    if not nome:
        flash('Informe o nome da forma de pagamento.', 'danger')
        return redirect(url_for('financeiro.formas_pagamento'))
    codigo = unicodedata.normalize('NFKD', nome).encode('ascii', 'ignore').decode().lower()
    codigo = re.sub(r'[^a-z0-9]+', '_', codigo).strip('_')[:50] or 'forma'
    if FormaPagamento.query.filter(
            (FormaPagamento.codigo == codigo) | (db.func.lower(FormaPagamento.nome) == nome.lower())).first():
        flash('Já existe uma forma de pagamento com esse nome.', 'warning')
        return redirect(url_for('financeiro.formas_pagamento'))
    tipo = request.form.get('tipo_taxa', 'nenhuma')
    if tipo not in ('nenhuma', 'debito', 'credito'):
        tipo = 'nenhuma'
    db.session.add(FormaPagamento(codigo=codigo, nome=nome, padrao=False, ativo=True, tipo_taxa=tipo))
    db.session.commit()
    flash(f'Forma de pagamento "{nome}" cadastrada.', 'success')
    return redirect(url_for('financeiro.formas_pagamento'))


@financeiro_bp.route('/formas-pagamento/<int:id>/editar', methods=['POST'])
def editar_forma_pagamento(id):
    """Edita nome, prazo e observações. O código interno não muda, então o histórico continua ligado."""
    f = FormaPagamento.query.get_or_404(id)
    nome = ' '.join(request.form.get('nome', '').split())
    if not nome:
        flash('Informe o nome da forma de pagamento.', 'danger')
    elif FormaPagamento.query.filter(FormaPagamento.id != f.id,
                                     db.func.lower(FormaPagamento.nome) == nome.lower()).first():
        flash('Já existe uma forma de pagamento com esse nome.', 'warning')
    else:
        f.nome = nome
        f.prazo = ' '.join(request.form.get('prazo', '').split())[:200]
        tipo = request.form.get('tipo_taxa')
        if tipo in ('nenhuma', 'debito', 'credito') and f.codigo not in TRAVADAS:
            f.tipo_taxa = tipo
        f.observacoes = request.form.get('observacoes', '').strip() or None
        db.session.commit()
        flash('Forma de pagamento atualizada.', 'success')
    return redirect(url_for('financeiro.formas_pagamento'))


@financeiro_bp.route('/formas-pagamento/<int:id>/alternar', methods=['POST'])
def alternar_forma_pagamento(id):
    f = FormaPagamento.query.get_or_404(id)
    if f.ativo and FormaPagamento.query.filter_by(ativo=True).count() <= 1:
        flash('Pelo menos uma forma de pagamento precisa ficar liberada.', 'danger')
        return redirect(url_for('financeiro.formas_pagamento'))
    f.ativo = not f.ativo
    db.session.commit()
    flash(f'"{f.nome}" {"liberada" if f.ativo else "bloqueada"}. Lançamentos antigos não são alterados.', 'success')
    return redirect(url_for('financeiro.formas_pagamento'))


def _valor_br(texto):
    """Converte "1.234,56", "1234,56" ou "1234.56" em float. None se vazio/inválido."""
    s = (texto or '').strip().replace('R$', '').replace(' ', '')
    if not s:
        return None
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif s.count('.') > 1:  # 1.234.567 (só separador de milhar)
        s = s.replace('.', '')
    try:
        return float(s)
    except ValueError:
        return None


def _vencimento_recorrente(lanc):
    """Despesa recorrente sem vencimento informado: vence no dia da recorrência do mês da competência
    (dia 31 = último dia do mês)."""
    if lanc.recorrente and not lanc.data_vencimento and lanc.data_competencia:
        a, m = lanc.data_competencia.year, lanc.data_competencia.month
        lanc.data_vencimento = date(a, m, min(lanc.dia_recorrencia or lanc.data_competencia.day, calendar.monthrange(a, m)[1]))


def _recorrencia(form, data_comp):
    """(recorrente, dia do mês, % do lucro bruto) do formulário; só vale para despesa.
    Sem dia informado, usa o da competência; o dia 31 vale como 'último dia do mês'."""
    if form.get('tipo') != 'despesa' or not form.get('recorrente'):
        return False, None, None
    dia = _int_or_none(form.get('dia_recorrencia')) or (data_comp.day if data_comp else None)
    pct = _valor_br(form.get('percentual_lucro'))
    return True, min(max(dia or 1, 1), 31), (min(pct, 100.0) if pct and pct > 0 else None)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _int_or_none(v):
    try:
        return int(v) if v else None
    except (ValueError, TypeError):
        return None
