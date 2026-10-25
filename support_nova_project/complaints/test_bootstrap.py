from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from catalog.models import Department
from genai_pipeline.models import PromptTemplate
from rules.models import ResolutionRule


class BootstrapDataTests(TestCase):
    def run_bootstrap(self, *args):
        out = StringIO()
        call_command("bootstrap_data", "--skip-documents", *args, stdout=out)
        return out.getvalue()

    def test_an_empty_database_gets_everything_and_a_second_run_changes_nothing(self):
        first = self.run_bootstrap()
        self.assertIn("loaded: catalog", first)
        self.assertTrue(Department.objects.exists() and ResolutionRule.objects.exists())
        self.assertTrue(PromptTemplate.objects.filter(is_active=True).exists())
        self.assertTrue(User.objects.filter(username="admin", role=User.Role.ADMIN).exists())
        customers = User.objects.filter(role=User.Role.CUSTOMER).count()
        self.assertGreater(customers, 0)

        second = self.run_bootstrap()
        self.assertNotIn("loading", second)
        self.assertEqual(User.objects.filter(role=User.Role.CUSTOMER).count(), customers)

    def test_a_database_that_already_has_data_is_left_alone(self):
        User.objects.create_user("existing_admin", password="x", role=User.Role.ADMIN)
        out = self.run_bootstrap()
        self.assertIn("already there: demo accounts and orders", out)
        self.assertFalse(User.objects.filter(username="cust001").exists())  # the demo customers were not added on top
