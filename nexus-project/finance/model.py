#!/usr/bin/env python3
"""NEXUS 36-month financial model (stdlib only, Python 3.9).

Run:  python3 finance/model.py            (writes finance/output/*.csv and resumen.md)

EVERYTHING HERE IS A PROJECTION WITH EXPLICIT ASSUMPTIONS. There is no revenue, no
customer, no paying user and no real-money settlement today (alpha closed, testnet,
no token). Parameters tagged [FUENTE] come from an external page (see docs/business/02-precios.md
for URL and date); [SUPUESTO] means an assumption of the team to be validated; [POR VERIFICAR]
means that even the assumption lacks a reference. Currency: USD (FX parameter for EUR inputs).

Structure of the model (monthly, months 1..36):
  demand (accounts x tokens)  -> capacity of the node pool -> served tokens -> GMV
  GMV -> split (node / author / verification / burn / platform) -> NET revenue = platform take
  + enclave fees + SLA + certification + fine-tuning.  Costs: COGS, team, marketing, legal,
  audits, G&A, operator start-up incentives.  Cash = financing + cumulative EBITDA (no tax, no capex).
"""
import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "output")
MONTHS = 36
SEC_PER_MONTH = 30.4 * 24 * 3600

# --------------------------------------------------------------------------------------
# SINGLE PARAMETER BLOCK.  name: (conservador, base, optimista, comment)
# --------------------------------------------------------------------------------------
PARAM_TABLE = {
    # ---- calendar ----
    "beta_start_month": (7, 7, 6, "[SUPUESTO] end of closed alpha (testnet) -> beta begins; still no external real-money flows in alpha"),
    "paid_start_month": (13, 10, 8, "[SUPUESTO] first month with real-money settlement. Needs legal/KYC + audited contract first (docs 05)"),
    "ga_month": (22, 16, 13, "[SUPUESTO] general availability (public gateway, SLA offered)"),
    # ---- pricing ----
    "price_mult_std": (0.90, 0.90, 0.90, "[SUPUESTO] standard price as a fraction of reference market price (10% under); see 02-precios"),
    "premium_mult": (2.0, 2.5, 2.5, "[SUPUESTO] 'verified/SLA' tier multiplier on standard price (signed receipts, canary re-execution, priority)"),
    "premium_share_dev": (0.03, 0.08, 0.15, "[SUPUESTO] share of self-serve developer tokens bought in the premium tier"),
    "premium_share_biz": (0.20, 0.35, 0.45, "[SUPUESTO] share of business-account tokens in the premium tier"),
    "elasticity": (-1.2, -1.2, -1.2, "[SUPUESTO] price elasticity of volume (commodity API demand is elastic; sensitivity run -0.6..-2.0)"),
    "acq_elasticity_share": (0.5, 0.5, 0.5, "[SUPUESTO] fraction of the elasticity that also affects new-account acquisition"),
    "adapter_share": (0.01, 0.04, 0.10, "[SUPUESTO] share of tokens run with an author .nram adapter (royalty-bearing jobs)"),
    "split": ("proposed", "proposed", "proposed", "'proposed' (15% platform, 5% verification, 10% author on adapter jobs, node=rest, no burn) or 'current' (escrow v0.1: 75/10/5/5/5)"),
    # ---- developer (self-serve) demand ----
    "waitlist_signups": (200, 600, 2000, "[POR VERIFICAR] waitlist size at paid start. NOT a measured figure: no waitlist data exists yet"),
    "waitlist_conv": (0.08, 0.12, 0.15, "[SUPUESTO] fraction of waitlist that becomes a paying account"),
    "organic_new_start": (3, 8, 20, "[SUPUESTO] organic new paying dev accounts / month at paid start"),
    "organic_growth": (0.03, 0.05, 0.08, "[SUPUESTO] monthly growth of organic acquisition"),
    "cac_dev": (250.0, 120.0, 80.0, "[SUPUESTO] USD of paid marketing per new paying dev account"),
    "mkt_alpha": (0.0, 500.0, 500.0, "[SUPUESTO] USD/month marketing during alpha (content, community)"),
    "mkt_beta": (1500.0, 4000.0, 6000.0, "[SUPUESTO] USD/month marketing during beta"),
    "mkt_ga": (3000.0, 10000.0, 20000.0, "[SUPUESTO] USD/month marketing in GA"),
    "dev_churn": (0.07, 0.05, 0.035, "[SUPUESTO] monthly churn of self-serve accounts"),
    "tok_per_dev_m": (8.0, 20.0, 50.0, "[SUPUESTO] M tokens/month per paying dev account at parity price"),
    "dev_expansion": (0.015, 0.02, 0.03, "[SUPUESTO] monthly growth of tokens per account"),
    "dev_expansion_cap": (3.0, 3.0, 4.0, "[SUPUESTO] cap on that growth (x initial)"),
    # ---- business accounts (teams, SLA) ----
    "biz_start_month": (18, 14, 11, "[SUPUESTO] first month of sales-assisted business accounts"),
    "biz_new_start": (0.5, 1.5, 3.0, "[SUPUESTO] new business accounts / month at start"),
    "biz_growth": (0.02, 0.03, 0.05, "[SUPUESTO] monthly growth of business-account acquisition"),
    "biz_churn": (0.025, 0.02, 0.015, "[SUPUESTO] monthly churn of business accounts"),
    "tok_per_biz_m": (200.0, 800.0, 2500.0, "[SUPUESTO] M tokens/month per business account"),
    "biz_vol_discount": (0.0, 0.05, 0.10, "[SUPUESTO] volume discount for business accounts"),
    "sla_attach": (0.30, 0.40, 0.50, "[SUPUESTO] fraction of business accounts that buy a support/SLA plan"),
    "sla_price_month": (250.0, 300.0, 400.0, "[SUPUESTO] USD/month support+SLA plan (price vs cost of 0.05 FTE support)"),
    # ---- enclaves / private swarms ----
    "enclave_start_month": (28, 20, 15, "[SUPUESTO] first signed enclave contract"),
    "enclave_new_per_quarter": (0.5, 1.0, 2.0, "[SUPUESTO] expected new enclave contracts / quarter (fractions = expectation)"),
    "enclave_churn": (0.012, 0.010, 0.008, "[SUPUESTO] monthly churn of enclave contracts (enclaves use customer/certified nodes, not the public pool)"),
    "enclave_infra": (1200.0, 1200.0, 1200.0, "[SUPUESTO] USD/month dedicated coordinator + gateway instance per enclave (COGS)"),
    "enclave_support": (2000.0, 2000.0, 2000.0, "[SUPUESTO] USD/month support+SRE share per enclave (~0.3 FTE) (COGS)"),
    "enclave_compliance": (600.0, 600.0, 600.0, "[SUPUESTO] USD/month compliance/security share per enclave (COGS)"),
    "enclave_margin": (0.80, 1.20, 1.60, "[SUPUESTO] markup on direct cost: monthly fee = cost x (1+markup) -> gross margin 44%/55%/62%. Cost is a floor, not a market price [POR VERIFICAR vs real enterprise quotes]"),
    "enclave_setup_fee": (4000.0, 6000.0, 8000.0, "[SUPUESTO] one-off onboarding fee per enclave (about 0.5 FTE-month)"),
    # ---- certified operators ----
    "cert_start_month": (18, 18, 14, "[SUPUESTO] certified-operator programme launches"),
    "cert_share_ops": (0.10, 0.20, 0.30, "[SUPUESTO] fraction of operators that pay for certification"),
    "cert_fee_year": (180.0, 180.0, 180.0, "[SUPUESTO] USD/year per certified operator (covers KYC, attestation review); roughly cost-neutral"),
    # ---- fine-tuning (future) ----
    "ft_start_month": (99, 33, 27, "[SUPUESTO] 99 = never inside the horizon. Research problem: see research/swarm-sim (59 stages for 70B)"),
    "ft_jobs_month": (0.0, 6.0, 20.0, "[SUPUESTO] fine-tuning jobs per month"),
    "ft_avg_gross": (150.0, 150.0, 200.0, "[SUPUESTO] USD gross per job (centralised list: Llama 3.3 70B SFT ~$2/M training tokens at Together, 2026-10-27)"),
    # ---- supply: operators and capacity ----
    "node_tps": (190.0, 190.0, 190.0, "[FUENTE swarm-sim] UPPER BOUND tok/s per node: 0.95 M tok/s / 5000 nodes, 70B int4, S=8, batch 32 (simulator, not a measurement)"),
    "net_eff": (0.25, 0.50, 0.75, "[SUPUESTO] fraction of that simulator upper bound reached in practice. NOT measured: no multi-node throughput measurement exists yet"),
    "avail": (0.80, 0.85, 0.90, "[FUENTE swarm-sim] mean uptime 85% (illustrative)"),
    "target_util": (0.35, 0.45, 0.55, "[SUPUESTO] pool utilisation the operator-recruitment loop aims for"),
    "max_util": (0.75, 0.75, 0.75, "[SUPUESTO] hard ceiling on sustained utilisation (latency/queueing); excess demand is lost"),
    "floor_ops_alpha": (12, 12, 12, "[SUPUESTO] seeded nodes in alpha (team + volunteers), S=8 x ~1.5"),
    "floor_ops_beta": (24, 24, 24, "[SUPUESTO] minimum nodes in beta, S=8 x 3"),
    "floor_ops_ga": (40, 40, 40, "[SUPUESTO] minimum nodes in GA, S=8 x 5 for redundancy"),
    "op_join_cap": (4.0, 12.0, 30.0, "[SUPUESTO] max net new operators per month"),
    "op_lag": (0.30, 0.30, 0.30, "[SUPUESTO] fraction of the recruitment gap closed per month"),
    "op_churn_base": (0.03, 0.025, 0.02, "[SUPUESTO] monthly operator churn when profitable"),
    "op_churn_loss_extra": (0.06, 0.06, 0.06, "[SUPUESTO] extra monthly churn while average operator profit < 0"),
    # operator profile mix (dedicated rig / existing PC / Apple-silicon Mac); see operator_profiles
    "mix_dedicated": (0.30, 0.20, 0.15, "[SUPUESTO] share of operators that bought hardware for this"),
    "mix_sunk": (0.40, 0.45, 0.45, "[SUPUESTO] share using an existing gaming PC (marginal cost only)"),
    "mix_mac": (0.30, 0.35, 0.40, "[SUPUESTO] share using an Apple-silicon Mac (H0/H1 target; marginal cost only)"),
    "kwh_eur": (0.27, 0.27, 0.27, "[FUENTE] Spain H1-2026 avg household 27.39 c/kWh (Selectra calc. from Eurostat) -> docs 02"),
    "fx_usd_per_eur": (1.10, 1.10, 1.10, "[POR VERIFICAR] USD per EUR"),
    "op_incentive_cov": (0.30, 0.50, 0.50, "[SUPUESTO] share of the floor-node cost gap the company covers as startup credit (NOT a yield promise)"),
    "op_incentive_end": (22, 24, 20, "[SUPUESTO] last month of the start-up credit"),
    "kyc_per_operator": (8.0, 8.0, 8.0, "[POR VERIFICAR] USD per operator payout KYC check"),
    # ---- costs ----
    "fte_plan": ([(1, 3), (10, 4), (19, 6), (31, 8)],
                 [(1, 4), (10, 7), (19, 10), (31, 13)],
                 [(1, 4), (10, 7), (19, 11), (25, 14), (31, 18)],
                 "[SUPUESTO] (from_month, FTE) headcount by phase; founders included at loaded cost"),
    "fte_cost": (5500.0, 6000.0, 6500.0, "[SUPUESTO] USD/month fully loaded per FTE (Spain-like salary + social charges); not from a salary survey"),
    "ga_fixed": (1500.0, 1500.0, 1500.0, "[SUPUESTO] USD/month accounting, insurance, admin"),
    "ga_per_fte": (350.0, 350.0, 350.0, "[SUPUESTO] USD/month per FTE of tools/equipment"),
    "infra_alpha": (800.0, 800.0, 800.0, "[SUPUESTO] USD/month coordinator+gateway+RPC+monitoring in alpha (COGS)"),
    "infra_beta": (2500.0, 2500.0, 2500.0, "[SUPUESTO] USD/month in beta (COGS)"),
    "infra_ga": (6000.0, 6000.0, 8000.0, "[SUPUESTO] USD/month in GA (HA coordinator, multi-region gateway) (COGS)"),
    "infra_var_per_mtok": (0.004, 0.004, 0.004, "[SUPUESTO] USD per M tokens served (egress, logs, receipts storage) (COGS)"),
    "pay_fee_pct": (0.03, 0.03, 0.03, "[POR VERIFICAR] blended card-processing cost on self-serve/business billing"),
    "legal_retainer_alpha": (1000.0, 1000.0, 1000.0, "[SUPUESTO] USD/month"),
    "legal_retainer_beta": (2000.0, 2000.0, 2000.0, "[SUPUESTO] USD/month"),
    "legal_retainer_ga": (3500.0, 3500.0, 3500.0, "[SUPUESTO] USD/month"),
    "legal_one_offs": ([(1, 15000.0, "incorporation + shareholder agreement"), (2, 4000.0, "trademark clearance (NEXUS name risk)"),
                        (4, 14000.0, "payments/KYC + token-qualification opinion"), (5, 7000.0, "ToS, AUP, DPA, privacy notice")],
                       [(1, 15000.0, "incorporation + shareholder agreement"), (2, 4000.0, "trademark clearance (NEXUS name risk)"),
                        (4, 14000.0, "payments/KYC + token-qualification opinion"), (5, 7000.0, "ToS, AUP, DPA, privacy notice")],
                       [(1, 15000.0, "incorporation + shareholder agreement"), (2, 4000.0, "trademark clearance (NEXUS name risk)"),
                        (4, 14000.0, "payments/KYC + token-qualification opinion"), (5, 7000.0, "ToS, AUP, DPA, privacy notice")],
                       "[SUPUESTO] one-off legal costs, all [POR VERIFICAR] with quotes"),
    "audit_contract": (80000.0, 60000.0, 45000.0, "[POR VERIFICAR] smart-contract + bridge audit before real money (quote needed)"),
    "audit_contract_lead": (3, 3, 3, "[SUPUESTO] months before paid_start when the audit is paid"),
    "audit_pentest": (20000.0, 20000.0, 25000.0, "[POR VERIFICAR] annual pen test of gateway/coordinator at months 12, 24, 36"),
    "audit_protocol": (40000.0, 40000.0, 50000.0, "[POR VERIFICAR] independent review of slot assignment/key vault/receipts, month 18"),
    # ---- reference prices (USD per 1M tokens), see 02-precios.md ----
    "ref_prices": ([(0.10, 0.32)], [(0.10, 0.32)], [(0.10, 0.32)],
                   "[FUENTE] DeepInfra pricing page 2026-10-27: Llama-3.3-70B-Instruct-Turbo 0.10/0.32 USD per M (input/output); 70B class to match swarm-sim throughput"),
    "io_ratio": (3.0, 3.0, 3.0, "[SUPUESTO] input:output token ratio used to blend the reference price"),
    "tokens_per_request": (900, 900, 900, "[SUPUESTO] avg tokens per request (600 in + 300 out) for unit economics"),
    # ---- financing (derived by derive_financing, see below) ----
    "buffer": (1.25, 1.25, 1.25, "[SUPUESTO] safety multiplier when sizing rounds"),
    "seed_month": (19, 19, 19, "[SUPUESTO] month at which the seed round closes"),
}

