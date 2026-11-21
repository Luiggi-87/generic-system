# Sistema de Gestão Clínica Materna — pacote white label

Sistema web de gestão para clínicas e consultorias de acompanhamento gestacional e obstétrico: clientes (gestantes), contratos, atendimentos, financeiro completo, notas fiscais e ISS, folha de repasse das prestadoras de serviço e relatórios gerenciais.

Este pacote é **white label**: o nome, o logo, as cores e os principais parâmetros ficam em um arquivo (`marca.json`), sem mexer no código. O código-fonte vem completo e pode ser modificado.

## O que o sistema faz

| Área | O que entrega |
|---|---|
| **Clientes** | Ficha da gestante (DPP, semanas, parto, médico, hospital), contrato e plano, nova gestação com ficha própria |
| **Atendimentos** | Agenda, realização, lançamentos automáticos por procedimento, consulta rápida |
| **Financeiro** | Contas a pagar e a receber, regime de caixa e de competência, despesas recorrentes (inclusive em % do lucro bruto), taxa de cartão automática, DRE, fluxo de caixa |
| **Notas fiscais e ISS** | Importação do XML da NFS-e, ISS a pagar, baixa, painel de possíveis duplicidades, relatório de ISS do mês, contratos × ISS |
| **Folha e repasse** | Escala por horas (diurnas, noturnas e extras), rateio da receita e das despesas entre as prestadoras, fechamento com pagamentos no caixa, demonstrativo individual |
| **Notas das prestadoras** | A prestadora envia o XML da própria nota, o sistema confere com o repasse e a administração registra o pagamento |
| **Gerência** | Relatório gerencial, caixa da empresa, contas bancárias (saldo real x sistema), formas de pagamento e operadoras |
| **Acesso** | Perfis (administradora, prestadora de serviço, contabilidade) e permissão por área |

Mais detalhes comerciais em [FICHA_COMERCIAL.md](FICHA_COMERCIAL.md). Uso no dia a dia em [MANUAL_DE_UTILIZACAO.md](MANUAL_DE_UTILIZACAO.md).

## Tecnologia

- Python 3 (testado com 3.14), Flask 3, SQLAlchemy 2, Flask-Login
- Banco SQLite (um arquivo, `instance/gestao_clinica.db`), sem servidor de banco
- Telas em Jinja2 e Bootstrap 5 (carregado por CDN)

## Início rápido

```bash
# 1. dependências
pip install -r requirements.txt

# 2. (opcional) defina a senha do administrador; sem isso, uma senha aleatória aparece uma vez no console
set SENHA_INICIAL=troque-esta-senha        # Windows (cmd)
export SENHA_INICIAL=troque-esta-senha     # Linux / macOS

# 3. suba o sistema
python app.py
```

Abra http://localhost:5000 e entre com o e-mail de `email_admin` do `marca.json` (padrão `admin@exemplo.com`) e a senha definida. Na primeira execução o sistema cria o banco, as formas de pagamento, os centros de custo, procedimentos, materiais e planos de exemplo. **Troque a senha** em "Alterar senha" (ícone de chave no menu).

No Windows, `run.bat` faz o passo 3.

## Personalização em 1 minuto

Edite o `marca.json`, reinicie o sistema e pronto:

```json
{
  "nome": "Clínica Aurora",
  "subtitulo": "Painel de Gestão",
  "slogan": "Cuidado do começo ao fim",
  "cor_primaria": "#00796b",
  "cor_primaria_escura": "#004d40",
  "logo": "logo.png"
}
```

Coloque o arquivo do logo em `static/`. Todas as opções estão em [GUIA_DE_PERSONALIZACAO.md](GUIA_DE_PERSONALIZACAO.md).

## Instalação em servidor

Passo a passo para PythonAnywhere, VPS (Linux com Gunicorn e Nginx) e para rodar em um computador da clínica: [INSTALACAO.md](INSTALACAO.md).

## Estrutura do projeto

```
app.py                  aplicação, login, painel e dados iniciais
marca.json / marca.py   identidade visual e parâmetros (edite o .json)
models.py               tabelas do banco
permissoes.py           áreas e perfis de acesso
routes/                 uma pasta de telas por módulo (clientes, financeiro, folha, notas fiscais...)
templates/              páginas (Jinja2)
static/                 arquivos estáticos (coloque o logo aqui)
servicos_financeiros.py regras financeiras compartilhadas (taxas, recorrências, backup)
taxas.py                tabela de exemplo das taxas de cartão
run_migration.py        atualiza o banco ao instalar uma versão nova
```

## Antes de entregar a um cliente

- [ ] Defina o `marca.json` (nome, cores, logo, e-mail do administrador).
- [ ] Use um **banco novo** por cliente. Nunca reaproveite o `instance/` de outra instalação.
- [ ] Defina `SENHA_INICIAL` e `SECRET_KEY` próprios por cliente (ver INSTALACAO.md).
- [ ] Confira as **taxas de cartão** (Gerência > Formas de Pagamento) e a **alíquota do ISS** do município.
- [ ] Revise os **centros de custo, procedimentos e planos de exemplo** e ajuste ao cliente.
- [ ] Cadastre as prestadoras de serviço e os usuários (Usuários e Permissões).
- [ ] Configure o backup (ver INSTALACAO.md) e o HTTPS.

## Licença

Ver [LICENCA_MODELO.md](LICENCA_MODELO.md) (modelo para adaptar à sua operação comercial).
