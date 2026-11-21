"""ISS do mês (somente consulta): notas fiscais emitidas no mês e o ISS a recolher, para a contabilidade emitir a guia.
O imposto é somado ao longo do mês sobre as notas emitidas e vence no dia 20 do mês seguinte."""
import csv
import io
from datetime import date

from flask import Blueprint, Response, render_template, request

from config import ALIQUOTA_ISS
from models import NotaFiscal
from routes.notas_fiscais import venc_iss

iss_bp = Blueprint('iss_mensal', __name__, url_prefix='/iss')

MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']


def _periodo():
    hoje = date.today()
    mes = request.args.get('mes', hoje.month, type=int)
    ano = request.args.get('ano', hoje.year, type=int)
    if not (1 <= mes <= 12 and 2000 <= ano <= 2100):
        mes, ano = hoje.month, hoje.year
    return mes, ano


def _notas(mes, ano):
    ini = date(ano, mes, 1)
    fim = date(ano + (mes == 12), 1 if mes == 12 else mes + 1, 1)
    return (NotaFiscal.query.filter(NotaFiscal.status != 'anulada', NotaFiscal.data_emissao >= ini, NotaFiscal.data_emissao < fim)
            .order_by(NotaFiscal.data_emissao, NotaFiscal.id).all())


def _totais(notas):
    return {'qtd': len(notas), 'bruto': round(sum(n.valor_bruto for n in notas), 2), 'iss': round(sum(n.valor_iss for n in notas), 2)}


@iss_bp.route('/')
def index():
    mes, ano = _periodo()
    notas = _notas(mes, ano)
    # resumo do ano, mês a mês
    anual = []
    for m in range(1, 13):
        t = _totais(_notas(m, ano))
        if t['qtd']:
            anual.append({'mes': m, 'nome': MESES[m - 1], 'vencimento': venc_iss(date(ano, m, 1)), **t})
    hoje = date.today()
    return render_template('iss_mensal/index.html', mes=mes, ano=ano, meses=MESES, anos=range(hoje.year - 3, hoje.year + 2), notas=notas,
                           tot=_totais(notas), vencimento=venc_iss(date(ano, mes, 1)), aliquota=ALIQUOTA_ISS, anual=anual)


@iss_bp.route('/csv')
def exportar():
    mes, ano = _periodo()
    saida = io.StringIO()
    w = csv.writer(saida, delimiter=';')
    w.writerow(['Nº da nota', 'Sistema', 'Cliente', 'Data de emissão', 'Valor da nota (R$)', 'ISS (R$)'])
    notas = _notas(mes, ano)
    for n in notas:
        w.writerow([n.numero, n.sistema_emissao, n.cliente.nome if n.cliente else '', n.data_emissao.strftime('%d/%m/%Y'),
                    f'{n.valor_bruto:.2f}'.replace('.', ','), f'{n.valor_iss:.2f}'.replace('.', ',')])
    t = _totais(notas)
    w.writerow([])
    w.writerow(['TOTAL', '', f"{t['qtd']} nota(s)", '', f"{t['bruto']:.2f}".replace('.', ','), f"{t['iss']:.2f}".replace('.', ',')])
    w.writerow(['Vencimento da guia', venc_iss(date(ano, mes, 1)).strftime('%d/%m/%Y')])
    return Response('﻿' + saida.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="iss_{ano}-{mes:02d}.csv"'})
