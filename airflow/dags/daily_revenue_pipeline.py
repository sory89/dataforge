"""Pipeline quotidien : seed -> dbt build -> data quality -> notification."""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

DBT_DIR = "/opt/airflow/dbt"

default_args = {
    "owner": "dataforge",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def notify_success(**context) -> None:
    """Hook de notification (Slack/Teams en réel)."""
    print(f"Pipeline OK pour {context['ds']}")


with DAG(
    dag_id="daily_revenue_pipeline",
    schedule="0 6 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["dbt", "revenue"],
) as dag:
    dbt_seed = BashOperator(
        task_id="dbt_seed",
        bash_command=f"cd {DBT_DIR} && dbt seed --target prod",
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"cd {DBT_DIR} && dbt build --target prod --exclude-resource-type seed",
    )

    dbt_test_critical = BashOperator(
        task_id="dbt_test_critical",
        bash_command=f"cd {DBT_DIR} && dbt test --select tag:critical --target prod",
    )

    notify = PythonOperator(task_id="notify_success", python_callable=notify_success)

    dbt_seed >> dbt_build >> dbt_test_critical >> notify
