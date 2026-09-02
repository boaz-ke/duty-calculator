import unittest
from pathlib import Path

from app import parser


WORKBOOK = Path(__file__).resolve().parent.parent / "New-CRSP---July-2025.xlsx"


class ParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = parser.parse_workbook(WORKBOOK, WORKBOOK.name)

    def test_counts_match_source(self):
        self.assertEqual(self.parsed["counts"]["vehicles"], 5279)
        self.assertEqual(self.parsed["counts"]["motorcycles"], 465)
        self.assertGreater(self.parsed["counts"]["machinery"], 100)
        self.assertEqual(self.parsed["counts"]["blocks"], 11)

    def test_no_parse_errors(self):
        self.assertEqual(self.parsed["errors"], [])

    def test_all_rate_blocks_parsed(self):
        block_keys = [b["key"] for b in self.parsed["blocks"]]
        self.assertEqual(block_keys, parser.BLOCK_KEYS)

    def test_known_rates(self):
        by_key = {b["key"]: b for b in self.parsed["blocks"]}
        self.assertEqual(by_key["mv_small"]["duty_rate"], 0.35)
        self.assertEqual(by_key["mv_small"]["excise_rate"], 0.2)
        self.assertEqual(by_key["mv_small"]["backout_divisors"], [1.35, 1.2, 1.16])
        self.assertEqual(by_key["electric"]["duty_rate"], 0.25)
        self.assertEqual(by_key["motorcycle"]["duty_rate"], 0.25)
        self.assertAlmostEqual(by_key["motorcycle"]["excise_fixed"], 12953.0)

    def test_depreciation_schedules(self):
        direct = self.parsed["depreciation"]["direct"]
        self.assertEqual(direct[0]["low"], 1)
        self.assertEqual(direct[-1]["rate"], 0.65)
        registered = self.parsed["depreciation"]["registered"]
        self.assertEqual(registered[7]["age"], 8)
        self.assertEqual(registered[7]["rate"], 0.83)
        self.assertEqual(registered[-1]["rate"], 0.95)

    def test_label_and_effective_date(self):
        self.assertEqual(self.parsed["release_label"], "CRSP July 2025")
        self.assertEqual(self.parsed["effective_date"], "2025-07-01")


if __name__ == "__main__":
    unittest.main()

