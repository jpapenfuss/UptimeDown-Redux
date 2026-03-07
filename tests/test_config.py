"""Tests for the config module and CLI argument parsing."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.config import Config, create_argument_parser


class TestConfigDefaults(unittest.TestCase):
    """Test default configuration values."""

    def test_default_values(self):
        """Test that defaults are applied when no config.ini exists."""
        with patch('monitoring.config.os.path.exists', return_value=False):
            cfg = Config()
            self.assertEqual(cfg.run_interval, 60)
            self.assertIsNone(cfg.max_iterations)
            self.assertEqual(cfg.log_level, "ERROR")
            self.assertFalse(cfg.dump_json)
            self.assertEqual(cfg.data_dir, "collected-data")
            self.assertEqual(cfg.gatherer_intervals, {})
            self.assertEqual(cfg.base_tick, 1)


class TestConfigIniLoading(unittest.TestCase):
    """Test config.ini file loading."""

    def test_load_run_interval(self):
        """Test loading run_interval from config.ini."""
        mock_parser = MagicMock()
        mock_parser.has_section.return_value = True
        mock_parser.has_option.return_value = True
        mock_parser.getint.return_value = 30

        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.run_interval, 30)

    def test_minimum_run_interval(self):
        """Test that run_interval enforces 5 second minimum."""
        mock_parser = MagicMock()
        mock_parser.has_section.return_value = True
        mock_parser.has_option.return_value = True
        mock_parser.getint.return_value = 2

        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.run_interval, 5)

    def test_load_max_iterations(self):
        """Test loading max_iterations from config.ini."""
        mock_parser = MagicMock()
        mock_parser.has_section.return_value = True
        mock_parser.has_option.side_effect = lambda section, option: option == "max_iterations"
        mock_parser.getint.return_value = 100

        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.max_iterations, 100)

    def test_load_log_level(self):
        """Test loading log_level from config.ini."""
        mock_parser = MagicMock()
        mock_parser.has_section.side_effect = lambda section: section == "logging"
        mock_parser.has_option.return_value = True
        mock_parser.get.return_value = "DEBUG"

        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.log_level, "DEBUG")

    def test_load_data_dir(self):
        """Test loading data_dir from config.ini."""
        mock_parser = MagicMock()
        mock_parser.has_section.side_effect = lambda section: section == "output"
        mock_parser.has_option.side_effect = lambda section, option: option == "data_dir"
        mock_parser.get.return_value = "/var/log/uptimedown"

        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.data_dir, "/var/log/uptimedown")


class TestCliArgumentParsing(unittest.TestCase):
    """Test CLI argument parser."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = create_argument_parser()

    def test_parse_run_interval(self):
        """Test parsing --run-interval."""
        args = self.parser.parse_args(['--run-interval', '30'])
        self.assertEqual(args.run_interval, 30)

    def test_parse_run_interval_short(self):
        """Test parsing -i short form."""
        args = self.parser.parse_args(['-i', '45'])
        self.assertEqual(args.run_interval, 45)

    def test_parse_max_iterations(self):
        """Test parsing --max-iterations."""
        args = self.parser.parse_args(['--max-iterations', '10'])
        self.assertEqual(args.max_iterations, 10)

    def test_parse_max_iterations_short(self):
        """Test parsing -m short form."""
        args = self.parser.parse_args(['-m', '5'])
        self.assertEqual(args.max_iterations, 5)

    def test_parse_log_level_debug(self):
        """Test parsing --log-level DEBUG."""
        args = self.parser.parse_args(['--log-level', 'DEBUG'])
        self.assertEqual(args.log_level, 'DEBUG')

    def test_parse_log_level_error(self):
        """Test parsing --log-level ERROR."""
        args = self.parser.parse_args(['--log-level', 'ERROR'])
        self.assertEqual(args.log_level, 'ERROR')

    def test_parse_log_level_short(self):
        """Test parsing -l short form."""
        args = self.parser.parse_args(['-l', 'DEBUG'])
        self.assertEqual(args.log_level, 'DEBUG')

    def test_parse_once_flag(self):
        """Test parsing --once flag."""
        args = self.parser.parse_args(['--once'])
        self.assertTrue(args.once)

    def test_no_arguments(self):
        """Test parsing with no arguments."""
        args = self.parser.parse_args([])
        self.assertIsNone(args.run_interval)
        self.assertIsNone(args.max_iterations)
        self.assertIsNone(args.log_level)
        self.assertFalse(args.once)
        self.assertFalse(args.dump)

    def test_parse_dump_flag(self):
        """Test parsing --dump flag."""
        args = self.parser.parse_args(['--dump'])
        self.assertTrue(args.dump)

    def test_parse_dump_short(self):
        """Test parsing -d short form."""
        args = self.parser.parse_args(['-d'])
        self.assertTrue(args.dump)

    def test_parse_data_dir(self):
        """Test parsing --data-dir."""
        args = self.parser.parse_args(['--data-dir', '/tmp/metrics'])
        self.assertEqual(args.data_dir, '/tmp/metrics')

    def test_multiple_arguments(self):
        """Test parsing multiple arguments together."""
        args = self.parser.parse_args(['-i', '20', '-m', '100', '--log-level', 'DEBUG'])
        self.assertEqual(args.run_interval, 20)
        self.assertEqual(args.max_iterations, 100)
        self.assertEqual(args.log_level, 'DEBUG')


