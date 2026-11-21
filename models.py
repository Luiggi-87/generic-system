from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
from taxas import operadora_padrao
from permissoes import AREAS_DO_REPASSE, OCULTAR_REPASSE_DAS_PRESTADORAS

db = SQLAlchemy()

_schema_pronto = set()


def schema_pronto(tabela, coluna=None):
    """True se a tabela (e coluna) já existe no banco. Consulta o esquema por outra conexão,
    sem tocar na sessão atual; depois de confirmado, não consulta mais."""
    chave = (tabela, coluna)
    if chave in _schema_pronto:
        return True
    try:
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        ok = insp.has_table(tabela) and (
            coluna is None or coluna in {c['name'] for c in insp.get_columns(tabela)})
    except Exception:
        ok = False
    if ok:
        _schema_pronto.add(chave)
    return ok


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id          = db.Column(db.Integer, primary_key=True)
    nome        = db.Column(db.String(100), nullable=False)
    email       = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash  = db.Column(db.String(256), nullable=False)
    ativo       = db.Column(db.Boolean, default=True)
    # 'admin' = acessa tudo; 'funcionario' = só as áreas em `permissoes` (permissoes.py). Linhas antigas = admin.
    perfil      = db.Column(db.String(20), default='funcionario')
    permissoes  = db.Column(db.Text, default='')   # áreas liberadas, separadas por vírgula
    funcionario_id = db.Column(db.Integer, db.ForeignKey('funcionarios.id'), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    funcionario = db.relationship('Funcionario', foreign_keys=[funcionario_id])

    @property
    def eh_admin(self):
        return (self.perfil or 'admin') == 'admin'

    @property
    def areas(self):
        return {a for a in (self.permissoes or '').split(',') if a}

    @property
    def repasse_oculto(self):
        """Prestadora de serviço (vinculada, sem perfil de administradora) com o repasse temporariamente oculto (permissoes.py)."""
        return OCULTAR_REPASSE_DAS_PRESTADORAS and not self.eh_admin and bool(self.funcionario_id)

    def pode(self, area):
        """Admin acessa tudo; a área 'usuarios' é só do admin."""
        if self.repasse_oculto and area in AREAS_DO_REPASSE:
            return False
        if area == 'notas_funcionarias':   # todas as notas das prestadoras de serviço: só a administradora
            return self.eh_admin
        if area == 'minhas_notas':   # nunca para a administradora; precisa estar vinculada a uma prestadora de serviço
            return (not self.eh_admin) and bool(self.funcionario_id) and (self.perfil == 'funcionario' or area in self.areas)
        return self.eh_admin or (area != 'usuarios' and area in self.areas)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)


class FormaPagamento(db.Model):
    """Formas de pagamento oferecidas nos formulários. Bloquear = ativo False (histórico preservado)."""
    __tablename__ = 'formas_pagamento'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    padrao = db.Column(db.Boolean, default=False, nullable=False)  # cadastradas pelo sistema
    prazo = db.Column(db.String(200))        # prazo de recebimento, texto livre (ex.: "D+1", "30 dias")
    observacoes = db.Column(db.Text)         # condições, regras, contrato com a operadora…
    # como a taxa é calculada: 'nenhuma', 'debito' (tabela de débito) ou 'credito' (tabela por parcela)
    tipo_taxa = db.Column(db.String(10), default='nenhuma')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Operadora(db.Model):
    """Maquininha / operadora de cartão (inclui link de pagamento). Bloquear = ativo False."""
    __tablename__ = 'operadoras'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TaxaOperadora(db.Model):
    """Taxa de cartão por operadora/modalidade/parcelas (editável pela cliente)."""
    __tablename__ = 'taxas_operadora'
    __table_args__ = (db.UniqueConstraint('operadora', 'modalidade', 'parcelas'),)
    id = db.Column(db.Integer, primary_key=True)
    operadora = db.Column(db.String(50), nullable=False)    # 'tom', 'infinite'
    modalidade = db.Column(db.String(20), nullable=False)   # 'debito', 'credito'
    parcelas = db.Column(db.Integer, nullable=False, default=1)
    taxa_pct = db.Column(db.Float, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CentroCusto(db.Model):
    __tablename__ = 'centros_custo'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True, nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(20), nullable=False, default='ambos')  # 'receita', 'despesa', 'ambos'
    descricao = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lancamentos = db.relationship('Lancamento', backref='centro_custo', lazy=True)
    procedimentos = db.relationship('Procedimento', backref='centro_custo', lazy=True)
    materiais = db.relationship('Material', backref='centro_custo', lazy=True)