SCENARIO_NAMES = ["conservador", "base", "optimista"]

SPLITS = {
    # fractions of GMV. node = remainder; author only on adapter jobs (if absent, current escrow gives it to the node).
    "current": {"platform": 0.05, "verification": 0.05, "burn": 0.05, "author": 0.10},
    "proposed": {"platform": 0.15, "verification": 0.05, "burn": 0.00, "author": 0.10},
}

# Operator hardware profiles (USD amounts; EUR electricity converted via FX).
OPERATOR_PROFILES = {
    "dedicated": {"hw_usd": 2800.0, "life_months": 36, "resale": 0.30, "load_w": 350.0, "idle_w": 40.0,
                  "marginal_only": False, "conn_usd": 15.0,
                  "note": "used RTX 4090-class (~2200 USD per eBay sold data, tech-insider 2026) + 600 host; 450 W TDP -> ~350 W avg load [SUPUESTO]"},
    "sunk": {"hw_usd": 0.0, "life_months": 36, "resale": 0.0, "load_w": 300.0, "idle_w": 40.0,
             "marginal_only": True, "conn_usd": 0.0,
             "note": "existing gaming PC; only marginal electricity above idle counts"},
    "mac": {"hw_usd": 0.0, "life_months": 36, "resale": 0.0, "load_w": 45.0, "idle_w": 8.0,
            "marginal_only": True, "conn_usd": 0.0,
            "note": "Apple-silicon Mac already owned; watts are [SUPUESTO] not measured"},
}


