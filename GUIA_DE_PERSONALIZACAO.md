# Guia de personalização

Do mais simples (um arquivo de texto) ao mais profundo (alterar o código).

## 1. Identidade visual: `marca.json`

Edite o arquivo e **reinicie o sistema**. Nada mais é necessário.

| Chave | O que muda | Exemplo |
|---|---|---|
| `nome` | Menu lateral, login, títulos das páginas, cabeçalho dos relatórios | `"Clínica Aurora"` |
| `subtitulo` | Texto abaixo do nome, no menu e no login | `"Painel de Gestão"` |
| `slogan` | Cabeçalho dos relatórios impressos | `"Cuidado do começo ao fim"` |
| `icone` | Ícone do menu e do login, quando não há logo ([lista de ícones](https://icons.getbootstrap.com)) | `"flower1"` |
| `logo` | Imagem dentro de `static/` que substitui o ícone | `"logo.png"` |
| `cor_primaria` | Botões, destaques, links e títulos | `"#00796b"` |
| `cor_primaria_escura` | Cabeçalhos, hover dos botões | `"#004d40"` |
| `cor_secundaria` | Cartões e detalhes em segunda cor | `"#6a4c93"` |
| `cor_destaque` | Faixas, bordas e fundos suaves | `"#cfe6f5"` |
| `cor_menu` / `cor_menu_texto` | Fundo e texto do menu lateral | `"#0b2a40"` / `"#d6e6f2"` |
| `cor_fundo` | Fundo das páginas | `"#f2f5f8"` |
| `email_admin` | Usuário administrador criado na primeira execução | `"dona@aurora.com.br"` |

Dicas:
- **Logo:** use PNG com fundo transparente, na horizontal (altura exibida: 26 px no menu e 56 px no login). Um logo escuro some no menu escuro: use a versão clara.
- **Cores:** escolha uma primária de bom contraste com branco (os botões têm texto branco). Teste em [coolors.co](https://coolors.co) ou parecido.
- **Várias marcas, um código:** aponte a variável de ambiente `MARCA_ARQUIVO` para um `.json` diferente por instalação.

## 2. Regras de negócio configuráveis

Também em `marca.json`:

| Chave | Significado | Padrão |
|---|---|---|
| `aliquota_iss` | Alíquota do ISS sobre as notas (0.06 = 6%). Confira a do município do cliente | `0.06` |
| `fator_hora_noturna` | A hora noturna vale este fator da diurna no rateio da Folha | `1.25` |
| `rateio_custos_desde` | `AAAA-MM`: a partir deste mês as despesas são rateadas entre as prestadoras (mesmo % para todas). Antes dele vale o desconto individual cadastrado em cada prestadora | `"2000-01"` (sempre rateio) |

Outros ajustes simples, direto no código:

- `permissoes.py`: `OCULTAR_REPASSE_DAS_PRESTADORAS = True` esconde das prestadoras a Folha e o demonstrativo (por exemplo, enquanto a administração ajusta valores).
- `permissoes.py`: lista `AREAS` (áreas do sistema) e `PERFIS_PRONTOS` (marcações rápidas ao criar um usuário).
- `taxas.py`: tabela de **exemplo** das taxas de cartão. Em produção, edite pela tela **Gerência > Formas de Pagamento**.

## 3. Dados iniciais

Na primeira execução, `app.py` cria (só se o banco estiver vazio):

- **Centros de custo** `CC001` a `CC007`. Atenção: o código usa `CC005` para taxas de cartão e `CC006` para a folha; mantenha esses dois códigos. Os nomes podem ser alterados na tela.
- **Procedimentos, materiais e planos** de exemplo (funções `seed_dados_iniciais` e `seed_planos`). Edite a lista no código para o seu modelo de negócio, ou ajuste depois pela tela.
- **Formas de pagamento** e **operadoras** (`servicos_financeiros.py`).
- Nenhuma prestadora e nenhum cliente. O único usuário é o administrador de `email_admin`.

## 4. Textos e telas

- **Textos das telas:** estão em `templates/` (Jinja2). Procure o texto com o editor e altere.
- **Cabeçalho dos relatórios impressos:** `templates/relatorios/_faturamento_css.html` (estilos) e os próprios arquivos de `templates/relatorios/` e `templates/folha/relatorio.html`.
- **Menu lateral:** `templates/base.html` (cada item usa `pode('area')` para respeitar as permissões).
- **Idioma e moeda:** o sistema é em português do Brasil, em reais. O formato de data e de moeda está nos filtros `data_br` e `brl`, em `app.py`.

## 5. Alterar o código (para desenvolvedores)

Estrutura em camadas simples:

- `models.py`: as tabelas. Para **adicionar uma coluna** a uma tabela existente, declare-a no modelo e acrescente uma linha `ALTER TABLE ...` na lista `MIGRATIONS` de `run_migration.py` (o script é seguro para rodar várias vezes: ignora o que já existe). Tabelas novas são criadas sozinhas por `db.create_all()`.
- `routes/`: uma pasta por módulo, cada um com um `Blueprint`. Para uma tela nova, crie o blueprint, registre-o em `app.py` e inclua sua área em `permissoes.py` (`_BLUEPRINT_AREA`) para a permissão funcionar.
- `servicos_financeiros.py`: regras reutilizadas em mais de uma tela (taxa de cartão, recorrências, backup do banco).
- Regras do repasse: `routes/folha.py` (cálculo e fechamento) e `routes/relatorio_faturamento.py` (relatório e demonstrativo).

Boas práticas:
- Faça alterações em um **ramo** (git) e teste em um banco de teste (copie a pasta e use um `instance/` vazio).
- Antes de mexer em regras financeiras, faça uma **cópia do banco** (`instance/gestao_clinica.db`).
- Não ponha dados de clientes reais dentro do código nem no Git.

## 6. Uma instalação por cliente

Recomendado quando você vende para vários clientes:

1. Uma pasta (ou servidor) por cliente, com o código deste pacote.
2. Um `marca.json` por cliente.
3. Banco de dados, `SECRET_KEY` e senha do administrador próprios.
4. Para atualizar um cliente: copie a versão nova do código **sem** apagar `instance/` nem `marca.json`, e rode `python run_migration.py`.