class TestCliOverrides(unittest.TestCase):
    """Test that CLI arguments override config.ini."""

    def test_cli_overrides_run_interval(self):
        """Test that CLI --run-interval overrides config.ini."""
        with patch('monitoring.config.os.path.exists', return_value=False):
            parser = create_argument_parser()
            args = parser.parse_args(['-i', '25'])
            cfg = Config(args)
            self.assertEqual(cfg.run_interval, 25)

    def test_cli_overrides_max_iterations(self):
        """Test that CLI --max-iterations overrides config.ini."""
        with patch('monitoring.config.os.path.exists', return_value=False):
            parser = create_argument_parser()
            args = parser.parse_args(['-m', '50'])
            cfg = Config(args)
            self.assertEqual(cfg.max_iterations, 50)

    def test_cli_overrides_log_level(self):
        """Test that CLI --log-level overrides config.ini."""
        with patch('monitoring.config.os.path.exists', return_value=False):
            parser = create_argument_parser()
            args = parser.parse_args(['--log-level', 'DEBUG'])
            cfg = Config(args)
            self.assertEqual(cfg.log_level, 'DEBUG')

    def test_cli_once_sets_max_iterations(self):
        """Test that --once sets max_iterations to 1."""
        with patch('monitoring.config.os.path.exists', return_value=False):
            parser = create_argument_parser()
            args = parser.parse_args(['--once'])
            # Simulate what main() does
            if args.once:
                args.max_iterations = 1
            cfg = Config(args)
            self.assertEqual(cfg.max_iterations, 1)

    def test_cli_enforces_minimum_interval(self):
        """Test that CLI also enforces 5 second minimum."""
        with patch('monitoring.config.os.path.exists', return_value=False):
            parser = create_argument_parser()
            args = parser.parse_args(['-i', '2'])
            cfg = Config(args)
            self.assertEqual(cfg.run_interval, 5)

    def test_cli_dump_flag_sets_dump_json(self):
        """Test that --dump sets dump_json to True."""
        with patch('monitoring.config.os.path.exists', return_value=False):
            parser = create_argument_parser()
            args = parser.parse_args(['--dump'])
            cfg = Config(args)
            self.assertTrue(cfg.dump_json)

    def test_cli_dump_short_sets_dump_json(self):
        """Test that -d sets dump_json to True."""
        with patch('monitoring.config.os.path.exists', return_value=False):
            parser = create_argument_parser()
            args = parser.parse_args(['-d'])
            cfg = Config(args)
            self.assertTrue(cfg.dump_json)

    def test_cli_data_dir_override(self):
        """Test that --data-dir overrides config.ini."""
        with patch('monitoring.config.os.path.exists', return_value=False):
            parser = create_argument_parser()
            args = parser.parse_args(['--data-dir', '/var/log/metrics'])
            cfg = Config(args)
            self.assertEqual(cfg.data_dir, '/var/log/metrics')


