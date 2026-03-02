"""Configuration module for UptimeDown monitoring daemon.

Reads settings from config.ini in the monitoring directory. Falls back to
sensible defaults if the file is missing or incomplete.
"""
import configparser
import os


class Config:
    """Daemon configuration."""

    def __init__(self):
        """Initialize config from config.ini or defaults."""
        self.run_interval = 60  # seconds
        self.max_iterations = None  # None = run forever
        self.log_level = "ERROR"  # ERROR or DEBUG
        self._load_config()

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

    def __repr__(self):
        return (
            f"Config(run_interval={self.run_interval}s, "
            f"max_iterations={self.max_iterations})"
        )
