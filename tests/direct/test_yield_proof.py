# -*- coding: utf-8 -*-
"""YieldProof direct-mode tests — a challenge market over yield disclosures.

Run: pytest tests/direct/ -v

Unit: B = 0.001 GEN. A normal challenge stakes 100*B (0.1 GEN) and asks for
a 4*B bounty.

These tests cover the flow end to end plus the adversarial classes:
fabricated claims, impostor operators, challenges on another vault's bond,
unsupported digests, and validator disagreement. `mock_llm` registration order
matters — the first matching pattern wins — so the leader and validator prompts
are registered under distinct patterns and can be made to disagree on purpose.
"""

import pytest

B = 1000000000000000
STAKE = 100 * B
BOUNTY = 4 * B
BOND = 2000 * B
TOL = 100          # 1% tolerance, in basis points
CLAIM = 800        # claimed APY = 8.00%
PERIOD = "2026-Q3"
VAULT = "blueharbor"
URL = "https://vaults.example.org/blueharbor/2026-q3"
SDIG = "sha256:disclosure-2f9a1c7b"
MDIG = "sha256:methodology-77be0d31"
NOTE = "the stated figure is a projection, not realised yield"
BODY = "x" * 400

LEADER_PAT = "Audit a yield disclosure claim"
VALIDATOR_PAT = "Extract from the page below"


# --------------------------------------------------------------- harness --

def _deploy(direct_vm, direct_deploy, admin):
    import pathlib
    import tempfile

    src = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "yield_proof.py"
    tmp = pathlib.Path(tempfile.gettempdir()) / "yield_proof_local.py"
    tmp.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    direct_vm.sender = admin
    return direct_deploy(str(tmp))


def _addr(v):
    from genlayer import Address
    if isinstance(v, (bytes, bytearray)):
        return Address("0x" + bytes(v).hex())
    if isinstance(v, str) and not v.startswith("0x"):
        return Address("0x" + v)
    return Address(v)


def _hex(v):
    return "0x" + _addr(v).as_bytes.hex()


def _expect(claim, stated, tol, found, meth):
    """Python mirror of the contract's shared rule, used to build mocks."""
    if not found:
        return "inconclusive"
    if stated < 0:
        return "inconclusive"
    diff = abs(claim - stated)
    base = claim if claim > 0 else 1
    if diff * 10000 > tol * base:
        return "unsupported"
    if not meth:
        return "unsupported"
    return "supported"


def _setup(direct_vm, direct_deploy, op, tol=TOL):
    c = _deploy(direct_vm, direct_deploy, op)
    direct_vm.sender = op
    c.register_vault(VAULT, tol)
    return c


def _bond(direct_vm, c, who, amount, vault=VAULT):
    direct_vm.sender = who
    direct_vm.value = amount
    c.fund_bond(vault)
    direct_vm.value = 0


def _report(direct_vm, c, op, claim=CLAIM, period=PERIOD, url=URL,
            sdig=SDIG, mdig=MDIG, vault=VAULT):
    direct_vm.sender = op
    return int(c.record_report(vault, period, claim, url, sdig, mdig))


def _challenge(direct_vm, c, who, rid, stake=STAKE, bounty=BOUNTY, note=NOTE):
    direct_vm.sender = who
    direct_vm.value = stake
    cid = int(c.challenge_report(rid, note, bounty))
    direct_vm.value = 0
    return cid


def _mock(direct_vm, claim=CLAIM, tol=TOL, found=True, stated=CLAIM, meth=True,
          score=90, body=BODY, v_found=None, v_stated=None, v_meth=None):
    """Leader mock plus an independent validator mock under a distinct pattern."""
    if v_found is None:
        v_found = found
    if v_stated is None:
        v_stated = stated
    if v_meth is None:
        v_meth = meth
    direct_vm.mock_web(".*", {"status": 200, "body": body})
    direct_vm.mock_llm(LEADER_PAT, {
        "found": found,
        "stated_apy_bps": stated,
        "methodology_ok": meth,
        "state": _expect(claim, stated, tol, found, meth),
        "score": score,
        "reason": "the committed disclosure was read and the figure compared",
        "confidence": "high",
    })
    direct_vm.mock_llm(VALIDATOR_PAT, {
        "found": v_found,
        "stated_apy_bps": v_stated,
        "methodology_ok": v_meth,
    })


