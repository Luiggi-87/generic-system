import sys

project_home = '/home/SEU_USUARIO/gestao_clinica'   # ajuste: pasta do projeto no servidor
if project_home not in sys.path:
    sys.path.insert(0, project_home)

from app import app, db

import time

# Inicialização com novas tentativas: se o banco estiver bloqueado por alguns segundos (deploy, backup),
# o site não deve deixar de subir por isso.
for tentativa in range(1, 6):
    try:
        with app.app_context():
            db.create_all()
            from app import seed_dados_iniciais, seed_planos, seed_funcionarios, seed_usuario, seed_formas
            seed_formas()
            seed_dados_iniciais()
            seed_planos()
            seed_funcionarios()
            seed_usuario()
        break
    except Exception as e:
        print(f'Inicialização do banco falhou (tentativa {tentativa}/5): {e}')
        with app.app_context():
            db.session.rollback()
        if tentativa == 5:
            raise
        time.sleep(3)

application = app
