"""Identidade e parâmetros do sistema, lidos de marca.json (edite o arquivo; não precisa mexer no código).

Para usar outro arquivo (por exemplo, uma marca por cliente), defina a variável de ambiente MARCA_ARQUIVO.
Reinicie o sistema depois de alterar o arquivo."""
import json
import os

PADRAO = {
    'nome': 'Sua Marca',                 # aparece no menu, no login, nos relatórios e nos títulos
    'subtitulo': 'Sistema de Gestão',    # abaixo do nome, no menu e no login
    'slogan': 'Gestão clínica e financeira',   # no cabeçalho dos relatórios impressos
    'icone': 'heart-pulse-fill',         # ícone do Bootstrap Icons (https://icons.getbootstrap.com), se não houver logo
    'logo': '',                          # arquivo dentro de static/ (ex.: "logo.png"); vazio = usa o ícone
    'cor_primaria': '#1d6fa5',
    'cor_primaria_escura': '#0f4c75',
    'cor_secundaria': '#6a4c93',
    'cor_destaque': '#cfe6f5',
    'cor_menu': '#0b2a40',
    'cor_menu_texto': '#d6e6f2',
    'cor_fundo': '#f2f5f8',
    'email_admin': 'admin@exemplo.com',  # usuário administrador criado na 1ª execução
    'aliquota_iss': 0.06,                # ISS sobre as notas (0.06 = 6%)
    'fator_hora_noturna': 1.25,          # a hora noturna vale este fator da diurna, no rateio da Folha
    'rateio_custos_desde': '2000-01',    # AAAA-MM: a partir daqui as despesas do mês são rateadas entre as prestadoras
}


def _rgb(cor):
    cor = cor.lstrip('#')
    return ','.join(str(int(cor[i:i + 2], 16)) for i in (0, 2, 4))


def carregar():
    caminho = os.environ.get('MARCA_ARQUIVO') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'marca.json')
    marca = dict(PADRAO)
    try:
        with open(caminho, encoding='utf-8') as f:
            marca.update({k: v for k, v in json.load(f).items() if k in PADRAO})
    except FileNotFoundError:
        pass
    marca['cor_primaria_rgb'] = _rgb(marca['cor_primaria'])
    return marca


MARCA = carregar()
