from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from models import db, Atendimento, ItemAtendimento, Cliente, Procedimento, Lancamento, Funcionario, ReceitaFolha
from taxas import calcular as calcular_taxa, operadora_padrao
from servicos_financeiros import sincronizar_taxa
import re
from datetime import datetime

atendimentos_bp = Blueprint('atendimentos', __name__, url_prefix='/atendimentos')

TIPOS = [
    ('consulta', 'Consulta'),
    ('retorno', 'Retorno'),
    ('procedimento', 'Procedimento'),
    ('parto', 'Parto'),
    ('urgencia', 'Urgência'),
    ('outros', 'Outros'),
]


@atendimentos_bp.route('/')
def index():
    status = request.args.get('status', '')
    cliente_id = request.args.get('cliente_id', '')
    data_de = request.args.get('data_de', '')
    data_ate = request.args.get('data_ate', '')

    query = Atendimento.query
    if status:
        query = query.filter_by(status=status)
    if cliente_id.isdigit():
        query = query.filter_by(cliente_id=int(cliente_id))
    if data_de:
        d = _parse_date(data_de)
        if d:
            query = query.filter(Atendimento.data_atendimento >= d)
    if data_ate:
        d = _parse_date(data_ate)
        if d:
            query = query.filter(Atendimento.data_atendimento <= d)

    atendimentos = query.order_by(Atendimento.data_atendimento.desc()).all()
    clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template('atendimentos/index.html',
        atendimentos=atendimentos, clientes=clientes, tipos=TIPOS,
        status=status, cliente_id=cliente_id, data_de=data_de, data_ate=data_ate)


@atendimentos_bp.route('/novo', methods=['GET', 'POST'])
def novo():
    clientes = Cliente.query.filter(Cliente.status != 'inativa').order_by(Cliente.nome).all()
    procedimentos = Procedimento.query.filter_by(ativo=True).order_by(Procedimento.nome).all()
    cliente_id = request.args.get('cliente_id', '')

    if request.method == 'POST':
        cliente_id = int(request.form['cliente_id'])
        data_atend = _parse_date(request.form.get('data_atendimento'))
        if not data_atend:
            flash('Data do atendimento é obrigatória.', 'danger')
            return render_template('atendimentos/form.html', funcionarios=_funcionarios(), atendimento=None,
                clientes=clientes, procedimentos=procedimentos, tipos=TIPOS,
                form_data=request.form)

        try:
            a = Atendimento(
                cliente_id=cliente_id,
                data_atendimento=data_atend,
                hora_atendimento=request.form.get('hora_atendimento', '').strip() or None,
                tipo=request.form.get('tipo', 'consulta'),
                profissional=request.form.get('profissional', '').strip() or None,
                # direcionar o valor a uma prestadora de serviço é da administradora; quando a prestadora de serviço agenda, é sempre rateio
                funcionario_id=(request.form.get('funcionario_id', type=int) or None) if current_user.eh_admin else None,
                observacoes=request.form.get('observacoes', '').strip() or None,
                status='agendado',
                valor_total=0.0,
            )
            db.session.add(a)
            db.session.flush()

            valor_total = 0.0
            proc_ids = request.form.getlist('procedimento_id[]')
            qtds = request.form.getlist('quantidade[]')
            valores = request.form.getlist('valor_unitario[]')

            for i, proc_id in enumerate(proc_ids):
                if not proc_id:
                    continue
                proc = Procedimento.query.get(int(proc_id))
                if not proc:
                    continue
                qtd = float(qtds[i]) if i < len(qtds) and qtds[i] else 1.0
                valor_unit = float(valores[i]) if i < len(valores) and valores[i] else proc.valor_padrao
                valor_tot = qtd * valor_unit
                valor_total += valor_tot
                item = ItemAtendimento(
                    atendimento_id=a.id,
                    procedimento_id=proc.id,
                    quantidade=qtd,
                    valor_unitario=valor_unit,
                    valor_total=valor_tot,
                )
                db.session.add(item)

            a.valor_total = valor_total
            db.session.commit()
            flash('Atendimento agendado com sucesso!', 'success')
            return redirect(url_for('atendimentos.detail', id=a.id))
        except Exception:
            db.session.rollback()
            flash('Erro ao salvar atendimento. Tente novamente.', 'danger')

    return render_template('atendimentos/form.html', funcionarios=_funcionarios(), atendimento=None,
        clientes=clientes, procedimentos=procedimentos, tipos=TIPOS,
        form_data={'cliente_id': cliente_id})


@atendimentos_bp.route('/<int:id>')
def detail(id):
    a = Atendimento.query.get_or_404(id)
    return render_template('atendimentos/detail.html', atendimento=a)


