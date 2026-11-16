# YieldProof

**A challenge market over yield disclosures, judged on-chain.**

A vault can advertise any annualised yield it likes. YieldProof makes that number
something a third party can attack — and makes the payout depend on what the
committed page actually says, not on what either party claims it says.

- **Primary tag:** DeFi
- **Sub-tags:** Yield Optimization · Treasury Rebalancing
- **Network:** GenLayer Studionet (chain 61999)
- **Contract:** [`0x00b3ef8e9D3F0e57f5C63345202fCb8ae8dc801d`](https://explorer-studio.genlayer.com/address/0x00b3ef8e9D3F0e57f5C63345202fCb8ae8dc801d)
- **Deploy tx:** `0xcf0365f9aa57070b43bfed79ad9838d410f67788b12700a93365eb85d3cd3616` — ACCEPTED, MAJORITY_AGREE, leader `return`
- **Size:** 26,346 bytes · **14 public methods** · **73 direct-mode tests passing**
- **Admin:** the deploying account (the operator of the first vault, not a privileged role)

> **Revision 2.** Challenge bounties are now **reserved atomically when the
> challenge opens**, not when it is judged. A bond can therefore only back as many
> open bounties as it can actually pay, the reserved amount is unavailable to
> `withdraw_bond` for the whole life of the challenge, and settlement either pays
> or releases it. See [Money](#money) and
> [the reservation transcript](#the-reviewers-case-reservation-in-action).


---

## The problem this addresses

A treasury allocating capital to vaults has to believe a number it cannot check.
A vault reports "8.00% realised for the quarter", links a page, and the allocator
either trusts it or walks away. There is no cheap way to dispute a figure that is
technically published but practically unauditable — and no consequence when the
figure turns out to be a projection dressed up as realised yield.

YieldProof turns that into a market with money on both sides.

## Who commits what

The design rule is that **the party with authority commits the evidence, and the
party with the grievance can only reference it.**

| Party | Can do | Cannot do |
|---|---|---|
| Vault operator | `register_vault`, `record_report`, `withdraw_bond` | challenge their own report, withdraw committed bounty |
| Anyone | `fund_bond`, `challenge_report`, `settle_challenge`, `reclaim_stake` | record a report on someone else's vault |
| Jury (validators) | fetch the committed URL and extract the figure | see any URL a challenger chose |

`record_report` binds, in one commitment: the vault id, the reporting period, the
claimed APY in basis points, the disclosure URL, a digest of the disclosure and a
digest of the stated methodology. There is no appeal without a decision, and there
is no challenge without a report.

`challenge_report` takes **no URL argument at all**. A challenger stakes GEN and
gives a reason; the jury reads the URL the operator committed. A challenger
therefore cannot point the jury at a page of their own choosing, which is the
obvious way a naive design gets farmed.

## How the verdict is derived

The jury does not get to invent an outcome. It returns two numbers and a boolean,
and the contract derives the verdict from them with a rule that is applied
identically everywhere:

```
derive(claimed, stated, tolerance, found, methodology_ok):
    not found ................................ inconclusive
    stated missing or > 1,000,000 bps ........ inconclusive
    |stated - claimed| * 10000 > tolerance * claimed ... unsupported
    within tolerance, methodology_ok false ... unsupported
    within tolerance, methodology_ok true .... supported
```

`tolerance` is set by the vault at registration (basis points, capped at 2000) so a
stablecoin vault and a volatile strategy can use different bands without changing
the rule.

Three properties follow from that:

1. **An unreadable page slashes nothing.** Fetch failure, missing figure or
   unparseable payload all resolve to `inconclusive`, and the challenger simply
   gets the stake back. Ambiguity never costs anyone money.
2. **A number outside tolerance is unsupported regardless of method.** A vault
   cannot publish a rigorous methodology for a figure it did not earn.
3. **The rule is public.** `check_verdict(claimed, stated, tolerance, found,
   methodology_ok, leader_state)` returns the same boolean the consensus stops on,
   so the equivalence check can be audited without running consensus. Seven live
   calls against the deployed contract returned exactly the expected booleans
   (table below).

### Independent validator evaluation

Every validator re-fetches the committed URL, re-extracts the figure and
`methodology_ok` with its own prompt, and re-derives the outcome with the same
`_derive`. It reports disagreement when:

- its own derived outcome differs from the leader's echoed `state`, **or**
- its own extracted figure differs from the leader's beyond the vault's tolerance.

So a well-formed but substantively wrong leader payload cannot satisfy the
equivalence check — the validator is not comparing shape, it is comparing its own
reading of the page against the leader's.

In addition, `judge_challenge` refuses deterministically, after consensus and
before any state change:

- a payload missing any of the seven required keys (`Malformed verdict payload`), and
- a payload whose echoed `state` is not what `_derive` produces from **its own
  numbers** (`Verdict contradicts its own numbers`).

That second guard matters because a leader echoing "supported" while returning a
figure 1100 bps away from the claim is internally inconsistent. It is rejected by
the contract itself, not merely by validators, and there is a test for it.

## Money

- **Per-vault bonds.** `fund_bond(vault_id)` holds GEN per vault. A payout on
  `blueharbor` can never touch `othervault`'s bond; there is a test for that.
- **The bounty is reserved when the challenge opens.** `challenge_report` calls
  `_reserve`, which requires `bounty ≤ bond − committed` and then adds the bounty to
  `committed` in the same call. Reservation is therefore atomic with the challenge
  being created: there is no window in which a challenge exists whose bounty is not
  already set aside.
- **This is what makes concurrency safe.** Because each open challenge has already
  taken its bounty out of the free part of the bond, a second challenger asking for
  money the bond cannot spare is **refused at open** instead of being accepted and
  quietly downgraded later. `committed ≤ bond` holds as an invariant.
- **The reserved amount is unavailable to the operator for the whole life of the
  challenge** — from before judgment through until settlement. `withdraw_bond` can
  only ever reach `bond − committed`, so the operator cannot pull the bounty out
  from under a live or judged-but-unsettled challenge.
- **Judgment moves no money and reserves nothing new.** The verdict only decides
  which way the already-reserved bounty will go.
- **Settlement pays or releases it, exactly once.** `unsupported` pays
  `stake + bounty` and draws the bounty out of the bond; `supported` releases the
  reservation and forfeits the stake into the bond; `inconclusive` releases the
  reservation and returns the stake. `stake_settled` is set before the transfer is
  emitted, so a second `settle_challenge` reverts.
- **`reclaim_stake` releases the reservation too**, so an unjudged challenge that
  times out cannot lock the bond forever.
- `UNFUNDED` is now **unreachable by construction** — a reservation can always be
  paid. The state and its settlement branch are kept as a defensive exit so that an
  unexpected state still refunds the challenger rather than trapping the stake.

Transfers use `emit_transfer(..., on='finalized')`; without `on='finalized'` no
message is emitted at all.

## Test coverage — 73 tests, all passing

```
tests/direct/test_yield_proof.py ......................... 73 passed
```

Grouped by what they defend:

| Area | Tests | Notable adversarial cases |
|---|---|---|
| Vault registry | 6 | re-registration, tolerance over the 2000 cap, id normalisation |
| Bond pool | 7 | non-operator withdraw, withdrawing committed bounty, anyone can top up |
| Report commitment | 8 | **third party recording on someone else's vault**, missing period, non-http URL, missing digests, implausible APY |
| Challenge | 9 | **operator challenging their own report**, stake/bounty bounds, 100x cap, **bounty the bond cannot back**, one challenge per report |
| Judging | 10 | supported, inside tolerance, outside tolerance, method not supported, unreadable page, no figure stated, re-judging, **validator disagreement on the figure**, **validator disagreement on methodology**, **self-contradictory leader**, malformed payload |
| Shared rule (`check_verdict`) | 7 | wrong word for a wrong figure, supported without methodology, conclusions on a missing figure, vault-specific tolerance, unknown state word |
| Settlement | 8 | settle before judging, supported forfeits stake, unsupported pays, inconclusive slashes nothing, double settle, unfunded path, reclaim before window, settled cannot be reclaimed |
| **Bounty reservation** | **8** | **withdrawal attempted between challenge creation and judgment**, **withdrawal blocked after judgment until settlement**, second challenge **cannot overbook** the bond, reservation released on supported, consumed on unsupported, released on inconclusive, reservations stack across reports, a reservation in one vault never touches another |
| Adversarial set | 5 | **fabricated claim (no report)**, **impostor operator**, **challenger cannot supply a URL**, **bond segregation across vaults**, digests recorded verbatim |

The reservation tests are the ones this revision exists for. The reviewer's exact
scenario is `test_withdrawal_is_blocked_between_challenge_and_judgment`: it opens a
challenge, asserts `committed` already equals the bounty while the challenge is
still `OPEN`, then requires that withdrawing the whole bond **and** withdrawing one
wei more than the free part both revert with `Committed bounty is protected`, that
exactly the free part still moves, and that the bounty is still fully payable
afterwards.

The validator-disagreement tests use the harness's `run_validator` replay, which
runs the real captured validator function against a deliberately different
independent reading — not a re-implementation of it.


## Verified live on Studionet

Two real funded accounts: the vault operator, and an unrelated challenger. Every
`bond / committed / withdrawable` figure below was read back from the contract after
the fact with `get_vault`, not inferred from the transactions.

`execution_result` is the leader receipt's execution status — that is the field that
distinguishes a return from a rollback here. `result_name` is the consensus outcome
(`MAJORITY_AGREE`) and is identical whether the call succeeded or reverted.

### The reviewer's case: reservation in action

The exact scenario this revision was asked for: a **0.02 GEN bounty on a 1.00 GEN
bond**, with withdrawals attempted **between challenge creation and judgment**.

| # | Call (actor) | Result | bond | committed | withdrawable | Tx |
|---|---|---|---|---|---|---|
| 1 | `fund_bond` 1.0 GEN (operator) | **return** | 1.00 | 0.00 | 1.00 | `0x82aaf977867893f3336b4bcd9d9dbfb501d28f40881f91340c0ba332362eeb94` |
| 2 | `challenge_report` bounty 0.02 (challenger) | **return** — bounty **reserved on open** | 1.00 | **0.02** | **0.98** | `0xec3f12b39739e8a67446168563c1aea9bc118cf6164aa0d4ff10410fc9aaa207` |
| 3 | **`withdraw_bond` 1.00** (operator, challenge still OPEN) | **ERROR** — committed bounty protected | 1.00 | 0.02 | 0.98 | `0x0b5a1ba0a7b1f2934909b1b50b9b8841e3c15821740cc1486f45a71f5ce76cd9` |
| 4 | **`withdraw_bond` 0.99** (one wei over the free part) | **ERROR** — committed bounty protected | 1.00 | 0.02 | 0.98 | `0x4ec8be58b43e92f39a952d8020a15eed42f0dc692be7314df4d60e76d057abfa` |
| 5 | `withdraw_bond` 0.98 (exactly the free part) | **return** | 0.02 | 0.02 | 0.00 | `0xf9f2a45a5311b6d27144832248dcb41a1aeab203369573d307ac9c3de7fc9bed` |
| 6 | `judge_challenge` (challenger) | **return** — verdict `SUPPORTED`, stated 800 bps, score 95 | 0.02 | 0.02 | 0.00 | `0x086ca973b6a70530c4ae187c8eb3bc0082ffe018c9843b9b69e3ffdd8a46be31` |
| 7 | **`withdraw_bond` 0.01** (judged, not yet settled) | **ERROR** — still reserved | 0.02 | 0.02 | 0.00 | `0x105a54c3fbb9a6874e65be6d6e65db125f7547f32521bb19914bfd3a6a14bab3` |
| 8 | `settle_challenge` (challenger) | **return** — reservation **released**, stake forfeited in | **0.12** | **0.00** | 0.12 | `0xf81373a72b04e16e7d5c11b99f7ba72d6629ae900b63eb2a51e1fab534c50d90` |
| 9 | `withdraw_bond` 0.12 (now free) | **return** | 0.00 | 0.00 | 0.00 | `0xb25b64822dc9c392ba9951c274178bd68d392a5a86f040c473e71eadf4f585e7` |

Row 3 and 4 are the reviewer's ask, demonstrated on chain: with the challenge open
and unjudged, the operator can reach **none** of the reserved amount — not by taking
the whole bond, not by taking one wei more than the free part. Row 7 shows the
reservation also survives judgment: it is only released when the challenge is
actually settled, in row 8.

### Verdict rounds

| Round | Report | Claim | Verdict | Jury reason (abridged) | Money |
|---|---|---|---|---|---|
| **A** | 800 bps, 2026-Q3 (honest) | page states 8.00%, method explained | **SUPPORTED** (1), stated 800, score 95 | *"…the disclosed 8.00 percent matches the claim within tolerance and the methodology is described…"* | reservation released, 0.1 GEN stake forfeited into the bond |
| **B** | 1990 bps, 2026-Q3 (inflated) | page states 8.00% | **UNSUPPORTED** (2), stated 800 | *"the figure sat 1190 bps outside the 100 bps band, so the claim is unsupported despite the page explaining its methodology"* | reservation **paid out**: bond 0.20 → 0.18 GEN, challenger received stake + 0.02 GEN bounty |

Round B transactions:

| Call | Tx |
|---|---|
| `fund_bond` 0.2 GEN | `0xab909a5934f8e13bb227bd0b1a4cb2a4a62eb17c9ada237f429f37f3d3ef3ed6` |
| `record_report` 1990 bps | `0xa1ff334ad5309b54c273b76f37299fb04df9c5f4b3c56aeb75d3c8b82c2d6982` |
| `challenge_report` (bounty reserved: 0.18 free) | `0xc84a1df7bb612719edfcdaad13146516272d5ff88e8fe43696c82b15f00cb76c` |
| `judge_challenge` → UNSUPPORTED | `0xefd36f21555153c1c27b4cd35cb786ba3ebef0a2e67e573ed3d492987c98a30e` |
| `settle_challenge` | `0x85999e45962b7a8e8c679063a1560ae63032b98072a8f6f381a877d4b0bbf19c` |

### Adversarial calls, refused on chain

| Attempted | Result | Tx |
|---|---|---|
| A non-operator recording a report on the operator's vault | **ERROR** | `0x95dfef673c6cf1db4d90ebae02f3689e87bca9c8099423bfd9892755b7a94743` |
| The operator challenging their own report | **ERROR** | `0xde5970762f3c17a98a1303a8c52d7109090b43f606671ee139f8c98b211e5dfb` |
| Challenging a report id that does not exist | **ERROR** | `0x32b8c5910aa63bc90640f225c3d79ea6078dba253b1dcb85cdf543114bc1465b` |
| A second challenge asking for more bounty than the free bond | **ERROR** — refused at open, not downgraded later | covered by `test_a_second_challenge_cannot_overbook_the_bond` |

### Also verified

| Check | Result |
|---|---|
| `gen_getContractSchema` | contract exists, **14 public methods** |
| Deploy transaction | `0xcf0365f9aa57070b43bfed79ad9838d410f67788b12700a93365eb85d3cd3616` — ACCEPTED, MAJORITY_AGREE, leader `return` |
| Final `get_counts` | 3 reports, 2 challenges (the third was the operator exercising its own authority in the adversarial round) |
| Direct-mode suite | **73 / 73 passing** |
| Evidence page reachable from the jury | the base64 fixture at a 507-char URL, read successfully in rounds A and B |

### `check_verdict` live results

Seven calls against the deployed contract, each with the expected boolean — **7/7 as
intended**:

| claimed | stated | tolerance | found | methodology_ok | leader_state | result |
|---|---|---|---|---|---|---|
| 800 | 800 | 100 | true | true | supported | **true** |
| 800 | 1600 | 100 | true | true | unsupported | **true** |
| 800 | 1600 | 100 | true | true | supported | **false** |
| 800 | 800 | 100 | true | false | supported | **false** |
| 800 | -1 | 100 | false | false | inconclusive | **true** |
| 800 | 900 | 100 | true | true | supported | **false** |
| 800 | 800 | 100 | true | true | fine | **false** |

## Known platform behaviour

A `gl.vm.UserError` revert on a **payable** call in this environment does not return
the attached value to the sender — the GEN stays in the contract. Nothing can move
it afterwards (there is no arbitrary-withdraw entry point), so it is locked, not
stealable. This was observed on the previous deployment, where a refused
self-challenge left its 0.1 GEN stake behind.

The application layer accounts for this rather than ignoring it: before submitting
`challenge_report` the frontend re-reads the report and the vault and refuses to
send value when the challenge would be rejected anyway — already challenged, caller
is the operator, stake or bounty out of bounds, bounty above 100x stake, or **bounty
larger than the vault's currently uncommitted bond**. That last check is the one
this revision changed: it compares against `withdrawable`, not `bond`, because the
bounty now has to fit inside the part of the bond that is not already reserved.

## Repository layout

```
contracts/yield_proof.py            the contract (26,346 bytes, 14 public methods)
tests/direct/test_yield_proof.py    73 tests, including the reservation + adversarial suites
index.html                          the dApp (wallet-pinned genlayer-js client)
disclosure-sample.md                fixture with a stated yield, for the live round
judge_round.mjs                     replays the verdict rounds against the fixture
genlayer.config.yaml                network config
ruff.toml                           lint config
```

## Running it

```bash
python -m pytest tests/direct/ -v        # 73 tests
```

Deploy (Studionet, chain 61999):

```js
import { createClient, createAccount } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

const client = createClient({ chain: studionet, account: createAccount(PRIVATE_KEY) });
client.estimateTransactionGas = async () => 3_000_000n;   // see note below
const hash = await client.deployContract({ code, args: [] });
```

The contract address of a Studio deploy is `tx.recipient` on the deploy
transaction — EVM-style CREATE derivation does not apply here.

## Two implementation notes worth keeping

**Override `estimateTransactionGas`.** When a call is *expected* to revert, gas
estimation throws and the SDK falls back to `200_000n`, which starves legitimate
calls too. Pinning it to 3M is what makes a verification script that deliberately
includes refusals run at all.

**Address arguments are typed `str` and parsed inside the contract.** `withdraw_bond`
takes `to: str`, not `to: Address`. GenVM rejects `Address`-typed public parameters
on chain even though the direct VM accepts them, so this shape is required rather
than stylistic.

## What this contract deliberately does not do

- It does not decide whether a yield is *good*, only whether the disclosed number
  is supported by the page the operator committed.
- It does not authenticate the operator against the real-world vault. It
  authenticates that **this** operator committed **this** claim, which is the
  strongest statement available on-chain without an external registry.
- It does not trust the challenger with evidence. Their only input is a stake and a
  reason.