class Plano(db.Model):
    __tablename__ = 'planos'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    descricao = db.Column(db.Text)
    valor = db.Column(db.Float, nullable=False, default=0.0)
    parcelas_sem_taxa = db.Column(db.Integer, default=3)  # parcelamento sem taxa adicional
    ativo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    itens = db.relationship('ItemPlano', backref='plano', lazy=True,
                             cascade='all, delete-orphan',
                             order_by='ItemPlano.ordem')

    @property
    def total_clientes(self):
        return Cliente.query.filter_by(plano_id=self.id).count()


class ItemPlano(db.Model):
    __tablename__ = 'itens_plano'
    id = db.Column(db.Integer, primary_key=True)
    plano_id = db.Column(db.Integer, db.ForeignKey('planos.id'), nullable=False)
    servico = db.Column(db.String(150), nullable=False)
    quantidade = db.Column(db.Integer, default=1)
    descricao = db.Column(db.Text)
    ordem = db.Column(db.Integer, default=0)


class Cliente(db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    cpf = db.Column(db.String(14), unique=True)
    data_nascimento = db.Column(db.Date)
    telefone = db.Column(db.String(20))
    celular = db.Column(db.String(20))
    email = db.Column(db.String(120))
    endereco = db.Column(db.String(200))
    cidade = db.Column(db.String(100))
    estado = db.Column(db.String(2))
    cep = db.Column(db.String(10))
    data_inicio_acompanhamento = db.Column(db.Date)
    data_ultima_menstruacao = db.Column(db.Date)
    data_prevista_parto = db.Column(db.Date)
    data_parto = db.Column(db.Date)
    plano_saude = db.Column(db.String(100))
    numero_carteirinha = db.Column(db.String(50))
    status = db.Column(db.String(20), default='ativa')  # 'ativa', 'pos_parto', 'inativa'
    observacoes = db.Column(db.Text)
    # Campos de contrato / parto
    medico_grupo = db.Column(db.String(150))   # rótulo na tela: Médico pré-natalista
    grupo_parto = db.Column(db.String(150))    # Grupo de parto / plantão
    hospital_parto = db.Column(db.String(150))
    nome_bebe = db.Column(db.String(100))
    tipo_parto = db.Column(db.String(20))   # 'parto_normal', 'parto_cesario'
    contrato_status = db.Column(db.String(50))  # 'ASSINADO', 'ENVIADO', etc.
    ano_referencia = db.Column(db.Integer)   # 2022, 2025, 2026 …
    plano_id = db.Column(db.Integer, db.ForeignKey('planos.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    atendimentos = db.relationship('Atendimento', backref='cliente', lazy=True)
    lancamentos = db.relationship('Lancamento', backref='cliente', lazy=True)

    @property
    def total_vencido(self):
        """Soma de receitas pendentes com vencimento já passado (inadimplência)."""
        hoje = date.today()
        return sum(
            l.valor for l in self.lancamentos
            if l.tipo == 'receita'
            and l.status == 'pendente'
            and l.data_vencimento
            and l.data_vencimento < hoje
        )

    @property
    def semanas_gestacao(self):
        """Semanas de gestação calculadas a partir do DPP.
        DPP = DUM + 280 dias (40 semanas), portanto:
          semanas = 40 + (referência − DPP) / 7
        Se já houve parto, congela na data do parto.
        """
        if not self.data_prevista_parto:
            return None
        referencia = self.data_parto if self.data_parto else date.today()
        delta = referencia - self.data_prevista_parto
        return 40 + delta.days // 7

    @property
    def semanas_dias_gestacao(self):
        """Retorna semanas e dias no formato: '38s 2d'"""
        if not self.data_prevista_parto:
            return None
        referencia = self.data_parto if self.data_parto else date.today()
        delta = referencia - self.data_prevista_parto
        total_semanas = 40 + delta.days // 7
        dias_restantes = delta.days % 7
        return f"{total_semanas}s {dias_restantes}d"


class Procedimento(db.Model):
    __tablename__ = 'procedimentos'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True)
    nome = db.Column(db.String(150), nullable=False)
    categoria = db.Column(db.String(50), default='consulta')  # 'consulta', 'exame', 'procedimento', 'parto', 'outros'
    descricao = db.Column(db.Text)
    valor_padrao = db.Column(db.Float, nullable=False, default=0.0)
    centro_custo_id = db.Column(db.Integer, db.ForeignKey('centros_custo.id'))
    ativo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    itens_atendimento = db.relationship('ItemAtendimento', backref='procedimento', lazy=True)


class Material(db.Model):
    __tablename__ = 'materiais'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True)
    nome = db.Column(db.String(150), nullable=False)
    descricao = db.Column(db.Text)
    unidade_medida = db.Column(db.String(20), default='un')
    valor_unitario = db.Column(db.Float, default=0.0)
    quantidade_atual = db.Column(db.Float, default=0.0)
    quantidade_minima = db.Column(db.Float, default=0.0)
    centro_custo_id = db.Column(db.Integer, db.ForeignKey('centros_custo.id'))
    ativo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    movimentos = db.relationship('MovimentoEstoque', backref='material', lazy=True)

    @property
    def estoque_baixo(self):
        return self.quantidade_atual <= self.quantidade_minima


class MovimentoEstoque(db.Model):
    __tablename__ = 'movimentos_estoque'
    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey('materiais.id'), nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # 'entrada', 'saida'
    quantidade = db.Column(db.Float, nullable=False)
    valor_unitario = db.Column(db.Float, default=0.0)
    valor_total = db.Column(db.Float, default=0.0)
    motivo = db.Column(db.String(100))
    data = db.Column(db.Date, default=date.today)
    observacoes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Atendimento(db.Model):
    __tablename__ = 'atendimentos'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    data_atendimento = db.Column(db.Date, nullable=False)
    hora_atendimento = db.Column(db.String(5))
    tipo = db.Column(db.String(50), default='consulta')
    profissional = db.Column(db.String(100))   # Enfermeira/EO que realizou
    observacoes = db.Column(db.Text)
    status = db.Column(db.String(20), default='agendado')  # 'agendado', 'realizado', 'cancelado'
    valor_total = db.Column(db.Float, default=0.0)
    # None = o valor entra no rateio da folha; senão, é direcionado só a esta prestadora de serviço
    funcionario_id = db.Column(db.Integer, db.ForeignKey('funcionarios.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    funcionario = db.relationship('Funcionario', foreign_keys=[funcionario_id])
    itens = db.relationship('ItemAtendimento', backref='atendimento', lazy=True, cascade='all, delete-orphan')
    lancamentos = db.relationship('Lancamento', backref='atendimento', lazy=True)


class ItemAtendimento(db.Model):
    __tablename__ = 'itens_atendimento'
    id = db.Column(db.Integer, primary_key=True)
    atendimento_id = db.Column(db.Integer, db.ForeignKey('atendimentos.id'), nullable=False)
    procedimento_id = db.Column(db.Integer, db.ForeignKey('procedimentos.id'), nullable=False)
    quantidade = db.Column(db.Float, default=1.0)
    valor_unitario = db.Column(db.Float, nullable=False)
    valor_total = db.Column(db.Float, nullable=False)
    observacoes = db.Column(db.Text)


class Funcionario(db.Model):
    __tablename__ = 'funcionarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    cpf = db.Column(db.String(14))
    cargo = db.Column(db.String(100))
    taxa_desconto = db.Column(db.Float, default=0.15)  # ex: 0.15 = 15%
    ativo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    escalas = db.relationship('EscalaFolha', backref='funcionario', lazy=True)


class PeriodoFolha(db.Model):
    __tablename__ = 'periodos_folha'
    id = db.Column(db.Integer, primary_key=True)
    mes = db.Column(db.Integer, nullable=False)   # 1-12
    ano = db.Column(db.Integer, nullable=False)
    total_dias = db.Column(db.Integer, default=30)
    horas_diurnas = db.Column(db.Float, default=0.0)   # total diurnas do período
    horas_noturnas = db.Column(db.Float, default=0.0)  # total noturnas do período
    horas_extra = db.Column(db.Float, default=0.0)     # total extras do período
    status = db.Column(db.String(20), default='aberto')  # 'aberto', 'fechado'
    custos_rateados = db.Column(db.Float)   # despesas do mês rateadas entre as prestadoras, gravadas no fechamento (None = desconto em %)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    receitas = db.relationship('ReceitaFolha', backref='periodo', lazy=True,
                                cascade='all, delete-orphan')
    escalas = db.relationship('EscalaFolha', backref='periodo', lazy=True,
                               cascade='all, delete-orphan')

    @property
    def mes_nome(self):
        meses = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
        return meses[self.mes - 1]

    @property
    def titulo(self):
        return f"{self.mes_nome}/{self.ano}"


class ReceitaFolha(db.Model):
    __tablename__ = 'receitas_folha'
    id = db.Column(db.Integer, primary_key=True)
    periodo_id = db.Column(db.Integer, db.ForeignKey('periodos_folha.id'), nullable=False)
    data = db.Column(db.Date)
    cliente_nome = db.Column(db.String(150), default='')
    parto = db.Column(db.Float, default=0.0)
    aeo = db.Column(db.Float, default=0.0)
    amamentacao = db.Column(db.Float, default=0.0)
    laser = db.Column(db.Float, default=0.0)
    curso = db.Column(db.Float, default=0.0)
    brinco = db.Column(db.Float, default=0.0)
    funcionario_id = db.Column(db.Integer, db.ForeignKey('funcionarios.id'), nullable=True)
    atendimento_id = db.Column(db.Integer, db.ForeignKey('atendimentos.id'), nullable=True)  # receita vinda de um atendimento
    detalhes_pagamentos = db.Column(db.Text, default='')  # JSON: [{"data": "YYYY-MM-DD", "valor": 0.0}, ...]

    funcionario = db.relationship('Funcionario', foreign_keys=[funcionario_id])

    @property
    def total(self):
        return (self.parto or 0) + (self.aeo or 0) + (self.amamentacao or 0) + (self.laser or 0) + (self.curso or 0) + (self.brinco or 0)

    @property
    def detalhes_list(self):
        import json
        try:
            return json.loads(self.detalhes_pagamentos) if self.detalhes_pagamentos else []
        except (ValueError, TypeError):
            return []


class EscalaFolha(db.Model):
    __tablename__ = 'escalas_folha'
    id = db.Column(db.Integer, primary_key=True)
    periodo_id = db.Column(db.Integer, db.ForeignKey('periodos_folha.id'), nullable=False)
    funcionario_id = db.Column(db.Integer, db.ForeignKey('funcionarios.id'), nullable=False)
    horas_diurnas = db.Column(db.Float, default=0.0)
    horas_noturnas = db.Column(db.Float, default=0.0)
    horas_extra = db.Column(db.Float, default=0.0)           # extras diurnas
    horas_extra_noturnas = db.Column(db.Float, default=0.0)  # extras noturnas
    taxa_desconto = db.Column(db.Float)  # None = usa funcionario.taxa_desconto


class NotaFiscal(db.Model):
    __tablename__ = 'notas_fiscais'
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(50), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    valor_bruto = db.Column(db.Float, nullable=False)
    valor_liquido = db.Column(db.Float, nullable=False)
    aliquota_iss = db.Column(db.Float, default=0.06)
    valor_iss = db.Column(db.Float, nullable=False)
    data_emissao = db.Column(db.Date, nullable=False)
    competencia_mes = db.Column(db.Integer, nullable=False)
    competencia_ano = db.Column(db.Integer, nullable=False)
    lancamento_iss_id = db.Column(db.Integer, db.ForeignKey('lancamentos.id'), nullable=True)
    chave_acesso = db.Column(db.String(60), nullable=True)  # NFS-e nacional: chave de 50 dígitos (evita importar duas vezes)
    status = db.Column(db.String(20), default='emitida')  # 'emitida', 'anulada'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cliente = db.relationship('Cliente', backref='notas_fiscais')
    lancamento_iss = db.relationship('Lancamento', foreign_keys=[lancamento_iss_id])

    @property
    def sistema_emissao(self):
        """Até 31/12/2025 a nota saiu no sistema municipal; de 2026 em diante, no sistema nacional (governo federal).
        As duas numerações se repetem, então o número só identifica a nota junto com o sistema."""
        return 'Municipal' if self.data_emissao and self.data_emissao.year < 2026 else 'Nacional'

    @property
    def status_iss(self):
        if self.status == 'anulada':
            return 'anulada'
        if not self.lancamento_iss_id:
            # o ISS é pago no mês seguinte ao da nota; o histórico de 2025 não tem despesas no sistema (o caixa começa em 2026)
            return 'pago' if self.data_emissao and self.data_emissao.year < 2026 else 'nao_lancado'
        if self.lancamento_iss.status == 'pago':
            return 'pago'
        return 'a_pagar'

    @property
    def competencia_label(self):
        meses = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
                 'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
        return f"{meses[self.competencia_mes - 1]}/{self.competencia_ano}"


class ContaBancaria(db.Model):
    """Conta bancária da empresa (só o nome, por enquanto): cada saldo registrado pertence a uma conta."""
    __tablename__ = 'contas_bancarias'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SaldoBancario(db.Model):
    """Saldo real da conta bancária numa data (conferência com o extrato), para comparar com o saldo em caixa do sistema."""
    __tablename__ = 'saldos_bancarios'
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, nullable=False)
    saldo = db.Column(db.Float, nullable=False)
    conta_id = db.Column(db.Integer, db.ForeignKey('contas_bancarias.id'), nullable=True)
    observacao = db.Column(db.Text)
    registrado_por = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DecisaoDuplicidade(db.Model):
    """Decisão da administração sobre um grupo de notas apontado como possível duplicidade (chave = ids das notas do grupo).
    'ok' = não é duplicidade (com o motivo); 'duplicada' = é duplicidade, a nota `nota_id` é a repetida (a tratar)."""
    __tablename__ = 'decisoes_duplicidade'
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(200), unique=True, nullable=False)
    decisao = db.Column(db.String(20), nullable=False)   # 'ok' ou 'duplicada'
    motivo = db.Column(db.String(120))
    nota_id = db.Column(db.Integer, db.ForeignKey('notas_fiscais.id'), nullable=True)
    observacao = db.Column(db.Text)
    decidido_por = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    nota = db.relationship('NotaFiscal', foreign_keys=[nota_id])


