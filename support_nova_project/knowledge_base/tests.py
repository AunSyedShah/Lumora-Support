import shutil
import tempfile

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from accounts.auth import ACCESS, create_token
from accounts.models import User

from .chunking import chunk_blocks
from .models import DocumentStatus, PolicyDocument
from .parsing import Block

SAMPLES = settings.BASE_DIR / "sample_documents"
TEMP_MEDIA = tempfile.mkdtemp()


def text_doc(doc_id="TST-POL", version="1.0", status="Active", effective="2026-01-01", body=None):
    """Build a small .txt policy with a metadata header."""
    body = body or "## 1. Scope\nThis test policy covers warranty repairs for Lumora devices.\n"
    return (
        f"# Test Policy\n"
        f"Document ID: {doc_id} | Version: {version} | Type: Policy | Status: {status}\n"
        f"Effective Date: {effective}\n{body}"
    ).encode()


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class KnowledgeBaseApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)
        cls.admin = User.objects.create_user("admin1", password="x", role=User.Role.ADMIN)
        cls.agent = User.objects.create_user("agent1", password="x", role=User.Role.AGENT)
        cls.customer = User.objects.create_user("cust1", password="x")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def headers(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_token(user, ACCESS)}"}

    def upload(self, name, data, user=None, **form):
        payload = {"file": SimpleUploadedFile(name, data), **form}
        return self.client.post("/api/kb/documents", payload, **self.headers(user or self.admin))

    def upload_sample(self, name, **form):
        return self.upload(name, (SAMPLES / name).read_bytes(), **form)

    # ---------- parsing real PDF / DOCX ----------

    def test_upload_pdf_reads_header_and_sections(self):
        res = self.upload_sample("refund_policy_v2.pdf")
        self.assertEqual(res.status_code, 201, res.content)
        doc = res.json()["document"]
        self.assertEqual((doc["doc_id"], doc["version"], doc["status"]), ("REF-POL", "2.0", "active"))
        self.assertEqual(doc["effective_date"], "2026-01-01")  # needs ligature normalisation
        self.assertEqual(doc["category"], "REFUND")
        self.assertEqual(doc["page_count"], 2)

        chunks = self.client.get(f"/api/kb/documents/{doc['id']}/chunks", **self.headers(self.agent)).json()
        sections = [c["section"] for c in chunks]
        self.assertIn("2.1", sections)
        self.assertIn("4.2", sections)
        self.assertTrue(all(c["page"] for c in chunks))
        self.assertTrue(chunks[0]["chunk_id"].startswith("REF-POL-v2.0-"))

    def test_upload_docx(self):
        res = self.upload_sample("delivery_policy.docx")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["document"]["doc_id"], "DEL-POL")
        self.assertGreaterEqual(res.json()["document"]["chunk_count"], 8)

    # ---------- version control ----------

    def test_new_active_version_supersedes_old_ones(self):
        self.upload_sample("refund_policy_v1.docx")
        res = self.upload_sample("refund_policy_v2.pdf")
        self.assertIn("now marked Previous", " ".join(res.json()["warnings"]))
        self.assertEqual(PolicyDocument.objects.get(version="1.0").status, DocumentStatus.PREVIOUS)

        self.upload("ref_v3.txt", text_doc("REF-POL", "3.0", effective="2026-06-01"))
        statuses = dict(PolicyDocument.objects.values_list("version", "status"))
        self.assertEqual(statuses, {"1.0": "superseded", "2.0": "previous", "3.0": "active"})

    def test_cannot_activate_version_older_than_current_active(self):
        self.upload_sample("refund_policy_v2.pdf")
        res = self.upload_sample("refund_policy_v1.docx")
        self.assertEqual(res.status_code, 409)
        # ...but it can be stored as history
        res = self.upload_sample("refund_policy_v1.docx", status="previous")
        self.assertEqual(res.status_code, 201)

    def test_patch_status_to_active_reapplies_versioning(self):
        self.upload("a.txt", text_doc(version="1.0"))
        draft = self.upload("b.txt", text_doc(version="2.0", status="Draft")).json()["document"]
        res = self.client.patch(
            f"/api/kb/documents/{draft['id']}", {"status": "active"},
            content_type="application/json", **self.headers(self.admin),
        )
        self.assertEqual(res.json()["status"], "active")
        self.assertEqual(PolicyDocument.objects.get(version="1.0").status, DocumentStatus.PREVIOUS)

    # ---------- validation ----------

    def test_duplicate_file_rejected(self):
        self.upload_sample("delivery_policy.docx")
        self.assertEqual(self.upload_sample("delivery_policy.docx").status_code, 409)

    def test_duplicate_doc_id_and_version_rejected(self):
        self.upload("a.txt", text_doc(version="1.0"))
        res = self.upload("b.txt", text_doc(version="1.0", body="## 1. Other\nDifferent content here, long enough to pass.\n"))
        self.assertEqual(res.status_code, 409)

    def test_bad_files_rejected(self):
        self.assertEqual(self.upload("virus.exe", b"MZ...").status_code, 400)
        self.assertEqual(self.upload("empty.pdf", b"").status_code, 400)
        self.assertEqual(self.upload("fake.pdf", b"just text renamed to pdf").status_code, 400)

    def test_missing_metadata_rejected(self):
        res = self.upload("plain.txt", b"1. Scope\nSome policy text without any header information at all.")
        self.assertEqual(res.status_code, 400)
        self.assertIn("doc_id", res.json()["detail"])

    def test_form_values_override_header(self):
        res = self.upload("a.txt", text_doc(status="Active"), status="draft", doc_id="FORM-ID")
        doc = res.json()["document"]
        self.assertEqual((doc["doc_id"], doc["status"]), ("FORM-ID", "draft"))

    def test_blank_form_fields_fall_back_to_header(self):
        """Swagger/HTML forms send '' for empty fields; those must not override the header."""
        res = self.upload_sample("delivery_policy.docx", doc_id="", doc_type="", status="", effective_date="")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["document"]["doc_id"], "DEL-POL")

    def test_expiry_must_be_after_effective(self):
        res = self.upload("a.txt", text_doc(), expiry_date="2025-01-01")
        self.assertEqual(res.status_code, 400)

    # ---------- permissions ----------

    def test_permissions(self):
        self.assertEqual(self.upload("a.txt", text_doc(), user=self.agent).status_code, 403)
        self.assertEqual(self.client.get("/api/kb/documents", **self.headers(self.customer)).status_code, 403)
        self.assertEqual(self.client.get("/api/kb/documents", **self.headers(self.agent)).status_code, 200)

    def test_only_drafts_can_be_deleted(self):
        active = self.upload("a.txt", text_doc(version="1.0")).json()["document"]
        draft = self.upload("b.txt", text_doc(version="2.0", status="Draft")).json()["document"]
        admin = self.headers(self.admin)
        self.assertEqual(self.client.delete(f"/api/kb/documents/{active['id']}", **admin).status_code, 409)
        self.assertEqual(self.client.delete(f"/api/kb/documents/{draft['id']}", **admin).status_code, 204)

    # ---------- retrieval ----------

    def test_search_finds_section_and_ignores_outdated_versions(self):
        self.upload_sample("refund_policy_v1.docx")
        self.upload_sample("refund_policy_v2.pdf")
        hits = self.client.get(
            "/api/kb/search", {"q": "refund window days after delivery"}, **self.headers(self.agent)
        ).json()
        self.assertTrue(hits)
        self.assertEqual(hits[0]["doc_id"], "REF-POL")
        self.assertTrue(all(h["version"] == "2.0" for h in hits))  # v1.0 is 'previous' -> never returned

    def test_future_effective_document_not_searchable_yet(self):
        self.upload("f.txt", text_doc(effective="2099-01-01"))
        hits = self.client.get("/api/kb/search", {"q": "warranty repairs"}, **self.headers(self.agent)).json()
        self.assertEqual(hits, [])


class ChunkingTests(TestCase):
    def test_numbered_list_sentence_is_not_a_heading(self):
        blocks = [
            Block("1. Delays", heading_hint=True),
            Block("Follow these steps:"),
            Block("1. Check the courier tracking status."),  # ends with '.', not bold -> body text
        ]
        chunks = chunk_blocks(blocks)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].section, "1")
        self.assertIn("Check the courier", chunks[0].text)

    def test_document_without_title_keeps_its_first_section(self):
        from .parsing import ParsedDocument, count_header_blocks, extract_header_metadata

        parsed = ParsedDocument(blocks=[
            Block("Document ID: X-POL | Version: 1.0"),
            Block("2.1 First Rule", heading_hint=True),
            Block("Body text of the first rule."),
        ])
        meta = extract_header_metadata(parsed)
        self.assertNotIn("title", meta)
        chunks = chunk_blocks(parsed.blocks, count_header_blocks(parsed, meta.get("title")))
        self.assertEqual(chunks[0].section, "2.1")

    def test_long_section_is_split_but_keeps_section(self):
        long_text = "This sentence is part of a long section. " * 80
        chunks = chunk_blocks([Block("2.1 Long Section"), Block(long_text)])
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.section == "2.1" for c in chunks))
