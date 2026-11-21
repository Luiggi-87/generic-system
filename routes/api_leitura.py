"""API somente-leitura para conferência dos dados (varreduras e relatórios).

Protegida por chave (cabeçalho X-API-Key = variável REPORT_API_KEY). Só expõe GET e só os
campos abaixo — não inclui CPF, telefone, endereço nem configurações do servidor.
"""
import hmac
import json
import os

from flask import Blueprint, jsonify, request

from models import (CentroCusto, FormaPagamento, Funcionario, Lancamento, NotaFiscal, Operadora,
                    PeriodoFolha, TaxaOperadora)

api_leitura_bp = Blueprint('api_leitura', __name__, url_prefix='/api')


@api_leitura_bp.before_request
def _exigir_chave():
    esperado = os.environ.get('REPORT_API_KEY')
    chave = request.headers.get('X-API-Key', '')
    if not esperado or not hmac.compare_digest(chave, esperado):
        return jsonify({'erro': 'não autorizado'}), 403


def _d(v):
    return v.isoformat() if v else None


def _lancamento(l):
    return {
        'id': l.id,
        'tipo': l.tipo,
        'cliente_nome': l.cliente.nome if l.cliente else None,
        'descricao': l.descricao,
        'valor': l.valor,
        'valor_liquido': l.valor_liquido,
        'taxa_operadora_pct': l.taxa_operadora_pct,
        'taxa_operadora_valor': l.taxa_operadora_valor,
        'status': l.status,
        'forma_pagamento': l.forma_pagamento,
        'operadora': l.operadora,
        'parcelas': l.parcelas,
        'centro_custo': l.centro_custo.nome if l.centro_custo else None,
        'atendimento_id': l.atendimento_id,
        'periodo_folha_id': l.periodo_folha_id,
        'data_competencia': _d(l.data_competencia),
        'data_vencimento': _d(l.data_vencimento),
        'data_pagamento': _d(l.data_pagamento),
        'observacoes': l.observacoes,
    }


@api_leitura_bp.route('/despesas')
def despesas():
    """Todas as despesas (inclui as taxas automáticas de cartão e a folha)."""
    q = (Lancamento.query.filter(Lancamento.tipo == 'despesa')
         .order_by(Lancamento.data_competencia, Lancamento.id).all())
    return jsonify([_lancamento(l) for l in q])


@api_leitura_bp.route('/receitas')
def receitas():
    """Todas as receitas, inclusive as de atendimento (a /api/lancamentos traz só contratos)."""
    q = (Lancamento.query.filter(Lancamento.tipo == 'receita')
         .order_by(Lancamento.data_competencia, Lancamento.id).all())
    return jsonify([_lancamento(l) for l in q])


@api_leitura_bp.route('/folha')
def folha():
    """Períodos de folha com receitas (cópias dos valores), escalas e horas."""
    saida = []
    for p in PeriodoFolha.query.order_by(PeriodoFolha.ano, PeriodoFolha.mes).all():
        receitas = []
        for r in p.receitas:
            try:
                detalhes = json.loads(r.detalhes_pagamentos) if r.detalhes_pagamentos else []
            except ValueError:
                detalhes = []
            receitas.append({
                'id': r.id, 'data': _d(r.data), 'cliente_nome': r.cliente_nome,
                'parto': r.parto, 'aeo': r.aeo, 'amamentacao': r.amamentacao,
                'laser': r.laser, 'curso': r.curso, 'brinco': r.brinco, 'total': r.total,
                'funcionario_id': r.funcionario_id, 'detalhes_pagamentos': detalhes,
            })
        escalas = [{
            'funcionario_id': e.funcionario_id,
            'funcionario': e.funcionario.nome if e.funcionario else None,
            'horas_diurnas': e.horas_diurnas, 'horas_noturnas': e.horas_noturnas,
            'horas_extra': e.horas_extra, 'horas_extra_noturnas': e.horas_extra_noturnas,
            'taxa_desconto': e.taxa_desconto,
        } for e in p.escalas]
        saida.append({'id': p.id, 'mes': p.mes, 'ano': p.ano, 'status': p.status,
                      'total_dias': p.total_dias, 'receitas': receitas, 'escalas': escalas})
    return jsonify({
        'periodos': saida,
        'funcionarios': [{'id': f.id, 'nome': f.nome, 'cargo': f.cargo, 'taxa_desconto': f.taxa_desconto,
                          'ativo': f.ativo} for f in Funcionario.query.order_by(Funcionario.nome).all()],
    })


@api_leitura_bp.route('/notas-fiscais')
def notas_fiscais():
    """Notas fiscais registradas (inclui anuladas) com o status do ISS."""
    return jsonify([{
        'id': n.id, 'numero': n.numero, 'cliente_nome': n.cliente.nome if n.cliente else None,
        'valor_bruto': n.valor_bruto, 'valor_liquido': n.valor_liquido,
        'aliquota_iss': n.aliquota_iss, 'valor_iss': n.valor_iss,
        'data_emissao': _d(n.data_emissao), 'competencia_mes': n.competencia_mes,
        'competencia_ano': n.competencia_ano, 'status': n.status, 'status_iss': n.status_iss,
        'lancamento_iss_id': n.lancamento_iss_id,
    } for n in NotaFiscal.query.order_by(NotaFiscal.data_emissao, NotaFiscal.id).all()])


@api_leitura_bp.route('/formas-pagamento')
def formas_pagamento():
    """Formas de pagamento e operadoras com suas tabelas de taxas."""
    taxas = {}
    for t in TaxaOperadora.query.order_by(TaxaOperadora.operadora, TaxaOperadora.parcelas).all():
        o = taxas.setdefault(t.operadora, {'debito': None, 'credito': {}})
        if t.modalidade == 'debito':
            o['debito'] = t.taxa_pct
        else:
            o['credito'][str(t.parcelas)] = t.taxa_pct
    return jsonify({
        'formas': [{'codigo': f.codigo, 'nome': f.nome, 'ativo': f.ativo, 'padrao': f.padrao,
                    'tipo_taxa': f.tipo_taxa, 'prazo': f.prazo, 'observacoes': f.observacoes}
                   for f in FormaPagamento.query.order_by(FormaPagamento.id).all()],
        'operadoras': [{'codigo': o.codigo, 'nome': o.nome, 'ativo': o.ativo,
                        'taxas': taxas.get(o.codigo, {'debito': None, 'credito': {}})}
                       for o in Operadora.query.order_by(Operadora.id).all()],
        'centros_custo': [{'codigo': c.codigo, 'nome': c.nome, 'tipo': c.tipo, 'ativo': c.ativo}
                          for c in CentroCusto.query.order_by(CentroCusto.codigo).all()],
    })
