from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, CentroCusto

centros_custo_bp = Blueprint('centros_custo', __name__, url_prefix='/centros-custo')

TIPOS = [('receita', 'Receita'), ('despesa', 'Despesa'), ('ambos', 'Ambos')]


@centros_custo_bp.route('/')
def index():
    tipo = request.args.get('tipo', '')
    query = CentroCusto.query
    if tipo:
        query = query.filter_by(tipo=tipo)
    centros = query.order_by(CentroCusto.codigo).all()
    return render_template('centros_custo/index.html', centros=centros, tipo=tipo, tipos=TIPOS)


@centros_custo_bp.route('/novo', methods=['GET', 'POST'])
def novo():
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip()
        if CentroCusto.query.filter_by(codigo=codigo).first():
            flash('Código já cadastrado.', 'danger')
            return render_template('centros_custo/form.html', centro=None,
                                   tipos=TIPOS, form_data=request.form)
        c = CentroCusto(
            codigo=codigo,
            nome=request.form['nome'].strip(),
            tipo=request.form.get('tipo', 'ambos'),
            descricao=request.form.get('descricao', '').strip() or None,
            ativo=request.form.get('ativo') == 'on',
        )
        db.session.add(c)
        db.session.commit()
        flash('Centro de custo cadastrado!', 'success')
        return redirect(url_for('centros_custo.index'))
    return render_template('centros_custo/form.html', centro=None, tipos=TIPOS, form_data={})


@centros_custo_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    c = CentroCusto.query.get_or_404(id)
    if request.method == 'POST':
        c.codigo = request.form.get('codigo', '').strip()
        c.nome = request.form['nome'].strip()
        c.tipo = request.form.get('tipo', 'ambos')
        c.descricao = request.form.get('descricao', '').strip() or None
        c.ativo = request.form.get('ativo') == 'on'
        db.session.commit()
        flash('Centro de custo atualizado!', 'success')
        return redirect(url_for('centros_custo.index'))
    return render_template('centros_custo/form.html', centro=c, tipos=TIPOS, form_data={})


@centros_custo_bp.route('/<int:id>/excluir', methods=['POST'])
def excluir(id):
    c = CentroCusto.query.get_or_404(id)
    if c.lancamentos or c.procedimentos or c.materiais:
        flash('Centro de custo com vínculos não pode ser excluído.', 'danger')
        return redirect(url_for('centros_custo.index'))
    db.session.delete(c)
    db.session.commit()
    flash('Centro de custo excluído.', 'success')
    return redirect(url_for('centros_custo.index'))
