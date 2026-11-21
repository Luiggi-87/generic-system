"""Áreas do sistema e permissões de acesso por usuário.

O administrador (perfil 'admin') acessa tudo, inclusive Usuários e Permissões. O perfil 'contabilidade' (contador)
acessa só as áreas de consulta marcadas (repasses e ISS), sem dados clínicos das clientes. O perfil 'funcionario' só
acessa as áreas marcadas pelo administrador. Cada rota pertence a uma área (area_do_endpoint)."""

# (chave, nome mostrado, descrição, rota inicial da área)
AREAS = [
    ('dashboard', 'Início (painel)', 'Painel com alertas, gestantes e próximos atendimentos', 'dashboard'),
    ('clientes', 'Clientes', 'Cadastro e ficha das clientes', 'clientes.index'),
    ('atendimentos', 'Atendimentos', 'Agenda e registro de atendimentos', 'atendimentos.index'),
    ('cadastros', 'Cadastros de apoio', 'Procedimentos, planos, materiais e centros de custo', 'procedimentos.index'),
    ('financeiro', 'Financeiro', 'Lançamentos, contas a pagar e a receber', 'financeiro.lancamentos'),
    ('notas_fiscais', 'Notas fiscais', 'Cadastrar, importar e dar baixa nas notas e no ISS', 'notas_fiscais.index'),
    ('iss', 'ISS do mês (consulta)', 'Notas emitidas no mês e ISS a recolher, só para consulta (guia da contabilidade)', 'iss_mensal.index'),
    ('relatorios', 'Relatórios financeiros', 'DRE, fluxo de caixa e caixa da empresa', 'relatorios.dre'),
    ('faturamento', 'Relatório de faturamento', 'Faturamento e repasse por prestadora de serviço', 'faturamento.index'),
    ('folha', 'Folha de pagamento', 'Escalas, receitas e pagamentos da folha', 'folha.index'),
    ('notas_funcionarias', 'Notas das prestadoras de serviço', 'Conferir as notas enviadas pelas prestadoras de serviço e registrar o pagamento', 'notas_func.index'),
    ('minhas_notas', 'Minhas notas fiscais', 'Enviar a própria nota fiscal do repasse e acompanhar o pagamento (precisa estar vinculada a uma prestadora de serviço; no perfil Prestadora de serviço já vem liberado)', 'notas_func.minhas'),
    ('gerencial', 'Gerência', 'Relatório gerencial, contratos × ISS e formas de pagamento', 'gerencial.index'),
]
CHAVES = [a[0] for a in AREAS]

# Perfis prontos (só preenchem as caixas na tela; o administrador pode ajustar)
# Áreas do perfil Contabilidade (somente consulta): repasses de todos (relatório de faturamento) e notas emitidas + ISS do mês
AREAS_CONTABILIDADE = ['faturamento', 'iss']

# Áreas já marcadas ao escolher o perfil Prestadora de serviço (o envio da própria nota fiscal é sempre liberado a ela)
AREAS_FUNCIONARIA = ['faturamento', 'minhas_notas']

# TEMPORÁRIO: enquanto a administradora ajusta a folha, as prestadoras de serviço (acesso vinculado a uma prestadora, sem perfil
# de administradora) não veem o repasse. Para voltar ao normal, basta trocar para False.
OCULTAR_REPASSE_DAS_PRESTADORAS = False
AREAS_DO_REPASSE = ('folha', 'faturamento')
MSG_REPASSE_OCULTO = 'O repasse está temporariamente indisponível enquanto a administração faz alguns ajustes. Em breve volta ao normal.'

PERFIS_PRONTOS = [
    ('Operacional', ['dashboard', 'clientes', 'atendimentos']),
    ('Financeiro', ['dashboard', 'clientes', 'atendimentos', 'financeiro', 'notas_fiscais', 'relatorios', 'faturamento']),
    ('Contabilidade', AREAS_CONTABILIDADE),
]

_BLUEPRINT_AREA = {
    'clientes': 'clientes', 'atendimentos': 'atendimentos',
    'procedimentos': 'cadastros', 'planos': 'cadastros', 'materiais': 'cadastros', 'centros_custo': 'cadastros',
    'notas_fiscais': 'notas_fiscais', 'iss_mensal': 'iss', 'relatorios': 'relatorios', 'faturamento': 'faturamento',
    'folha': 'folha', 'gerencial': 'gerencial', 'contratos_iss': 'gerencial', 'usuarios': 'usuarios',
}
# no blueprint financeiro, estas telas ficam na Gerência
_FINANCEIRO_GERENCIA = ('formas_pagamento', 'editar_forma_pagamento', 'nova_forma_pagamento', 'alternar_forma_pagamento',
                        'alternar_operadora', 'nova_operadora', 'salvar_taxas_operadora')


def area_do_endpoint(endpoint, blueprint):
    """Área de uma rota; None = livre para qualquer usuário logado (login, senha, arquivos estáticos...)."""
    if endpoint == 'dashboard':
        return 'dashboard'
    if blueprint == 'notas_func':
        nome = endpoint.split('.')[-1]
        if nome == 'baixar_xml':   # a própria rota confere (dona da nota ou quem confere as notas)
            return None
        return 'minhas_notas' if nome in ('minhas', 'enviar') else 'notas_funcionarias'
    if blueprint == 'financeiro':
        return 'gerencial' if endpoint.split('.')[-1] in _FINANCEIRO_GERENCIA else 'financeiro'
    return _BLUEPRINT_AREA.get(blueprint)


def primeira_rota(usuario):
    """Endpoint da primeira área liberada para o usuário (None se não tiver nenhuma)."""
    for chave, _n, _d, rota in AREAS:
        if usuario.pode(chave):
            return rota
    return None
