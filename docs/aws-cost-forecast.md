# AWS comparison cost forecast

This feature extends the project-scoped Governance Budget service. It is a
comparison estimate, not an AWS invoice and not a replacement for CloudKitty's
immutable DCN ledger.

## Flow

```text
Gnocchi usage -> CloudKitty raw ledger -> meter/SKU mapping
                                      -> versioned AWS price profile
AWS CUR/invoice observations --------> calibration profile
                                      -> month-end projection + range
                                      -> Budget percentage / exceeded flag
```

`aws_price_profile` records the AWS region, currency, effective timestamp,
SKU/unit prices and DCN meter-to-SKU conversion factors. A profile is immutable
by revision and preserves price provenance. `aws_calibration_profile` records
per-SKU multiplier, historical error percentage and sample count. Until real
AWS observations are supplied, an unmapped SKU uses multiplier `1` and a
conservative `25%` interval.

The forecast reads only the authenticated project's `usage_raw` ledger. It
projects month-to-date quantities by `elapsed_fraction`, converts them to AWS
SKU quantities, applies unit prices, then applies calibration. It returns the
central estimate, lower/upper bounds, coverage, missing meters, confidence and
per-SKU explanation. Supplying `budget_id` additionally returns projected
budget utilization and whether the forecast exceeds the budget.

## API

- `POST /v1/aws-price-profiles`
- `POST /v1/aws-calibration-profiles`
- `GET /v1/aws-cost-forecast?period=YYYY-MM&price_profile_id=...`

Optional forecast parameters are `calibration_profile_id`, `budget_id`, and
`elapsed_fraction`. All profiles, ledger reads and budgets are project scoped;
Keystone and central OPA remain fail-closed.

Future AWS input should be normalized outside this API from CUR or invoices
into per-SKU observations. Secret keys, payer identifiers, raw CUR files and
credentials must not be stored in profile bodies.
