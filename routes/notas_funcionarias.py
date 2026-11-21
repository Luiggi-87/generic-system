"""Notas fiscais das prestadoras de serviço para receber o repasse do mês.

A prestadora de serviço (prestadora) envia o XML da nota que emitiu para a empresa; o sistema confere o valor da nota
com o repasse do mês (o mesmo do demonstrativo) e avisa quem paga quando está tudo certo. Nada é pago por aqui:
o pagamento é feito pela empresa e apenas registrado."""
from datetime import date, datetime
from types import SimpleNamespace

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import db, Funcionario, NotaFuncionaria
from nfse_xml import ler_nfse
from routes.relatorio_faturamento import MESES, montar_faturamento

notas_func_bp = Blueprint('notas_func', __name__, url_prefix='/notas-funcionarias')

TOLERANCIA = 0.05   # centavos de arredondamento entre o repasse e a nota


# ── conferência ───────────────────────────────────────────────────────────────
def _repasses(mes, ano, cache, definitivo=False):
    """{funcionario_id: repasse} do mês (mesmo cálculo do demonstrativo). `definitivo`: devolve vazio enquanto a
    Folha do mês está aberta (o valor ainda pode mudar), para a prestadora não ver nem emitir nota de um repasse provisório."""
    if (mes, ano) not in cache:
        d = montar_faturamento(mes, ano)
        cache[(mes, ano)] = ({f['id']: f['repasse'] for f in d['funcionarias']}, d['folha_aberta'])
    repasses, aberta = cache[(mes, ano)]
    return {} if definitivo and aberta else repasses


def _veredito(nota, esperado):
    """'paga' | 'sem_repasse' | 'conferida' | 'divergente' (calculado na hora, com o repasse atual)."""
    if nota.pago_em:
        return 'paga'
    if esperado is None:
        return 'sem_repasse'
    for v in (nota.valor, nota.valor_liquido):
        if v is not None and abs(v - esperado) <= TOLERANCIA:
            return 'conferida'
    return 'divergente'


def resumo_pendentes():
    """Para o painel: quantas notas estão conferidas (pode pagar) e quantas divergentes."""
    cache = {}
    ok = SimpleNamespace(qtd_ok=0, valor_ok=0.0, qtd_div=0)
    for n in NotaFuncionaria.query.filter(NotaFuncionaria.pago_em.is_(None)).all():
        esperado = _repasses(n.mes, n.ano, cache).get(n.funcionario_id)
        v = _veredito(n, esperado)
        if v == 'conferida':
            ok.qtd_ok += 1
            ok.valor_ok += esperado
        elif v == 'divergente':
            ok.qtd_div += 1
    ok.valor_ok = round(ok.valor_ok, 2)
    return ok


def _meses_recentes(n=7):
    hoje = date.today()
    a, m, out = hoje.year, hoje.month, []
    for _ in range(n):
        out.append((a, m))
        a, m = (a - 1, 12) if m == 1 else (a, m - 1)
    return out


# ── prestadora de serviço: enviar a própria nota ────────────────────────────────────────
def _minha_funcionaria():
    return db.session.get(Funcionario, current_user.funcionario_id) if current_user.funcionario_id else None


def _sem_vinculo():
    return render_template('sem_permissao.html', mensagem='Seu acesso ainda não está vinculado a uma prestadora de serviço. '
                           'Peça à administradora para vincular.'), 403


@notas_func_bp.route('/minhas')
def minhas():
    f = _minha_funcionaria()
    if f is None:
        return _sem_vinculo()
    cache = {}
    notas = (NotaFuncionaria.query.filter_by(funcionario_id=f.id)
             .order_by(NotaFuncionaria.ano.desc(), NotaFuncionaria.mes.desc(), NotaFuncionaria.id.desc()).all())
    itens = [{'nota': n, 'esperado': _repasses(n.mes, n.ano, cache, True).get(f.id),
              'veredito': _veredito(n, _repasses(n.mes, n.ano, cache, True).get(f.id))} for n in notas]
    pagas = {(n.ano, n.mes) for n in notas if n.pago_em}
    opcoes = []
    for a, m in _meses_recentes():
        esperado = _repasses(m, a, cache, True).get(f.id)
        if esperado and esperado > 0 and (a, m) not in pagas:
            opcoes.append({'ano': a, 'mes': m, 'nome': f'{MESES[m - 1]}/{a}', 'valor': esperado})
    return render_template('notas_funcionarias/minhas.html', f=f, itens=itens, opcoes=opcoes)


