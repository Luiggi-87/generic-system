# Instalação

## Requisitos

- Python 3.11 ou mais novo (testado com 3.14)
- Acesso à internet nas telas (o Bootstrap é carregado por CDN)
- Para leitura de PDF de nota fiscal, o pacote `pypdf` (já está no `requirements.txt`)

## Variáveis de ambiente

| Variável | Para quê | Obrigatória |
|---|---|---|
| `SECRET_KEY` | Assina as sessões de login. Use um texto longo e aleatório, diferente por cliente. Se faltar, o sistema gera um arquivo `instance/secret.key` na primeira execução | recomendada em produção |
| `SENHA_INICIAL` | Senha do administrador criado na primeira execução. Se faltar, uma senha aleatória aparece uma única vez no console | recomendada |
| `MARCA_ARQUIVO` | Caminho de outro `marca.json` (uma marca por instalação) | não |
| `HOST` / `PORT` | Endereço e porta do `python app.py` (padrão `127.0.0.1` e `5000`). Use `HOST=0.0.0.0` para acessar de outros computadores da rede | não |
| `FLASK_DEBUG` | `1` liga o modo de depuração. **Nunca use em produção** | não |
| `REPORT_API_KEY` | Ativa a API de leitura (somente consulta) protegida por chave. Sem ela, a API fica desativada | não |
| `DEPLOY_WEBHOOK_SECRET` | Ativa a rota de deploy automático por webhook, que executa um `deploy.sh` que você deve criar. Sem ela, a rota fica desativada | não |

## A. Computador da clínica (Windows)

1. Instale o Python (marque "Add Python to PATH").
2. Abra a pasta do sistema, abra um terminal ali e rode `pip install -r requirements.txt`.
3. Defina a senha: `set SENHA_INICIAL=sua-senha`.
4. Dê dois cliques em `run.bat`, ou rode `python app.py`.
5. Acesse http://localhost:5000. Para acessar de outros computadores da rede, defina `HOST=0.0.0.0` antes de subir e libere a porta 5000 no firewall.

Esse modo serve para uso interno e testes. Para acesso pela internet, use as opções B ou C.

## B. PythonAnywhere (simples, com HTTPS pronto)

1. Crie uma conta em pythonanywhere.com e abra o console **Bash**.
2. Envie a pasta do sistema (upload de um `.zip` ou `git clone` de um repositório privado seu) para `~/gestao_clinica`.
3. No Bash: `cd ~/gestao_clinica && pip install --user -r requirements.txt`.
4. Na aba **Web**, crie uma aplicação **Flask (manual configuration)** com o Python correspondente.
5. No arquivo WSGI, aponte para o projeto. O `wsgi.py` do pacote serve de modelo: ajuste `project_home` com o seu usuário e a pasta.
6. Na aba Web, em **Environment variables**, defina `SECRET_KEY` e `SENHA_INICIAL`.
7. Clique em **Reload**. O banco e os dados iniciais são criados no primeiro acesso.
8. Para atualizar depois: envie os arquivos novos (sem apagar `instance/` nem `marca.json`), rode `python run_migration.py` no Bash e faça **Reload**.

O plano gratuito atende para testes e clínicas pequenas; para produção avalie um plano pago (mais folga de recursos e domínio próprio).

## C. Servidor próprio (Linux, Gunicorn + Nginx)

```bash
sudo apt install python3-venv nginx
cd /opt && sudo mkdir gestao && sudo chown $USER gestao && cd gestao
# copie o sistema para esta pasta
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt gunicorn
export SECRET_KEY="texto-longo-e-aleatorio" SENHA_INICIAL="sua-senha"
gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app
```

- Rode o Gunicorn como serviço (systemd) com as variáveis de ambiente definidas no arquivo da unidade.
- No Nginx, faça um `proxy_pass http://127.0.0.1:8000;` para o domínio do cliente e ative o HTTPS (Certbot / Let's Encrypt).
- Como o banco é SQLite, mantenha **poucos processos** (2 a 4 workers bastam para uma clínica).
- O `wsgi.py` do pacote tem um caminho de exemplo (`project_home`): ajuste para a pasta do servidor.

## Primeiro acesso

1. Entre com o e-mail de `email_admin` (em `marca.json`) e a senha definida.
2. Troque a senha (ícone de chave).
3. Crie os demais usuários em **Usuários e Permissões**.
4. Cadastre as prestadoras (Folha de Pagamento > Prestadores de serviço) e ajuste centros de custo, procedimentos, planos, formas de pagamento e taxas.

## Backup

O sistema inteiro de dados está em **um arquivo**: `instance/gestao_clinica.db`.

- **Diário:** copie o arquivo para outro lugar (outro disco, nuvem). Em Linux, um `cron` com `sqlite3 instance/gestao_clinica.db ".backup '/caminho/backup.db'"` gera uma cópia consistente mesmo com o sistema em uso.
- Os scripts de correção em lote, quando você criar os seus, devem usar `backup_banco()` (em `servicos_financeiros.py`), que grava em `instance/backups/`.
- Guarde as cópias fora do servidor. Teste a restauração de tempos em tempos.

## Segurança

- Use **HTTPS** sempre que o sistema estiver na internet.
- Senhas fortes e únicas por usuário; o sistema bloqueia temporariamente tentativas de login repetidas.
- Os dados das clientes são sensíveis (LGPD): restrinja os acessos pelas permissões e mantenha o servidor atualizado.
- Não envie o `instance/` (banco e chave) para repositórios nem por e-mail.

## Atualização do sistema

1. Faça **backup** do banco.
2. Substitua o código, mantendo `instance/` e `marca.json`.
3. Rode `python run_migration.py` (adiciona colunas e tabelas novas, sem apagar dados).
4. Reinicie o sistema.
