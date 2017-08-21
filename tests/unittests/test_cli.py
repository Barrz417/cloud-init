# This file is part of cloud-init. See LICENSE file for license information.

import six

from . import helpers as test_helpers

from cloudinit.cmd import main as cli

mock = test_helpers.mock


class TestCLI(test_helpers.FilesystemMockingTestCase):

    def setUp(self):
        super(TestCLI, self).setUp()
        self.stderr = six.StringIO()
        self.patchStdoutAndStderr(stderr=self.stderr)

    def _call_main(self, sysv_args=None):
        if not sysv_args:
            sysv_args = ['cloud-init']
        try:
            return cli.main(sysv_args=sysv_args)
        except SystemExit as e:
            return e.code

    def test_no_arguments_shows_usage(self):
        exit_code = self._call_main()
        self.assertIn('usage: cloud-init', self.stderr.getvalue())
        self.assertEqual(2, exit_code)

    def test_no_arguments_shows_error_message(self):
        exit_code = self._call_main()
        missing_subcommand_message = [
            'too few arguments',  # python2.7 msg
            'the following arguments are required: subcommand'  # python3 msg
        ]
        error = self.stderr.getvalue()
        matches = ([msg in error for msg in missing_subcommand_message])
        self.assertTrue(
            any(matches), 'Did not find error message for missing subcommand')
        self.assertEqual(2, exit_code)

    def test_all_subcommands_represented_in_help(self):
        """All known subparsers are represented in the cloud-int help doc."""
        self._call_main()
        error = self.stderr.getvalue()
        expected_subcommands = ['analyze', 'init', 'modules', 'single',
                                'dhclient-hook', 'features']
        for subcommand in expected_subcommands:
            self.assertIn(subcommand, error)

    @mock.patch('cloudinit.cmd.main.status_wrapper')
    def test_init_subcommand_parser(self, m_status_wrapper):
        """The subcommand 'init' calls status_wrapper passing init."""
        self._call_main(['cloud-init', 'init'])
        (name, parseargs) = m_status_wrapper.call_args_list[0][0]
        self.assertEqual('init', name)
        self.assertEqual('init', parseargs.subcommand)
        self.assertEqual('init', parseargs.action[0])
        self.assertEqual('main_init', parseargs.action[1].__name__)

    @mock.patch('cloudinit.cmd.main.status_wrapper')
    def test_modules_subcommand_parser(self, m_status_wrapper):
        """The subcommand 'modules' calls status_wrapper passing modules."""
        self._call_main(['cloud-init', 'modules'])
        (name, parseargs) = m_status_wrapper.call_args_list[0][0]
        self.assertEqual('modules', name)
        self.assertEqual('modules', parseargs.subcommand)
        self.assertEqual('modules', parseargs.action[0])
        self.assertEqual('main_modules', parseargs.action[1].__name__)

    def test_analyze_subcommand_parser(self):
        """The subcommand cloud-init analyze calls the correct subparser."""
        self._call_main(['cloud-init', 'analyze'])
        # These subcommands only valid for cloud-init analyze script
        expected_subcommands = ['blame', 'show', 'dump']
        error = self.stderr.getvalue()
        for subcommand in expected_subcommands:
            self.assertIn(subcommand, error)

    @mock.patch('cloudinit.cmd.main.main_single')
    def test_single_subcommand(self, m_main_single):
        """The subcommand 'single' calls main_single with valid args."""
        self._call_main(['cloud-init', 'single', '--name', 'cc_ntp'])
        (name, parseargs) = m_main_single.call_args_list[0][0]
        self.assertEqual('single', name)
        self.assertEqual('single', parseargs.subcommand)
        self.assertEqual('single', parseargs.action[0])
        self.assertFalse(parseargs.debug)
        self.assertFalse(parseargs.force)
        self.assertIsNone(parseargs.frequency)
        self.assertEqual('cc_ntp', parseargs.name)
        self.assertFalse(parseargs.report)

    @mock.patch('cloudinit.cmd.main.dhclient_hook')
    def test_dhclient_hook_subcommand(self, m_dhclient_hook):
        """The subcommand 'dhclient-hook' calls dhclient_hook with args."""
        self._call_main(['cloud-init', 'dhclient-hook', 'net_action', 'eth0'])
        (name, parseargs) = m_dhclient_hook.call_args_list[0][0]
        self.assertEqual('dhclient_hook', name)
        self.assertEqual('dhclient-hook', parseargs.subcommand)
        self.assertEqual('dhclient_hook', parseargs.action[0])
        self.assertFalse(parseargs.debug)
        self.assertFalse(parseargs.force)
        self.assertEqual('net_action', parseargs.net_action)
        self.assertEqual('eth0', parseargs.net_interface)

    @mock.patch('cloudinit.cmd.main.main_features')
    def test_features_hook_subcommand(self, m_features):
        """The subcommand 'features' calls main_features with args."""
        self._call_main(['cloud-init', 'features'])
        (name, parseargs) = m_features.call_args_list[0][0]
        self.assertEqual('features', name)
        self.assertEqual('features', parseargs.subcommand)
        self.assertEqual('features', parseargs.action[0])
        self.assertFalse(parseargs.debug)
        self.assertFalse(parseargs.force)

# : ts=4 expandtab