@atendimentos_bp.route('/<int:id>/realizar', methods=['POST'])
def realizar(id):
    a = Atendimento.query.get_or_404(id)
    if a.status != 'agendado':
        flash('Atendimento não está agendado.', 'danger')
        return redirect(url_for('atendimentos.detail', id=id))

    a.status = 'realizado'

    # Gera lançamentos financeiros por procedimento
    for item in a.itens:
        cc_id = item.procedimento.centro_custo_id if item.procedimento else None
        lanc = Lancamento(
            descricao=f'{item.procedimento.nome if item.procedimento else "Procedimento"} — {a.cliente.nome if a.cliente else "Cliente"}',
            tipo='receita',
            valor=item.valor_total,
            data_competencia=a.data_atendimento,
            data_vencimento=a.data_atendimento,
            status='pendente',
            centro_custo_id=cc_id,
            cliente_id=a.cliente_id,
            atendimento_id=a.id,
        )
        db.session.add(lanc)

    db.session.commit()
    flash('Atendimento realizado! Lançamentos financeiros gerados.', 'success')
    return _voltar(id)


@atendimentos_bp.route('/<int:id>/cancelar', methods=['POST'])
def cancelar(id):
    a = Atendimento.query.get_or_404(id)
    a.status = 'cancelado'
    for lanc in a.lancamentos:
        if lanc.status == 'pendente':
            lanc.status = 'cancelado'
    db.session.commit()
    flash('Atendimento cancelado.', 'warning')
    return redirect(url_for('atendimentos.detail', id=id))


@atendimentos_bp.route('/<int:id>/excluir', methods=['POST'])
def excluir(id):
    a = Atendimento.query.get_or_404(id)
    for l in a.lancamentos:
        db.session.delete(l)
    ReceitaFolha.query.filter_by(atendimento_id=a.id).update({'atendimento_id': None})
    db.session.delete(a)
    db.session.commit()
    flash('Atendimento e lançamentos vinculados excluídos.', 'success')
    return redirect(url_for('atendimentos.index'))


@atendimentos_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    a = Atendimento.query.get_or_404(id)
    if a.status == 'cancelado':
        flash('Atendimentos cancelados não podem ser editados.', 'danger')
        return redirect(url_for('atendimentos.detail', id=id))

    clientes = Cliente.query.filter(Cliente.status != 'inativa').order_by(Cliente.nome).all()
    procedimentos = Procedimento.query.filter_by(ativo=True).order_by(Procedimento.nome).all()

    if request.method == 'POST':
        era_realizado = a.status == 'realizado'

        a.cliente_id = int(request.form['cliente_id'])
        a.data_atendimento = _parse_date(request.form.get('data_atendimento'))
        a.hora_atendimento = request.form.get('hora_atendimento', '').strip() or None
        a.tipo = request.form.get('tipo', 'consulta')
        a.profissional = request.form.get('profissional', '').strip() or None
        if current_user.eh_admin:   # a prestadora de serviço não altera o direcionamento definido pela administradora
            a.funcionario_id = request.form.get('funcionario_id', type=int) or None
        a.observacoes = request.form.get('observacoes', '').strip() or None

        cliente = Cliente.query.get(a.cliente_id)
        cliente_nome = cliente.nome if cliente else ''

        # Rebuild itens
        for item in a.itens:
            db.session.delete(item)
        db.session.flush()

        valor_total = 0.0
        proc_ids = request.form.getlist('procedimento_id[]')
        qtds     = request.form.getlist('quantidade[]')
        valores  = request.form.getlist('valor_unitario[]')
        novos_itens = []

        for i, proc_id in enumerate(proc_ids):
            if not proc_id:
                continue
            proc = Procedimento.query.get(int(proc_id))
            if not proc:
                continue
            qtd       = float(qtds[i])   if i < len(qtds)    and qtds[i]    else 1.0
            valor_unit = float(valores[i]) if i < len(valores) and valores[i] else proc.valor_padrao
            valor_tot  = qtd * valor_unit
            valor_total += valor_tot
            db.session.add(ItemAtendimento(
                atendimento_id=a.id,
                procedimento_id=proc.id,
                quantidade=qtd,
                valor_unitario=valor_unit,
                valor_total=valor_tot,
            ))
            novos_itens.append({'proc': proc, 'valor': valor_tot})

        a.valor_total = valor_total

        # ── Atualiza lançamentos se o atendimento já estava realizado ──
        if era_realizado:
            lancs = Lancamento.query.filter_by(atendimento_id=a.id).all()
            lancs_recebidos = [l for l in lancs if l.status in ('recebido', 'pago')]
            lancs_pendentes  = [l for l in lancs if l.status == 'pendente']

            # Remove os pendentes (serão recriados abaixo se necessário)
            for l in lancs_pendentes:
                db.session.delete(l)

            # Emparelha cada item novo a um lançamento já recebido: primeiro pelo nome do
            # procedimento (reordenar itens não troca valores), depois pela ordem.
            livres = list(lancs_recebidos)
            pares = {}
            for i, ni in enumerate(novos_itens):
                m = next((l for l in livres if l.descricao.startswith(f"{ni['proc'].nome} —")), None)
                if m:
                    pares[i] = m
                    livres.remove(m)
            for i in range(len(novos_itens)):
                if i not in pares and livres:
                    pares[i] = livres.pop(0)

            for l in lancs_recebidos:
                l.data_competencia = a.data_atendimento
                l.cliente_id = a.cliente_id

            for i, l in pares.items():
                ni = novos_itens[i]
                l.valor = ni['valor']
                l.descricao = f"{ni['proc'].nome} — {cliente_nome}"
                # valor mudou: taxa de cartão, líquido e despesa de taxa precisam acompanhar
                if l.status == 'recebido':
                    taxa_pct, taxa_val, liq = calcular_taxa(
                        l.valor, l.forma_pagamento or 'pix', l.parcelas or 1,
                        l.operadora or operadora_padrao(l.data_pagamento))
                    l.taxa_operadora_pct, l.taxa_operadora_valor = taxa_pct, taxa_val
                    l.valor_liquido = liq if taxa_pct > 0 else None
                    sincronizar_taxa(l)

            # Itens sem lançamento recebido correspondente viram lançamentos pendentes
            for i, ni in enumerate(novos_itens):
                if i in pares:
                    continue
                db.session.add(Lancamento(
                    descricao=f"{ni['proc'].nome} — {cliente_nome}",
                    tipo='receita',
                    valor=ni['valor'],
                    data_competencia=a.data_atendimento,
                    data_vencimento=a.data_atendimento,
                    status='pendente',
                    centro_custo_id=ni['proc'].centro_custo_id,
                    cliente_id=a.cliente_id,
                    atendimento_id=a.id,
                ))

            if livres:
                flash(f'{len(livres)} lançamento(s) já recebido(s) não correspondem a nenhum item '
                      'do atendimento e foram mantidos. Revise em Financeiro.', 'warning')

        db.session.commit()
        flash('Atendimento e lançamentos atualizados com sucesso!', 'success')
        return redirect(url_for('atendimentos.detail', id=a.id))

    return render_template('atendimentos/form.html', funcionarios=_funcionarios(), atendimento=a,
        clientes=clientes, procedimentos=procedimentos, tipos=TIPOS, form_data={})


