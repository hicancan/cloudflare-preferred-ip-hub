from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CfstConfig:
    path: Path
    input_file: Path
    test_url: str


@dataclass(frozen=True)
class ScanConfig:
    regions: list[str]
    delay_limit_ms: int
    disable_download: bool
    download_speed_min_mbps: float
    download_count: int
    download_duration_seconds: int
    console_rows: int
    top_per_region: int
    default_port: int


@dataclass(frozen=True)
class OutputConfig:
    csv_dir: Path
    preferred_ip_file: Path
    name_template: str


@dataclass(frozen=True)
class AppConfig:
    root: Path
    cfst: CfstConfig
    scan: ScanConfig
    output: OutputConfig


@dataclass(frozen=True)
class PreferredIP:
    ip: str
    port: int
    name: str
    region: str
    latency_ms: float
    speed_mbps: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate cfnew-compatible preferred IP lists.")
    parser.add_argument(
        "--config",
        default="config.toml",
        help="Path to config.toml. Defaults to ./config.toml",
    )
    parser.add_argument(
        "--skip-scan",
        action="store_true",
        help="Reuse existing CSV files in artifacts/ and only rebuild cloudflare_ips.txt",
    )
    parser.add_argument(
        "--regions",
        nargs="+",
        help="Optional region override, for example: --regions HKG TPE NRT",
    )
    return parser.parse_args()


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base / path).resolve()


def load_config(config_path: Path) -> AppConfig:
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent.resolve()

    cfst_data = data["cfst"]
    scan_data = data["scan"]
    output_data = data["output"]

    return AppConfig(
        root=base,
        cfst=CfstConfig(
            path=resolve_path(base, cfst_data["path"]),
            input_file=resolve_path(base, cfst_data["input_file"]),
            test_url=cfst_data["test_url"],
        ),
        scan=ScanConfig(
            regions=[region.upper() for region in scan_data["regions"]],
            delay_limit_ms=int(scan_data["delay_limit_ms"]),
            disable_download=bool(scan_data["disable_download"]),
            download_speed_min_mbps=float(scan_data["download_speed_min_mbps"]),
            download_count=int(scan_data["download_count"]),
            download_duration_seconds=int(scan_data["download_duration_seconds"]),
            console_rows=int(scan_data["console_rows"]),
            top_per_region=int(scan_data["top_per_region"]),
            default_port=int(scan_data["default_port"]),
        ),
        output=OutputConfig(
            csv_dir=resolve_path(base, output_data["csv_dir"]),
            preferred_ip_file=resolve_path(base, output_data["preferred_ip_file"]),
            name_template=output_data["name_template"],
        ),
    )


def expected_csv_path(config: AppConfig, region: str) -> Path:
    suffix = "delay" if config.scan.disable_download else "speed"
    return config.output.csv_dir / f"result_{region.lower()}_{suffix}.csv"


def build_cfst_command(config: AppConfig, region: str, output_csv: Path) -> list[str]:
    command = [
        str(config.cfst.path),
        "-httping",
        "-cfcolo",
        region,
        "-f",
        str(config.cfst.input_file),
        "-tl",
        str(config.scan.delay_limit_ms),
        "-p",
        str(config.scan.console_rows),
        "-url",
        config.cfst.test_url,
        "-o",
        str(output_csv),
    ]

    if config.scan.disable_download:
        command.insert(6, "-dd")
    else:
        command[6:6] = [
            "-sl",
            str(config.scan.download_speed_min_mbps),
            "-dn",
            str(config.scan.download_count),
            "-dt",
            str(config.scan.download_duration_seconds),
        ]

    return command


def run_scan(config: AppConfig, region: str) -> Path:
    output_csv = expected_csv_path(config, region)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if output_csv.exists():
        output_csv.unlink()

    command = build_cfst_command(config, region, output_csv)
    print(f"[scan] {region}: {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)
    if not output_csv.exists():
        raise FileNotFoundError(f"cfst did not produce the expected CSV file: {output_csv}")
    return output_csv


def parse_float(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def load_preferred_ips(config: AppConfig, csv_path: Path, region: str) -> list[PreferredIP]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    preferred: list[PreferredIP] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            ip = (row.get("IP 地址") or "").strip()
            if not ip:
                continue

            region_code = (row.get("地区码") or region).strip().upper()
            latency_ms = parse_float(row.get("平均延迟"))
            speed_mbps = parse_float(row.get("下载速度(MB/s)"))
            name = config.output.name_template.format(
                region=region_code,
                latency_ms=f"{latency_ms:.2f}",
                speed_mbps=f"{speed_mbps:.2f}",
                index=index,
            )
            preferred.append(
                PreferredIP(
                    ip=ip,
                    port=config.scan.default_port,
                    name=name,
                    region=region_code,
                    latency_ms=latency_ms,
                    speed_mbps=speed_mbps,
                )
            )
            if len(preferred) >= config.scan.top_per_region:
                break
    if not preferred:
        raise ValueError(f"No preferred IPs found in {csv_path.name} for region {region}")
    return preferred


def write_preferred_ip_file(config: AppConfig, preferred_ips: list[PreferredIP]) -> None:
    lines = [f"{item.ip}:{item.port}#{item.name}" for item in preferred_ips]
    text = "\n".join(lines).rstrip() + "\n"
    config.output.preferred_ip_file.write_text(text, encoding="utf-8")


def generate(config: AppConfig, regions: list[str], skip_scan: bool) -> list[PreferredIP]:
    all_preferred: list[PreferredIP] = []

    for region in regions:
        csv_path = expected_csv_path(config, region)
        if skip_scan:
            print(f"[reuse] {region}: {csv_path}")
        else:
            csv_path = run_scan(config, region)

        preferred = load_preferred_ips(config, csv_path, region)
        print(f"[select] {region}: kept {len(preferred)} IPs from {csv_path.name}")
        all_preferred.extend(preferred)

    write_preferred_ip_file(config, all_preferred)
    return all_preferred


def validate_paths(config: AppConfig, skip_scan: bool) -> None:
    if skip_scan:
        return

    if not config.cfst.path.exists():
        raise FileNotFoundError(f"cfst executable not found: {config.cfst.path}")
    if not config.cfst.input_file.exists():
        raise FileNotFoundError(f"cfst input file not found: {config.cfst.input_file}")


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    regions = [region.upper() for region in (args.regions or config.scan.regions)]

    try:
        validate_paths(config, args.skip_scan)
        preferred_ips = generate(config, regions, args.skip_scan)
    except subprocess.CalledProcessError as exc:
        print(f"[error] cfst failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    print(f"[done] wrote {len(preferred_ips)} preferred IPs to {config.output.preferred_ip_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
