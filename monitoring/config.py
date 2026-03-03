"""Configuration module for UptimeDown monitoring daemon.

Reads settings from config.ini in the monitoring directory. Falls back to
sensible defaults if the file is missing or incomplete. CLI arguments override
config.ini values.
"""
import argparse
import configparser
import os


class Config:
    """Daemon configuration."""

    def __init__(self, args=None):
        """Initialize config from config.ini or defaults, with CLI overrides.

        Args:
            args: Optional argparse.Namespace object with CLI arguments.
                  If None, no CLI overrides are applied.
        """
        self.run_interval = 60  # seconds
        self.max_iterations = None  # None = run forever
        self.log_level = "ERROR"  # ERROR or DEBUG
        self._load_config()
        if args:
            self._apply_cli_overrides(args)

    def _load_config(self):
        """Load config.ini if it exists."""
        config_path = os.path.join(os.path.dirname(__file__), "config.ini")
        if not os.path.exists(config_path):
            return

        parser = configparser.ConfigParser()
        try:
            parser.read(config_path)
        except configparser.Error:
            # Config file exists but is malformed; use defaults
            return

        # Load run_interval from [daemon] section
        if parser.has_section("daemon"):
            if parser.has_option("daemon", "run_interval"):
                try:
                    interval = parser.getint("daemon", "run_interval")
                    # Enforce minimum 5 seconds
                    if interval < 5:
                        self.run_interval = 5
                    else:
                        self.run_interval = interval
                except ValueError:
                    pass

            # Load max_iterations (optional)
            if parser.has_option("daemon", "max_iterations"):
                try:
                    self.max_iterations = parser.getint("daemon", "max_iterations")
                except ValueError:
                    pass

        # Load log_level from [logging] section
        if parser.has_section("logging"):
            if parser.has_option("logging", "level"):
                level = parser.get("logging", "level").upper()
                if level in ("DEBUG", "ERROR"):
                    self.log_level = level

    def _apply_cli_overrides(self, args):
        """Apply command-line argument overrides to config."""
        if args.run_interval is not None:
            interval = args.run_interval
            # Enforce minimum 5 seconds
            if interval < 5:
                self.run_interval = 5
            else:
                self.run_interval = interval

        if args.max_iterations is not None:
            self.max_iterations = args.max_iterations

        if args.log_level is not None:
            level = args.log_level.upper()
            if level in ("DEBUG", "ERROR"):
                self.log_level = level

    def __repr__(self):
        return (
            f"Config(run_interval={self.run_interval}s, "
            f"max_iterations={self.max_iterations}, "
            f"log_level={self.log_level})"
        )


def create_argument_parser():
    """Create and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="UptimeDown system monitoring daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 monitoring                          # Run with config.ini settings
  python3 monitoring --once                   # Collect once and exit
  python3 monitoring -i 30                    # Collect every 30 seconds
  python3 monitoring -i 10 -m 5               # Collect every 10s, max 5 times
  python3 monitoring --log-level DEBUG        # Enable debug logging
        """,
    )
    parser.add_argument(
        "-i", "--run-interval",
        type=int,
        default=None,
        help="Collection interval in seconds (minimum 5; overrides config.ini)",
        metavar="SECONDS",
    )
    parser.add_argument(
        "-m", "--max-iterations",
        type=int,
        default=None,
        help="Maximum number of collection iterations before exiting (overrides config.ini)",
        metavar="NUM",
    )
    parser.add_argument(
        "-l", "--log-level",
        default=None,
        choices=["DEBUG", "ERROR"],
        help="Log level: DEBUG or ERROR (overrides config.ini)",
        metavar="LEVEL",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Shorthand for --max-iterations 1 (collect once and exit)",
    )
    return parser