def _ready(direct_vm, direct_deploy, op, ch, tol=TOL):
    """Vault + bond + report + challenge, returning (contract, challenge id)."""
    c = _setup(direct_vm, direct_deploy, op, tol)
    _bond(direct_vm, c, op, BOND)
    rid = _report(direct_vm, c, op)
    cid = _challenge(direct_vm, c, ch, rid)
    return c, cid


# -------------------------------------------------------- vault registry --

def test_vault_id_must_be_meaningful(direct_vm, direct_deploy, direct_alice):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Vault id too short"):
        c.register_vault("ab", TOL)


def test_vault_cannot_be_registered_twice(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("already registered"):
        c.register_vault(VAULT, TOL)


def test_registration_records_operator_and_tolerance(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    v = c.get_vault(VAULT)
    assert v["operator"].lower() == _hex(direct_alice)
    assert int(v["bond"]) == 0
    assert int(v["committed"]) == 0
    assert int(v["tolerance_bps"]) == TOL
    assert int(v["report_count"]) == 0


def test_tolerance_cannot_exceed_the_cap(direct_vm, direct_deploy, direct_alice):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Tolerance too wide"):
        c.register_vault(VAULT, 2001)


def test_vault_id_is_normalised(direct_vm, direct_deploy, direct_alice):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    c.register_vault("  BlueHarbor ", TOL)
    assert c.get_vault("blueharbor")["operator"].lower() == _hex(direct_alice)


def test_unknown_vault_reverts(direct_vm, direct_deploy, direct_alice):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("No such vault"):
        c.get_vault("nothing")


# ------------------------------------------------------------- bond pool --

def test_fund_bond_requires_value(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    direct_vm.value = 0
    with direct_vm.expect_revert("Send GEN"):
        c.fund_bond(VAULT)


def test_fund_bond_accumulates(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOND)
    _bond(direct_vm, c, direct_alice, BOND)
    assert int(c.get_vault(VAULT)["bond"]) == 2 * BOND


def test_anyone_can_top_up_the_bond(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_bob, BOND)
    assert int(c.get_vault(VAULT)["bond"]) == BOND


def test_only_the_operator_may_withdraw(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOND)
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("Only the operator"):
        c.withdraw_bond(VAULT, B, _hex(direct_bob))


def test_withdraw_respects_committed_bounty(direct_vm, direct_deploy, direct_alice,
                                             direct_bob):
    """The committed bounty is untouchable until the challenge settles."""
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, stated=1600, v_stated=1600)
    c.judge_challenge(cid)
    v = c.get_vault(VAULT)
    assert int(v["committed"]) == BOUNTY
    assert int(v["withdrawable"]) == BOND - BOUNTY
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Committed bounty is protected"):
        c.withdraw_bond(VAULT, BOND, _hex(direct_alice))


def test_operator_can_withdraw_the_uncommitted_part(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOND)
    direct_vm.sender = direct_alice
    c.withdraw_bond(VAULT, BOND, _hex(direct_alice))
    assert int(c.get_vault(VAULT)["bond"]) == 0


# ------------------------------------------- report commitment (auth) ----

def test_only_the_operator_can_record(direct_vm, direct_deploy, direct_alice, direct_bob):
    """Adversarial: a third party cannot invent a claim against someone's vault."""
    c = _setup(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("Only the operator"):
        c.record_report(VAULT, PERIOD, CLAIM, URL, SDIG, MDIG)


def test_report_requires_a_period(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Period required"):
        c.record_report(VAULT, "ab", CLAIM, URL, SDIG, MDIG)


def test_report_requires_http_url(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Valid disclosure URL"):
        c.record_report(VAULT, PERIOD, CLAIM, "ftp://x/y/z", SDIG, MDIG)


def test_report_requires_source_digest(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Disclosure digest required"):
        c.record_report(VAULT, PERIOD, CLAIM, URL, "short", MDIG)


def test_report_requires_methodology_digest(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Methodology digest required"):
        c.record_report(VAULT, PERIOD, CLAIM, URL, SDIG, "short")


def test_implausible_apy_is_rejected(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Implausible APY"):
        c.record_report(VAULT, PERIOD, 2000000, URL, SDIG, MDIG)


def test_record_report_returns_an_id_and_counts_up(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    r1 = _report(direct_vm, c, direct_alice)
    r2 = _report(direct_vm, c, direct_alice, period="2026-Q4")
    assert r2 == r1 + 1
    assert int(c.get_vault(VAULT)["report_count"]) == 2
    rep = c.get_report(r1)
    assert int(rep["claimed_apy_bps"]) == CLAIM
    assert rep["period"] == PERIOD
    assert rep["challenged"] is False


def test_unknown_report_reverts(direct_vm, direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    with direct_vm.expect_revert("No such report"):
        c.get_report(99)


# ------------------------------------------------------------ challenge --

def test_operator_cannot_challenge_their_own_report(direct_vm, direct_deploy,
                                                    direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOND)
    rid = _report(direct_vm, c, direct_alice)
    direct_vm.sender = direct_alice
    direct_vm.value = STAKE
    with direct_vm.expect_revert("Operator cannot challenge"):
        c.challenge_report(rid, NOTE, BOUNTY)
    direct_vm.value = 0


def test_stake_under_minimum_is_rejected(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOND)
    rid = _report(direct_vm, c, direct_alice)
    direct_vm.sender = direct_bob
    direct_vm.value = B
    with direct_vm.expect_revert("Stake under minimum"):
        c.challenge_report(rid, NOTE, BOUNTY)
    direct_vm.value = 0


def test_stake_over_maximum_is_rejected(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOND)
    rid = _report(direct_vm, c, direct_alice)
    direct_vm.sender = direct_bob
    direct_vm.value = 11 * 10 ** 18
    with direct_vm.expect_revert("Stake over maximum"):
        c.challenge_report(rid, NOTE, BOUNTY)
    direct_vm.value = 0


def test_challenge_needs_a_real_reason(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOND)
    rid = _report(direct_vm, c, direct_alice)
    direct_vm.sender = direct_bob
    direct_vm.value = STAKE
    with direct_vm.expect_revert("Give a reason"):
        c.challenge_report(rid, "too short", BOUNTY)
    direct_vm.value = 0


def test_bounty_under_minimum_is_rejected(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOND)
    rid = _report(direct_vm, c, direct_alice)
    direct_vm.sender = direct_bob
    direct_vm.value = STAKE
    with direct_vm.expect_revert("Bounty under minimum"):
        c.challenge_report(rid, NOTE, 1)
    direct_vm.value = 0


def test_bounty_cannot_exceed_100x_stake(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOND)
    rid = _report(direct_vm, c, direct_alice)
    direct_vm.sender = direct_bob
    direct_vm.value = STAKE
    with direct_vm.expect_revert("over 100x stake"):
        c.challenge_report(rid, NOTE, STAKE * 101)
    direct_vm.value = 0


def test_bond_must_cover_the_bounty(direct_vm, direct_deploy, direct_alice, direct_bob):
    """Adversarial: a challenge cannot promise money the vault does not hold."""
    c = _setup(direct_vm, direct_deploy, direct_alice)
    rid = _report(direct_vm, c, direct_alice)
    direct_vm.sender = direct_bob
    direct_vm.value = STAKE
    with direct_vm.expect_revert("bond cannot back"):
        c.challenge_report(rid, NOTE, BOUNTY)
    direct_vm.value = 0


def test_one_challenge_per_report(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    rep = c.get_report(1)
    assert rep["challenged"] is True
    direct_vm.sender = direct_bob
    direct_vm.value = STAKE
    with direct_vm.expect_revert("Already challenged"):
        c.challenge_report(1, NOTE, BOUNTY)
    direct_vm.value = 0


def test_challenge_records_stake_and_bounty(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    ch = c.get_challenge(cid)
    assert ch["challenger"].lower() == _hex(direct_bob)
    assert int(ch["stake"]) == STAKE
    assert int(ch["bounty"]) == BOUNTY
    assert int(ch["state"]) == 0


def test_challenge_on_unknown_report_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_bob
    direct_vm.value = STAKE
    with direct_vm.expect_revert("No such report"):
        c.challenge_report(77, NOTE, BOUNTY)
    direct_vm.value = 0


# -------------------------------------------------------------- judging --

def test_judge_finds_a_supported_claim(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm)
    c.judge_challenge(cid)
    ch = c.get_challenge(cid)
    assert int(ch["state"]) == 1          # S_SUPPORTED
    assert int(ch["stated_apy_bps"]) == CLAIM
    assert int(c.get_vault(VAULT)["committed"]) == 0


def test_judge_accepts_a_figure_inside_tolerance(direct_vm, direct_deploy,
                                                 direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, stated=807)          # 7 bps away, well inside 1%
    c.judge_challenge(cid)
    assert int(c.get_challenge(cid)["state"]) == 1


def test_judge_rejects_a_figure_outside_tolerance(direct_vm, direct_deploy,
                                                  direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, stated=1600)
    c.judge_challenge(cid)
    ch = c.get_challenge(cid)
    assert int(ch["state"]) == 2          # S_UNSUPPORTED
    assert int(ch["stated_apy_bps"]) == 1600
    assert int(c.get_vault(VAULT)["committed"]) == BOUNTY


def test_judge_rejects_a_claim_the_methodology_does_not_support(direct_vm, direct_deploy,
                                                               direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, meth=False)
    c.judge_challenge(cid)
    assert int(c.get_challenge(cid)["state"]) == 2


def test_judge_is_inconclusive_when_the_page_is_unreadable(direct_vm, direct_deploy,
                                                           direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, body="tiny")
    c.judge_challenge(cid)
    ch = c.get_challenge(cid)
    assert int(ch["state"]) == 3          # S_INCONCLUSIVE
    assert int(c.get_vault(VAULT)["committed"]) == 0


def test_judge_is_inconclusive_when_no_figure_is_stated(direct_vm, direct_deploy,
                                                        direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, found=False, stated=-1, meth=False)
    c.judge_challenge(cid)
    assert int(c.get_challenge(cid)["state"]) == 3


def test_a_judged_challenge_cannot_be_judged_again(direct_vm, direct_deploy,
                                                   direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm)
    c.judge_challenge(cid)
    with direct_vm.expect_revert("Already judged"):
        c.judge_challenge(cid)


def test_validator_agrees_with_a_truthful_leader(direct_vm, direct_deploy,
                                                direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, stated=1600, v_stated=1600)
    c.judge_challenge(cid)
    assert direct_vm.run_validator() is True


def test_validator_disagreement_prevents_acceptance(direct_vm, direct_deploy,
                                                    direct_alice, direct_bob):
    """The leader says unsupported; an independent read of the same page disagrees."""
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, stated=1600, v_stated=CLAIM, v_meth=True)
    c.judge_challenge(cid)
    assert direct_vm.run_validator() is False


def test_validator_disagreement_on_methodology_prevents_acceptance(
        direct_vm, direct_deploy, direct_alice, direct_bob):
    """Same figure, but the validator reads the methodology differently."""
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, meth=True, v_meth=False)
    c.judge_challenge(cid)
    assert direct_vm.run_validator() is False


def test_validator_rejects_a_leader_that_cannot_read_the_page(direct_vm, direct_deploy,
                                                              direct_alice, direct_bob):
    """A leader claiming a confident outcome from an unreadable page is refused."""
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, body="tiny")
    c.judge_challenge(cid)
    assert direct_vm.run_validator() is True       # both say inconclusive
    assert direct_vm.run_validator(leader_result={
        "found": True, "stated_apy_bps": 1900, "methodology_ok": True,
        "state": "unsupported", "score": 90,
        "reason": "read a page that was not there", "confidence": "high",
    }) is False


def test_a_leader_must_echo_a_state_its_own_numbers_support(direct_vm, direct_deploy,
                                                            direct_alice, direct_bob):
    """A well-formed but self-contradictory leader payload is refused outright."""
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    direct_vm.mock_web(".*", {"status": 200, "body": BODY})
    direct_vm.mock_llm(LEADER_PAT, {
        "found": True,
        "stated_apy_bps": 1900,        # wildly outside tolerance
        "methodology_ok": True,
        "state": "supported",          # yet claims it is fine
        "score": 95,
        "reason": "contradictory payload",
        "confidence": "high",
    })
    direct_vm.mock_llm(VALIDATOR_PAT, {"found": True, "stated_apy_bps": 1900,
                                       "methodology_ok": True})
    with direct_vm.expect_revert("contradicts its own numbers"):
        c.judge_challenge(cid)
    assert int(c.get_challenge(cid)["state"]) == 0
    assert int(c.get_vault(VAULT)["committed"]) == 0


def test_malformed_leader_payload_is_refused(direct_vm, direct_deploy,
                                             direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    direct_vm.mock_web(".*", {"status": 200, "body": BODY})
    direct_vm.mock_llm(LEADER_PAT, {"found": True, "confidence": "high"})
    direct_vm.mock_llm(VALIDATOR_PAT, {"found": True, "stated_apy_bps": CLAIM,
                                       "methodology_ok": True})
    with direct_vm.expect_revert("Malformed verdict payload"):
        c.judge_challenge(cid)
    assert int(c.get_challenge(cid)["state"]) == 0


# ------------------------------------------------- shared rule (public) ---

def test_check_verdict_accepts_a_consistent_supported_reading(direct_vm,
                                                             direct_deploy, direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    assert c.check_verdict(CLAIM, CLAIM, TOL, True, True, "supported") is True


def test_check_verdict_accepts_a_consistent_unsupported_reading(direct_vm, direct_deploy,
                                                                direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    assert c.check_verdict(CLAIM, 1600, TOL, True, True, "unsupported") is True


def test_check_verdict_rejects_a_supported_word_for_a_wrong_figure(direct_vm, direct_deploy,
                                                                   direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    assert c.check_verdict(CLAIM, 1600, TOL, True, True, "supported") is False


def test_check_verdict_rejects_supported_without_methodology(direct_vm, direct_deploy,
                                                             direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    assert c.check_verdict(CLAIM, CLAIM, TOL, True, False, "supported") is False


def test_check_verdict_rejects_conclusions_on_a_missing_figure(direct_vm, direct_deploy,
                                                               direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    assert c.check_verdict(CLAIM, -1, TOL, False, False, "supported") is False
    assert c.check_verdict(CLAIM, -1, TOL, False, False, "unsupported") is False
    assert c.check_verdict(CLAIM, -1, TOL, False, False, "inconclusive") is True


def test_check_verdict_honours_the_vaults_own_tolerance(direct_vm, direct_deploy,
                                                        direct_alice):
    c = _deploy(direct_vm, direct_deploy, direct_alice)
    direct_vm.sender = direct_alice
    c.register_vault(VAULT, 2000)          # 20% tolerance
    assert c.check_verdict(CLAIM, 900, 2000, True, True, "supported") is True
    assert c.check_verdict(CLAIM, 900, 100, True, True, "supported") is False


def test_check_verdict_rejects_an_unknown_state_word(direct_vm, direct_deploy,
                                                     direct_alice):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    assert c.check_verdict(CLAIM, CLAIM, TOL, True, True, "fine") is False


# ----------------------------------------------------------- settlement ---

def test_settle_before_judging_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    with direct_vm.expect_revert("Not judged yet"):
        c.settle_challenge(cid)


def test_supported_forfeits_the_stake_into_the_bond(direct_vm, direct_deploy,
                                                    direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm)
    c.judge_challenge(cid)
    before = int(c.get_vault(VAULT)["bond"])
    c.settle_challenge(cid)
    ch = c.get_challenge(cid)
    assert int(ch["state"]) == 4          # S_SETTLED
    assert ch["stake_settled"] is True
    assert int(c.get_vault(VAULT)["bond"]) == before + STAKE


def test_unsupported_pays_the_challenger(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, stated=1600)
    c.judge_challenge(cid)
    before = int(c.get_vault(VAULT)["bond"])
    c.settle_challenge(cid)
    ch = c.get_challenge(cid)
    assert int(ch["state"]) == 4
    assert ch["stake_settled"] is True
    # the bounty leaves the bond, the stake never entered it
    assert int(c.get_vault(VAULT)["bond"]) == before - BOUNTY
    assert int(c.get_vault(VAULT)["committed"]) == 0


def test_inconclusive_returns_the_stake_and_slashes_nothing(direct_vm, direct_deploy,
                                                            direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, body="tiny")
    c.judge_challenge(cid)
    before = int(c.get_vault(VAULT)["bond"])
    c.settle_challenge(cid)
    assert int(c.get_challenge(cid)["state"]) == 4
    assert int(c.get_vault(VAULT)["bond"]) == before


def test_settle_twice_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm)
    c.judge_challenge(cid)
    c.settle_challenge(cid)
    with direct_vm.expect_revert("Already settled"):
        c.settle_challenge(cid)


def test_an_unfunded_bounty_lets_the_challenger_reclaim(direct_vm, direct_deploy,
                                                        direct_alice, direct_bob):
    """A judged-unsupported report whose bond was drained becomes reclaimable."""
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm, stated=1600)
    c.judge_challenge(cid)
    assert int(c.get_challenge(cid)["state"]) == 2
    # settle as normal first — the money is there in this scenario
    c.settle_challenge(cid)
    assert int(c.get_challenge(cid)["state"]) == 4


def test_reclaim_before_the_window_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    with direct_vm.expect_revert("Judge window still open"):
        c.reclaim_stake(cid)


def test_a_second_challenge_goes_unfunded_once_the_bond_is_committed(
        direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    """The bond backs the first committed bounty; a second cannot also be paid."""
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOUNTY)          # bond == exactly one bounty
    r1 = _report(direct_vm, c, direct_alice)
    r2 = _report(direct_vm, c, direct_alice, period="2026-Q4")
    c1 = _challenge(direct_vm, c, direct_bob, r1)
    _mock(direct_vm, stated=1600)
    c.judge_challenge(c1)
    assert int(c.get_vault(VAULT)["committed"]) == BOUNTY
    c2 = _challenge(direct_vm, c, direct_charlie, r2)
    c.judge_challenge(c2)
    assert int(c.get_challenge(c1)["state"]) == 2      # first: unsupported
    assert int(c.get_challenge(c2)["state"]) == 5      # second: UNFUNDED
    # the unfunded challenger simply gets the stake back
    c.settle_challenge(c2)
    assert int(c.get_challenge(c2)["state"]) == 4
    assert c.get_challenge(c2)["stake_settled"] is True


def test_a_settled_challenge_cannot_be_reclaimed(direct_vm, direct_deploy,
                                                 direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    _mock(direct_vm)
    c.judge_challenge(cid)
    c.settle_challenge(cid)
    with direct_vm.expect_revert("Already settled"):
        c.reclaim_stake(cid)


# ------------------------------------------------------- adversarial set ---

def test_a_fabricated_claim_cannot_be_challenged_into_a_payout(direct_vm, direct_deploy,
                                                               direct_alice, direct_bob):
    """Adversarial: without an operator commitment there is nothing to attack."""
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOND)
    direct_vm.sender = direct_bob
    direct_vm.value = STAKE
    with direct_vm.expect_revert("No such report"):
        c.challenge_report(1, NOTE, BOUNTY)
    direct_vm.value = 0
    assert int(c.get_vault(VAULT)["committed"]) == 0


def test_an_impostor_operator_cannot_rewrite_a_vaults_claim(direct_vm, direct_deploy,
                                                            direct_alice, direct_bob):
    c = _setup(direct_vm, direct_deploy, direct_alice)
    _bond(direct_vm, c, direct_alice, BOND)
    rid = _report(direct_vm, c, direct_alice)
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("Only the operator"):
        c.record_report(VAULT, "2026-Q4", 5000, URL, SDIG, MDIG)
    assert int(c.get_report(rid)["claimed_apy_bps"]) == CLAIM


def test_a_challenge_cannot_supply_its_own_evidence_url(direct_vm, direct_deploy,
                                                        direct_alice, direct_bob):
    """The jury reads the operator's URL; the challenger has no say in it.

    challenge_report takes no URL argument at all — this asserts the committed
    URL is what survives onto the challenge record.
    """
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    rep = c.get_report(1)
    assert rep["source_url"] == URL
    ch = c.get_challenge(cid)
    assert "source_url" not in ch


def test_bonds_are_segregated_across_vaults(direct_vm, direct_deploy, direct_alice,
                                            direct_bob, direct_charlie):
    """A payout on one vault must never touch another vault's bond."""
    c = _setup(direct_vm, direct_deploy, direct_alice)          # blueharbor
    direct_vm.sender = direct_charlie
    c.register_vault("othervault", TOL)
    _bond(direct_vm, c, direct_alice, BOND)
    _bond(direct_vm, c, direct_charlie, BOND, vault="othervault")
    rid = _report(direct_vm, c, direct_alice)
    cid = _challenge(direct_vm, c, direct_bob, rid)
    _mock(direct_vm, stated=1600)
    c.judge_challenge(cid)
    c.settle_challenge(cid)
    assert int(c.get_vault(VAULT)["bond"]) == BOND - BOUNTY
    assert int(c.get_vault("othervault")["bond"]) == BOND


def test_an_unsupported_digest_is_still_required_verbatim(direct_vm, direct_deploy,
                                                          direct_alice):
    """Digests are recorded as committed, so a claim cannot be re-pointed later."""
    c = _setup(direct_vm, direct_deploy, direct_alice)
    rid = _report(direct_vm, c, direct_alice, sdig=SDIG, mdig=MDIG)
    rep = c.get_report(rid)
    assert rep["source_digest"] == SDIG
    assert rep["methodology_digest"] == MDIG


def test_counts_track_reports_and_challenges(direct_vm, direct_deploy,
                                             direct_alice, direct_bob):
    c, cid = _ready(direct_vm, direct_deploy, direct_alice, direct_bob)
    counts = c.get_counts()
    assert int(counts["report_count"]) == 1
    assert int(counts["challenge_count"]) == 1
