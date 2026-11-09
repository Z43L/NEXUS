"""Tests for finance/model.py.  Run: python3 -m unittest finance.test_model  (from nexus-project/)
or: python3 finance/test_model.py"""
import csv
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as M  # noqa: E402


class TestParams(unittest.TestCase):
    def test_every_param_has_three_scenarios_and_comment(self):
        for k, v in M.PARAM_TABLE.items():
            self.assertEqual(len(v), 4, k)
            self.assertIsInstance(v[3], str, k)
            self.assertTrue(v[3].strip(), k)

    def test_splits_sum_to_one(self):
        for name, sp in M.SPLITS.items():
            self.assertAlmostEqual(sp["platform"] + sp["verification"] + sp["burn"] + sp["author"], 1.0 - self.node_plain(sp), places=9)
        cur = M.SPLITS["current"]
        # escrow InferenceEscrow.sol: node 75, author 10, verification 5, burn 5, treasury 5
        self.assertAlmostEqual(cur["platform"], 0.05)
        self.assertAlmostEqual(1.0 - cur["platform"] - cur["verification"] - cur["burn"] - cur["author"], 0.75)

    @staticmethod
    def node_plain(sp):
        return 1.0 - sp["platform"] - sp["verification"] - sp["burn"] - sp["author"]

    def test_mix_weights_normalise(self):
        for n in M.SCENARIO_NAMES:
            w = M.mix_weights(M.scenario_params(n))
            self.assertAlmostEqual(sum(w.values()), 1.0)

    def test_reference_price(self):
        p = M.scenario_params("base")
        self.assertAlmostEqual(M.reference_price(p), (3 * 0.10 + 0.32) / 4)


class TestSimulation(unittest.TestCase):
    def setUp(self):
        self.base = M.scenario_params("base")
        self.fin, self.info = M.derive_financing(self.base)

    def test_36_months_and_no_revenue_before_paid_start(self):
        for n in M.SCENARIO_NAMES:
            p = M.scenario_params(n)
            rows, _ = M.simulate(p, self.fin)
            self.assertEqual(len(rows), 36)
            for r in rows:
                if r["month"] < p["paid_start_month"]:
                    self.assertEqual(r["gmv"], 0.0)
                    self.assertEqual(r["net_revenue"], 0.0)

    def test_cash_identity(self):
        rows, _ = M.simulate(self.base, self.fin)
        cash = 0.0
        for r in rows:
            cash += r["ebitda"] + r["financing"]
            self.assertAlmostEqual(r["cash"], cash, places=4)

    def test_ebitda_identity(self):
        rows, _ = M.simulate(self.base, self.fin)
        for r in rows:
            self.assertAlmostEqual(r["ebitda"], r["net_revenue"] - r["cogs"] - r["opex"], places=4)

    def test_served_never_exceeds_capacity_or_demand(self):
        for n in M.SCENARIO_NAMES:
            rows, _ = M.simulate(M.scenario_params(n), self.fin)
            for r in rows:
                self.assertLessEqual(r["served_mtok"], r["capacity_mtok"] + 1e-6)
                self.assertLessEqual(r["served_mtok"], r["demand_mtok"] + 1e-6)
                self.assertLessEqual(r["utilisation"], 0.75 + 1e-9)

    def test_gmv_split_conserves_money(self):
        rows, _ = M.simulate(self.base, self.fin)
        for r in rows:
            parts = r["node_pay"] + r["author_pay"] + r["verification_pool"] + r["burned"] + r["rev_inference"] + r["rev_royalty_fee"]
            self.assertAlmostEqual(parts, r["gmv"], places=6)

    def test_scenarios_ordered_by_revenue(self):
        cum = [M.simulate(M.scenario_params(n), self.fin)[1]["cum_net_revenue"] for n in M.SCENARIO_NAMES]
        self.assertLess(cum[0], cum[1])
        self.assertLess(cum[1], cum[2])

    def test_deterministic(self):
        a = M.simulate(self.base, self.fin)[1]
        b = M.simulate(M.scenario_params("base"), self.fin)[1]
        self.assertEqual(a, b)

    def test_financing_covers_base_with_buffer(self):
        _, s = M.simulate(self.base, self.fin)
        self.assertGreater(s["min_cash"], 0.0)
        self.assertEqual(sum(self.fin.values()), self.info["pre_seed"] + self.info["seed"])

    def test_proposed_split_yields_more_platform_revenue_than_current(self):
        cur = M.simulate(M.scenario_params("base", {"split": "current"}), self.fin)[1]["cum_net_revenue"]
        pro = M.simulate(M.scenario_params("base", {"split": "proposed"}), self.fin)[1]["cum_net_revenue"]
        self.assertGreater(pro, cur)

    def test_no_enclaves_means_no_enclave_revenue(self):
        p = M.scenario_params("base", {"enclave_new_per_quarter": 0.0})
        rows, _ = M.simulate(p, self.fin)
        self.assertEqual(sum(r["rev_enclave"] for r in rows), 0.0)

    def test_fine_tuning_off_when_start_is_beyond_horizon(self):
        rows, _ = M.simulate(M.scenario_params("conservador"), self.fin)
        self.assertEqual(sum(r["rev_finetune"] for r in rows), 0.0)


