import unicodedata
from collections import Counter

from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from models import db, Cliente, Atendimento, Lancamento, CentroCusto, Plano
from datetime import date, datetime
from taxas import calcular as calcular_taxa, operadora_padrao
from servicos_financeiros import sincronizar_taxa, partos_sem_pagamento

clientes_bp = Blueprint('clientes', __name__, url_prefix='/clientes')


# ── helpers ───────────────────────────────────────────────────────────────

def _chave_nome(nome):
    n = unicodedata.normalize('NFKD', nome or '')
    return ' '.join(''.join(c for c in n if not unicodedata.combining(c)).lower().split())


def _ref_gestacao(c):
    """Como distinguir duas fichas do mesmo nome: data do parto, DPP ou ano do contrato."""
    if c.data_parto:
        return f'parto {c.data_parto:%d/%m/%Y}'
    if c.data_prevista_parto:
        return f'DPP {c.data_prevista_parto:%d/%m/%Y}'
    return f'contrato {c.ano_referencia}' if c.ano_referencia else 'outra gestação'


def rotulo_cliente(c):
    """Nome da cliente; se houver mais de uma ficha com o mesmo nome (nova gestação), acrescenta a referência."""
    if c is None:
        return ''
    if 'nomes_repetidos' not in g:
        cont = Counter(_chave_nome(n) for (n,) in db.session.query(Cliente.nome))
        g.nomes_repetidos = {k for k, v in cont.items() if v > 1}
    return f'{c.nome} ({_ref_gestacao(c)})' if _chave_nome(c.nome) in g.nomes_repetidos else c.nome


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None

def _cc_parto():
    """Centro de custo padrão para receitas de contrato."""
    cc = CentroCusto.query.filter_by(codigo='CC002').first()
    return cc.id if cc else None

def _salvar_campos_cliente(c, form):
    """Aplica todos os campos do formulário ao objeto Cliente."""
    c.nome                       = form.get('nome', '').strip()
    c.cpf                        = form.get('cpf', '').strip() or None
    c.data_nascimento            = _parse_date(form.get('data_nascimento'))
    # Campos que não estão mais no formulário (celular, plano de saúde, carteirinha...) ficam como estão no banco:
    # só são atualizados se vierem no envio.
    for campo in ('telefone', 'celular', 'email', 'endereco', 'cidade', 'estado', 'cep'):
        if campo in form:
            setattr(c, campo, form.get(campo, '').strip() or None)
    c.data_inicio_acompanhamento = _parse_date(form.get('data_inicio_acompanhamento'))
    # DUM removida do formulário — campo preservado no banco, não sobrescrito
    c.data_prevista_parto        = _parse_date(form.get('data_prevista_parto'))
    c.data_parto                 = _parse_date(form.get('data_parto'))
    for campo in ('plano_saude', 'numero_carteirinha'):
        if campo in form:
            setattr(c, campo, form.get(campo, '').strip() or None)
    c.status                     = form.get('status', 'ativa')
    c.observacoes                = form.get('observacoes', '').strip() or None
    # Campos do contrato
    c.medico_grupo               = form.get('medico_grupo', '').strip() or None
    c.grupo_parto                = form.get('grupo_parto', '').strip() or None
    c.hospital_parto             = form.get('hospital_parto', '').strip() or None
    c.nome_bebe                  = form.get('nome_bebe', '').strip() or None
    c.tipo_parto                 = form.get('tipo_parto', '').strip() or None
    c.contrato_status            = form.get('contrato_status', '').strip() or None
    ano_raw = form.get('ano_referencia', '').strip()
    c.ano_referencia             = int(ano_raw) if ano_raw.isdigit() else None
    plano_raw = form.get('plano_id', '').strip()
    c.plano_id                   = int(plano_raw) if plano_raw.isdigit() else None

def _lancamentos_contrato(cliente_id):
    """Retorna todos os lançamentos de contrato do cliente, em ordem de criação."""
    return (Lancamento.query
            .filter_by(cliente_id=cliente_id, tipo='receita')
            .filter(Lancamento.atendimento_id.is_(None), Lancamento.periodo_folha_id.is_(None))
            .order_by(Lancamento.id)
            .all())


