from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import func
from models import db, Usuario, Cliente, Atendimento, Lancamento, CentroCusto, Procedimento, Material, Funcionario, Plano, ItemPlano
from datetime import date, datetime
import hashlib
import hmac
import os
import subprocess
import time

# O servidor roda em UTC: sem isto, depois das 21h (Brasília) date.today() já seria o dia seguinte
# (alertas, vencimentos, datas padrão e despesas recorrentes sairiam no dia errado).
os.environ.setdefault('TZ', 'America/Sao_Paulo')
if hasattr(time, 'tzset'):
    time.tzset()

from routes.clientes import clientes_bp
from routes.procedimentos import procedimentos_bp
from routes.materiais import materiais_bp
from routes.centros_custo import centros_custo_bp
from routes.atendimentos import atendimentos_bp
from routes.financeiro import financeiro_bp
from routes.relatorios import relatorios_bp
from routes.folha import folha_bp
from routes.planos import planos_bp
from routes.notas_fiscais import nf_bp
from routes.relatorios_gerenciais import gerencial_bp
from routes.contratos_iss import contratos_iss_bp
from routes.api_leitura import api_leitura_bp
from routes.usuarios import usuarios_bp
from routes.iss_mensal import iss_bp
from routes.notas_funcionarias import notas_func_bp, resumo_pendentes
from permissoes import AREAS_DO_REPASSE, MSG_REPASSE_OCULTO, area_do_endpoint, primeira_rota
from routes.relatorio_faturamento import faturamento_bp

app = Flask(__name__)


def _chave_secreta():
    """SECRET_KEY: variável de ambiente, senão um arquivo gerado na 1ª execução (fora do Git)."""
    chave = os.environ.get('SECRET_KEY')
    if chave:
        return chave
    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, 'secret.key')
    try:
        fd = os.open(caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(os.urandom(32).hex())
    except FileExistsError:
        pass
    with open(caminho) as f:
        return f.read().strip()


app.config['SECRET_KEY'] = _chave_secreta()
# SQLite: espera até 30 s por um bloqueio (deploy, backup ou outro acesso gravando) em vez de falhar em 5 s com
# "database is locked" — que já derrubou a inicialização do site (create_all no arquivo WSGI).
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'timeout': 30}}
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # bloqueia POST vindo de outro site (CSRF)
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gestao_clinica.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Lido do ambiente (definido no arquivo WSGI do PythonAnywhere, nunca commitado).
# Sem essa variável configurada, a rota /deploy-webhook fica desativada.
DEPLOY_WEBHOOK_SECRET = os.environ.get('DEPLOY_WEBHOOK_SECRET')

# Idem, para a rota /api/clientes (relatório somente-leitura).
REPORT_API_KEY = os.environ.get('REPORT_API_KEY')

db.init_app(app)

# ── Flask-Login ───────────────────────────────────────────────────────────────
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Faça login para acessar o sistema.'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))


# ── Login / Logout ────────────────────────────────────────────────────────────
_FALHAS_LOGIN = {}          # (ip, e-mail) -> [tentativas, início da janela]  (memória do processo)
_MAX_FALHAS, _JANELA_SEG = 5, 15 * 60


def _destino_seguro(destino):
    """Só aceita caminhos internos (/algo): evita redirecionar o login para outro site."""
    if destino and destino.startswith('/') and not destino.startswith('//') and '\\' not in destino:
        return destino
    return None


def _bloqueado(chave):
    reg = _FALHAS_LOGIN.get(chave)
    if not reg:
        return False
    if time.time() - reg[1] > _JANELA_SEG:
        del _FALHAS_LOGIN[chave]
        return False
    return reg[0] >= _MAX_FALHAS


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        chave = (request.remote_addr, email)
        if _bloqueado(chave):
            flash('Muitas tentativas de acesso. Aguarde 15 minutos e tente de novo.', 'danger')
            return render_template('login.html'), 429
        usuario = Usuario.query.filter_by(email=email, ativo=True).first()
        if usuario and usuario.check_senha(senha):
            _FALHAS_LOGIN.pop(chave, None)
            login_user(usuario, remember=request.form.get('lembrar') == 'on')
            return redirect(_destino_seguro(request.args.get('next')) or url_for('dashboard'))
        reg = _FALHAS_LOGIN.setdefault(chave, [0, time.time()])
        reg[0] += 1
        flash('E-mail ou senha incorretos.', 'danger')
    return render_template('login.html')