@atendimentos_bp.route('/registrar-consulta-rapida', methods=['POST'])
def registrar_consulta_rapida():
    """Agenda consulta EO incluída no plano — sem custo, sem lançamento financeiro.
    Entra em "Próximos Atendimentos" como agendada; ao confirmar (realizar) sobe para o quadro de gestantes."""
    cliente_id   = request.form.get('cliente_id', type=int)
    data_atend   = _parse_date(request.form.get('data_atendimento'))
    profissional = request.form.get('profissional', '').strip() or None
    hora = request.form.get('hora_atendimento', '').strip()
    hora = hora[:5] if re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d(:\d\d)?', hora) else None

    if not cliente_id or not data_atend:
        flash('Data da consulta é obrigatória.', 'danger')
        return redirect(url_for('dashboard'))

    a = Atendimento(
        cliente_id       = cliente_id,
        data_atendimento = data_atend,
        hora_atendimento = hora,
        tipo             = 'consulta',
        profissional     = profissional,
        status           = 'agendado',
        valor_total      = 0.0,
    )
    db.session.add(a)
    db.session.commit()
    flash('Consulta EO agendada. Confirme ou remarque em "Próximos Atendimentos".', 'success')
    return redirect(url_for('dashboard'))


@atendimentos_bp.route('/<int:id>/remarcar', methods=['POST'])
def remarcar(id):
    a = Atendimento.query.get_or_404(id)
    nova = _parse_date(request.form.get('data_atendimento'))
    if a.status != 'agendado':
        flash('Só atendimentos agendados podem ser remarcados.', 'danger')
    elif not nova:
        flash('Informe a nova data do atendimento.', 'danger')
    else:
        a.data_atendimento = nova
        a.hora_atendimento = (request.form.get('hora_atendimento') or '').strip()[:5] or None
        db.session.commit()
        flash('Atendimento remarcado.', 'success')
    return _voltar(id)


def _funcionarios():
    return Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()


def _voltar(id):
    """Quem veio do dashboard (campo next) volta para ele; os demais, para o atendimento."""
    if request.form.get('next') == 'dashboard':
        return redirect(url_for('dashboard'))
    return redirect(url_for('atendimentos.detail', id=id))


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None