def _salvar_lancamentos(cliente, form, existentes=None):
    """Cria/atualiza lançamentos de contrato. Suporta múltiplos pagamentos."""
    valores  = form.getlist('valor_contrato[]')
    formas   = form.getlist('forma_pagamento[]')
    ops      = form.getlist('operadora[]')
    parcelas = form.getlist('parcelas[]')
    datas    = form.getlist('data_pagamento[]')

    # Aceita formato legado (campos sem [])
    if not valores:
        v = form.get('valor_contrato', '').strip()
        if v:
            valores  = [v]
            formas   = [form.get('forma_pagamento', 'pix')]
            ops      = [form.get('operadora') or '']
            parcelas = [form.get('parcelas', '1')]
            datas    = [form.get('data_pagamento', '')]

    novos = []
    for i, val_raw in enumerate(valores):
        val_raw = str(val_raw).strip()
        if not val_raw:
            continue
        try:
            valor_bruto = float(val_raw.replace(',', '.'))
        except ValueError:
            continue
        if valor_bruto <= 0:
            continue
        forma   = formas[i] if i < len(formas) else 'pix'
        parc    = int(parcelas[i]) if i < len(parcelas) and parcelas[i] else 1
        data_pg = _parse_date(datas[i]) if i < len(datas) else None
        op      = (ops[i] if i < len(ops) else '') or operadora_padrao(data_pg)
        status  = 'recebido' if data_pg else 'pendente'
        taxa_pct, taxa_val, liquido = calcular_taxa(valor_bruto, forma, parc, op)
        data_comp = data_pg or cliente.data_parto or cliente.data_prevista_parto or date.today()
        novos.append({
            'valor': valor_bruto, 'forma': forma, 'op': op, 'parc': parc,
            'data_pg': data_pg, 'status': status, 'taxa_pct': taxa_pct,
            'taxa_val': taxa_val, 'liquido': liquido, 'data_comp': data_comp,
        })

    if not novos:
        return

    existentes = existentes or []
    recebidos = [l for l in existentes if l.status in ('recebido', 'pago')]
    pendentes = [l for l in existentes if l.status == 'pendente']

    if len(novos) < len(recebidos):
        flash(f'{len(recebidos) - len(novos)} recebimento(s) já registrado(s) foram mantidos, '
              'pois pagamento recebido não é apagado pelo cadastro. Ajuste em Financeiro, se precisar.',
              'warning')

    for l in pendentes:
        db.session.delete(l)

    for idx, ni in enumerate(novos):
        if idx < len(recebidos):
            l = recebidos[idx]
            # Se nada relevante mudou, preserva competência, taxa e líquido já gravados (inclusive
            # ajustes manuais ao demonstrativo): reabrir e salvar o cadastro não deve sobrescrevê-los.
            inalterado = (abs((l.valor or 0) - ni['valor']) < 0.005
                          and (l.forma_pagamento or '') == (ni['forma'] or '')
                          and (l.parcelas or 1) == ni['parc']
                          and (l.operadora or '') == (ni['op'] or '')
                          and l.data_pagamento == ni['data_pg']
                          and l.status == ni['status'])
            l.descricao         = f'Contrato — {cliente.nome}'
            if not inalterado:
                l.valor             = ni['valor']
                l.data_competencia  = ni['data_comp']
                l.data_pagamento    = ni['data_pg']
                l.status            = ni['status']
                l.forma_pagamento   = ni['forma']
                l.operadora         = ni['op']
                l.parcelas          = ni['parc']
                l.taxa_operadora_pct   = ni['taxa_pct']
                l.taxa_operadora_valor = ni['taxa_val']
                l.valor_liquido     = ni['liquido'] if ni['taxa_pct'] > 0 else None
            if ni['status'] == 'pendente' and not l.data_vencimento:
                l.data_vencimento = ni['data_comp']
            sincronizar_taxa(l)
        else:
            novo = Lancamento(
                descricao          = f'Contrato — {cliente.nome}',
                cliente_id         = cliente.id,
                tipo               = 'receita',
                centro_custo_id    = _cc_parto(),
                valor              = ni['valor'],
                data_competencia   = ni['data_comp'],
                data_pagamento     = ni['data_pg'],
                status             = ni['status'],
                forma_pagamento    = ni['forma'],
                operadora          = ni['op'],
                parcelas           = ni['parc'],
                taxa_operadora_pct    = ni['taxa_pct'],
                taxa_operadora_valor  = ni['taxa_val'],
                valor_liquido      = ni['liquido'] if ni['taxa_pct'] > 0 else None,
                # contrato pendente vence na data prevista (parto/DPP) — alimenta alertas de atraso
                data_vencimento    = ni['data_comp'] if ni['status'] == 'pendente' else None,
            )
            db.session.add(novo)
            sincronizar_taxa(novo)


