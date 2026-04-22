from django.test.runner import DiscoverRunner


class TeardownSafeTestRunner(DiscoverRunner):
    def teardown_databases(self, old_config, **kwargs):
        for connection, _old_name, destroy in old_config:
            if destroy and connection.vendor == "postgresql":
                test_db_name = connection.settings_dict["NAME"]
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_terminate_backend(pid) "
                            "FROM pg_stat_activity "
                            "WHERE datname = %s AND pid <> pg_backend_pid()",
                            [test_db_name],
                        )
                except Exception:
                    pass
        super().teardown_databases(old_config, **kwargs)