def scenario_params(name, overrides=None):
    idx = SCENARIO_NAMES.index(name)
    p = {k: v[idx] for k, v in PARAM_TABLE.items()}
    if overrides:
        p.update(overrides)
    return p


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def reference_price(p):
    """Blended USD/M-token reference price: mean over reference models of (r*in+out)/(r+1)."""
    r = p["io_ratio"]
    blends = [(r * a + b) / (r + 1.0) for a, b in p["ref_prices"]]
    return sum(blends) / len(blends)


def operator_cost_month(profile, util, p):
    """Monthly cost (USD) of one operator at a given utilisation of its time."""
    pr = OPERATOR_PROFILES[profile]
    kwh_usd = p["kwh_eur"] * p["fx_usd_per_eur"]
    hours = 730.0
    if pr["marginal_only"]:
        watts = (pr["load_w"] - pr["idle_w"]) * util  # only above-idle draw is attributable
    else:
        watts = pr["load_w"] * util + pr["idle_w"] * (1.0 - util)
    elec = watts * hours / 1000.0 * kwh_usd
    amort = pr["hw_usd"] * (1.0 - pr["resale"]) / pr["life_months"]
    return elec + amort + pr["conn_usd"]


def mix_weights(p):
    w = {"dedicated": p["mix_dedicated"], "sunk": p["mix_sunk"], "mac": p["mix_mac"]}
    tot = sum(w.values())
    return {k: v / tot for k, v in w.items()}


def avg_operator_cost(util, p):
    w = mix_weights(p)
    return sum(w[k] * operator_cost_month(k, util, p) for k in w)


def node_capacity_mtok(p):
    """Raw tokens (millions) one node can deliver per month at 100% of its availability-adjusted time."""
    return p["node_tps"] * p["net_eff"] * p["avail"] * SEC_PER_MONTH / 1e6


def breakeven_price(profile, util, p, node_share):
    """USD per M tokens the customer must pay so that the operator (profile) recovers cost at util.
    node_share = fraction of customer price that reaches the node (e.g. 0.80)."""
    tokens_m = node_capacity_mtok(p) * util
    if tokens_m <= 0:
        return float("inf")
    node_needs_per_m = operator_cost_month(profile, util, p) / tokens_m
    return node_needs_per_m / node_share


def fte_at(plan, m):
    cur = 0
    for start, n in plan:
        if m >= start:
            cur = n
    return cur


def phase_of(m, p):
    if m < p["beta_start_month"]:
        return "alpha"
    if m < p["ga_month"]:
        return "beta"
    return "ga"


