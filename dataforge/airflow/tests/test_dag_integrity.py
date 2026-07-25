"""Test d'intégrité : tous les DAGs s'importent sans erreur ni cycle."""
from pathlib import Path

from airflow.models import DagBag

DAGS_DIR = Path(__file__).parents[1] / "dags"


def test_no_import_errors():
    dagbag = DagBag(dag_folder=str(DAGS_DIR), include_examples=False)
    assert not dagbag.import_errors, f"Erreurs d'import DAG : {dagbag.import_errors}"


def test_dags_have_required_settings():
    dagbag = DagBag(dag_folder=str(DAGS_DIR), include_examples=False)
    for dag_id, dag in dagbag.dags.items():
        assert dag.catchup is False, f"{dag_id} : catchup doit être False"
        assert dag.default_args.get("retries", 0) >= 1, f"{dag_id} : retries manquants"
        assert dag.tags, f"{dag_id} : tags obligatoires"
