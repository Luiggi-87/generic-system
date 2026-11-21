"""
Executa migrações de banco de dados (colunas novas em tabelas existentes).
Rode UMA VEZ após atualizar o código:

    python run_migration.py
"""

from models import db
from sqlalchemy import text
from servicos_financeiros import (
    sincronizar_todas, preencher_vencimentos, backup_banco, seed_formas_pagamento,
)


MIGRATIONS = [
    # Auditoria: data da última edição de um lançamento
    "ALTER TABLE lancamentos ADD COLUMN updated_at DATETIME",
    # Soft-delete de NF: status emitida/anulada
    "ALTER TABLE notas_fiscais ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'emitida'",
    # Profissional que realizou o atendimento
    "ALTER TABLE atendimentos ADD COLUMN profissional VARCHAR(100)",
    # Detalhes de pagamentos (JSON) nas receitas da folha
    "ALTER TABLE receitas_folha ADD COLUMN detalhes_pagamentos TEXT DEFAULT ''",
    # Operadora do cartão (tom/infinite)
    "ALTER TABLE lancamentos ADD COLUMN operadora VARCHAR(50) DEFAULT 'tom'",
    # Formas de pagamento: prazo de recebimento e observações
    "ALTER TABLE formas_pagamento ADD COLUMN prazo VARCHAR(200)",
    "ALTER TABLE formas_pagamento ADD COLUMN observacoes TEXT",
    # Como a taxa da forma é calculada (nenhuma/debito/credito)
    "ALTER TABLE formas_pagamento ADD COLUMN tipo_taxa VARCHAR(10)",
    # Despesas recorrentes (modelo + cópias mensais)
    "ALTER TABLE lancamentos ADD COLUMN recorrente BOOLEAN DEFAULT 0",
    "ALTER TABLE lancamentos ADD COLUMN dia_recorrencia INTEGER",
    "ALTER TABLE lancamentos ADD COLUMN recorrencia_origem_id INTEGER REFERENCES lancamentos(id)",
    # Recorrente com valor = % do lucro bruto do mês
    "ALTER TABLE lancamentos ADD COLUMN percentual_lucro FLOAT",
    # Usuários: perfil (os já existentes ficam administradores), áreas liberadas e funcionária vinculada
    "ALTER TABLE usuarios ADD COLUMN perfil VARCHAR(20) DEFAULT 'admin'",
    "ALTER TABLE usuarios ADD COLUMN permissoes TEXT DEFAULT ''",
    "ALTER TABLE usuarios ADD COLUMN funcionario_id INTEGER REFERENCES funcionarios(id)",
    # Atendimento: valor direcionado a uma funcionária (senão, rateio); receita da folha ligada ao atendimento
    "ALTER TABLE atendimentos ADD COLUMN funcionario_id INTEGER REFERENCES funcionarios(id)",
    "ALTER TABLE receitas_folha ADD COLUMN atendimento_id INTEGER REFERENCES atendimentos(id)",
    # NFS-e importada de XML: chave de acesso
    "ALTER TABLE notas_fiscais ADD COLUMN chave_acesso VARCHAR(60)",
    # Cliente: grupo de parto / plantão (o médico pré-natalista continua em medico_grupo)
    "ALTER TABLE clientes ADD COLUMN grupo_parto VARCHAR(150)",
    # Folha: despesas do mês rateadas entre as prestadoras (gravadas no fechamento)
    "ALTER TABLE periodos_folha ADD COLUMN custos_rateados FLOAT",
    # Conta bancária: cada saldo registrado pertence a uma conta
    "ALTER TABLE saldos_bancarios ADD COLUMN conta_id INTEGER REFERENCES contas_bancarias(id)",
]


def run(flask_app=None):
    """Aplica as migrações. Chamada no início do sistema (app.py e wsgi.py) ou pelo terminal."""
    if flask_app is None:
        from app import app as flask_app
    with flask_app.app_context():
        with db.engine.connect() as conn:
            for sql in MIGRATIONS:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                    print(f"OK  {sql[:60]}...")
                except Exception as e:
                    # coluna que já existe é o caso normal depois da 1ª execução: não polui o log
                    if 'duplicate column' not in str(e).lower():
                        print(f"ERRO na migração — {sql[:60]}... — {e}")
        db.create_all()  # tabelas novas (ex.: formas_pagamento)
        seed_formas_pagamento()
        corrigir_dados()
        print("Migração concluída.")


def corrigir_dados():
    """Correções de dados idempotentes (taxas de cartão e vencimentos). Faz backup se alterar algo."""
    verificadas, orfas = sincronizar_todas()
    venc = preencher_vencimentos()
    mudou = bool(db.session.new or db.session.dirty or db.session.deleted)
    if not mudou:
        print("OK  dados financeiros já consistentes")
        return
    print("BACKUP", backup_banco())  # antes do commit: o arquivo ainda está intacto
    db.session.commit()
    print(f"OK  taxas reconciliadas ({verificadas} receitas, {orfas} órfãs removidas); "
          f"{venc} contrato(s) pendente(s) com vencimento preenchido")


if __name__ == "__main__":
    run()
