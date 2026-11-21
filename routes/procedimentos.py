from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Procedimento, CentroCusto

procedimentos_bp = Blueprint('procedimentos', __name__, url_prefix='/procedimentos')

CATEGORIAS = [
    ('consulta', 'Consulta'),
    ('exame', 'Exame'),
    ('procedimento', 'Procedimento'),
    ('parto', 'Parto'),
    ('outros', 'Outros'),
]


@procedimentos_bp.route('/')
def index():
    q = request.args.get('q', '').strip()
    categoria = request.args.get('categoria', '')
    query = Procedimento.query
    if q:
        query = query.filter(Procedimento.nome.ilike(f'%{q}%'))
    if categoria:
        query = query.filter_by(categoria=categoria)
    procedimentos = query.order_by(Procedimento.categoria, Procedimento.nome).all()
    return render_template('procedimentos/index.html',
        procedimentos=procedimentos, q=q, categoria=categoria, categorias=CATEGORIAS)


@procedimentos_bp.route('/novo', methods=['GET', 'POST'])
def novo():
    centros = CentroCusto.query.filter_by(ativo=True).order_by(CentroCusto.nome).all()
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip() or None
        if codigo and Procedimento.query.filter_by(codigo=codigo).first():
            flash('Código já cadastrado.', 'danger')
            return render_template('procedimentos/form.html', procedimento=None,
                                   centros=centros, categorias=CATEGORIAS, form_data=request.form)
        p = Procedimento(
            codigo=codigo,
            nome=request.form['nome'].strip(),
            categoria=request.form.get('categoria', 'consulta'),
            descricao=request.form.get('descricao', '').strip() or None,
            valor_padrao=float(request.form.get('valor_padrao', 0) or 0),
            centro_custo_id=_int_or_none(request.form.get('centro_custo_id')),
            ativo=request.form.get('ativo') == 'on',
        )
        db.session.add(p)
        db.session.commit()
        flash('Procedimento cadastrado com sucesso!', 'success')
        return redirect(url_for('procedimentos.index'))
    return render_template('procedimentos/form.html', procedimento=None,
                           centros=centros, categorias=CATEGORIAS, form_data={})


@procedimentos_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    p = Procedimento.query.get_or_404(id)
    centros = CentroCusto.query.filter_by(ativo=True).order_by(CentroCusto.nome).all()
    if request.method == 'POST':
        p.nome = request.form['nome'].strip()
        p.codigo = request.form.get('codigo', '').strip() or None
        p.categoria = request.form.get('categoria', 'consulta')
        p.descricao = request.form.get('descricao', '').strip() or None
        p.valor_padrao = float(request.form.get('valor_padrao', 0) or 0)
        p.centro_custo_id = _int_or_none(request.form.get('centro_custo_id'))
        p.ativo = request.form.get('ativo') == 'on'
        db.session.commit()
        flash('Procedimento atualizado!', 'success')
        return redirect(url_for('procedimentos.index'))
    return render_template('procedimentos/form.html', procedimento=p,
                           centros=centros, categorias=CATEGORIAS, form_data={})


@procedimentos_bp.route('/<int:id>/excluir', methods=['POST'])
def excluir(id):
    p = Procedimento.query.get_or_404(id)
    if p.itens_atendimento:
        flash('Procedimento vinculado a atendimentos e não pode ser excluído.', 'danger')
        return redirect(url_for('procedimentos.index'))
    db.session.delete(p)
    db.session.commit()
    flash('Procedimento excluído.', 'success')
    return redirect(url_for('procedimentos.index'))


def _int_or_none(v):
    try:
        return int(v) if v else None
    except (ValueError, TypeError):
        return None
