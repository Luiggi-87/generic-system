from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from models import db, Plano, ItemPlano, Cliente

planos_bp = Blueprint('planos', __name__, url_prefix='/planos')


# ── helpers ───────────────────────────────────────────────────────────────

def _salvar_itens(plano, form):
    """Reconstrói a lista de itens do plano a partir do formulário."""
    # Remove itens antigos
    for item in list(plano.itens):
        db.session.delete(item)
    db.session.flush()

    servicos   = form.getlist('servico[]')
    quantidades = form.getlist('quantidade[]')
    descricoes = form.getlist('descricao_item[]')

    for i, srv in enumerate(servicos):
        srv = srv.strip()
        if not srv:
            continue
        try:
            qtd = int(quantidades[i]) if i < len(quantidades) and quantidades[i] else 1
        except (ValueError, TypeError):
            qtd = 1
        desc = descricoes[i].strip() if i < len(descricoes) else ''
        item = ItemPlano(
            plano_id=plano.id,
            servico=srv,
            quantidade=max(1, qtd),
            descricao=desc or None,
            ordem=i,
        )
        db.session.add(item)


# ── rotas ─────────────────────────────────────────────────────────────────

@planos_bp.route('/')
def index():
    planos = Plano.query.order_by(Plano.ativo.desc(), Plano.nome).all()
    return render_template('planos/index.html', planos=planos)


@planos_bp.route('/novo', methods=['GET', 'POST'])
def novo():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        if not nome:
            flash('Nome do plano é obrigatório.', 'danger')
            return render_template('planos/form.html', plano=None, form_data=request.form)

        try:
            valor = float(request.form.get('valor', '0').replace(',', '.') or 0)
        except ValueError:
            valor = 0.0

        try:
            parcelas = int(request.form.get('parcelas_sem_taxa', 3) or 3)
        except (ValueError, TypeError):
            parcelas = 3

        plano = Plano(
            nome=nome,
            descricao=request.form.get('descricao', '').strip() or None,
            valor=valor,
            parcelas_sem_taxa=parcelas,
            ativo=True,
        )
        db.session.add(plano)
        db.session.flush()
        _salvar_itens(plano, request.form)
        db.session.commit()
        flash(f'Plano "{nome}" criado com sucesso!', 'success')
        return redirect(url_for('planos.index'))

    return render_template('planos/form.html', plano=None, form_data={})


@planos_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    plano = Plano.query.get_or_404(id)

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        if not nome:
            flash('Nome do plano é obrigatório.', 'danger')
            return render_template('planos/form.html', plano=plano, form_data=request.form)

        try:
            valor = float(request.form.get('valor', '0').replace(',', '.') or 0)
        except ValueError:
            valor = 0.0

        try:
            parcelas = int(request.form.get('parcelas_sem_taxa', 3) or 3)
        except (ValueError, TypeError):
            parcelas = 3

        plano.nome       = nome
        plano.descricao  = request.form.get('descricao', '').strip() or None
        plano.valor      = valor
        plano.parcelas_sem_taxa = parcelas
        plano.ativo      = request.form.get('ativo') == 'on'

        _salvar_itens(plano, request.form)
        db.session.commit()
        flash(f'Plano "{nome}" atualizado!', 'success')
        return redirect(url_for('planos.index'))

    return render_template('planos/form.html', plano=plano, form_data={})


@planos_bp.route('/<int:id>/excluir', methods=['POST'])
def excluir(id):
    plano = Plano.query.get_or_404(id)
    if plano.total_clientes > 0:
        flash(f'Não é possível excluir: {plano.total_clientes} cliente(s) vinculada(s) a este plano.', 'danger')
        return redirect(url_for('planos.index'))
    nome = plano.nome
    db.session.delete(plano)
    db.session.commit()
    flash(f'Plano "{nome}" excluído.', 'success')
    return redirect(url_for('planos.index'))


@planos_bp.route('/<int:id>/toggle-ativo', methods=['POST'])
def toggle_ativo(id):
    plano = Plano.query.get_or_404(id)
    plano.ativo = not plano.ativo
    db.session.commit()
    estado = 'ativado' if plano.ativo else 'desativado'
    flash(f'Plano "{plano.nome}" {estado}.', 'success')
    return redirect(url_for('planos.index'))


@planos_bp.route('/api')
def api_planos():
    """Retorna JSON com todos os planos ativos para uso no formulário de cliente."""
    planos = Plano.query.filter_by(ativo=True).order_by(Plano.nome).all()
    resultado = []
    for p in planos:
        resultado.append({
            'id': p.id,
            'nome': p.nome,
            'valor': p.valor,
            'parcelas_sem_taxa': p.parcelas_sem_taxa,
            'itens': [
                {'servico': i.servico, 'quantidade': i.quantidade, 'descricao': i.descricao or ''}
                for i in p.itens
            ],
        })
    return jsonify(resultado)