class TestGathererIntervalsLoading(unittest.TestCase):
    """Test loading [intervals] section from config.ini."""

    def _make_parser(self, options):
        """Return a mock ConfigParser that has only the [intervals] section
        with the given {option: value} dict."""
        mock_parser = MagicMock()
        mock_parser.has_section.side_effect = lambda s: s == "intervals"
        mock_parser.has_option.side_effect = lambda s, o: s == "intervals" and o in options
        mock_parser.getint.side_effect = lambda s, o: options[o]
        return mock_parser

    def test_load_single_interval(self):
        mock_parser = self._make_parser({"cpu": 10})
        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.gatherer_intervals.get("cpu"), 10)

    def test_load_multiple_intervals(self):
        mock_parser = self._make_parser({"cpu": 5, "memory": 30, "disk": 120})
        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.gatherer_intervals["cpu"], 5)
                self.assertEqual(cfg.gatherer_intervals["memory"], 30)
                self.assertEqual(cfg.gatherer_intervals["disk"], 120)

    def test_interval_below_minimum_ignored(self):
        """Values below 5 seconds must be silently dropped."""
        mock_parser = self._make_parser({"cpu": 2})
        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertNotIn("cpu", cfg.gatherer_intervals)

    def test_interval_exactly_minimum_accepted(self):
        mock_parser = self._make_parser({"network": 5})
        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.gatherer_intervals["network"], 5)

    def test_no_intervals_section_leaves_empty_dict(self):
        mock_parser = MagicMock()
        mock_parser.has_section.return_value = False
        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.gatherer_intervals, {})

    def test_unknown_gatherer_name_not_loaded(self):
        """Only the known gatherer names (cpu, memory, etc.) are read."""
        mock_parser = self._make_parser({"bogus": 60})
        # bogus key is not in the known list, so has_option returns False for it
        mock_parser.has_option.side_effect = lambda s, o: False
        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertNotIn("bogus", cfg.gatherer_intervals)

    def test_prime_valued_intervals_accepted(self):
        """Prime-number intervals are valid and should be stored as-is."""
        mock_parser = self._make_parser({"cpu": 13, "memory": 17, "disk": 37})
        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.gatherer_intervals["cpu"], 13)
                self.assertEqual(cfg.gatherer_intervals["memory"], 17)
                self.assertEqual(cfg.gatherer_intervals["disk"], 37)


class TestBaseTick(unittest.TestCase):
    """Test loading base_tick from config.ini [daemon] section."""

    def test_default_base_tick(self):
        with patch('monitoring.config.os.path.exists', return_value=False):
            cfg = Config()
            self.assertEqual(cfg.base_tick, 1)

    def test_load_base_tick_from_ini(self):
        mock_parser = MagicMock()
        mock_parser.has_section.side_effect = lambda s: s == "daemon"
        mock_parser.has_option.side_effect = lambda s, o: s == "daemon" and o == "base_tick"
        mock_parser.getint.return_value = 5
        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.base_tick, 5)

    def test_base_tick_below_minimum_ignored(self):
        """base_tick values below 1 are rejected; default (1) is kept."""
        mock_parser = MagicMock()
        mock_parser.has_section.side_effect = lambda s: s == "daemon"
        mock_parser.has_option.side_effect = lambda s, o: s == "daemon" and o == "base_tick"
        mock_parser.getint.return_value = 0
        with patch('monitoring.config.os.path.exists', return_value=True):
            with patch('monitoring.config.configparser.ConfigParser', return_value=mock_parser):
                cfg = Config()
                self.assertEqual(cfg.base_tick, 1)  # unchanged default


if __name__ == '__main__':
    unittest.main()