# --------------------------------------------------------------------------------------
# Core simulation
# --------------------------------------------------------------------------------------
def simulate(p, financing=None):
    """Return (rows, summary). financing: {month: amount}."""
    financing = financing or {}
    split = SPLITS[p["split"]]
    pref = reference_price(p)
    p_std = pref * p["price_mult_std"]
    p_prem = p_std * p["premium_mult"]
    vol_mult = p["price_mult_std"] ** p["elasticity"]            # volume effect of the price level
    acq_mult = p["price_mult_std"] ** (p["elasticity"] * p["acq_elasticity_share"])
    enclave_cost = p["enclave_infra"] + p["enclave_support"] + p["enclave_compliance"]
    enclave_fee = enclave_cost * (1.0 + p["enclave_margin"])
    cap_node = node_capacity_mtok(p)

    dev = 0.0
    biz = 0.0
    encl = 0.0
    ops = float(p["floor_ops_alpha"])
    demand_prev = 0.0
    op_profit_prev = 0.0
    cash = 0.0
    rows = []
    cum_ebitda = 0.0
    paid0 = p["paid_start_month"]

    for m in range(1, MONTHS + 1):
        ph = phase_of(m, p)
        paid = m >= paid0
        k = m - paid0
        mkt = {"alpha": p["mkt_alpha"], "beta": p["mkt_beta"], "ga": p["mkt_ga"]}[ph]

        # ---- accounts ----
        new_dev = new_biz = new_enc = 0.0
        if paid:
            organic = p["organic_new_start"] * (1.0 + p["organic_growth"]) ** k
            bought = (mkt / p["cac_dev"]) * acq_mult
            new_dev = organic * acq_mult + bought
            if k == 0:
                new_dev += p["waitlist_signups"] * p["waitlist_conv"]
            dev = dev * (1.0 - p["dev_churn"]) + new_dev
            if m >= p["biz_start_month"]:
                new_biz = p["biz_new_start"] * (1.0 + p["biz_growth"]) ** (m - p["biz_start_month"])
            biz = biz * (1.0 - p["biz_churn"]) + new_biz
            if m >= p["enclave_start_month"]:
                new_enc = p["enclave_new_per_quarter"] / 3.0
            encl = encl * (1.0 - p["enclave_churn"]) + new_enc
        tpa = p["tok_per_dev_m"] * min(p["dev_expansion_cap"], (1.0 + p["dev_expansion"]) ** max(k, 0))

        d_dev = dev * tpa * vol_mult
        d_biz = biz * p["tok_per_biz_m"] * vol_mult
        # enclaves run on the customer's own / certified nodes: they pay a coordination fee and do not load the public pool
        demand = d_dev + d_biz

        # ---- supply ----
        floor = p["floor_ops_alpha"] if ph == "alpha" else (p["floor_ops_beta"] if ph == "beta" else p["floor_ops_ga"])
        target = demand_prev / (cap_node * p["target_util"]) if demand_prev > 0 else 0.0
        add = min(p["op_join_cap"], max(0.0, p["op_lag"] * (target - ops)))
        churn = ops * (p["op_churn_base"] + (p["op_churn_loss_extra"] if op_profit_prev < 0 else 0.0))
        ops_new = max(float(floor), ops + add - churn)
        joined = max(0.0, ops_new - (ops - churn))
        ops = ops_new
        usable = ops * cap_node * p["max_util"]
        served = min(demand, usable)
        util = served / (ops * cap_node) if ops > 0 else 0.0
        fill = served / demand if demand > 0 else 0.0

        # ---- GMV and split ----
        g_dev = d_dev * fill * ((1 - p["premium_share_dev"]) * p_std + p["premium_share_dev"] * p_prem)
        g_biz = d_biz * fill * (1 - p["biz_vol_discount"]) * ((1 - p["premium_share_biz"]) * p_std + p["premium_share_biz"] * p_prem)
        gmv = g_dev + g_biz
        gmv_adapter = gmv * p["adapter_share"]
        gmv_plain = gmv - gmv_adapter
        pl = split["platform"]
        rev_inference = gmv_plain * pl
        rev_royalty_fee = gmv_adapter * pl
        verification_pool = gmv * split["verification"]
        burned = gmv * split["burn"]
        author_pay = gmv_adapter * split["author"]
        node_pay = gmv - rev_inference - rev_royalty_fee - verification_pool - burned - author_pay
        if paid and ops > 0:
            op_rev = node_pay / ops
            op_cost = avg_operator_cost(util, p)
            op_profit = op_rev - op_cost
        else:
            op_rev = op_cost = op_profit = 0.0

        rev_enclave = (encl * enclave_fee + new_enc * p["enclave_setup_fee"]) if paid else 0.0
        rev_sla = biz * p["sla_attach"] * p["sla_price_month"] if paid else 0.0
        rev_cert = (ops * p["cert_share_ops"] * p["cert_fee_year"] / 12.0) if (paid and m >= p["cert_start_month"]) else 0.0
        rev_ft = (p["ft_jobs_month"] * p["ft_avg_gross"] * pl) if (paid and m >= p["ft_start_month"]) else 0.0
        net_rev = rev_inference + rev_royalty_fee + rev_enclave + rev_sla + rev_cert + rev_ft

        # ---- COGS ----
        infra_fixed = {"alpha": p["infra_alpha"], "beta": p["infra_beta"], "ga": p["infra_ga"]}[ph]
        infra_var = served * p["infra_var_per_mtok"] if paid else 0.0
        encl_cogs = encl * enclave_cost
        billed_cards = g_dev + g_biz
        pay_fees = billed_cards * p["pay_fee_pct"]
        cogs = infra_fixed + infra_var + encl_cogs + pay_fees
        gross = net_rev - cogs
        gross_margin = gross / net_rev if net_rev > 0 else float("nan")

        # ---- opex ----
        fte = fte_at(p["fte_plan"], m)
        team = fte * p["fte_cost"]
        ga = p["ga_fixed"] + fte * p["ga_per_fte"]
        legal = {"alpha": p["legal_retainer_alpha"], "beta": p["legal_retainer_beta"], "ga": p["legal_retainer_ga"]}[ph]
        legal += sum(a for (mo, a, _l) in p["legal_one_offs"] if mo == m)
        audits = 0.0
        if m == max(1, paid0 - p["audit_contract_lead"]):
            audits += p["audit_contract"]
        if m in (12, 24, 36):
            audits += p["audit_pentest"]
        if m == 18:
            audits += p["audit_protocol"]
        kyc = joined * p["kyc_per_operator"] if paid else 0.0
        incentive = 0.0
        if paid and m <= p["op_incentive_end"]:
            gap = max(0.0, avg_operator_cost(util, p) - op_rev)
            incentive = p["op_incentive_cov"] * gap * min(ops, float(floor))
        opex = team + mkt + legal + audits + ga + kyc + incentive
        ebitda = gross - opex
        cum_ebitda += ebitda
        cash += ebitda + financing.get(m, 0.0)

        rows.append({
            "month": m, "phase": ph, "paid": int(paid), "dev_accounts": dev, "biz_accounts": biz, "enclaves": encl,
            "demand_mtok": demand, "capacity_mtok": usable, "served_mtok": served, "fill": fill,
            "operators": ops, "utilisation": util, "gmv": gmv, "node_pay": node_pay, "author_pay": author_pay,
            "verification_pool": verification_pool, "burned": burned,
            "rev_inference": rev_inference, "rev_royalty_fee": rev_royalty_fee, "rev_enclave": rev_enclave,
            "rev_sla": rev_sla, "rev_cert": rev_cert, "rev_finetune": rev_ft, "net_revenue": net_rev,
            "cogs": cogs, "gross_profit": gross, "gross_margin": gross_margin,
            "fte": fte, "team": team, "marketing": mkt, "legal": legal, "audits": audits, "ga": ga, "kyc": kyc,
            "operator_incentive": incentive, "opex": opex, "ebitda": ebitda, "cum_ebitda": cum_ebitda,
            "financing": financing.get(m, 0.0), "cash": cash,
            "op_revenue": op_rev, "op_cost": op_cost, "op_profit": op_profit,
        })
        demand_prev = demand
        op_profit_prev = op_profit if paid else 0.0

    return rows, summarize(rows, p)