# ── rotas ─────────────────────────────────────────────────────────────────

@clientes_bp.route('/')
def index():
    q          = request.args.get('q', '').strip()
    status     = request.args.get('status', '')
    ano        = request.args.get('ano', '')
    tipo_parto = request.args.get('tipo_parto', '')
    pagamento  = request.args.get('pagamento', '')
    sem_pag = partos_sem_pagamento()

    query = Cliente.query
    if pagamento == 'pendente':
        query = query.filter(Cliente.id.in_(sem_pag.keys() or [-1]))
    if q:
        query = query.filter(
            (Cliente.nome.ilike(f'%{q}%')) |
            (Cliente.medico_grupo.ilike(f'%{q}%')) |
            (Cliente.grupo_parto.ilike(f'%{q}%')) |
            (Cliente.hospital_parto.ilike(f'%{q}%')) |
            (Cliente.nome_bebe.ilike(f'%{q}%'))
        )
    if status:
        query = query.filter_by(status=status)
    if ano.isdigit():
        query = query.filter_by(ano_referencia=int(ano))
    if tipo_parto:
        query = query.filter_by(tipo_parto=tipo_parto)

    # gestantes primeiro, depois por DPP crescente (sem DPP por último)
    clientes = query.order_by(
        (Cliente.status != 'ativa'),
        Cliente.data_prevista_parto.asc().nullslast(),
    ).all()
    return render_template('clientes/index.html',
        clientes=clientes, q=q, status=status, ano=ano, tipo_parto=tipo_parto, pagamento=pagamento, sem_pag=sem_pag)


def _get_planos():
    return Plano.query.filter_by(ativo=True).order_by(Plano.nome).all()


def _fichas_existentes():
    """Nome (sem acento/caixa) -> fichas já cadastradas, para avisar quando o nome se repete (nova gestação?)."""
    fichas = {}
    for c in Cliente.query.all():
        fichas.setdefault(_chave_nome(c.nome), []).append(f'{c.nome} — {_ref_gestacao(c)}')
    return fichas


@clientes_bp.route('/novo', methods=['GET', 'POST'])
def novo():
    if request.method == 'POST':
        cpf = request.form.get('cpf', '').strip() or None
        if cpf and Cliente.query.filter_by(cpf=cpf).first():
            flash('CPF já cadastrado.', 'danger')
            return render_template('clientes/form.html', cliente=None,
                                   lancamentos=[], form_data=request.form,
                                   planos=_get_planos(), fichas_existentes=_fichas_existentes())

        c = Cliente()
        _salvar_campos_cliente(c, request.form)
        db.session.add(c)
        db.session.flush()
        _salvar_lancamentos(c, request.form)
        db.session.commit()
        flash('Cliente cadastrada com sucesso!', 'success')
        return redirect(url_for('clientes.detail', id=c.id))

    return render_template('clientes/form.html', cliente=None,
                           lancamentos=[], form_data={}, planos=_get_planos(), fichas_existentes=_fichas_existentes())


@clientes_bp.route('/<int:id>')
def detail(id):
    cliente    = Cliente.query.get_or_404(id)
    atendimentos = Atendimento.query.filter_by(cliente_id=id).order_by(
        Atendimento.data_atendimento.desc()).all()
    lancamentos  = Lancamento.query.filter_by(cliente_id=id).order_by(
        Lancamento.data_competencia.desc()).all()
    recebidos      = [l for l in lancamentos if l.tipo == 'receita' and l.status == 'recebido']
    total_recebido = sum(l.valor for l in recebidos)
    total_taxas    = sum((l.taxa_operadora_valor or 0) for l in recebidos)
    total_liquido  = sum(l.valor_net for l in recebidos)
    total_pendente = sum(l.valor for l in lancamentos
                         if l.tipo == 'receita' and l.status == 'pendente')
    return render_template('clientes/detail.html',
        cliente=cliente,
        atendimentos=atendimentos,
        lancamentos=lancamentos,
        total_recebido=total_recebido,
        total_taxas=total_taxas,
        total_liquido=total_liquido,
        total_pendente=total_pendente,
    )


