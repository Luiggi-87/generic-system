from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from models import db, NotaFiscal, Cliente, Lancamento, CentroCusto, DecisaoDuplicidade
from datetime import date
from sqlalchemy import func
from types import SimpleNamespace
from config import ALIQUOTA_ISS
from nfse_xml import ler_nfse, so_digitos
from nfse_pdf import ler_nfse_pdf
import re
import difflib
import unicodedata

nf_bp = Blueprint('notas_fiscais', __name__, url_prefix='/financeiro/notas-fiscais')


def _lancamentos_sem_nf():
    """Agrupa receitas recebidas sem NF por cliente, somando todos os lançamentos."""
    nf_cliente_ids = {nf.cliente_id for nf in NotaFiscal.query.filter(NotaFiscal.status != 'anulada')}
    lancs = (Lancamento.query
             .filter(Lancamento.tipo == 'receita',
                     Lancamento.status.in_(['recebido', 'pago']),
                     Lancamento.cliente_id.isnot(None))
             .order_by(Lancamento.data_pagamento.desc())
             .all())

    grupos = {}
    for l in lancs:
        if l.cliente_id in nf_cliente_ids:
            continue
        if l.cliente_id not in grupos:
            grupos[l.cliente_id] = SimpleNamespace(
                cliente_id=l.cliente_id,
                cliente=l.cliente,
                valor=0.0,
                valor_liquido=0.0,
                data_pagamento=l.data_pagamento,   # mais recente (ordem desc)
                forma_pagamento=l.forma_pagamento,  # forma do lançamento mais recente
            )
        grupos[l.cliente_id].valor += l.valor
        grupos[l.cliente_id].valor_liquido += (l.valor_liquido or l.valor)

    return list(grupos.values())


def _cc_imposto(centros):
    """Centro de custo padrão do ISS: o primeiro cujo nome contém 'imposto'."""
    return next((c for c in centros if 'imposto' in (c.nome or '').lower()), None)


def venc_iss(data_emissao):
    """O ISS vence no dia 20 do mês seguinte ao da emissão da nota."""
    a, m = (data_emissao.year + 1, 1) if data_emissao.month == 12 else (data_emissao.year, data_emissao.month + 1)
    return date(a, m, 20)


_NIVEL = {'alta': 0, 'media': 1, 'baixa': 2}


def _chave_grupo(notas):
    """Identifica o grupo pelas notas que ele tem: se entrar outra nota na mesma situação, o grupo volta a aparecer para decidir."""
    return '-'.join(str(i) for i in sorted(n.id for n in notas))


def possiveis_duplicidades(notas):
    """Notas que podem ter sido lançadas em duplicidade (só para conferir; quem decide é a administração).
    - alta: mesma ficha de cliente, mesmo sistema (municipal/nacional) e mesmo valor.
    - media: mesma ficha, mas valor ou sistema diferente (pode ser serviço adicional ou nota reemitida).
    - baixa: mesmo nome em fichas diferentes (pode ser outro filho: a referência do parto/DPP mostra qual é qual).
    Notas anuladas não entram."""
    from routes.clientes import rotulo_cliente
    ativas = [n for n in notas if n.status != 'anulada' and n.cliente is not None]
    saida, por_ficha = [], {}
    for n in ativas:
        por_ficha.setdefault(n.cliente_id, []).append(n)
    for grupo in por_ficha.values():
        if len(grupo) < 2:
            continue
        grupo = sorted(grupo, key=lambda n: (n.data_emissao, n.id))
        iguais = len({(n.sistema_emissao, round(n.valor_bruto, 2)) for n in grupo}) < len(grupo)
        saida.append({'nivel': 'alta' if iguais else 'media', 'cliente': rotulo_cliente(grupo[0].cliente), 'notas': grupo, 'chave': _chave_grupo(grupo),
                      'motivo': ('Mesma cliente, mesmo sistema e mesmo valor em mais de uma nota.' if iguais else
                                 'Mesma ficha com mais de uma nota, de valor ou sistema diferente (pode ser serviço adicional ou nota reemitida).')})
    por_nome = {}
    for n in ativas:
        por_nome.setdefault(_norm(n.cliente.nome), {}).setdefault(n.cliente_id, []).append(n)
    for fichas in por_nome.values():
        if len(fichas) < 2:
            continue
        grupo = sorted((n for ns in fichas.values() for n in ns), key=lambda n: (n.data_emissao, n.id))
        saida.append({'nivel': 'baixa', 'cliente': grupo[0].cliente.nome, 'notas': grupo, 'chave': _chave_grupo(grupo),
                      'motivo': 'Mesmo nome em fichas diferentes: pode ser outra gestação (outro filho). Confira pela referência do parto/DPP de cada nota.'})
    return sorted(saida, key=lambda d: (_NIVEL[d['nivel']], _norm(d['cliente'])))


