"""Usuários e permissões (somente administrador: a área 'usuarios' nunca é delegável)."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from models import db, Usuario, Funcionario
from permissoes import AREAS, AREAS_CONTABILIDADE, AREAS_FUNCIONARIA, CHAVES, PERFIS_PRONTOS

usuarios_bp = Blueprint('usuarios', __name__, url_prefix='/usuarios')


def _funcionarias():
    return Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()


def _admins_ativos(excluindo=None):
    return Usuario.query.filter(Usuario.ativo.is_(True), Usuario.perfil == 'admin',
                                Usuario.id != (excluindo or 0)).count()


def _render_form(usuario, dados=None):
    return render_template('usuarios/form.html', usuario=usuario, dados=dados or {}, areas=AREAS, areas_contabilidade=AREAS_CONTABILIDADE, areas_funcionaria=AREAS_FUNCIONARIA,
                           perfis_prontos=PERFIS_PRONTOS, funcionarias=_funcionarias())


def _ler_form(usuario=None):
    """Lê e valida o formulário. Devolve (dados, erro)."""
    f = request.form
    dados = {
        'nome': f.get('nome', '').strip(),
        'email': f.get('email', '').strip().lower(),
        'perfil': f.get('perfil') if f.get('perfil') in ('admin', 'contabilidade') else 'funcionario',
        'funcionario_id': f.get('funcionario_id', type=int) or None,
        'areas': [a for a in f.getlist('areas') if a in CHAVES],
        'senha': f.get('senha', ''),
    }
    if not dados['nome'] or '@' not in dados['email']:
        return dados, 'Informe o nome e um e-mail válido.'
    outro = Usuario.query.filter(Usuario.email == dados['email'])
    if usuario:
        outro = outro.filter(Usuario.id != usuario.id)
    if outro.first():
        return dados, 'Já existe um usuário com este e-mail.'
    if (usuario is None or dados['senha']) and len(dados['senha']) < 8:
        return dados, 'A senha precisa ter pelo menos 8 caracteres.'
    if usuario and usuario.id == current_user.id and dados['perfil'] != 'admin':
        return dados, 'Você não pode tirar o seu próprio acesso de administrador.'
    if usuario and usuario.perfil == 'admin' and dados['perfil'] != 'admin' and _admins_ativos(usuario.id) == 0:
        return dados, 'É preciso manter pelo menos um administrador ativo.'
    return dados, None


def _aplicar(u, dados):
    u.nome, u.email, u.perfil = dados['nome'], dados['email'], dados['perfil']
    u.funcionario_id = dados['funcionario_id']
    u.permissoes = ','.join(dados['areas']) if dados['perfil'] != 'admin' else ''
    if dados['senha']:
        u.set_senha(dados['senha'])


@usuarios_bp.route('/')
def index():
    usuarios = Usuario.query.order_by(Usuario.ativo.desc(), Usuario.nome).all()
    return render_template('usuarios/index.html', usuarios=usuarios, areas=dict((a[0], a[1]) for a in AREAS))


@usuarios_bp.route('/novo', methods=['GET', 'POST'])
def novo():
    if request.method == 'POST':
        dados, erro = _ler_form()
        if erro:
            flash(erro, 'danger')
            return _render_form(None, dados)
        u = Usuario(ativo=True)
        _aplicar(u, dados)
        db.session.add(u)
        db.session.commit()
        flash(f'Acesso criado para {u.nome}. Passe a senha inicial por um meio seguro e peça para ela trocá-la no ícone de chave.', 'success')
        return redirect(url_for('usuarios.index'))
    return _render_form(None, {'perfil': 'funcionario', 'areas': list(AREAS_FUNCIONARIA)})


@usuarios_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    u = Usuario.query.get_or_404(id)
    if request.method == 'POST':
        dados, erro = _ler_form(u)
        if erro:
            flash(erro, 'danger')
            return _render_form(u, dados)
        _aplicar(u, dados)
        db.session.commit()
        flash('Usuário atualizado.', 'success')
        return redirect(url_for('usuarios.index'))
    return _render_form(u, {'perfil': u.perfil or 'admin', 'areas': sorted(u.areas), 'funcionario_id': u.funcionario_id})


@usuarios_bp.route('/<int:id>/ativo', methods=['POST'])
def alternar_ativo(id):
    u = Usuario.query.get_or_404(id)
    if u.id == current_user.id:
        flash('Você não pode bloquear o seu próprio acesso.', 'danger')
    elif u.ativo and u.perfil == 'admin' and _admins_ativos(u.id) == 0:
        flash('É preciso manter pelo menos um administrador ativo.', 'danger')
    else:
        u.ativo = not u.ativo
        db.session.commit()
        flash(f'Acesso de {u.nome} {"liberado" if u.ativo else "bloqueado"}.', 'success')
    return redirect(url_for('usuarios.index'))