class NotaFuncionaria(db.Model):
    """Nota fiscal que a prestadora de serviço (prestadora) emite para a empresa para receber o repasse do mês.
    A conferência (valor da nota x repasse) é calculada na hora; só o pagamento fica gravado."""
    __tablename__ = 'notas_funcionarias'
    id = db.Column(db.Integer, primary_key=True)
    funcionario_id = db.Column(db.Integer, db.ForeignKey('funcionarios.id'), nullable=False)
    mes = db.Column(db.Integer, nullable=False)    # mês do repasse a que a nota se refere
    ano = db.Column(db.Integer, nullable=False)
    numero = db.Column(db.String(50), nullable=False)
    data_emissao = db.Column(db.Date)
    valor = db.Column(db.Float, nullable=False)            # valor do serviço na nota
    valor_liquido = db.Column(db.Float)                    # valor líquido na nota, se informado
    chave_acesso = db.Column(db.String(60))
    prestador_nome = db.Column(db.String(150))
    tomador_nome = db.Column(db.String(150))
    xml = db.Column(db.Text)
    enviada_em = db.Column(db.DateTime, default=datetime.utcnow)
    enviada_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    pago_em = db.Column(db.Date)                           # preenchido quando a empresa paga a prestadora de serviço

    funcionario = db.relationship('Funcionario', foreign_keys=[funcionario_id])