@clientes_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    cliente             = Cliente.query.get_or_404(id)
    lancamentos_contrato = _lancamentos_contrato(id)

    if request.method == 'POST':
        cpf = request.form.get('cpf', '').strip() or None
        if cpf and cpf != cliente.cpf and Cliente.query.filter_by(cpf=cpf).first():
            flash('CPF já cadastrado para outro cliente.', 'danger')
            return render_template('clientes/form.html', cliente=cliente,
                                   lancamentos=lancamentos_contrato, form_data=request.form,
                                   planos=_get_planos())

        _salvar_campos_cliente(cliente, request.form)
        _salvar_lancamentos(cliente, request.form, existentes=lancamentos_contrato)
        db.session.commit()
        flash('Cliente atualizada com sucesso!', 'success')
        return redirect(url_for('clientes.detail', id=cliente.id))

    return render_template('clientes/form.html', cliente=cliente,
                           lancamentos=lancamentos_contrato, form_data={}, planos=_get_planos())


@clientes_bp.route('/<int:id>/registrar-parto', methods=['POST'])
def registrar_parto(id):
    cliente = Cliente.query.get_or_404(id)
    data_parto = _parse_date(request.form.get('data_parto'))
    tipo_parto = request.form.get('tipo_parto', '').strip() or None

    if not data_parto:
        flash('Data do parto é obrigatória.', 'danger')
        return redirect(url_for('clientes.index'))

    cliente.data_parto = data_parto
    cliente.status = 'pos_parto'
    if tipo_parto:
        cliente.tipo_parto = tipo_parto

    # Atualiza data_competencia de todos os lançamentos de contrato para o mês do parto.
    for lanc in _lancamentos_contrato(cliente.id):
        lanc.data_competencia = data_parto
        if lanc.status == 'pendente':
            lanc.data_vencimento = data_parto

    db.session.commit()
    flash(f'Parto de {cliente.nome} registrado! Status → Puérpera e competência atualizada para {data_parto.strftime("%m/%Y")}.', 'success')
    return redirect(request.referrer or url_for('clientes.index'))


@clientes_bp.route('/<int:id>/excluir', methods=['POST'])
def excluir(id):
    from sqlalchemy import text
    nome = db.session.execute(
        text("SELECT nome FROM clientes WHERE id = :id"), {"id": id}
    ).scalar() or ''
    if not nome:
        return redirect(url_for('clientes.index'))

    try:
        db.session.execute(text("UPDATE notas_fiscais SET lancamento_iss_id = NULL WHERE cliente_id = :id"), {"id": id})
        db.session.execute(text("DELETE FROM notas_fiscais WHERE cliente_id = :id"), {"id": id})
        # despesas automáticas de taxa de cartão ligadas às receitas desta cliente
        db.session.execute(text(
            "DELETE FROM lancamentos WHERE tipo = 'despesa' AND observacoes LIKE '[taxa_de:%' "
            "AND CAST(substr(observacoes, 10, instr(observacoes, ']') - 10) AS INTEGER) "
            "IN (SELECT id FROM lancamentos WHERE cliente_id = :id)"
        ), {"id": id})
        db.session.execute(text("DELETE FROM lancamentos WHERE cliente_id = :id"), {"id": id})
        db.session.execute(text(
            "UPDATE receitas_folha SET atendimento_id = NULL WHERE atendimento_id IN "
            "(SELECT id FROM atendimentos WHERE cliente_id = :id)"
        ), {"id": id})
        db.session.execute(text(
            "DELETE FROM itens_atendimento WHERE atendimento_id IN "
            "(SELECT id FROM atendimentos WHERE cliente_id = :id)"
        ), {"id": id})
        db.session.execute(text("DELETE FROM atendimentos WHERE cliente_id = :id"), {"id": id})
        db.session.execute(text("DELETE FROM clientes WHERE id = :id"), {"id": id})
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir cliente: {e}', 'danger')
        return redirect(url_for('clientes.index'))

    flash(f'Cliente "{nome}" excluída com todos os registros.', 'success')
    return redirect(url_for('clientes.index'))
