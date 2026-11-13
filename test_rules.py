"""Deadline and sale-size checks. No network."""

import unittest
from datetime import date

from rules import assess

TODAY = date(2026, 11, 13)


def run(symbol="ACME", listing=None, mcap=None, psu=False, history=None,
        today=TODAY):
    return assess(symbol, listing, mcap, psu, history or [], today)


class RulesTest(unittest.TestCase):
    def test_meets(self):
        row = run(mcap=1000, history=[(date(2026, 9, 30), 25.0)])
        self.assertEqual(row["status"], "Meets MPS")
        self.assertEqual(row["sale_cr"], 0.0)

    def test_small_company_overdue_since_listing(self):
        row = run(listing=date(2010, 1, 1), mcap=500, history=[(date(2026, 9, 30), 20)])
        self.assertEqual(row["end_date"], date(2010, 1, 1))
        self.assertEqual(row["status"], "Overdue")
        self.assertEqual(row["target"], 25)
        self.assertEqual(row["sale_cr"], 25.0)

    def test_band_edge_1600(self):
        at = run(listing=date(2024, 1, 1), mcap=1600,
                 history=[(date(2026, 9, 30), 20)])
        above = run(listing=date(2024, 1, 1), mcap=1600.01,
                    history=[(date(2026, 9, 30), 20)])
        self.assertEqual(at["end_date"], date(2024, 1, 1))
        self.assertEqual(above["end_date"], date(2027, 1, 1))

    def test_three_year_glide(self):
        row = run(listing=date(2025, 1, 1), mcap=10000,
                  history=[(date(2025, 3, 31), 12), (date(2026, 9, 30), 12)])
        self.assertEqual(row["end_date"], date(2028, 1, 1))
        self.assertEqual(row["status"], "Within time")
        self.assertEqual(row["sale_cr"], 1300.0)
        self.assertEqual(row["kind"], "glide")

    def test_due_on_the_end_date_is_still_within_time(self):
        listing = date(2025, 1, 1)
        row = run(listing=listing, mcap=10000, today=date(2028, 1, 1),
                  history=[(date(2026, 9, 30), 12)])
        self.assertEqual(row["status"], "Within time")
        nxt = run(listing=listing, mcap=10000, today=date(2028, 1, 2),
                  history=[(date(2026, 9, 30), 12)])
        self.assertEqual(nxt["status"], "Overdue")

    def test_leap_day_listing(self):
        row = run(listing=date(2024, 2, 29), mcap=10000,
                  history=[(date(2026, 9, 30), 10)])
        self.assertEqual(row["end_date"], date(2027, 2, 28))

    def test_one_lakh_is_five_years_not_the_mega_split(self):
        row = run(listing=date(2024, 6, 1), mcap=100000,
                  history=[(date(2024, 6, 30), 10), (date(2026, 9, 30), 10)])
        self.assertEqual(row["end_date"], date(2029, 6, 1))
        self.assertEqual(row["target"], 25)

    def test_mega_cap_listed_below_15(self):
        row = run(listing=date(2024, 6, 1), mcap=150000,
                  history=[(date(2024, 6, 30), 10), (date(2026, 9, 30), 12)])
        self.assertEqual(row["target"], 15)
        self.assertEqual(row["end_date"], date(2029, 6, 1))
        self.assertEqual(row["sale_cr"], 4500.0)
        self.assertEqual(row["sale_25_cr"], 19500.0)
        self.assertIn("15%", row["basis"])

    def test_mega_cap_listed_at_15_or_more(self):
        row = run(listing=date(2024, 6, 1), mcap=200000,
                  history=[(date(2024, 6, 30), 16), (date(2026, 9, 30), 16)])
        self.assertEqual(row["target"], 25)
        self.assertEqual(row["end_date"], date(2029, 6, 1))

    def test_mega_cap_unknown_listing_public_still_below_15(self):
        row = run(listing=date(2024, 6, 1), mcap=150000,
                  history=[(date(2026, 9, 30), 12)])
        self.assertEqual(row["target"], 15)
        self.assertEqual(row["end_date"], date(2029, 6, 1))
        self.assertIn("unknown", row["basis"])

    def test_fall_overrides_a_later_glide_date(self):
        row = run(listing=date(2024, 1, 1), mcap=10000,
                  history=[(date(2026, 6, 30), 26), (date(2026, 9, 30), 22)])
        self.assertEqual(row["kind"], "cure")
        self.assertEqual(row["end_date"], date(2027, 7, 1))
        self.assertEqual(row["status"], "Cure period")
        self.assertEqual(row["sale_cr"], 300.0)

    def test_exact_25_then_a_fall(self):
        row = run(history=[(date(2026, 6, 30), 25.0), (date(2026, 9, 30), 24.5)],
                  mcap=8000, listing=date(2010, 1, 1))
        self.assertEqual(row["kind"], "cure")

    def test_never_reached_25_is_not_a_fall(self):
        row = run(listing=date(2025, 1, 1), mcap=10000,
                  history=[(date(2025, 6, 30), 24.99), (date(2026, 9, 30), 20)])
        self.assertEqual(row["kind"], "glide")

    def test_psu_fall_after_the_exemption_is_24_months(self):
        row = run(psu=True, mcap=20000,
                  history=[(date(2026, 9, 30), 30), (date(2026, 10, 15), 18)])
        self.assertEqual(row["end_date"], date(2028, 10, 1))
        self.assertIn("24 months", row["basis"])

    def test_old_psu_uses_the_august_2026_exemption(self):
        row = run(psu=True, listing=date(2010, 1, 1), mcap=500,
                  history=[(date(2026, 9, 30), 10)])
        self.assertEqual(row["end_date"], date(2026, 8, 1))
        self.assertEqual(row["status"], "Overdue")
        self.assertIn("1 Aug 2026", row["basis"])

    def test_recent_psu_keeps_the_longer_glide_path(self):
        row = run(psu=True, listing=date(2025, 1, 1), mcap=10000,
                  history=[(date(2026, 9, 30), 12)])
        self.assertEqual(row["end_date"], date(2028, 1, 1))
        self.assertEqual(row["status"], "Within time")
        self.assertNotIn("1 Aug 2026", row["basis"])

    def test_lic_at_10_aims_at_25_in_2032(self):
        row = run("LICI", mcap=500000, psu=True,
                  history=[(date(2026, 9, 30), 10)])
        self.assertEqual(row["target"], 25)
        self.assertEqual(row["end_date"], date(2032, 5, 16))
        self.assertEqual(row["sale_cr"], 75000.0)
        self.assertEqual(row["status"], "Within time")

    def test_lic_below_10(self):
        row = run("lici", mcap=500000, history=[(date(2026, 6, 30), 9)])
        self.assertEqual(row["target"], 10)
        self.assertEqual(row["end_date"], date(2027, 5, 16))
        self.assertEqual(row["sale_cr"], 5000.0)
        self.assertEqual(row["sale_25_cr"], 80000.0)

    def test_missing_listing_still_prices_a_sale_to_25(self):
        row = run(listing=None, mcap=1000, history=[(date(2026, 9, 30), 20)])
        self.assertEqual(row["status"], "Date unknown")
        self.assertIsNone(row["end_date"])
        self.assertEqual(row["sale_cr"], 50.0)

    def test_missing_mcap_with_a_fall_still_has_a_date(self):
        row = run(mcap=None, listing=date(2018, 1, 1),
                  history=[(date(2026, 6, 30), 40), (date(2026, 9, 30), 22)])
        self.assertEqual(row["end_date"], date(2027, 7, 1))
        self.assertIsNone(row["sale_cr"])

    def test_above_5_lakh_uses_the_same_split_as_the_1_to_5_band(self):
        row = run(listing=date(2024, 1, 15), mcap=600000,
                  history=[(date(2024, 3, 31), 8), (date(2026, 9, 30), 8)])
        self.assertEqual(row["target"], 15)
        self.assertEqual(row["end_date"], date(2029, 1, 15))
        self.assertEqual(row["slab"], "above ₹5 lakh cr")


if __name__ == "__main__":
    unittest.main()
