import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def django_db_setup(django_test_environment, django_db_blocker, postgres_container):
    from django.conf import settings

    settings.DATABASES["default"]["NAME"] = postgres_container.dbname
    settings.DATABASES["default"]["USER"] = postgres_container.username
    settings.DATABASES["default"]["PASSWORD"] = postgres_container.password
    settings.DATABASES["default"]["HOST"] = postgres_container.get_container_host_ip()
    settings.DATABASES["default"]["PORT"] = postgres_container.get_exposed_port(5432)

    with django_db_blocker.unblock():
        from django.core.management import call_command

        call_command("migrate", "--run-syncdb")
