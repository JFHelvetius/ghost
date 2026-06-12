| Category | Expected | BAUD | ERUR | MD | RLB | FPB | Detected |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `calibrator_no_downgrade` | **BAUD-v1** | VIOL | OK | OK | OK | OK | YES |
| `calibrator_invents_confidence` | **MD-v1** | VIOL | OK | VIOL | OK | OK | YES |
| `decision_proceeds_anyway` | **BAUD-v1** | VIOL | OK | OK | OK | OK | YES |
| `decision_never_proceeds` | **ERUR-v1** | OK | VIOL | OK | OK | OK | YES |
| `actuation_non_safe_reason` | **BAUD-v1** | VIOL | OK | OK | OK | OK | YES |
| `fpb_threshold_exceeded` | **FPB-v1** | OK | OK | OK | OK | VIOL | YES |

All 6 bug categories correctly detected.
