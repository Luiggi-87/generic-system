from flask import Blueprint, render_template, request
from models import db, Lancamento, NotaFiscal
from datetime import date
import calendar
from config import ALIQUOTA_ISS

contratos_iss_bp = Blueprint('contratos_iss', __name__, url_prefix='/gerencial/contratos-iss')
MESES_NOMES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
               'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']


def _build_contratos(data_de=None, data_ate=None, status_filtro=''):
    q = Lancamento.query.filter(
        Lancamento.tipo == 'receita',
        Lancamento.status.in_(['recebido', 'pago']),
        Lancamento.cliente_id.isnot(None),
    )
    if data_de:
        q = q.filter(Lancamento.data_pagamento >= data_de)
    if data_ate:
        q = q.filter(Lancamento.data_pagamento <= data_ate)

    lancamentos = q.order_by(Lancamento.data_pagamento.desc()).all()

    # Agrupa por cliente — soma todos os lançamentos, mantém o mais recente para referência
    clientes_map = {}
    for l in lancamentos:
        if l.cliente_id not in clientes_map:
            clientes_map[l.cliente_id] = {'lancamento': l, 'total_valor': 0.0}
        clientes_map[l.cliente_id]['total_valor'] += l.valor

    # NFs válidas (não anuladas) por cliente, da mais recente para a mais antiga
    nfs_map = {}
    for nf in (NotaFiscal.query.filter(NotaFiscal.status != 'anulada')
               .order_by(NotaFiscal.data_emissao.desc(), NotaFiscal.id.desc()).all()):
        nfs_map.setdefault(nf.cliente_id, []).append(nf)

    rows = []
    for cliente_id, info in clientes_map.items():
        l = info['lancamento']
        valor_contrato = info['total_valor']
        nfs = nfs_map.get(cliente_id, [])
        nf = nfs[0] if nfs else None  # mais recente (referência)

        if nf:
            # soma todas as NFs válidas do cliente (antes só a mais recente entrava)
            iss = round(sum(n.valor_iss for n in nfs), 2)
            nf_numero = nf.numero if len(nfs) == 1 else f'{nf.numero} (+{len(nfs) - 1})'
            valor_nf = sum(n.valor_bruto for n in nfs)
            status_nf = 'emitida'
            status_iss = 'pago' if all(n.status_iss == 'pago' for n in nfs) else 'a_pagar'
        else:
            iss = round(valor_contrato * ALIQUOTA_ISS, 2)
            nf_numero = None
            valor_nf = None
            status_nf = 'sem_nf'
            status_iss = 'estimado'

        row = {
            'cliente': l.cliente,
            'lancamento': l,
            'valor_contrato': valor_contrato,
            'nf': nf,
            'nf_numero': nf_numero,
            'valor_nf': valor_nf,
            'iss': iss,
            'status_nf': status_nf,
            'status_iss': status_iss,
        }
        if not status_filtro or status_iss == status_filtro:
            rows.append(row)

    ordem = {'estimado': 0, 'a_pagar': 1, 'pago': 2}
    rows.sort(key=lambda r: ordem.get(r['status_iss'], 99))

    total_contratos = sum(r['valor_contrato'] for r in rows)
    total_iss_pago = sum(r['iss'] for r in rows if r['status_iss'] == 'pago')
    total_iss_a_pagar = sum(r['iss'] for r in rows if r['status_iss'] == 'a_pagar')
    total_iss_estimado = sum(r['iss'] for r in rows if r['status_iss'] == 'estimado')
    total_iss = total_iss_pago + total_iss_a_pagar + total_iss_estimado

    pct_pago = int(total_iss_pago / total_iss * 100) if total_iss > 0 else 0
    pct_a_pagar = int(total_iss_a_pagar / total_iss * 100) if total_iss > 0 else 0
    pct_estimado = 100 - pct_pago - pct_a_pagar if total_iss > 0 else 0

    return {
        'rows': rows,
        'total_contratos': total_contratos,
        'total_iss_pago': total_iss_pago,
        'total_iss_a_pagar': total_iss_a_pagar,
        'total_iss_estimado': total_iss_estimado,
        'total_iss': total_iss,
        'count_pago': sum(1 for r in rows if r['status_iss'] == 'pago'),
        'count_a_pagar': sum(1 for r in rows if r['status_iss'] == 'a_pagar'),
        'count_sem_nf': sum(1 for r in rows if r['status_iss'] == 'estimado'),
        'pct_pago': pct_pago,
        'pct_a_pagar': pct_a_pagar,
        'pct_estimado': pct_estimado,
    }


@contratos_iss_bp.route('/')
def index():
    hoje = date.today()
    periodo = request.args.get('periodo', '')   # 'YYYY-MM' ou vazio = todo histórico
    status_filtro = request.args.get('status_iss', '')
    gerar = request.args.get('gerar')

    data_de = data_ate = None
    periodo_label = 'Todo o histórico'

    if periodo:
        try:
            ano, mes = int(periodo[:4]), int(periodo[5:7])
            data_de = date(ano, mes, 1)
            data_ate = date(ano, mes, calendar.monthrange(ano, mes)[1])
            periodo_label = f'{MESES_NOMES[mes-1]}/{ano}'
        except Exception:
            pass

    dados = None
    if gerar:
        dados = _build_contratos(data_de, data_ate, status_filtro)

    return render_template('relatorios/contratos_iss.html',
        periodo=periodo,
        status_filtro=status_filtro,
        periodo_label=periodo_label,
        dados=dados,
        hoje=hoje,
        meses_nomes=MESES_NOMES,
    )