@nf_bp.route('/')
def index():
    notas = (NotaFiscal.query
             .order_by(NotaFiscal.data_emissao.desc())
             .all())

    sem_nf = _lancamentos_sem_nf()

    total_sem_nf = sum(l.valor for l in sem_nf)
    total_iss_pendente = sum(
        n.valor_iss for n in notas if n.status_iss == 'a_pagar'
    )
    total_iss_pago_mes = sum(
        n.valor_iss for n in notas
        if n.status_iss == 'pago'
        and n.competencia_mes == date.today().month
        and n.competencia_ano == date.today().year
    )

    decisoes = {d.chave: d for d in DecisaoDuplicidade.query.all()}
    todas = possiveis_duplicidades(notas)
    duplicidades = [d for d in todas if d['chave'] not in decisoes]
    duplicidades_decididas = [dict(d, decisao=decisoes[d['chave']]) for d in todas if d['chave'] in decisoes]
    clientes = Cliente.query.order_by(Cliente.nome).all()
    centros_despesa = CentroCusto.query.filter(
        CentroCusto.tipo.in_(['despesa', 'ambos']),
        CentroCusto.ativo == True
    ).order_by(CentroCusto.nome).all()

    return render_template('financeiro/notas_fiscais.html',
        notas=notas,
        duplicidades=duplicidades,
        duplicidades_decididas=duplicidades_decididas,
        sem_nf=sem_nf,
        clientes=clientes,
        centros_despesa=centros_despesa,
        cc_imposto_id=(_cc_imposto(centros_despesa).id if _cc_imposto(centros_despesa) else None),
        total_sem_nf=total_sem_nf,
        total_iss_pendente=total_iss_pendente,
        total_iss_pago_mes=total_iss_pago_mes,
        aliquota_iss=ALIQUOTA_ISS,
    )


def _criar_nota(numero, cliente_id, valor_bruto, valor_liquido, data_emissao, comp_ano, comp_mes,
                lancar_iss, centro_custo_id, vencimento_str=None, valor_iss=None, aliquota=None, chave=None):
    """Cria a NF e, se pedido, a despesa de ISS pendente (vence no dia 20 do mês seguinte, se não informado)."""
    aliquota = aliquota if aliquota else ALIQUOTA_ISS
    if valor_iss is None:
        valor_iss = round(valor_bruto * aliquota, 2)
    nf = NotaFiscal(
        numero=numero, cliente_id=cliente_id, valor_bruto=valor_bruto, valor_liquido=valor_liquido,
        aliquota_iss=aliquota, valor_iss=valor_iss, data_emissao=data_emissao,
        competencia_mes=comp_mes, competencia_ano=comp_ano, chave_acesso=chave or None,
    )
    db.session.add(nf)
    db.session.flush()

    if lancar_iss and valor_iss > 0:
        try:
            vencimento = date.fromisoformat(vencimento_str) if vencimento_str else venc_iss(data_emissao)
        except ValueError:
            vencimento = venc_iss(data_emissao)
        lanc = Lancamento(
            descricao=f'ISS — Nota Fiscal {numero}',
            tipo='despesa',
            valor=valor_iss,
            data_competencia=date(comp_ano, comp_mes, 1),
            data_vencimento=vencimento,
            status='pendente',
            centro_custo_id=centro_custo_id or None,
            observacoes=f'ISS {aliquota * 100:g}% sobre NF {numero} — cliente {nf.cliente.nome if nf.cliente else ""}',
        )
        db.session.add(lanc)
        db.session.flush()
        nf.lancamento_iss_id = lanc.id
    return nf


