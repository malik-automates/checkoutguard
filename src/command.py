import argparse


def build_arg_parse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Checkoutguard Monitor",
        description="Automated E-commerce Regression & Funnel-Health Monitor ",
    )
    parser.add_argument(
        "--headless", type=str, default="true", choices=["true", "false"]
    )
    parser.add_argument("--max-retries", type=int, default=3, dest="max_retries")
    parser.add_argument(
        "--force-relogin", "-fr", action="store_true", dest="force_relogin"
    )
    parser.add_argument(
        "--log-level",
        "-lg",
        default="INFO",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        dest="log_level",
    )
    parser.add_argument(
        "--backoff-base", "-bb", type=float, default=1.5, dest="backoff_base"
    )
    parser.add_argument(
        "--timeout",
        "-t",
        default="20s",
        type=str,
        choices=["10s", "15s", "20s", "25s", "30s"],
        help="timeout preset(default: 20s -> 20000 ms)",
    )
    return parser