@app.route('/alterar-senha', methods=['GET', 'POST'])
@login_required
def alterar_senha():
    if request.method == 'POST':
        atual = request.form.get('senha_atual', '')
        nova = request.form.get('nova_senha', '')
        confirma = request.form.get('confirma_senha', '')
        if not current_user.check_senha(atual):
            flash('Senha atual incorreta.', 'danger')
        elif len(nova) < 8:
            flash('A nova senha precisa ter pelo menos 8 caracteres.', 'danger')
        elif nova != confirma:
            flash('A confirmação não confere com a nova senha.', 'danger')
        else:
            current_user.set_senha(nova)
            db.session.commit()
            flash('Senha alterada com sucesso.', 'success')
            return redirect(url_for('dashboard'))
    return render_template('alterar_senha.html')


@app.route('/logout')
def logout():
    logout_user()
    flash('Sessão encerrada.', 'info')
    return redirect(url_for('login'))


@app.context_processor
def inject_now():
    from taxas import operadora_padrao
    from servicos_financeiros import (formas_ativas, nomes_formas, operadoras_ativas,
                                      nomes_operadoras, tipos_taxa)
    from taxas import tabela_operadoras
    from routes.clientes import rotulo_cliente
    from marca import MARCA
    return {'now': datetime.now, 'marca': MARCA, 'rotulo': rotulo_cliente, 'pode': lambda area: current_user.is_authenticated and current_user.pode(area),
            'operadora_padrao_hoje': operadora_padrao(),
            'formas_ativas': formas_ativas(), 'formas_nomes': nomes_formas(),
            'taxas_db': tabela_operadoras(), 'operadoras_ativas': operadoras_ativas(),
            'operadoras_nomes': nomes_operadoras(), 'formas_taxa': tipos_taxa()}


app.register_blueprint(clientes_bp)
app.register_blueprint(procedimentos_bp)
app.register_blueprint(materiais_bp)
app.register_blueprint(centros_custo_bp)
app.register_blueprint(atendimentos_bp)
app.register_blueprint(financeiro_bp)
app.register_blueprint(relatorios_bp)
app.register_blueprint(folha_bp)
app.register_blueprint(planos_bp)
app.register_blueprint(nf_bp)
app.register_blueprint(gerencial_bp)
app.register_blueprint(contratos_iss_bp)
app.register_blueprint(api_leitura_bp)
app.register_blueprint(usuarios_bp)
app.register_blueprint(iss_bp)
app.register_blueprint(notas_func_bp)
app.register_blueprint(faturamento_bp)


@app.template_filter('brl')
def format_brl(value):
    if value is None:
        return 'R$ 0,00'
    return f"R$ {value:_.2f}".replace('.', ',').replace('_', '.')


@app.template_filter('cor_contrato')
def cor_contrato(status):
    """Classe de cor do status do contrato: assinado = verde, enviado = amarelo, pendente = vermelho."""
    s = (status or '').strip().upper()
    if s.startswith('ASSINAD'):
        return 'bg-success text-white'
    if s.startswith('ENVIAD'):
        return 'bg-warning text-dark'
    if s.startswith('PENDENT'):
        return 'bg-danger text-white'
    return 'bg-light text-dark'


@app.template_filter('data_br')
def format_data_br(value):
    if value is None:
        return '-'
    if isinstance(value, str):
        return value
    return value.strftime('%d/%m/%Y')


@app.before_request
def require_login():
    """Redireciona para login em qualquer rota não-pública."""
    public = {'login', 'static', 'deploy_webhook', 'api_clientes', 'api_lancamentos'}
    # a API de leitura se protege sozinha, por chave (routes/api_leitura.py)
    if (request.endpoint and request.endpoint not in public and request.blueprint != 'api_leitura'
            and not current_user.is_authenticated):
        return redirect(url_for('login', next=request.url))
    # permissão por área (o administrador acessa tudo; a prestadora de serviço só o que foi liberado)
    if current_user.is_authenticated and request.endpoint and request.blueprint != 'api_leitura':
        area = area_do_endpoint(request.endpoint, request.blueprint)
        if area and not current_user.pode(area):
            destino = primeira_rota(current_user)
            if destino is None:
                return render_template('sem_permissao.html', mensagem=MSG_REPASSE_OCULTO if current_user.repasse_oculto else None), 403
            flash(MSG_REPASSE_OCULTO if current_user.repasse_oculto and area in AREAS_DO_REPASSE else 'Você não tem permissão para acessar essa área.', 'warning')
            return redirect(url_for(destino))


