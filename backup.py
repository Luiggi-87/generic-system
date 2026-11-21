"""
Gera uma cópia de segurança do banco em instance/backups/.

    python backup.py

Use antes de atualizar o sistema ou agende este comando (Agendador de Tarefas do Windows).
"""

from app import app
from servicos_financeiros import backup_banco

if __name__ == '__main__':
    with app.app_context():
        print('Backup gerado em:', backup_banco())
