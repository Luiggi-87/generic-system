from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Material, MovimentoEstoque, CentroCusto
from datetime import date, datetime

materiais_bp = Blueprint('materiais', __name__, url_prefix='/materiais')

UNIDADES = ['un', 'cx', 'kg', 'g', 'L', 'mL', 'pct', 'par', 'rolo', 'fr']


@materiais_bp.route('/')
def index():
    q = request.args.get('q', '').strip()
    filtro = request.args.get('filtro', '')
    query = Material.query.filter_by(ativo=True)
    if q:
        query = query.filter(Material.nome.ilike(f'%{q}%'))
    if filtro == 'baixo':
        materiais_list = [m for m in query.all() if m.estoque_baixo]
    else:
        materiais_list = query.order_by(Material.nome).all()
    return render_template('materiais/index.html',
        materiais=materiais_list, q=q, filtro=filtro)


@materiais_bp.route('/novo', methods=['GET', 'POST'])
def novo():
    centros = CentroCusto.query.filter(CentroCusto.tipo.in_(['despesa', 'ambos'])).filter_by(ativo=True).all()
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip() or None
        if codigo and Material.query.filter_by(codigo=codigo).first():
            flash('Código já cadastrado.', 'danger')
            return render_template('materiais/form.html', material=None,
                                   centros=centros, unidades=UNIDADES, form_data=request.form)
        m = Material(
            codigo=codigo,
            nome=request.form['nome'].strip(),
            descricao=request.form.get('descricao', '').strip() or None,
            unidade_medida=request.form.get('unidade_medida', 'un'),
            valor_unitario=float(request.form.get('valor_unitario', 0) or 0),
            quantidade_atual=float(request.form.get('quantidade_atual', 0) or 0),
            quantidade_minima=float(request.form.get('quantidade_minima', 0) or 0),
            centro_custo_id=_int_or_none(request.form.get('centro_custo_id')),
            ativo=True,
        )
        db.session.add(m)
        db.session.flush()
        qtd_inicial = float(request.form.get('quantidade_atual', 0) or 0)
        if qtd_inicial > 0:
            mov = MovimentoEstoque(
                material_id=m.id,
                tipo='entrada',
                quantidade=qtd_inicial,
                valor_unitario=m.valor_unitario,
                valor_total=qtd_inicial * m.valor_unitario,
                motivo='Estoque inicial',
                data=date.today(),
            )
            db.session.add(mov)
        db.session.commit()
        flash('Material cadastrado!', 'success')
        return redirect(url_for('materiais.index'))
    return render_template('materiais/form.html', material=None,
                           centros=centros, unidades=UNIDADES, form_data={})


@materiais_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    m = Material.query.get_or_404(id)
    centros = CentroCusto.query.filter(CentroCusto.tipo.in_(['despesa', 'ambos'])).filter_by(ativo=True).all()
    if request.method == 'POST':
        m.nome = request.form['nome'].strip()
        m.codigo = request.form.get('codigo', '').strip() or None
        m.descricao = request.form.get('descricao', '').strip() or None
        m.unidade_medida = request.form.get('unidade_medida', 'un')
        m.valor_unitario = float(request.form.get('valor_unitario', 0) or 0)
        m.quantidade_minima = float(request.form.get('quantidade_minima', 0) or 0)
        m.centro_custo_id = _int_or_none(request.form.get('centro_custo_id'))
        m.ativo = request.form.get('ativo') == 'on'
        db.session.commit()
        flash('Material atualizado!', 'success')
        return redirect(url_for('materiais.index'))
    return render_template('materiais/form.html', material=m,
                           centros=centros, unidades=UNIDADES, form_data={})


@materiais_bp.route('/<int:id>/movimentar', methods=['GET', 'POST'])
def movimentar(id):
    m = Material.query.get_or_404(id)
    if request.method == 'POST':
        tipo = request.form.get('tipo')
        quantidade = float(request.form.get('quantidade', 0) or 0)
        if quantidade <= 0:
            flash('Quantidade deve ser maior que zero.', 'danger')
            return render_template('materiais/movimentar.html', material=m)
        if tipo == 'saida' and quantidade > m.quantidade_atual:
            flash(f'Estoque insuficiente. Disponível: {m.quantidade_atual} {m.unidade_medida}.', 'danger')
            return render_template('materiais/movimentar.html', material=m)

        valor_unit = float(request.form.get('valor_unitario', m.valor_unitario) or m.valor_unitario)
        mov = MovimentoEstoque(
            material_id=m.id,
            tipo=tipo,
            quantidade=quantidade,
            valor_unitario=valor_unit,
            valor_total=quantidade * valor_unit,
            motivo=request.form.get('motivo', '').strip() or None,
            data=_parse_date(request.form.get('data')) or date.today(),
            observacoes=request.form.get('observacoes', '').strip() or None,
        )
        db.session.add(mov)

        if tipo == 'entrada':
            m.quantidade_atual += quantidade
        else:
            m.quantidade_atual -= quantidade

        db.session.commit()
        flash(f'Movimentação de {"entrada" if tipo == "entrada" else "saída"} registrada!', 'success')
        return redirect(url_for('materiais.index'))

    movimentos = MovimentoEstoque.query.filter_by(material_id=id).order_by(
        MovimentoEstoque.data.desc()).limit(20).all()
    return render_template('materiais/movimentar.html', material=m, movimentos=movimentos)


@materiais_bp.route('/<int:id>/excluir', methods=['POST'])
def excluir(id):
    m = Material.query.get_or_404(id)
    m.ativo = False
    db.session.commit()
    flash('Material desativado.', 'success')
    return redirect(url_for('materiais.index'))


def _int_or_none(v):
    try:
        return int(v) if v else None
    except (ValueError, TypeError):
        return None


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None