@nf_bp.route('/nova', methods=['POST'])
def nova():
    numero = request.form.get('numero', '').strip()
    cliente_id = request.form.get('cliente_id', type=int)
    valor_bruto = request.form.get('valor_bruto', 0, type=float)
    valor_liquido = request.form.get('valor_liquido', 0, type=float)
    data_str = request.form.get('data_emissao')
    competencia_str = request.form.get('competencia', '')
    lancar_iss = request.form.get('lancar_iss') == 'on'
    centro_custo_id = request.form.get('centro_custo_id', type=int)
    vencimento_str = request.form.get('vencimento_iss')

    try:
        data_emissao = date.fromisoformat(data_str) if data_str else date.today()
    except ValueError:
        data_emissao = date.today()

    try:
        comp_parts = competencia_str.split('-')
        comp_ano = int(comp_parts[0])
        comp_mes = int(comp_parts[1])
    except Exception:
        comp_ano = date.today().year
        comp_mes = date.today().month

    if not numero or not cliente_id or valor_bruto <= 0:
        flash('Informe o número da nota, a cliente e um valor bruto maior que zero.', 'danger')
        return redirect(url_for('notas_fiscais.index'))

    if _duplicada({'chave': None, 'numero': numero, 'data_emissao': data_emissao}):
        flash(f'A nota {numero} já está cadastrada — nada foi lançado, para não duplicar.', 'warning')
        return redirect(url_for('notas_fiscais.index'))

    _criar_nota(numero, cliente_id, valor_bruto, valor_liquido, data_emissao, comp_ano, comp_mes,
                lancar_iss, centro_custo_id, vencimento_str)
    db.session.commit()
    flash(f'Nota Fiscal {numero} registrada com sucesso.', 'success')
    return redirect(url_for('notas_fiscais.index'))


@nf_bp.route('/baixa-iss', methods=['POST'])
def baixa_iss():
    """Lança (a pagar) ou dá baixa (pago) no ISS das notas selecionadas, criando a despesa quando ainda não existe."""
    ids = request.form.getlist('nf_ids', type=int)
    pagar = request.form.get('acao') == 'pagar'
    cc_id = request.form.get('centro_custo_id', type=int)
    if not cc_id:   # sem escolha: usa o centro de custo de imposto, se existir
        padrao = _cc_imposto(CentroCusto.query.filter(CentroCusto.tipo.in_(['despesa', 'ambos'])).all())
        cc_id = padrao.id if padrao else None
    try:
        data_pag = date.fromisoformat(request.form.get('data_pagamento') or '')
    except ValueError:
        data_pag = None
    if not ids:
        flash('Marque pelo menos uma nota.', 'warning')
        return redirect(url_for('notas_fiscais.index'))
    feitas = 0
    for nf in NotaFiscal.query.filter(NotaFiscal.id.in_(ids), NotaFiscal.status != 'anulada').all():
        lanc = nf.lancamento_iss
        venc = venc_iss(nf.data_emissao)   # sem data informada, vale o vencimento: dia 20 do mês seguinte
        if lanc is None:
            lanc = Lancamento(
                descricao=f'ISS — Nota Fiscal {nf.numero}', tipo='despesa', valor=nf.valor_iss, status='pendente',
                data_competencia=date(nf.competencia_ano, nf.competencia_mes, 1), data_vencimento=venc,
                centro_custo_id=cc_id or None,
                observacoes=f'ISS {int(ALIQUOTA_ISS * 100)}% sobre NF {nf.numero} — cliente {nf.cliente.nome if nf.cliente else ""}')
            db.session.add(lanc)
            db.session.flush()
            nf.lancamento_iss_id = lanc.id
        elif cc_id and not lanc.centro_custo_id:
            lanc.centro_custo_id = cc_id
        if pagar and lanc.status != 'pago':
            lanc.status, lanc.data_pagamento = 'pago', data_pag or venc
            lanc.data_vencimento = lanc.data_vencimento or venc
        feitas += 1
    db.session.commit()
    flash(f'ISS de {feitas} nota(s) ' + ('baixado (pago).' if pagar else 'lançado como a pagar.'), 'success')
    return redirect(url_for('notas_fiscais.index'))


@nf_bp.route('/duplicidade/decidir', methods=['POST'])
def decidir_duplicidade():
    """Grava a decisão sobre um grupo de possível duplicidade: 'ok|<motivo>' (não é duplicidade) ou 'duplicada|<id da nota repetida>'."""
    chave = request.form.get('chave', '').strip()
    tipo, _, valor = request.form.get('escolha', '').partition('|')
    ids = {int(x) for x in chave.split('-') if x.isdigit()}
    obs = request.form.get('observacao', '').strip() or None
    if not ids or tipo not in ('ok', 'duplicada'):
        flash('Escolha uma decisão para o grupo de notas.', 'warning')
        return redirect(url_for('notas_fiscais.index'))
    nota_id = None
    if tipo == 'duplicada':
        nota_id = int(valor) if valor.isdigit() and int(valor) in ids else None
        if nota_id is None:
            flash('Escolha qual das notas é a duplicada.', 'warning')
            return redirect(url_for('notas_fiscais.index'))
    d = DecisaoDuplicidade.query.filter_by(chave=chave).first() or DecisaoDuplicidade(chave=chave)
    d.decisao, d.motivo, d.nota_id, d.observacao = tipo, (valor if tipo == 'ok' else None), nota_id, obs
    d.decidido_por = current_user.nome
    db.session.add(d)
    db.session.commit()
    flash('Decisão registrada.' if tipo == 'ok' else 'Marcada como duplicada: veja em "Duplicidades confirmadas" o que falta tratar.', 'success')
    return redirect(url_for('notas_fiscais.index') + '#duplicidades')


