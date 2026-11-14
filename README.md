# YieldProof

**A challenge market over yield disclosures, judged on-chain.**

A vault can advertise any annualised yield it likes. YieldProof makes that number
something a third party can attack — and makes the payout depend on what the
committed page actually says, not on what either party claims it says.

- **Primary tag:** DeFi
- **Sub-tags:** Yield Optimization · Treasury Rebalancing
- **Network:** GenLayer Studionet (chain 61999)
- **Contract:** [`0x34747A848366656bDDdFefc6fDCf1cD6c917f9b8`](https://explorer-studio.genlayer.com/address/0x34747A848366656bDDdFefc6fDCf1cD6c917f9b8)
- **Deploy tx:** `0x603f4cfe71bd72e4f9d074cea8297c55733908f6bae0a76b2474efc7b408ac09` — ACCEPTED, MAJORITY_AGREE, leader `return`
- **Size:** 23,501 bytes · **14 public methods** · **65 direct-mode tests passing**
- **Admin:** the deploying account (the operator of the first vault, not a privileged role)

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
- **Committed bounty is untouchable.** When a verdict is `unsupported` the bounty
  is moved into `committed`, and `withdraw_bond` can only reach `bond - committed`.
- **A bounty the bond cannot cover becomes `UNFUNDED`**, never a partial payout or a
  negative balance. The challenger gets the stake back.
- **The stake is forfeited into the bond when the claim holds up**, so hopeless
  challenges cost the challenger money and the pool grows.
- **There is always a funding-free exit.** `reclaim_stake` returns the stake
  immediately when the verdict was `UNFUNDED`, and after the 7-day window if the
  challenge was never judged at all.
- **Every settlement is exactly once.** `stake_settled` is set before the transfer
  is emitted, and a second `settle_challenge` reverts.

Transfers use `emit_transfer(..., on='finalized')`; without `on='finalized'` no
message is emitted at all.

## Test coverage — 65 tests, all passing

```
tests/direct/test_yield_proof.py ......................... 65 passed
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
| Adversarial set | 5 | **fabricated claim (no report)**, **impostor operator**, **challenger cannot supply a URL**, **bond segregation across vaults**, digests recorded verbatim |

The validator-disagreement tests use the harness's `run_validator` replay, which
runs the real captured validator function against a deliberately different
independent reading — not a re-implementation of it.

## Verified live on Studionet

Full flow executed against the deployed contract with two real funded accounts.
`execution_result` is the leader receipt's execution status, which is the field
that distinguishes a return from a rollback (`result_name` is the consensus
outcome — `MAJORITY_AGREE` — and says nothing about whether the call succeeded).

| # | Call | Expected | Actual | Tx |
|---|---|---|---|---|
| 1 | `gen_getContractSchema` | contract exists | **14 methods** returned | — |
| 2 | `register_vault("blueharbor", 100)` by wallet 1 | return | **return**, operator recorded | `0x2c61166f525ef7e63d54a360b170e2688abffb74bc8d55036c0fc7b62d49f6a1` |
| 3 | `record_report` by **wallet 2** (not the operator) | rollback | **ERROR** ✅ refused | `0x2fd903006988f6a4391fc7c4b833e4dc0d1d074b10e4ecf0b91a3e0e30009e16` |
| 4 | `fund_bond("blueharbor")` 1 GEN | return | **return** | `0x8a5622402f36d0f88996a34331d3cfeae212a667567297116ea963133ee90909` |
| 5 | `record_report(... 800 bps ...)` by the operator | return | **return**, report #1 | `0x4aa216a32a9d0ee9d45663e06b40739d60adb885b148c3a509da3c1479fb45a2` |
| 6 | `challenge_report` by the **operator** on own report | rollback | **ERROR** ✅ refused | `0x66efe8c0170da69e6ebe3a518b57ca0a7574cc3086fe31093855237f33af8411` |
| 7 | `challenge_report` by wallet 2, 0.1 GEN stake | return | **return**, challenge #1 | `0xf1d5408f89e2f5ba1c78d04a499cfb613128a6b6bb1ddd95fc202cebde50261e` |
| 8 | `judge_challenge(1)` | return | **return**, state `INCONCLUSIVE` (3), stated 0 bps | `0xaa16da1aa0e13b4eedc4cf79e3a115c0304db7dfb7576365c9ce839bbe6ac2b5` |
| 9 | `settle_challenge(1)` | return | **return**, `SETTLED`, stake returned, nothing slashed | `0x8754b022665774d772c80ccf80ebcf245a7701ee3e09f0f4ef01c569cdc64a92` |
| 10 | `withdraw_bond("blueharbor", 0.1)` | return | **return**, bond 1.00 → 0.90 GEN | `0x961b47ce25966a52734581ada835e1e306c8ffaacaac77e243607496e7e4080c` |

Ending state read back from the contract:

```
get_vault("blueharbor") = bond 0.90 GEN, committed 0.00, withdrawable 0.90,
                          tolerance 100 bps, report_count 1
get_counts()            = report_count 1, challenge_count 1
get_challenge(1)        = state SETTLED, stake_settled true,
                          verdict_reason "The disclosure URL returned no usable text on this read."
```

Step 8 resolved to `inconclusive` **because the disclosure URL did not exist yet**
— the fixture file was still sitting in the local project folder rather than
published at the committed URL. That is the correct outcome for an unreadable page
and it is exactly why the three-state verdict exists: a node that could not reach
the page did not slash a challenger for it.

### The definitive verdict paths, proven live

All three verdict states were then driven through the deployed contract with real
money, against a real fetchable page. The evidence URL is the base64 form of
`disclosure-sample.md`, served back verbatim by httpbin, so it is reproducible
without depending on this repository being published:

```
https://httpbin.org/base64/<base64 of disclosure-sample.md>   (507 chars)
```

The page states *"Realised annualised yield for 2026-Q3: 8.00% (800 basis points)"*
followed by a methodology paragraph. That is enough for the jury to read a figure
and a method, and it is the only input to the derivation.

| Round | Report | Claimed | Challenge | Verdict | Jury reason (abridged) | Settlement |
|---|---|---|---|---|---|---|
| **A** | 800 bps, 2026-Q3 | honest | #2 | **SUPPORTED** (1), score 100, stated 800 | *"The page explicitly states an annualised yield of 800 bps for 2026-Q3, which matches the claimed yield within the 100 bps tolerance. The methodology is clearly described…"* | stake **forfeited** into the bond: 0.90 → 1.00 GEN |
| **B** | 1990 bps, 2026-Q4 | period mismatch | #3 | **INCONCLUSIVE** (3), stated 0 | *"The page states 8.00% (800 bps) for 2026-Q3, not the requested 2026-Q4. No usable annualised yield… for 2026-Q4, so the claim cannot be assessed."* | stake **returned**, nothing slashed |
| **C** | 1990 bps, 2026-Q3 | inflated | #4 | **UNSUPPORTED** (2), stated 800 | *"The page states a realised annualised yield of 8.00% (800 bps), while the claim is 1990 bps. The 1190 bps difference exceeds the 100 bps tolerance, so the claim is unsupported **despite the page explaining its methodology**."* | challenger paid stake + bounty = **0.12 GEN**, bond 1.00 → 0.98 |

Transactions:

| Round | Call | Tx |
|---|---|---|
| A | `record_report` | `0xb07df81247efed1af381418ccf48695a7e3bfd0f0108f4f68292189ccfb2f4a7` |
| A | `challenge_report` | `0xe10e2ea49ba3829ec0dc559316cddc66b1257a283082d10b6c6ff14614adc51d` |
| A | `judge_challenge` → SUPPORTED | `0x9d93048c19d584a8f803016728e3f0f622a7eeff5a5c3196a8e132acb10c1334` |
| A | `settle_challenge` | `0x936e1edd622de5202063dadd4a8b090d4206f9c4d9fdae11960b37ac29eac0ab` |
| B | `judge_challenge` → INCONCLUSIVE | `0xb59b18874270eb0387c77407307b1f39f7bb56790ec98a9919e61c626e8edea5` |
| B | `settle_challenge` | `0xb32052aada672f1c802609b156d7e65a437461d2ee1033501c3f95cadeb50e9c` |
| C | `record_report` | `0xd47079a58f59213e077911974209ad6c883c54494575382ecddfd039528f2f9e` |
| C | `challenge_report` | `0x3bff87ec6bc9d35c2d1c6458bfdaf671c839994b83285b55c8995881f70f9942` |
| C | `judge_challenge` → UNSUPPORTED | `0xb6375ed55b04f8eae86940c3068c5b9f1069b89b3a4fe0656e21f264fbb0903` |
| C | `settle_challenge` | `0xd864b9f651727b208cfc22e46b695650d6132466c4deabeb069a35a0fa01c52d` |

Round C is the important one for review: the jury found the methodology sound and
**still** returned `unsupported`, because the figure was outside the vault's own
band. A rigorous explanation cannot rescue a number the vault did not earn.

Balance reconciliation after finalization, read from the chain:

```
operator wallet    9.00 GEN   (10.00 funded − 1.00 bond − 0.10 stranded + 0.10 withdrawn)
challenger wallet  3.92 GEN   (4.00 − 0.10 forfeited in A + 0.02 net gain in C)
contract           1.08 GEN   (= 0.98 vault bond + 0.10 stranded by the refused self-challenge)
```

Every figure ties out. Re-run the whole thing at any time with:

```bash
GL_PK=0x<operator key> GL_PK_CH=0x<challenger key> node judge_round.mjs
```

The script derives the evidence URL from the local fixture itself, so it does not
depend on this repository being published — and the keys come from the environment,
never from the file. The same three paths are also proven deterministically by the
65 direct-mode tests, which need no network at all.

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
stealable. Observed directly during verification: the refused self-challenge in
step 6 left its 0.1 GEN stake behind, which is why the contract holds 1.1 GEN while
the vault's attributable bond is 0.9 GEN plus one pending outbound transfer.

The application layer accounts for this rather than ignoring it: before submitting
`challenge_report` the frontend re-reads the report and vault and refuses to send
value when the challenge would be rejected anyway — already challenged, caller is
the operator, stake or bounty out of bounds, bounty above 100x stake, or bounty
larger than the bond.

## Repository layout

```
contracts/yield_proof.py            the contract (23,501 bytes, 14 public methods)
tests/direct/test_yield_proof.py    65 tests, including the adversarial suite
index.html                          the dApp (wallet-pinned genlayer-js client)
disclosure-sample.md                fixture with a stated yield, for the live round
genlayer.config.yaml                network config
ruff.toml                           lint config
```

## Running it

```bash
python -m pytest tests/direct/ -v        # 65 tests
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