@notas_func_bp.route('/minhas/enviar', methods=['POST'])
def enviar():
    f = _minha_funcionaria()
    if f is None:
        return _sem_vinculo()
    try:
        ano, mes = (int(x) for x in request.form.get('referencia', '').split('-'))
        assert 1 <= mes <= 12 and (ano, mes) in _meses_recentes(13)
    except (ValueError, AssertionError):
        flash('Escolha o mês do repasse a que a nota se refere.', 'danger')
        return redirect(url_for('notas_func.minhas'))
    arq = request.files.get('arquivo')
    if not arq or not arq.filename:
        flash('Escolha o arquivo XML da nota fiscal.', 'warning')
        return redirect(url_for('notas_func.minhas'))
    bruto = arq.read(1024 * 1024 + 1)
    d = ler_nfse(bruto, arq.filename)
    if d.get('erro'):
        flash(d['erro'], 'danger')
        return redirect(url_for('notas_func.minhas'))
    esperado = _repasses(mes, ano, {}, True).get(f.id)
    if not esperado:
        if montar_faturamento(mes, ano)['folha_aberta']:
            flash(f'A Folha de {MESES[mes - 1]}/{ano} ainda não foi fechada: envie a nota depois que o repasse for confirmado.', 'warning')
        else:
            flash(f'Não há repasse seu em {MESES[mes - 1]}/{ano}.', 'danger')
        return redirect(url_for('notas_func.minhas'))
    if NotaFuncionaria.query.filter_by(funcionario_id=f.id, mes=mes, ano=ano).filter(NotaFuncionaria.pago_em.isnot(None)).first():
        flash(f'O repasse de {MESES[mes - 1]}/{ano} já foi pago.', 'warning')
        return redirect(url_for('notas_func.minhas'))
    repetida = NotaFuncionaria.query.filter(NotaFuncionaria.funcionario_id == f.id)
    if d['chave']:
        repetida = repetida.filter(NotaFuncionaria.chave_acesso == d['chave'])
    else:
        repetida = repetida.filter(NotaFuncionaria.numero == d['numero'])
    if repetida.filter((NotaFuncionaria.mes != mes) | (NotaFuncionaria.ano != ano)).first():
        flash('Esta nota já foi enviada para outro mês.', 'warning')
        return redirect(url_for('notas_func.minhas'))
    # um novo envio substitui a nota anterior ainda não paga do mesmo mês
    for antiga in NotaFuncionaria.query.filter_by(funcionario_id=f.id, mes=mes, ano=ano).all():
        db.session.delete(antiga)
    nota = NotaFuncionaria(
        funcionario_id=f.id, mes=mes, ano=ano, numero=d['numero'], data_emissao=d['data_emissao'], valor=d['valor_bruto'],
        valor_liquido=d.get('valor_liquido'), chave_acesso=d['chave'] or None, prestador_nome=d.get('prestador_nome') or None,
        tomador_nome=d.get('tomador_nome') or None, xml=bruto.decode('utf-8', errors='replace'), enviada_por_id=current_user.id)
    db.session.add(nota)
    db.session.commit()
    if _veredito(nota, esperado) == 'conferida':
        flash(f'Nota {nota.numero} conferida: o valor bate com o seu repasse de {MESES[mes - 1]}/{ano} '
              f'(R$ {esperado:,.2f}). A empresa foi avisada e fará o pagamento.'.replace(',', '_').replace('.', ',').replace('_', '.'), 'success')
    else:
        flash(f'O valor da nota (R$ {nota.valor:,.2f}) não bate com o seu repasse de {MESES[mes - 1]}/{ano} (R$ {esperado:,.2f}). '
              f'Emita a nota com o valor correto e envie de novo.'.replace(',', '_').replace('.', ',').replace('_', '.'), 'warning')
    return redirect(url_for('notas_func.minhas'))


# ── empresa: conferir e registrar o pagamento ─────────────────────────────────
@notas_func_bp.route('/')
def index():
    hoje = date.today()
    mes = request.args.get('mes', hoje.month, type=int)
    ano = request.args.get('ano', hoje.year, type=int)
    if not (1 <= mes <= 12 and 2000 <= ano <= 2100):
        mes, ano = hoje.month, hoje.year
    d = montar_faturamento(mes, ano)
    linhas = []
    for fun in d['funcionarias']:
        if not fun['repasse']:
            continue
        nota = (NotaFuncionaria.query.filter_by(funcionario_id=fun['id'], mes=mes, ano=ano)
                .order_by(NotaFuncionaria.id.desc()).first())
        status = 'aguardando' if nota is None else _veredito(nota, fun['repasse'])
        linhas.append({'nome': fun['nome'], 'repasse': fun['repasse'], 'nota': nota, 'status': status})
    total_pagar = round(sum(l['repasse'] for l in linhas if l['status'] == 'conferida'), 2)
    return render_template('notas_funcionarias/index.html', linhas=linhas, mes=mes, ano=ano, meses=MESES,
                           anos=range(hoje.year - 2, hoje.year + 2), total_pagar=total_pagar, hoje=hoje.isoformat())


@notas_func_bp.route('/<int:id>/pagar', methods=['POST'])
def pagar(id):
    n = NotaFuncionaria.query.get_or_404(id)
    esperado = _repasses(n.mes, n.ano, {}).get(n.funcionario_id)
    try:
        data = date.fromisoformat(request.form.get('pago_em') or '')
    except ValueError:
        data = date.today()
    if n.pago_em:
        flash('Este pagamento já está registrado.', 'warning')
    elif _veredito(n, esperado) != 'conferida':
        flash('O valor da nota não confere com o repasse: não é possível registrar o pagamento.', 'danger')
    else:
        n.pago_em = data
        db.session.commit()
        flash(f'Pagamento de {n.funcionario.nome} ({MESES[n.mes - 1]}/{n.ano}) registrado.', 'success')
    return redirect(url_for('notas_func.index', mes=n.mes, ano=n.ano))


@notas_func_bp.route('/<int:id>/desfazer', methods=['POST'])
def desfazer(id):
    n = NotaFuncionaria.query.get_or_404(id)
    n.pago_em = None
    db.session.commit()
    flash('Pagamento desmarcado.', 'info')
    return redirect(url_for('notas_func.index', mes=n.mes, ano=n.ano))


@notas_func_bp.route('/<int:id>/xml')
def baixar_xml(id):
    n = NotaFuncionaria.query.get_or_404(id)
    if not (current_user.pode('notas_funcionarias') or current_user.funcionario_id == n.funcionario_id):
        abort(403)
    return Response(n.xml or '', mimetype='application/xml',
                    headers={'Content-Disposition': f'attachment; filename="nota_{n.numero}.xml"'})
