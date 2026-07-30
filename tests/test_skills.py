from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allpath_agent.storage import Database, MemoryRepository
from allpath_agent.tools import SkillCatalog, WorkspaceAccessError, create_builtin_registry
from allpath_agent.tools.skills import default_skill_roots


class SkillCatalogTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.builtin = self.root / "builtin"
        self.user = self.root / "user"
        self.project = self.root / "project"
        self._write_skill(self.builtin, "example", "Builtin description", "Builtin body")
        self._write_skill(self.user, "example", "User description", "User body")
        self.catalog = SkillCatalog(
            (
                (self.builtin, "builtin"),
                (self.user, "user"),
                (self.project, "project"),
            )
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_later_source_overrides_builtin_and_list_is_metadata_only(self) -> None:
        listed = self.catalog.list_metadata()
        self.assertEqual(
            listed,
            [{"name": "example", "description": "User description", "source": "user"}],
        )
        self.assertNotIn("User body", str(listed))

    def test_view_loads_full_skill_and_supporting_file(self) -> None:
        skill_directory = self.user / "example"
        references = skill_directory / "references"
        references.mkdir()
        (references / "guide.md").write_text("supporting content", encoding="utf-8")

        main = self.catalog.view("example")
        supporting = self.catalog.view("example", "references/guide.md")
        self.assertIn("User body", main["content"])
        self.assertEqual(supporting["content"], "supporting content")

    def test_view_rejects_traversal_and_symlink(self) -> None:
        outside = self.root / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        (self.user / "example" / "linked.md").symlink_to(outside)
        for path in ("../outside.md", "linked.md"):
            with self.subTest(path=path), self.assertRaises(WorkspaceAccessError):
                self.catalog.view("example", path)

    def test_explicit_invocation_embeds_skill_as_user_turn_context(self) -> None:
        expanded = self.catalog.expand_invocation("/example analyze this project")
        self.assertIn("User body", expanded)
        self.assertIn("User instruction: analyze this project", expanded)
        self.assertIsNone(self.catalog.expand_invocation("/missing do something"))

    def test_builtin_package_skills_are_discoverable_and_registered(self) -> None:
        home = self.root / "home"
        workspace = self.root / "workspace"
        workspace.mkdir()
        roots = default_skill_roots(home, workspace)
        names = {item["name"] for item in SkillCatalog(roots).list_metadata()}
        self.assertIn("repository-analysis", names)

        database = Database(self.root / "state.db")
        database.initialize()
        registry = create_builtin_registry(
            MemoryRepository(database),
            (workspace,),
            roots,
        )
        tool_names = {schema["function"]["name"] for schema in registry.schemas()}
        self.assertIn("skills_list", tool_names)
        self.assertIn("skill_view", tool_names)

    @staticmethod
    def _write_skill(root: Path, name: str, description: str, body: str) -> None:
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