@nf_bp.route('/duplicidade/<int:id>/reabrir', methods=['POST'])
def reabrir_duplicidade(id):
    d = DecisaoDuplicidade.query.get_or_404(id)
    db.session.delete(d)
    db.session.commit()
    flash('Decisão desfeita: o grupo voltou para a lista de possíveis duplicidades.', 'info')
    return redirect(url_for('notas_fiscais.index') + '#duplicidades')


@nf_bp.route('/<int:id>/anular', methods=['POST'])
def anular(id):
    nf = NotaFiscal.query.get_or_404(id)
    if nf.status == 'anulada':
        flash('Nota fiscal já está anulada.', 'warning')
        return redirect(url_for('notas_fiscais.index'))
    if nf.lancamento_iss_id:
        lanc_iss = Lancamento.query.get(nf.lancamento_iss_id)
        if lanc_iss and lanc_iss.status == 'pago':
            flash('Não é possível anular: o ISS desta NF já foi pago. Contate a contabilidade.', 'danger')
            return redirect(url_for('notas_fiscais.index'))
        if lanc_iss and lanc_iss.status == 'pendente':
            lanc_iss.status = 'cancelado'
    nf.status = 'anulada'
    db.session.commit()
    flash('Nota fiscal anulada. O registro foi mantido para auditoria.', 'success')
    return redirect(url_for('notas_fiscais.index'))


# ── Importação de XML (NFS-e) ────────────────────────────────────────────────
def _norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    return ' '.join(''.join(c for c in s if not unicodedata.combining(c)).lower().split())


_STOP = {'de', 'da', 'do', 'das', 'dos', 'e'}


def _tokens(texto):
    return {t for t in re.findall(r'[a-z]+', _norm(texto)) if len(t) > 2 and t not in _STOP}