def summarize(rows, p):
    cum_rev = sum(r["net_revenue"] for r in rows)
    cum_gmv = sum(r["gmv"] for r in rows)
    min_cum = min(r["cum_ebitda"] for r in rows)
    min_cash = min(r["cash"] for r in rows)
    cash_out = next((r["month"] for r in rows if r["cash"] < 0), None)
    be = None
    for i in range(len(rows) - 2):
        if all(rows[j]["ebitda"] >= 0 for j in (i, i + 1, i + 2)):
            be = rows[i]["month"]
            break
    last = rows[-1]
    cum_pos = next((r["month"] for r in rows if r["cum_ebitda"] >= 0 and r["month"] > 1 and r["net_revenue"] > 0), None)
    burn_last3 = -sum(r["ebitda"] for r in rows[-3:]) / 3.0
    runway = None
    if burn_last3 > 0:
        runway = max(last["cash"], 0.0) / burn_last3
    needed = last["cogs"] + last["opex"]
    per_encl = (p["enclave_infra"] + p["enclave_support"] + p["enclave_compliance"]) * p["enclave_margin"]
    gap = max(0.0, needed - last["net_revenue"])
    return {
        "required_net_revenue_m36": needed, "extra_enclaves_for_breakeven_m36": gap / per_encl if per_encl > 0 else float("inf"),
        "cum_net_revenue": cum_rev, "cum_gmv": cum_gmv, "net_revenue_m36": last["net_revenue"],
        "gmv_m36": last["gmv"], "ebitda_m36": last["ebitda"], "gross_margin_m36": last["gross_margin"],
        "funding_need": -min_cum, "min_cash": min_cash, "cash_out_month": cash_out, "breakeven_month": be,
        "cum_breakeven_month": cum_pos, "cash_m36": last["cash"], "runway_after_m36": runway,
        "operators_m36": last["operators"], "util_m36": last["utilisation"], "served_m36": last["served_mtok"],
        "dev_m36": last["dev_accounts"], "biz_m36": last["biz_accounts"], "enclaves_m36": last["enclaves"],
        "op_profit_m36": last["op_profit"], "fill_m36": last["fill"],
    }


def derive_financing(base_p, cutoff=18):
    """Pre-seed sized from base months 1..cutoff burn (+buffer); seed from the remaining base trough."""
    rows, _ = simulate(base_p)
    # worst point inside 1..cutoff (cum_ebitda can still be falling at cutoff)
    burn_pre = -min(r["cum_ebitda"] for r in rows[:cutoff])
    pre = math.ceil(burn_pre * base_p["buffer"] / 50000.0) * 50000.0
    trough = -min(r["cum_ebitda"] for r in rows)
    seed_need = max(0.0, trough - pre / base_p["buffer"]) * base_p["buffer"]
    seed = math.ceil(seed_need / 100000.0) * 100000.0
    return {1: pre, base_p["seed_month"]: seed}, {"burn_pre_seed_window": burn_pre, "pre_seed": pre, "seed": seed,
                                                     "trough_base": trough}


# --------------------------------------------------------------------------------------
# Sensitivities
# --------------------------------------------------------------------------------------
def run_metrics(p, fin):
    _, s = simulate(p, fin)
    return s


def sens_price(fin):
    out = []
    for e in (-0.6, -1.2, -1.8):
        for pm in (0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.4, 2.0, 3.0):
            p = scenario_params("base", {"elasticity": e, "price_mult_std": pm})
            s = run_metrics(p, fin)
            out.append({"elasticity": e, "price_mult_vs_market": pm, "cum_net_revenue": s["cum_net_revenue"],
                        "net_revenue_m36": s["net_revenue_m36"], "gmv_m36": s["gmv_m36"], "funding_need": s["funding_need"],
                        "ebitda_m36": s["ebitda_m36"], "op_profit_m36": s["op_profit_m36"]})
    return out


def sens_util(fin):
    out = []
    for u in (0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75):
        p = scenario_params("base", {"target_util": u})
        rows, s = simulate(p, fin)
        subs = sum(r["operator_incentive"] for r in rows)
        out.append({"target_util": u, "util_m36": s["util_m36"], "operators_m36": s["operators_m36"],
                    "fill_m36": s["fill_m36"], "cum_net_revenue": s["cum_net_revenue"],
                    "operator_incentive_total": subs, "op_profit_m36": s["op_profit_m36"],
                    "funding_need": s["funding_need"], "ebitda_m36": s["ebitda_m36"]})
    return out