_recorrentes_em = None


@app.before_request
def lancar_recorrentes_do_dia():
    """Uma vez por dia (por processo), cria as despesas recorrentes que faltam, para o DRE/dashboard
    não dependerem de alguém abrir a lista de lançamentos."""
    global _recorrentes_em
    if _recorrentes_em == date.today() or not current_user.is_authenticated:
        return
    _recorrentes_em = date.today()
    try:
        from servicos_financeiros import gerar_recorrentes
        gerar_recorrentes()
    except Exception as e:  # nunca derruba a página
        db.session.rollback()
        print('gerar_recorrentes ignorado:', e)


@app.errorhandler(Exception)
def erro_inesperado(e):
    """Rede de segurança: valor inválido num formulário (texto onde era número, data impossível...) não derruba a
    página com erro 500. Desfaz a transação, registra no log e volta ao formulário com um aviso. Erros em
    consultas (GET) continuam aparecendo como erro, para não esconder defeitos."""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    db.session.rollback()
    app.logger.exception('Erro inesperado em %s %s', request.method, request.path)
    if request.method == 'POST' and not request.path.startswith('/api/'):
        flash('Não foi possível concluir. Confira os dados informados e tente de novo.', 'danger')
        return redirect(request.referrer or url_for('dashboard'))
    raise e


@app.errorhandler(400)
def campo_faltando(e):
    """Formulário enviado sem um campo obrigatório: volta à página anterior com aviso, em vez da tela 'Bad Request'."""
    if request.path.startswith('/api/'):
        return e
    flash('Faltou preencher algum campo obrigatório. Confira o formulário e tente de novo.', 'danger')
    return redirect(request.referrer or url_for('dashboard'))


@app.after_request
def cabecalhos_de_seguranca(resp):
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    resp.headers.setdefault('Referrer-Policy', 'same-origin')
    return resp