def _sugerir_cliente(clientes, doc, nome, descricao=''):
    """Cliente da nota. A paciente costuma estar na descrição do serviço (o tomador pode ser uma clínica):
    1) CPF completo no documento do tomador ou na descrição; 2) nome na descrição (todas as palavras do nome
    cadastrado aparecem nela, ao menos duas); 3) nome do tomador (igual ou muito parecido)."""
    cpfs = set()
    if doc and len(doc) == 11:
        cpfs.add(doc)
    cpfs |= {so_digitos(m) for m in re.findall(r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}', descricao or '')}
    for c in clientes:
        if c.cpf and so_digitos(c.cpf) in cpfs:
            return c
    palavras = _tokens(descricao)
    achados = [c for c in clientes if len(_tokens(c.nome)) >= 2 and _tokens(c.nome) <= palavras]
    if achados:
        melhor = max(len(_tokens(c.nome)) for c in achados)
        topo = [c for c in achados if len(_tokens(c.nome)) == melhor]
        if len(topo) == 1:
            return topo[0]
    alvo = _norm(nome)
    if not alvo:
        return None
    melhor_c, nota = None, 0.0
    for c in clientes:
        r = difflib.SequenceMatcher(None, alvo, _norm(c.nome)).ratio()
        if r > nota:
            melhor_c, nota = c, r
    return melhor_c if nota >= 0.9 else None


def _duplicada(d):
    """Já existe a nota? Pela chave de acesso ou por número + sistema (municipal até 2025 / nacional de 2026)."""
    if d.get('chave') and NotaFiscal.query.filter_by(chave_acesso=d['chave']).first():
        return True
    nacional = d['data_emissao'].year >= 2026
    return any((n.data_emissao.year >= 2026) == nacional
               for n in NotaFiscal.query.filter(NotaFiscal.numero == d['numero'], NotaFiscal.status != 'anulada').all())


def _liquido_da_cliente(cliente_id, bruto):
    """Valor líquido recebido: soma do contrato já recebido da cliente (descontada a taxa); senão, o bruto."""
    rec = Lancamento.query.filter(Lancamento.cliente_id == cliente_id, Lancamento.tipo == 'receita',
                                  Lancamento.status == 'recebido', Lancamento.atendimento_id.is_(None)).all()
    liq = round(sum(l.valor_liquido if l.valor_liquido is not None else l.valor for l in rec), 2)
    return liq if liq > 0 else bruto


@nf_bp.route('/importar-xml', methods=['POST'])
def importar_xml():
    """Lê os XMLs enviados e mostra a tela de conferência. Nada é salvo aqui."""
    arquivos = [a for a in request.files.getlist('arquivos') if a and a.filename]
    if not arquivos:
        flash('Escolha pelo menos um arquivo XML.', 'warning')
        return redirect(url_for('notas_fiscais.index'))
    if len(arquivos) > 50:
        flash('Envie no máximo 50 arquivos por vez.', 'warning')
        return redirect(url_for('notas_fiscais.index'))
    clientes = Cliente.query.order_by(Cliente.nome).all()
    itens = []
    vistos = set()
    lidos = [(a.filename, a.read(2 * 1024 * 1024 + 1)) for a in arquivos]
    lidos.sort(key=lambda x: x[1][:5] == b'%PDF-')   # XML primeiro: traz chave e ISS; o PDF da mesma nota é o que sobra repetido
    for nome, conteudo in lidos:
        d = ler_nfse_pdf(conteudo, nome) if conteudo[:5] == b'%PDF-' else ler_nfse(conteudo, nome)
        if not d.get('erro'):
            ids = [(d['numero'], d['data_emissao'].year >= 2026)] + ([d['chave']] if d['chave'] else [])
            if any(i in vistos for i in ids):   # mesma chave, ou mesmo número (um dos arquivos pode não trazer a chave)
                d['erro'] = 'Mesma nota de outro arquivo deste envio (o PDF e o XML da mesma nota valem uma vez só).'
            vistos.update(ids)
        if not d.get('erro'):
            d['duplicada'] = _duplicada(d)
            c = _sugerir_cliente(clientes, d['tomador_doc'], d['tomador_nome'], d.get('descricao', ''))
            d['cliente_id'] = c.id if c else None
        itens.append(d)
    centros = (CentroCusto.query.filter(CentroCusto.tipo.in_(['despesa', 'ambos']), CentroCusto.ativo == True)
               .order_by(CentroCusto.nome).all())
    padrao = _cc_imposto(centros)
    return render_template('financeiro/notas_fiscais_importar.html', itens=itens, clientes=clientes, centros=centros,
                           cc_imposto_id=padrao.id if padrao else None, aliquota_iss=ALIQUOTA_ISS)


@nf_bp.route('/importar-xml/confirmar', methods=['POST'])
def importar_xml_confirmar():
    f = request.form
    n = f.get('total', type=int) or 0
    cc_id = f.get('centro_custo_id', type=int)
    if not cc_id:
        padrao = _cc_imposto(CentroCusto.query.filter(CentroCusto.tipo.in_(['despesa', 'ambos'])).all())
        cc_id = padrao.id if padrao else None
    lancar = f.get('lancar_iss') == 'on'
    criadas, puladas = 0, []
    for i in range(n):
        if f.get(f'sel_{i}') != 'on':
            continue
        try:
            numero = f.get(f'numero_{i}', '').strip()
            cliente_id = f.get(f'cliente_{i}', type=int)
            bruto = float(f.get(f'bruto_{i}') or 0)
            iss = float(f.get(f'iss_{i}')) if f.get(f'iss_{i}') else None
            aliq = float(f.get(f'aliquota_{i}')) / 100 if f.get(f'aliquota_{i}') else None
            emissao = date.fromisoformat(f.get(f'emissao_{i}'))
            comp = date.fromisoformat(f.get(f'competencia_{i}') or f.get(f'emissao_{i}'))
        except (TypeError, ValueError):
            puladas.append(f'#{i + 1}: dados inválidos')
            continue
        chave = f.get(f'chave_{i}', '').strip() or None
        if not numero or not cliente_id or bruto <= 0:
            puladas.append(f'nota {numero or "#" + str(i + 1)}: falta cliente, número ou valor')
            continue
        if _duplicada({'chave': chave, 'numero': numero, 'data_emissao': emissao}):
            puladas.append(f'nota {numero}: já cadastrada')
            continue
        _criar_nota(numero, cliente_id, bruto, _liquido_da_cliente(cliente_id, bruto), emissao, comp.year, comp.month,
                    lancar, cc_id, valor_iss=iss, aliquota=aliq, chave=chave)
        criadas += 1
    db.session.commit()
    if criadas:
        flash(f'{criadas} nota(s) importada(s).' + (' ISS lançado em Contas a Pagar.' if lancar else ''), 'success')
    if puladas:
        flash('Não importadas: ' + '; '.join(puladas), 'warning')
    return redirect(url_for('notas_fiscais.index'))