class TestOperatorEconomics(unittest.TestCase):
    def test_breakeven_price_makes_profit_zero(self):
        p = M.scenario_params("base")
        for prof in M.OPERATOR_PROFILES:
            for util in (0.3, 0.6):
                node_share = 0.80
                price = M.breakeven_price(prof, util, p, node_share)
                revenue = M.node_capacity_mtok(p) * util * price * node_share
                self.assertAlmostEqual(revenue, M.operator_cost_month(prof, util, p), places=6)

    def test_dedicated_costs_more_than_sunk_and_mac(self):
        p = M.scenario_params("base")
        c = {k: M.operator_cost_month(k, 0.5, p) for k in M.OPERATOR_PROFILES}
        self.assertGreater(c["dedicated"], c["sunk"])
        self.assertGreater(c["sunk"], c["mac"])

    def test_cost_increases_with_utilisation(self):
        p = M.scenario_params("base")
        for prof in M.OPERATOR_PROFILES:
            self.assertGreater(M.operator_cost_month(prof, 0.9, p), M.operator_cost_month(prof, 0.1, p))

    def test_electricity_formula_sunk(self):
        p = M.scenario_params("base")
        kwh = p["kwh_eur"] * p["fx_usd_per_eur"]
        expected = (300.0 - 40.0) * 0.5 * 730 / 1000 * kwh
        self.assertAlmostEqual(M.operator_cost_month("sunk", 0.5, p), expected, places=6)


class TestSensitivityAndOutput(unittest.TestCase):
    def test_price_sensitivity_rows(self):
        fin, _ = M.derive_financing(M.scenario_params("base"))
        rows = M.sens_price(fin)
        self.assertEqual(len(rows), 27)
        self.assertTrue(all(math.isfinite(r["cum_net_revenue"]) for r in rows))

    def test_more_throughput_does_not_reduce_operator_profit(self):
        fin, _ = M.derive_financing(M.scenario_params("base"))
        rows = M.sens_throughput(fin)
        profits = [r["op_profit_m36"] for r in rows]
        self.assertEqual(profits, sorted(profits))

    def test_run_all_writes_files(self):
        with tempfile.TemporaryDirectory() as d:
            M.run_all(out_dir=d)
            for f in ("monthly_base.csv", "scenarios_summary.csv", "quarterly.csv", "sensitivity_price.csv",
                      "sensitivity_utilization.csv", "sensitivity_cac.csv", "unit_economics.csv",
                      "operator_economics.csv", "resumen.md"):
                self.assertTrue(os.path.exists(os.path.join(d, f)), f)
            with open(os.path.join(d, "monthly_base.csv")) as fh:
                self.assertEqual(len(list(csv.DictReader(fh))), 36)
            with open(os.path.join(d, "resumen.md")) as fh:
                text = fh.read()
            self.assertIn("Conservador", text)
            self.assertIn("proyecciones", text)


if __name__ == "__main__":
    unittest.main()