@app.route('/deploy-webhook', methods=['POST'])
def deploy_webhook():
    """Disparado pelo GitHub a cada push. Valida a assinatura HMAC e roda deploy.sh."""
    if not DEPLOY_WEBHOOK_SECRET:
        return 'Webhook não configurado', 503

    signature = request.headers.get('X-Hub-Signature-256', '')
    esperado = 'sha256=' + hmac.new(
        DEPLOY_WEBHOOK_SECRET.encode(), request.data, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(esperado, signature):
        return 'Assinatura inválida', 403

    payload = request.get_json(silent=True) or {}
    if payload.get('ref') != 'refs/heads/main':
        return 'Ignorado (não é a branch main)', 200

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deploy.sh')
    try:
        resultado = subprocess.run(
            ['bash', script], capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        return 'Deploy excedeu o tempo limite', 500
    except OSError as e:
        return f'Erro ao executar deploy.sh: {e}', 500

    if resultado.returncode != 0:
        return f'Deploy falhou:\n{resultado.stdout}\n{resultado.stderr}', 500

    return 'Deploy concluído', 200


@app.route('/api/clientes', methods=['GET'])
def api_clientes():
    """Relatório somente-leitura de clientes, protegido por chave de API.
    Não expõe arquivos, consoles nem configurações — só estes campos."""
    chave = request.headers.get('X-API-Key', '')
    if not REPORT_API_KEY or not hmac.compare_digest(chave, REPORT_API_KEY):
        return jsonify({'erro': 'não autorizado'}), 403

    clientes = Cliente.query.order_by(Cliente.nome).all()
    return jsonify([{
        'nome': c.nome,
        'cpf': c.cpf,
        'id': c.id,
        'data_parto': c.data_parto.isoformat() if c.data_parto else None,
        'tipo_parto': c.tipo_parto,
        'contrato_status': c.contrato_status,
        'data_prevista_parto': c.data_prevista_parto.isoformat() if c.data_prevista_parto else None,
        'ano_referencia': c.ano_referencia,
        'status': c.status,
    } for c in clientes])


@app.route('/api/lancamentos', methods=['GET'])
def api_lancamentos():
    """Relatório somente-leitura de lançamentos (receitas de contrato),
    protegido por chave de API. Usado para conferir valores com relatórios
    externos — não expõe arquivos, consoles nem configurações."""
    chave = request.headers.get('X-API-Key', '')
    if not REPORT_API_KEY or not hmac.compare_digest(chave, REPORT_API_KEY):
        return jsonify({'erro': 'não autorizado'}), 403

    lancs = (Lancamento.query
             .filter(Lancamento.tipo == 'receita')
             .filter(Lancamento.atendimento_id.is_(None))
             .order_by(Lancamento.data_pagamento)
             .all())
    return jsonify([{
        'id': l.id,
        'data_vencimento': l.data_vencimento.isoformat() if l.data_vencimento else None,
        'taxa_operadora_pct': l.taxa_operadora_pct,
        'taxa_operadora_valor': l.taxa_operadora_valor,
        'cliente_nome': l.cliente.nome if l.cliente else None,
        'descricao': l.descricao,
        'valor': l.valor,
        'valor_liquido': l.valor_liquido,
        'status': l.status,
        'forma_pagamento': l.forma_pagamento,
        'operadora': l.operadora,
        'parcelas': l.parcelas,
        'data_competencia': l.data_competencia.isoformat() if l.data_competencia else None,
        'data_pagamento': l.data_pagamento.isoformat() if l.data_pagamento else None,
    } for l in lancs])


@app.route('/')
def dashboard():
    hoje = date.today()
    inicio_mes = date(hoje.year, hoje.month, 1)

    total_clientes_ativos = Cliente.query.filter_by(status='ativa').count()
    total_clientes_pos_parto = Cliente.query.filter_by(status='pos_parto').count()

    atendimentos_mes = Atendimento.query.filter(
        Atendimento.data_atendimento >= inicio_mes,
        Atendimento.data_atendimento <= hoje,
        Atendimento.status == 'realizado'
    ).count()

    atendimentos_agendados = Atendimento.query.filter(
        Atendimento.data_atendimento >= hoje,
        Atendimento.status == 'agendado'
    ).count()

    # Regime de Caixa — mês atual
    receitas_caixa = db.session.query(func.sum(Lancamento.valor)).filter(
        Lancamento.tipo == 'receita',
        Lancamento.status == 'recebido',
        Lancamento.data_pagamento >= inicio_mes,
        Lancamento.data_pagamento <= hoje
    ).scalar() or 0.0

    despesas_caixa = db.session.query(func.sum(Lancamento.valor)).filter(
        Lancamento.tipo == 'despesa',
        Lancamento.status == 'pago',
        Lancamento.data_pagamento >= inicio_mes,
        Lancamento.data_pagamento <= hoje
    ).scalar() or 0.0

    # Regime de Competência — mês atual
    receitas_competencia = db.session.query(func.sum(Lancamento.valor)).filter(
        Lancamento.tipo == 'receita',
        Lancamento.status != 'cancelado',
        Lancamento.data_competencia >= inicio_mes,
        Lancamento.data_competencia <= hoje
    ).scalar() or 0.0

    despesas_competencia = db.session.query(func.sum(Lancamento.valor)).filter(
        Lancamento.tipo == 'despesa',
        Lancamento.status != 'cancelado',
        Lancamento.data_competencia >= inicio_mes,
        Lancamento.data_competencia <= hoje
    ).scalar() or 0.0

    contas_vencidas = Lancamento.query.filter(
        Lancamento.tipo == 'receita',
        Lancamento.status == 'pendente',
        Lancamento.data_vencimento < hoje
    ).count()

    a_pagar_vencidas = Lancamento.query.filter(
        Lancamento.tipo == 'despesa',
        Lancamento.status == 'pendente',
        Lancamento.data_vencimento < hoje
    ).count()

    # todos os agendados (os de data já passada aparecem como "confirmar ou remarcar")
    proximos_atendimentos = Atendimento.query.filter(
        Atendimento.status == 'agendado'
    ).order_by(Atendimento.data_atendimento, Atendimento.hora_atendimento).limit(15).all()

    # DPP ascendente = mais semanas primeiro (DPP mais próximo = gestação mais avançada)
    proximos_partos = Cliente.query.filter(
        Cliente.status == 'ativa',
        Cliente.data_prevista_parto.isnot(None)
    ).order_by(Cliente.data_prevista_parto).limit(5).all()

    gestantes_raw = Cliente.query.filter_by(status='ativa').order_by(
        Cliente.data_prevista_parto.asc().nullslast()
    ).all()

    # Para cada gestante busca as 2 primeiras consultas realizadas
    gestantes = []
    for g in gestantes_raw:
        atends = (Atendimento.query
                  .filter(Atendimento.cliente_id == g.id,
                          Atendimento.status.in_(['realizado', 'agendado']))
                  .order_by(Atendimento.data_atendimento).all())
        feitas = [a for a in atends if a.status == 'realizado']
        agendada = next((a for a in atends if a.status == 'agendado'), None)   # só entra no quadro depois de confirmada
        gestantes.append({
            'cliente': g,
            'c1': feitas[0] if len(feitas) > 0 else None,
            'c2': feitas[1] if len(feitas) > 1 else None,
            'ag1': agendada if not feitas else None,
            'ag2': agendada if len(feitas) == 1 else None,
        })

    materiais_baixo_estoque = Material.query.filter(
        Material.quantidade_atual <= Material.quantidade_minima,
        Material.ativo == True
    ).count()

    from servicos_financeiros import partos_sem_pagamento
    sem_pag = partos_sem_pagamento(hoje)
    from servicos_financeiros import gestantes_36_sem_pagamento
    alerta_36 = gestantes_36_sem_pagamento(hoje)

    return render_template('dashboard.html',
        hoje=hoje,
        alerta_36=alerta_36, alerta_36_ids={c.id: v for c, v in alerta_36},
        notas_func=resumo_pendentes() if current_user.pode('notas_funcionarias') else None,
        partos_sem_pagamento_qtd=len(sem_pag), partos_sem_pagamento_valor=sum(sem_pag.values()),
        total_clientes_ativos=total_clientes_ativos,
        total_clientes_pos_parto=total_clientes_pos_parto,
        atendimentos_mes=atendimentos_mes,
        atendimentos_agendados=atendimentos_agendados,
        receitas_caixa=receitas_caixa,
        despesas_caixa=despesas_caixa,
        resultado_caixa=receitas_caixa - despesas_caixa,
        receitas_competencia=receitas_competencia,
        despesas_competencia=despesas_competencia,
        resultado_competencia=receitas_competencia - despesas_competencia,
        contas_vencidas=contas_vencidas,
        a_pagar_vencidas=a_pagar_vencidas,
        proximos_atendimentos=proximos_atendimentos,
        proximos_partos=proximos_partos,
        materiais_baixo_estoque=materiais_baixo_estoque,
        gestantes=gestantes,
    )


def seed_dados_iniciais():
    if CentroCusto.query.count() > 0:
        return

    centros = [
        CentroCusto(codigo='CC001', nome='Consultas e Acompanhamento', tipo='receita',
                    descricao='Receitas de consultas pré-natais e acompanhamento'),
        CentroCusto(codigo='CC002', nome='Procedimentos Obstétricos', tipo='receita',
                    descricao='Receitas de procedimentos e partos'),
        CentroCusto(codigo='CC003', nome='Exames e Laudos', tipo='receita',
                    descricao='Receitas de exames e emissão de laudos'),
        CentroCusto(codigo='CC004', nome='Materiais Clínicos', tipo='despesa',
                    descricao='Despesas com materiais e insumos clínicos'),
        CentroCusto(codigo='CC005', nome='Despesas Administrativas', tipo='despesa',
                    descricao='Despesas gerais administrativas'),
        CentroCusto(codigo='CC006', nome='Recursos Humanos', tipo='despesa',
                    descricao='Despesas com pessoal e encargos'),
        CentroCusto(codigo='CC007', nome='Infraestrutura', tipo='despesa',
                    descricao='Aluguel, energia, manutenção'),
    ]
    for c in centros:
        db.session.add(c)
    db.session.commit()

    cc_consulta = CentroCusto.query.filter_by(codigo='CC001').first()
    cc_proc = CentroCusto.query.filter_by(codigo='CC002').first()
    cc_exame = CentroCusto.query.filter_by(codigo='CC003').first()

    procedimentos = [
        Procedimento(codigo='P001', nome='Consulta Pré-Natal', categoria='consulta',
                     valor_padrao=250.0, centro_custo_id=cc_consulta.id),
        Procedimento(codigo='P002', nome='Consulta de Retorno', categoria='consulta',
                     valor_padrao=180.0, centro_custo_id=cc_consulta.id),
        Procedimento(codigo='P003', nome='Acompanhamento de Parto Normal', categoria='parto',
                     valor_padrao=2500.0, centro_custo_id=cc_proc.id),
        Procedimento(codigo='P004', nome='Acompanhamento de Parto Cesáreo', categoria='parto',
                     valor_padrao=3500.0, centro_custo_id=cc_proc.id),
        Procedimento(codigo='P005', nome='Ultrassonografia Obstétrica', categoria='exame',
                     valor_padrao=350.0, centro_custo_id=cc_exame.id),
        Procedimento(codigo='P006', nome='Cardiotocografia', categoria='exame',
                     valor_padrao=150.0, centro_custo_id=cc_exame.id),
        Procedimento(codigo='P007', nome='Plano Maternidade Completo', categoria='procedimento',
                     valor_padrao=5000.0, centro_custo_id=cc_proc.id),
    ]
    for p in procedimentos:
        db.session.add(p)

    cc_mat = CentroCusto.query.filter_by(codigo='CC004').first()
    materiais = [
        Material(codigo='M001', nome='Luvas Cirúrgicas (cx 100un)', unidade_medida='cx',
                 valor_unitario=45.0, quantidade_atual=20, quantidade_minima=5,
                 centro_custo_id=cc_mat.id),
        Material(codigo='M002', nome='Gel para Ultrassom (500ml)', unidade_medida='un',
                 valor_unitario=28.0, quantidade_atual=8, quantidade_minima=3,
                 centro_custo_id=cc_mat.id),
        Material(codigo='M003', nome='Álcool 70% (1L)', unidade_medida='un',
                 valor_unitario=12.0, quantidade_atual=15, quantidade_minima=5,
                 centro_custo_id=cc_mat.id),
        Material(codigo='M004', nome='Máscaras Cirúrgicas (cx 50un)', unidade_medida='cx',
                 valor_unitario=35.0, quantidade_atual=10, quantidade_minima=3,
                 centro_custo_id=cc_mat.id),
    ]
    for m in materiais:
        db.session.add(m)

    db.session.commit()


def seed_planos():
    if Plano.query.count() > 0:
        return

    SERVICOS_PADRAO = [
        ('Consulta de pré-natal',    2, 'Acompanhamento gestacional'),
        ('Assistência ao parto',     1, None),
        ('Consulta pós-parto',       1, None),
    ]

    planos_data = [   # exemplos: edite ou desative em Planos de Contrato
        {'nome': 'Plano Essencial', 'descricao': 'Acompanhamento básico (exemplo).', 'valor': 3000.00, 'parcelas_sem_taxa': 3},
        {'nome': 'Plano Completo', 'descricao': 'Acompanhamento completo (exemplo).', 'valor': 3500.00, 'parcelas_sem_taxa': 3},
        {'nome': 'Plano Parceiros', 'descricao': 'Condição para médicos parceiros (exemplo).', 'valor': 3250.00, 'parcelas_sem_taxa': 1},
    ]

    for pd in planos_data:
        plano = Plano(**pd)
        db.session.add(plano)
        db.session.flush()
        for ordem, (srv, qtd, desc) in enumerate(SERVICOS_PADRAO):
            db.session.add(ItemPlano(
                plano_id=plano.id,
                servico=srv,
                quantidade=qtd,
                descricao=desc,
                ordem=ordem,
            ))
    db.session.commit()


def seed_funcionarios():
    """Sem prestadoras de exemplo: cadastre as suas em Folha de Pagamento > Prestadores de serviço."""
    return


def seed_usuario():
    """Cria os usuários iniciais só se não existirem. A senha vem de SENHA_INICIAL (ambiente);
    sem ela, é gerada uma senha aleatória e mostrada UMA vez no console."""
    import secrets
    from marca import MARCA
    usuarios_padrao = [{'nome': 'Administrador', 'email': MARCA['email_admin']}]
    criados = 0
    for u_data in usuarios_padrao:
        if not Usuario.query.filter_by(email=u_data['email']).first():
            senha = os.environ.get('SENHA_INICIAL') or secrets.token_urlsafe(9)
            u = Usuario(nome=u_data['nome'], email=u_data['email'], perfil='admin')
            u.set_senha(senha)
            db.session.add(u)
            criados += 1
            if not os.environ.get('SENHA_INICIAL'):
                print(f"[seed_usuario] senha inicial de {u_data['email']}: {senha} (troque em Alterar senha)")
    if criados:
        db.session.commit()


def seed_formas():
    from servicos_financeiros import seed_formas_pagamento
    try:
        seed_formas_pagamento()
    except Exception as e:  # ex.: coluna nova ainda sem migração — não derruba o site
        db.session.rollback()
        print('seed_formas_pagamento ignorado:', e)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_formas()
        seed_dados_iniciais()
        seed_planos()
        seed_funcionarios()
        seed_usuario()
    # modo de depuração só com FLASK_DEBUG=1 (nunca em produção); HOST=0.0.0.0 libera o acesso pela rede
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1', host=os.environ.get('HOST', '127.0.0.1'),
            port=int(os.environ.get('PORT', 5000)), use_reloader=False)