def sens_cac(fin):
    out = []
    for f in (0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
        p = scenario_params("base")
        p["cac_dev"] = p["cac_dev"] * f
        rows, s = simulate(p, fin)
        out.append({"cac_multiplier": f, "cac_usd": p["cac_dev"], "dev_m36": s["dev_m36"],
                    "cum_net_revenue": s["cum_net_revenue"], "funding_need": s["funding_need"],
                    "ebitda_m36": s["ebitda_m36"], "ltv_cac": unit_economics(p)["ltv_dev_net"] / p["cac_dev"]})
    return out


def sens_team(fin):
    out = []
    for f in (0.5, 0.75, 1.0, 1.25):
        p = scenario_params("base")
        p["fte_plan"] = [(mo, max(1.0, n * f)) for mo, n in p["fte_plan"]]
        s = run_metrics(p, fin)
        out.append({"headcount_multiplier": f, "fte_m36": p["fte_plan"][-1][1], "funding_need": s["funding_need"],
                    "ebitda_m36": s["ebitda_m36"], "breakeven_month": s["breakeven_month"] if s["breakeven_month"] else -1,
                    "required_net_revenue_m36": s["required_net_revenue_m36"], "net_revenue_m36": s["net_revenue_m36"]})
    return out


def sens_throughput(fin):
    """node throughput as multiples of the simulator upper bound (>1.0 is hypothetical, e.g. better batching/quantisation)."""
    out = []
    for e in (0.25, 0.5, 0.75, 1.0, 2.0, 4.0):
        p = scenario_params("base", {"net_eff": e})
        rows, s = simulate(p, fin)
        out.append({"net_eff_vs_bound": e, "node_tps_effective": p["node_tps"] * e, "op_profit_m36": s["op_profit_m36"],
                    "operators_m36": s["operators_m36"], "fill_m36": s["fill_m36"], "gmv_m36": s["gmv_m36"],
                    "net_revenue_m36": s["net_revenue_m36"], "cum_net_revenue": s["cum_net_revenue"],
                    "funding_need": s["funding_need"]})
    return out


def sens_enclave(fin):
    out = []
    for n in (0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 6.0):
        p = scenario_params("base", {"enclave_new_per_quarter": n})
        s = run_metrics(p, fin)
        out.append({"enclave_new_per_quarter": n, "enclaves_m36": s["enclaves_m36"], "net_revenue_m36": s["net_revenue_m36"],
                    "ebitda_m36": s["ebitda_m36"], "funding_need": s["funding_need"],
                    "breakeven_month": s["breakeven_month"] if s["breakeven_month"] else -1})
    return out


def sens_split(fin):
    out = []
    for sp in ("current", "proposed"):
        for name in SCENARIO_NAMES:
            p = scenario_params(name, {"split": sp})
            s = run_metrics(p, fin)
            out.append({"split": sp, "scenario": name, "cum_net_revenue": s["cum_net_revenue"],
                        "net_revenue_m36": s["net_revenue_m36"], "ebitda_m36": s["ebitda_m36"],
                        "funding_need": s["funding_need"], "op_profit_m36": s["op_profit_m36"]})
    return out


# --------------------------------------------------------------------------------------
# Unit economics and operator economics
# --------------------------------------------------------------------------------------
def unit_economics(p):
    pref = reference_price(p)
    p_std = pref * p["price_mult_std"]
    split = SPLITS[p["split"]]
    toks = p["tokens_per_request"]
    rev_req = toks / 1e6 * p_std
    take = split["platform"]
    gm_var = max(0.0, take - p["pay_fee_pct"]) if take > p["pay_fee_pct"] else 0.0
    vol_mult = p["price_mult_std"] ** p["elasticity"]
    arpa_gmv = p["tok_per_dev_m"] * vol_mult * p_std
    arpa_net = arpa_gmv * take
    contrib = arpa_gmv * (take - p["pay_fee_pct"]) - p["tok_per_dev_m"] * vol_mult * p["infra_var_per_mtok"]
    ltv = contrib / p["dev_churn"] if contrib > 0 else 0.0
    return {
        "p_ref_blended_usd_per_mtok": pref, "p_std_usd_per_mtok": p_std,
        "revenue_per_request_usd": rev_req, "platform_take_per_request_usd": rev_req * take,
        "infra_var_per_request_usd": toks / 1e6 * p["infra_var_per_mtok"],
        "arpa_gmv_dev_month": arpa_gmv, "arpa_net_dev_month": arpa_net, "contrib_dev_month": contrib,
        "ltv_dev_net": ltv, "cac_dev": p["cac_dev"],
        "payback_months_dev": (p["cac_dev"] / contrib) if contrib > 0 else float("inf"),
        "enclave_cost_month": p["enclave_infra"] + p["enclave_support"] + p["enclave_compliance"],
        "enclave_fee_month": (p["enclave_infra"] + p["enclave_support"] + p["enclave_compliance"]) * (1 + p["enclave_margin"]),
        "gmv_needed_per_fte_month_for_take": p["fte_cost"] / take if take > 0 else float("inf"),
    }


def operator_table(p):
    """Operator economics grid: for tps x util, cost, revenue at standard price, breakeven price."""
    pref = reference_price(p)
    p_std = pref * p["price_mult_std"]
    split = SPLITS[p["split"]]
    node_share_plain = 1.0 - split["platform"] - split["verification"] - split["burn"]
    rows = []
    for tps in (20.0, 50.0, 100.0, 190.0, 1000.0):  # 190 = simulator bound; 1000 = hypothetical, not NEXUS
        q = dict(p)
        q["node_tps"] = tps
        q["net_eff"] = 1.0
        for util in (0.3, 0.5, 0.7):
            cap = node_capacity_mtok(q) * util
            for prof in OPERATOR_PROFILES:
                cost = operator_cost_month(prof, util, q)
                rev = cap * p_std * node_share_plain
                rows.append({"node_tps": tps, "util": util, "profile": prof, "tokens_mtok_month": cap,
                             "cost_usd_month": cost, "revenue_at_std_price": rev, "profit": rev - cost,
                             "breakeven_price_usd_per_mtok": breakeven_price(prof, util, q, node_share_plain),
                             "std_price_usd_per_mtok": p_std, "node_share": node_share_plain})
    return rows


# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------
def write_csv(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})


def fmt(x, nd=0):
    if x is None:
        return "n/a"
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return "n/a"
    return "{:,.{nd}f}".format(x, nd=nd)


def fmtm(x):
    return "no (>36)" if x is None else str(x)


def run_all(out_dir=OUT_DIR):
    os.makedirs(out_dir, exist_ok=True)
    base_p = scenario_params("base")
    fin, finfo = derive_financing(base_p)
    results = {}
    for name in SCENARIO_NAMES:
        p = scenario_params(name)
        rows, s = simulate(p, fin)
        results[name] = (p, rows, s)
        write_csv(os.path.join(out_dir, "monthly_%s.csv" % name), rows)
    # scenario summary
    summ_rows = []
    for name in SCENARIO_NAMES:
        s = results[name][2]
        row = {"scenario": name}
        row.update(s)
        summ_rows.append(row)
    write_csv(os.path.join(out_dir, "scenarios_summary.csv"), summ_rows)
    # quarterly
    q_rows = []
    for name in SCENARIO_NAMES:
        rows = results[name][1]
        for q in range(12):
            chunk = rows[q * 3:(q + 1) * 3]
            q_rows.append({"scenario": name, "quarter": q + 1, "gmv": sum(r["gmv"] for r in chunk),
                           "net_revenue": sum(r["net_revenue"] for r in chunk), "cogs": sum(r["cogs"] for r in chunk),
                           "opex": sum(r["opex"] for r in chunk), "ebitda": sum(r["ebitda"] for r in chunk),
                           "cash_end": chunk[-1]["cash"], "operators_end": chunk[-1]["operators"],
                           "utilisation_end": chunk[-1]["utilisation"]})
    write_csv(os.path.join(out_dir, "quarterly.csv"), q_rows)
    sp, su, sc, ss = sens_price(fin), sens_util(fin), sens_cac(fin), sens_split(fin)
    write_csv(os.path.join(out_dir, "sensitivity_price.csv"), sp)
    write_csv(os.path.join(out_dir, "sensitivity_utilization.csv"), su)
    write_csv(os.path.join(out_dir, "sensitivity_cac.csv"), sc)
    st = sens_team(fin)
    sth, sen = sens_throughput(fin), sens_enclave(fin)
    write_csv(os.path.join(out_dir, "sensitivity_throughput.csv"), sth)
    write_csv(os.path.join(out_dir, "sensitivity_enclave.csv"), sen)
    write_csv(os.path.join(out_dir, "sensitivity_team.csv"), st)
    write_csv(os.path.join(out_dir, "split_comparison.csv"), ss)
    ue = []
    for name in SCENARIO_NAMES:
        u = unit_economics(results[name][0])
        r = {"scenario": name}
        r.update(u)
        ue.append(r)
    write_csv(os.path.join(out_dir, "unit_economics.csv"), ue)
    ot = operator_table(base_p)
    write_csv(os.path.join(out_dir, "operator_economics.csv"), ot)
    write_resumen(out_dir, results, fin, finfo, sp, su, sc, ss, ue, ot, st, sth, sen)
    return results, fin, finfo


