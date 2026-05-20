# Chaos Test Report - Wangsit V1

## Summary
All chaos tests for `wangsit-v1` have been updated to match the current architecture and executed successfully.

| Test Case | Status | Description |
|-----------|--------|-------------|
| **Skenario A: Latensi API** (`test_network.py`) | ✅ PASSED | Simulated 7s latency in API response. Bot handled the delay gracefully. |
| **Skenario B: Gagal Update Saldo** (`test_compound.py`) | ✅ PASSED | Simulated successful order execution followed by a balance API failure. Verified that the trade is still recorded in the persistent state. |
| **Skenario C: SIGTERM/Interruption** (`test_lifecycle.py`) | ✅ PASSED | Simulated `KeyboardInterrupt` (common on Railway/VPS stop). Verified that the bot saves the current state before exiting. |

## Detailed Logs

### test_network.py
```text
🔥 [CHAOS TEST] Memulai simulasi lonjakan latensi API 7 detik...
✅ [PASSED] Bot berhasil menyelesaikan fetch meskipun ada latensi (mocked).
Ran 1 test in 10.211s
OK
```

### test_compound.py
```text
🔥 [CHAOS TEST] Memulai simulasi order sukses namun API saldo hancur...
[2026-05-20T16:54:58Z] ENTERING [BTC Long] Test Market
[2026-05-20T16:54:58Z]    price=0.600 | time_left=30.0s | invested=$3.33 | expected_pnl=+$2.22 (+66.7%)
[2026-05-20T16:54:58Z]    Price:0.00 | delta:0.0100% | conf:50% | compound_base=$1.00
[2026-05-20T16:54:58Z]    Trade recorded [BTC] | next_base=$3.40
✅ [PASSED] State aman terproteksi. Bot mencatat trade meskipun ada gangguan (mocked).
Ran 1 test in 0.003s
OK
```

### test_lifecycle.py
```text
🔥 [CHAOS TEST] Simulasi KeyboardInterrupt pada bot...
✅ [PASSED] Bot menangani interupsi dan mengamankan state keuangan.
Ran 1 test in 0.002s
OK
```
