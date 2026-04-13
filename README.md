# Cloudflare Preferred IP Hub

This project keeps a local `cfnew`-compatible preferred IP list under version control.

## What It Does

- Runs local `cfst.exe` scans with your saved config
- Writes region CSV files into `artifacts/`
- Generates `cloudflare_ips.txt` in the format expected by `cfnew`
- Lets you commit and push the generated file so `cfnew` can read it from a GitHub Raw URL

## Why This Workflow Works

Your idea is sound:

1. Run the local generator
2. Review or adjust `cloudflare_ips.txt`
3. Commit and push the repository
4. Point `cfnew` `yxURL` to the GitHub Raw URL of `cloudflare_ips.txt`

That keeps preferred IP generation local, while distribution stays simple and static.

## Current Recommendation

- Use `cfst` as the local scan engine
- Use this repository only as the maintainer layer
- Commit `cloudflare_ips.txt`, but do not commit the temporary CSV scan artifacts unless you want history

## Configuration

Edit `config.toml` if your `cfst.exe` path, `ip.txt` path, or region list changes.

## Usage

Install and run with `uv`:

```powershell
cd D:\code\github\hicancan\cloudflare-preferred-ip-hub
uv run preferred-ip
```

If you already have CSV results and only want to rebuild the text list:

```powershell
uv run preferred-ip --skip-scan
```

## Output Files

- `cloudflare_ips.txt`: the file you commit and expose via GitHub Raw
- `artifacts/result_<region>_delay.csv`: local scan result files

## cfnew Example

After pushing this repository, `cfnew` can use a URL like:

```text
https://raw.githubusercontent.com/<your-user>/<your-repo>/main/cloudflare_ips.txt
```

Set that URL in `cfnew` as `yxURL`.