def write_resumen(out_dir, results, fin, finfo, sp, su, sc, ss, ue, ot, st, sth, sen):
    L = []
    a = L.append
    a("# Resumen del modelo financiero NEXUS (36 meses)")
    a("")
    a("Generado por `python3 finance/model.py`. **Todo son proyecciones con supuestos** (ver bloque `PARAM_TABLE` en `model.py`):")
    a("no existe hoy ningún ingreso, cliente de pago ni liquidación con dinero real (alpha cerrada, testnet, sin token). Moneda: USD.")
    a("Ingreso neto = lo que retiene la empresa (comisión de plataforma + tarifas de enclave/SLA/certificación/fine-tuning); el GMV es lo que paga el cliente.")
    a("")
    a("## Financiación derivada del caso base")
    a("")
    a("- Quema acumulada del caso base en la ventana de pre-seed (meses 1-18): **%s USD**." % fmt(finfo["burn_pre_seed_window"]))
    a("- Pre-seed dimensionada = quema x %.2f, redondeada a 50 k: **%s USD** (mes 1)." % (results["base"][0]["buffer"], fmt(finfo["pre_seed"])))
    a("- Seed (mes %d) para cubrir la fosa restante del caso base con el mismo colchón, redondeada a 100 k: **%s USD**." % (results["base"][0]["seed_month"], fmt(finfo["seed"])))
    a("- Esta misma financiación se aplica a los tres escenarios para ver quién se queda sin caja.")
    a("")
    a("## Resultados por escenario")
    a("")
    a("| Métrica | Conservador | Base | Optimista |")
    a("|---|---|---|---|")

    def line(label, key, nd=0, month=False):
        vals = []
        for n in SCENARIO_NAMES:
            v = results[n][2][key]
            vals.append(fmtm(v) if month else fmt(v, nd))
        a("| %s | %s | %s | %s |" % ((label,) + tuple(vals)))
    line("Ingreso neto acumulado 36 m (USD)", "cum_net_revenue")
    line("GMV acumulado 36 m (USD)", "cum_gmv")
    line("Ingreso neto mes 36 (USD/mes)", "net_revenue_m36")
    line("GMV mes 36 (USD/mes)", "gmv_m36")
    vals = ["%.0f%%" % (100 * results[n][2]["gross_margin_m36"]) if not math.isnan(results[n][2]["gross_margin_m36"]) else "n/a" for n in SCENARIO_NAMES]
    a("| Margen bruto mes 36 | %s | %s | %s |" % tuple(vals))
    line("EBITDA mes 36 (USD/mes)", "ebitda_m36")
    line("Necesidad máxima de financiación acumulada (USD)", "funding_need")
    line("Ingreso neto mensual necesario mes 36 para EBITDA = 0 (USD)", "required_net_revenue_m36")
    line("Contratos enclave ADICIONALES equivalentes para equilibrio mes 36", "extra_enclaves_for_breakeven_m36", nd=1)
    line("Caja mínima con la financiación derivada (USD)", "min_cash")
    line("Mes en que la caja es negativa", "cash_out_month", month=True)
    line("Punto de equilibrio mensual (EBITDA >= 0, 3 meses seguidos)", "breakeven_month", month=True)
    line("Caja al mes 36 (USD)", "cash_m36")
    line("Cuentas dev mes 36", "dev_m36")
    line("Cuentas business mes 36", "biz_m36", nd=1)
    line("Contratos enclave mes 36 (esperados)", "enclaves_m36", nd=1)
    line("Operadores mes 36", "operators_m36")
    vals = ["%.0f%%" % (100 * results[n][2]["util_m36"]) for n in SCENARIO_NAMES]
    a("| Utilización de nodos mes 36 | %s | %s | %s |" % tuple(vals))
    vals = ["%.0f%%" % (100 * results[n][2]["fill_m36"]) for n in SCENARIO_NAMES]
    a("| Demanda atendida mes 36 | %s | %s | %s |" % tuple(vals))
    line("Beneficio mensual medio por operador mes 36 (USD)", "op_profit_m36", nd=1)
    a("")
    a("## Ingresos por línea (mes 36, USD/mes)")
    a("")
    a("| Línea | Conservador | Base | Optimista |")
    a("|---|---|---|---|")
    for key, label in (("rev_inference", "Comisión sobre inferencia"), ("rev_royalty_fee", "Comisión sobre regalías (trabajos con adaptador)"),
                       ("rev_enclave", "Enclaves/swarms privados"), ("rev_sla", "Soporte y SLA"),
                       ("rev_cert", "Operadores certificados"), ("rev_finetune", "Fine-tuning")):
        a("| %s | %s | %s | %s |" % ((label,) + tuple(fmt(results[n][1][-1][key]) for n in SCENARIO_NAMES)))
    a("")
    a("## Ingresos netos por trimestre (USD)")
    a("")
    a("| Trimestre | Conservador | Base | Optimista |")
    a("|---|---|---|---|")
    for q in range(12):
        vals = [fmt(sum(r["net_revenue"] for r in results[n][1][q * 3:(q + 1) * 3])) for n in SCENARIO_NAMES]
        a("| T%d | %s | %s | %s |" % ((q + 1,) + tuple(vals)))
    a("")
    a("## Unidad económica (por escenario)")
    a("")
    a("| Concepto | Conservador | Base | Optimista |")
    a("|---|---|---|---|")
    for key, label, nd in (("p_ref_blended_usd_per_mtok", "Precio de referencia mezclado (USD/M tok)", 4),
                           ("p_std_usd_per_mtok", "Precio estándar NEXUS (USD/M tok)", 4),
                           ("revenue_per_request_usd", "Ingreso (GMV) por petición de 900 tok (USD)", 6),
                           ("platform_take_per_request_usd", "Retención de plataforma por petición (USD)", 6),
                           ("arpa_gmv_dev_month", "GMV mensual por cuenta dev (USD)", 2),
                           ("arpa_net_dev_month", "Ingreso neto mensual por cuenta dev (USD)", 3),
                           ("cac_dev", "CAC dev (USD)", 0),
                           ("ltv_dev_net", "LTV dev, margen de contribución (USD)", 2),
                           ("enclave_cost_month", "Coste mensual de un enclave (USD)", 0),
                           ("enclave_fee_month", "Tarifa mensual de enclave coste+margen (USD)", 0)):
        a("| %s | %s | %s | %s |" % ((label,) + tuple(fmt(u[key], nd) for u in ue)))
    a("")
    a("## Reparto del escrow: actual (75/10/5/5/5) frente a propuesto")
    a("")
    a("| Reparto | Escenario | Ingreso neto acum. 36 m | EBITDA mes 36 | Necesidad de financiación | Beneficio por operador m36 |")
    a("|---|---|---|---|---|---|")
    for r in ss:
        a("| %s | %s | %s | %s | %s | %s |" % (r["split"], r["scenario"], fmt(r["cum_net_revenue"]), fmt(r["ebitda_m36"]),
                                               fmt(r["funding_need"]), fmt(r["op_profit_m36"], 1)))
    a("")
    a("## Sensibilidad (caso base)")
    a("")
    a("### Precio y elasticidad (precio como fracción del precio de mercado)")
    a("")
    a("| Elasticidad | Precio/mercado | Ingreso neto acum. | Ingreso neto m36 | Necesidad financiación | Beneficio operador m36 |")
    a("|---|---|---|---|---|---|")
    for r in sp:
        a("| %.1f | %.2f | %s | %s | %s | %s |" % (r["elasticity"], r["price_mult_vs_market"], fmt(r["cum_net_revenue"]),
                                                   fmt(r["net_revenue_m36"]), fmt(r["funding_need"]), fmt(r["op_profit_m36"], 1)))
    a("")
    a("### Utilización objetivo de los nodos")
    a("")
    a("| Util. objetivo | Util. m36 | Operadores m36 | Demanda atendida m36 | Ingreso neto acum. | Incentivos a operadores acum. | Beneficio operador m36 | Necesidad financiación |")
    a("|---|---|---|---|---|---|---|---|")
    for r in su:
        a("| %.2f | %.0f%% | %s | %.0f%% | %s | %s | %s | %s |" % (r["target_util"], 100 * r["util_m36"], fmt(r["operators_m36"]),
                                                                  100 * r["fill_m36"], fmt(r["cum_net_revenue"]),
                                                                  fmt(r["operator_incentive_total"]), fmt(r["op_profit_m36"], 1), fmt(r["funding_need"])))
    a("")
    a("### Coste de adquisición")
    a("")
    a("| Multiplicador CAC | CAC (USD) | Cuentas dev m36 | Ingreso neto acum. | Necesidad financiación | LTV/CAC |")
    a("|---|---|---|---|---|---|")
    for r in sc:
        a("| %.2f | %s | %s | %s | %s | %.2f |" % (r["cac_multiplier"], fmt(r["cac_usd"]), fmt(r["dev_m36"]), fmt(r["cum_net_revenue"]),
                                                   fmt(r["funding_need"]), r["ltv_cac"]))
    a("")
    a("### Rendimiento por nodo (fracción de la cota del simulador, 190 tok/s; >1 es hipotético)")
    a("")
    a("| Fracción de la cota | tok/s efectivos | Beneficio operador m36 | Operadores m36 | Demanda atendida m36 | GMV m36 | Ingreso neto m36 | Necesidad financiación |")
    a("|---|---|---|---|---|---|---|---|")
    for r in sth:
        a("| %.2f | %s | %s | %s | %.0f%% | %s | %s | %s |" % (r["net_eff_vs_bound"], fmt(r["node_tps_effective"], 1), fmt(r["op_profit_m36"], 1),
                                                              fmt(r["operators_m36"]), 100 * r["fill_m36"], fmt(r["gmv_m36"]),
                                                              fmt(r["net_revenue_m36"]), fmt(r["funding_need"])))
    a("")
    a("### Contratos enclave nuevos por trimestre (caso base)")
    a("")
    a("| Nuevos/trimestre | Enclaves m36 | Ingreso neto m36 | EBITDA m36 | Necesidad financiación | Equilibrio (mes) |")
    a("|---|---|---|---|---|---|")
    for r in sen:
        a("| %.1f | %.1f | %s | %s | %s | %s |" % (r["enclave_new_per_quarter"], r["enclaves_m36"], fmt(r["net_revenue_m36"]), fmt(r["ebitda_m36"]),
                                                    fmt(r["funding_need"]), "no (>36)" if r["breakeven_month"] == -1 else r["breakeven_month"]))
    a("")
    a("### Tamaño del equipo (caso base)")
    a("")
    a("| Multiplicador de plantilla | FTE mes 36 | Ingreso neto necesario m36 | Ingreso neto m36 | EBITDA m36 | Necesidad financiación | Equilibrio (mes) |")
    a("|---|---|---|---|---|---|---|")
    for r in st:
        a("| %.2f | %.1f | %s | %s | %s | %s | %s |" % (r["headcount_multiplier"], r["fte_m36"], fmt(r["required_net_revenue_m36"]),
                                                       fmt(r["net_revenue_m36"]), fmt(r["ebitda_m36"]), fmt(r["funding_need"]),
                                                       "no (>36)" if r["breakeven_month"] == -1 else r["breakeven_month"]))
    a("")
    a("## Economía del operador (caso base, precio estándar, comisión propuesta)")
    a("")
    a("Parámetros de hardware y potencia en `OPERATOR_PROFILES`; electricidad %.2f EUR/kWh x %.2f USD/EUR. `node_tps` NO está medido." % (
        results["base"][0]["kwh_eur"], results["base"][0]["fx_usd_per_eur"]))
    a("")
    a("| tok/s por nodo | Util. | Perfil | M tok/mes | Coste USD/mes | Ingreso USD/mes | Beneficio | Precio de equilibrio USD/M tok (vs estándar %.4f) |" % ot[0]["std_price_usd_per_mtok"])
    a("|---|---|---|---|---|---|---|---|")
    for r in ot:
        a("| %s | %.1f | %s | %s | %s | %s | %s | %s |" % (fmt(r["node_tps"]), r["util"], r["profile"], fmt(r["tokens_mtok_month"], 1),
                                                           fmt(r["cost_usd_month"], 1), fmt(r["revenue_at_std_price"], 1),
                                                           fmt(r["profit"], 1), fmt(r["breakeven_price_usd_per_mtok"], 4)))
    a("")
    a("Dilución orientativa de una ronda con el importe derivado (aritmética pura, valoración PRE-money hipotética):")
    a("")
    a("| Pre-money hipotético (USD) | Pre-seed %s | Seed %s |" % (fmt(finfo["pre_seed"]), fmt(finfo["seed"])))
    a("|---|---|---|")
    for pre in (3e6, 5e6, 8e6):
        a("| %s | %.1f%% | %.1f%% |" % (fmt(pre), 100 * finfo["pre_seed"] / (pre + finfo["pre_seed"]),
                                        100 * finfo["seed"] / (pre * 2 + finfo["seed"])))
    a("")
    a("(La columna seed asume un pre-money del doble que el de la pre-seed; es un ejemplo, no una valoración.)")
    a("")
    with open(os.path.join(out_dir, "resumen.md"), "w") as f:
        f.write("\n".join(L) + "\n")


def main():
    results, fin, finfo = run_all()
    print("Financiación derivada: pre-seed %s USD (mes 1), seed %s USD (mes %d)" % (
        fmt(finfo["pre_seed"]), fmt(finfo["seed"]), results["base"][0]["seed_month"]))
    for n in SCENARIO_NAMES:
        s = results[n][2]
        print("%-12s ingreso neto acum %12s | m36 %9s/mes | EBITDA m36 %10s | necesidad %10s | caja negativa: %s | equilibrio: %s" % (
            n, fmt(s["cum_net_revenue"]), fmt(s["net_revenue_m36"]), fmt(s["ebitda_m36"]), fmt(s["funding_need"]),
            fmtm(s["cash_out_month"]), fmtm(s["breakeven_month"])))
    print("Salida en %s" % OUT_DIR)


if __name__ == "__main__":
    sys.exit(main())
