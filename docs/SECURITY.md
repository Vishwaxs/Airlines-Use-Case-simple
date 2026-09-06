# Data boundaries and PII

Raw passenger data belongs only in restricted local source/bronze storage. A Git ignore rule prevents accidental staging; it is not encryption or access control. Filesystem permissions and disk encryption remain the operator's responsibility.

| Field | Silver handling | Gold handling |
|---|---|---|
| Aadhaar | Normalize to 12 digits, then HMAC-SHA-256 with `ASG_PII_PEPPER`; discard original. | Stable passenger token only. |
| First/last name | Mask to initials with asterisks; a missing surname uses the available name. | Omitted, including masked names. |
| Email and phone | Omitted after survivorship and source checks. | Omitted. |
| Date of birth | Omitted; retain validated age and age band. | Age and age band only. |
| Passport and emergency contact | Omitted from cleaned bookings. | Omitted. |
| Source passenger ID | Retained locally to resolve bookings. | Replaced by `passenger_sk`; not exported. |

`src/pii.py:normalize_aadhaar()` converts numeric/text input into a twelve-digit string before `passenger_token()` calculates its HMAC. Invalid or missing Aadhaar uses a namespaced source passenger ID as a deterministic fallback; it is flagged. This source has no such fallback cases. The token is pseudonymous, not anonymous: repeated records can still be linked, and demographics can permit inference.

Set `ASG_PII_PEPPER` outside the repository. `.env.example` contains an empty placeholder; the program reads the environment and does not automatically load a `.env` file. Use the same pepper for reproducible identities. Changing it regenerates passenger tokens and requires a full refresh of downstream extracts. The CLI rejects a secret shorter than 32 characters. Never copy the pepper into logs, screenshots, reports or Power BI.

Reuse the existing private pepper when available. If a new pepper is needed, store it securely and use it for both the local baseline and the Azure comparison run. Tokens change with the pepper; business counts and monetary results stay unchanged. The deployment script uses a versioned Key Vault secret reference.

Bronze JSONL preserves original cell values and type labels. It contains PII and must not be shared with report consumers. Quarantine retains relevant source fields so rejected rows can be investigated; treat it as restricted even when this particular source only quarantines flight rows. Run metadata and quality summaries avoid names, contact data and Aadhaar values. The survivorship CSV records source row numbers and rule outcomes without emails or Aadhaar values.

Gold CSVs and DuckDB are the analytical sharing boundary. The passenger dimension has a token, age, age band and gender, with one unknown member. Tests compare exported analytical values against source PII, verify normalization before HMAC, and check allowed passenger fields. These tests do not provide access control or legal certification.

Layer separation is enforced on disk and in version control: `data/raw`, `data/bronze` and `data/silver` are excluded from the repository, and only `data/gold` and the PII-free flight quarantine are published. The pepper is read from `ASG_PII_PEPPER` and never written to logs, reports or the Power BI model. A reviewer working from the repository alone sees tokenised passenger keys and no raw identifiers.
