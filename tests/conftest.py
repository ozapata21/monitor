import os
import tempfile

# Debe ejecutarse antes de importar app.*
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/test.db"
# Aísla los tests del .env local
os.environ["FIRST_ADMIN_USERNAME"] = "admin"
os.environ["FIRST_ADMIN_PASSWORD"] = "ChangeMe123!"
