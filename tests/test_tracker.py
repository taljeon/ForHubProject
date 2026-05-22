from __future__ import annotations

import sqlite3
import unittest

from app.db import init_db
from app.services.tracker import create_application, update_application


def _make_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    init_db(connection)
    return connection


class TrackerApplicationUpdateTestCase(unittest.TestCase):
    def test_update_application_preserves_notes_when_none(self) -> None:
        connection = _make_connection()
        application_id = create_application(
            connection,
            company_name="Example Corp",
            route=None,
            contact_email=None,
            current_stage="applied",
            next_action=None,
            deadline="2026-05-22",
            my_priority=3,
            notes="keep me",
        )

        update_application(
            connection,
            application_id,
            current_stage="interview",
            next_action=None,
            deadline="2026-06-01",
            my_priority=2,
            notes=None,
        )

        row = connection.execute("SELECT notes FROM applications WHERE id = ?", (application_id,)).fetchone()
        self.assertEqual(row["notes"], "keep me")

    def test_update_application_clears_notes_when_blank(self) -> None:
        connection = _make_connection()
        application_id = create_application(
            connection,
            company_name="Example Corp",
            route=None,
            contact_email=None,
            current_stage="applied",
            next_action=None,
            deadline="2026-05-22",
            my_priority=3,
            notes="clear me",
        )

        update_application(
            connection,
            application_id,
            current_stage="interview",
            next_action=None,
            deadline="2026-06-01",
            my_priority=2,
            notes="   ",
        )

        row = connection.execute("SELECT notes FROM applications WHERE id = ?", (application_id,)).fetchone()
        self.assertIsNone(row["notes"])


if __name__ == "__main__":
    unittest.main()
