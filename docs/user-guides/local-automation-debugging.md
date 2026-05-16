# Debug Automated Ingestion Locally

Use `--debug-raw-xml-dir` only when you need to inspect raw XML fetched from IBKR Flex Web Service during local development.

## Privacy warning

Raw Flex XML can contain account identifiers, balances, transactions, and other sensitive data. Keep debug files in `scratch/` or another ignored private directory. Never commit them, attach them to public issues, or upload them to CI artifacts.

## Command

```bash
python scripts/run_automated_ingestion.py \
  --target-type accounts \
  --integration ibkr_flex_ws \
  --mode dry-run \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --account-external-ids U100 \
  --debug-raw-xml-dir scratch/ibkr-debug
```

The directory is created automatically. Files are named with sanitized connection and feed identifiers plus a random UUID.

## What it does

The flag saves fetched Flex XML to disk after a successful `GetStatement` response. The same run still follows normal automation behavior: dry-run does not write normalized facts, and load writes supported records.

## CI protection

This flag is blocked in GitHub Actions. If `GITHUB_ACTIONS=true` and `--debug-raw-xml-dir` is present, the CLI fails before constructing the run request.

The IBKR client also checks `GITHUB_ACTIONS=true` before saving raw XML, so CI blocking exists at both the CLI and client layers. The manual workflow does not expose this flag as an input.

An empty debug directory value is also rejected.

## Cleanup

After troubleshooting:

```bash
rm -rf scratch/ibkr-debug
```

Use a specific private path. Do not use broad cleanup commands against shared directories.
