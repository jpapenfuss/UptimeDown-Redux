"""Tests for the config module and CLI argument parsing."""
import sys
import unittest
from unittest.mock import patch, MagicMock
import os

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


if __name__ == '__main__':
    unittest.main()