class Lancamento(db.Model):
    __tablename__ = 'lancamentos'
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # 'receita', 'despesa'
    valor = db.Column(db.Float, nullable=False)
    data_competencia = db.Column(db.Date, nullable=False)
    data_vencimento = db.Column(db.Date)
    data_pagamento = db.Column(db.Date)
    status = db.Column(db.String(20), default='pendente')  # 'pendente', 'recebido', 'pago', 'cancelado'
    centro_custo_id = db.Column(db.Integer, db.ForeignKey('centros_custo.id'))
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'))
    atendimento_id = db.Column(db.Integer, db.ForeignKey('atendimentos.id'))
    forma_pagamento = db.Column(db.String(50))
    operadora = db.Column(db.String(50), default=lambda: operadora_padrao())  # 'tom', 'infinite' (para cartões)
    parcelas = db.Column(db.Integer, default=1)          # número de parcelas
    taxa_operadora_pct = db.Column(db.Float, default=0.0)  # % da taxa
    taxa_operadora_valor = db.Column(db.Float, default=0.0)  # R$ da taxa
    valor_liquido = db.Column(db.Float)                  # valor bruto - taxa (NULL = sem taxa)
    numero_documento = db.Column(db.String(50))
    observacoes = db.Column(db.Text)
    periodo_folha_id = db.Column(db.Integer, db.ForeignKey('periodos_folha.id'), nullable=True)
    # Despesa recorrente: o lançamento "modelo" tem recorrente=True e o dia do mês; os dos meses
    # seguintes são criados (pendentes) por servicos_financeiros.gerar_recorrentes e apontam ao modelo.
    recorrente = db.Column(db.Boolean, default=False)
    dia_recorrencia = db.Column(db.Integer)
    percentual_lucro = db.Column(db.Float)   # recorrente: valor = % do lucro bruto do mês (None = valor fixo)
    recorrencia_origem_id = db.Column(db.Integer, db.ForeignKey('lancamentos.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True)

    @property
    def bloqueado(self):
        """Lançamento gerado por folha fechada — não pode ser editado nem cancelado."""
        return self.periodo_folha_id is not None

    @property
    def valor_net(self):
        """Valor líquido efetivo. Usa valor_liquido quando há taxa, caso contrário valor bruto."""
        if self.valor_liquido is not None:
            return self.valor_liquido
        return self.valor

    @property
    def tem_taxa(self):
        return (self.taxa_operadora_pct or 0) > 0

    @property
    def vencido(self):
        if self.status == 'pendente' and self.data_vencimento:
            return self.data_vencimento < date.today()
        return False

    @property
    def status_label(self):
        labels = {
            'pendente': 'Pendente',
            'recebido': 'Recebido',
            'pago': 'Pago',
            'cancelado': 'Cancelado',
        }
        return labels.get(self.status, self.status)

    @property
    def status_class(self):
        classes = {
            'pendente': 'warning',
            'recebido': 'success',
            'pago': 'success',
            'cancelado': 'secondary',
        }
        return classes.get(self.status, 'secondary')
