# This file is part of cloud-init. See LICENSE file for license information.

import logging
from collections import namedtuple

import pytest

from cloudinit.config.cc_resizefs import (
    _resize_bcachefs,
    _resize_btrfs,
    _resize_ext,
    _resize_ufs,
    _resize_xfs,
    _resize_zfs,
    can_skip_resize,
    get_device_info_from_zpool,
    handle,
    maybe_get_writable_device_path,
)
from cloudinit.config.schema import (
    SchemaValidationError,
    get_schema,
    validate_cloudconfig_schema,
)
from cloudinit.subp import ProcessExecutionError, SubpResult
from tests.unittests.helpers import (
    mock,
    readResource,
    skipUnlessJsonSchema,
    util,
    wrap_and_call,
)

LOG = logging.getLogger(__name__)
M_PATH = "cloudinit.config.cc_resizefs."


class TestResizefs:
    def setUp(self):
        super(TestResizefs, self).setUp()
        self.name = "resizefs"

    @mock.patch("cloudinit.subp.subp")
    def test_skip_ufs_resize(self, m_subp):
        fs_type = "ufs"
        resize_what = "/"
        devpth = "/dev/da0p2"
        err = (
            "growfs: requested size 2.0GB is not larger than the "
            "current filesystem size 2.0GB\n"
        )
        exception = ProcessExecutionError(stderr=err, exit_code=1)
        m_subp.side_effect = exception
        res = can_skip_resize(fs_type, resize_what, devpth)
        assert res

    @mock.patch("cloudinit.subp.subp")
    def test_cannot_skip_ufs_resize(self, m_subp):
        fs_type = "ufs"
        resize_what = "/"
        devpth = "/dev/da0p2"
        m_subp.return_value = SubpResult(
            "stdout: super-block backups (for fsck_ffs -b #) at:\n\n",
            "growfs: no room to allocate last cylinder group; "
            "leaving 364KB unused\n",
        )
        res = can_skip_resize(fs_type, resize_what, devpth)
        assert not res

    @mock.patch("cloudinit.subp.subp")
    def test_cannot_skip_ufs_growfs_exception(self, m_subp):
        fs_type = "ufs"
        resize_what = "/"
        devpth = "/dev/da0p2"
        err = "growfs: /dev/da0p2 is not clean - run fsck.\n"
        exception = ProcessExecutionError(stderr=err, exit_code=1)
        m_subp.side_effect = exception
        with pytest.raises(ProcessExecutionError):
            can_skip_resize(fs_type, resize_what, devpth)

    def test_can_skip_resize_ext(self):
        assert not can_skip_resize("ext", "/", "/dev/sda1")

    def test_handle_noops_on_disabled(self, caplog):
        """The handle function logs when the configuration disables resize."""
        cfg = {"resize_rootfs": False}
        handle("cc_resizefs", cfg, cloud=None, args=[])
        assert (
            mock.ANY,
            logging.DEBUG,
            "Skipping module named cc_resizefs, resizing disabled",
        ) in caplog.record_tuples

    @mock.patch("cloudinit.config.cc_resizefs.util.get_mount_info")
    @mock.patch("cloudinit.config.cc_resizefs.LOG")
    def test_handle_warns_on_unknown_mount_info(
        self, m_log, m_get_mount_info, caplog
    ):
        """handle warns when get_mount_info sees unknown filesystem for /."""
        m_get_mount_info.return_value = None
        cfg = {"resize_rootfs": True}
        handle("cc_resizefs", cfg, cloud=None, args=[])
        logs = caplog.text
        assert (
            "WARNING: Invalid cloud-config provided:\nresize_rootfs:"
            not in logs
        )
        assert (
            "Could not determine filesystem type of %s",
            "/",
        ) == m_log.warning.call_args[0]
        assert [mock.call("/", m_log)] == m_get_mount_info.call_args_list

    @mock.patch("cloudinit.config.cc_resizefs.LOG")
    def test_handle_warns_on_undiscoverable_root_path_in_command_line(
        self, m_log
    ):
        """handle noops when the root path is not found on the command line."""
        cfg = {"resize_rootfs": True}
        exists_mock_path = "cloudinit.config.cc_resizefs.os.path.exists"

        def fake_mount_info(path, log):
            assert "/" == path
            assert m_log == log
            return ("/dev/root", "ext4", "/")

        with mock.patch(exists_mock_path) as m_exists:
            m_exists.return_value = False
            wrap_and_call(
                "cloudinit.config.cc_resizefs.util",
                {
                    "is_container": {"return_value": False},
                    "get_mount_info": {"side_effect": fake_mount_info},
                    "get_cmdline": {"return_value": "BOOT_IMAGE=/vmlinuz.efi"},
                },
                handle,
                "cc_resizefs",
                cfg,
                cloud=None,
                args=[],
            )
        assert (
            "Unable to find device '/dev/root'" in m_log.warning.call_args[0]
        )

    def test_resize_zfs_cmd_return(self):
        zpool = "zroot"
        devpth = "gpt/system"
        assert ("zpool", "online", "-e", zpool, devpth) == _resize_zfs(
            zpool, devpth
        )

    def test_resize_xfs_cmd_return(self):
        mount_point = "/mnt/test"
        devpth = "/dev/sda1"
        assert ("xfs_growfs", mount_point) == _resize_xfs(mount_point, devpth)

    def test_resize_ext_cmd_return(self):
        mount_point = "/"
        devpth = "/dev/sdb1"
        assert ("resize2fs", devpth) == _resize_ext(mount_point, devpth)

    def test_resize_ufs_cmd_return(self):
        mount_point = "/"
        devpth = "/dev/sda2"
        assert ("growfs", "-y", mount_point) == _resize_ufs(
            mount_point, devpth
        )

    def test_resize_bcachefs_cmd_return(self):
        mount_point = "/"
        devpth = "/dev/sdf3"
        assert ("bcachefs", "device", "resize", devpth) == _resize_bcachefs(
            mount_point, devpth
        )

    @mock.patch("cloudinit.util.is_container", return_value=False)
    @mock.patch("cloudinit.util.parse_mount")
    @mock.patch("cloudinit.config.cc_resizefs.get_device_info_from_zpool")
    @mock.patch("cloudinit.util.get_mount_info")
    def test_handle_zfs_root(
        self, mount_info, zpool_info, parse_mount, is_container
    ):
        devpth = "vmzroot/ROOT/freebsd"
        disk = "gpt/system"
        fs_type = "zfs"
        mount_point = "/"

        mount_info.return_value = (devpth, fs_type, mount_point)
        zpool_info.return_value = disk
        parse_mount.return_value = (devpth, fs_type, mount_point)

        cfg = {"resize_rootfs": True}

        with mock.patch("cloudinit.config.cc_resizefs.do_resize") as dresize:
            handle("cc_resizefs", cfg, cloud=None, args=[])
            ret = dresize.call_args[0]

        assert (("zpool", "online", "-e", "vmzroot", disk),) == ret

    @mock.patch("cloudinit.util.is_container", return_value=False)
    @mock.patch("cloudinit.util.get_mount_info")
    @mock.patch("cloudinit.config.cc_resizefs.get_device_info_from_zpool")
    @mock.patch("cloudinit.util.parse_mount")
    def test_handle_modern_zfsroot(
        self, mount_info, zpool_info, parse_mount, is_container
    ):
        devpth = "zroot/ROOT/default"
        disk = "da0p3"
        fs_type = "zfs"
        mount_point = "/"

        mount_info.return_value = (devpth, fs_type, mount_point)
        zpool_info.return_value = disk
        parse_mount.return_value = (devpth, fs_type, mount_point)

        cfg = {"resize_rootfs": True}

        def fake_stat(devpath):
            if devpath == disk:
                raise OSError("not here")
            FakeStat = namedtuple(
                "FakeStat", ["st_mode", "st_size", "st_mtime"]
            )  # minimal stat
            return FakeStat(25008, 0, 1)  # fake char block device

        with mock.patch("cloudinit.config.cc_resizefs.do_resize") as dresize:
            with mock.patch("cloudinit.config.cc_resizefs.os.stat") as m_stat:
                m_stat.side_effect = fake_stat
                handle("cc_resizefs", cfg, cloud=None, args=[])
        assert (
            ("zpool", "online", "-e", "zroot", "/dev/" + disk),
        ) == dresize.call_args[0]


class TestRootDevFromCmdline:
    def test_rootdev_from_cmdline_with_no_root(self):
        """Return None from rootdev_from_cmdline when root is not present."""
        invalid_cases = [
            "BOOT_IMAGE=/adsf asdfa werasef  root adf",
            "BOOT_IMAGE=/adsf",
            "",
        ]
        for case in invalid_cases:
            assert util.rootdev_from_cmdline(case) is None

    def test_rootdev_from_cmdline_with_root_startswith_dev(self):
        """Return the cmdline root when the path starts with /dev."""
        assert "/dev/this" == util.rootdev_from_cmdline("asdf root=/dev/this")

    def test_rootdev_from_cmdline_with_root_without_dev_prefix(self):
        """Add /dev prefix to cmdline root when the path lacks the prefix."""
        assert "/dev/this" == util.rootdev_from_cmdline("asdf root=this")

    def test_rootdev_from_cmdline_with_root_with_label(self):
        """When cmdline root contains a LABEL, our root is disk/by-label."""
        assert "/dev/disk/by-label/unique" == util.rootdev_from_cmdline(
            "asdf root=LABEL=unique"
        )

    def test_rootdev_from_cmdline_with_root_with_uuid(self):
        """When cmdline root contains a UUID, our root is disk/by-uuid."""
        assert "/dev/disk/by-uuid/adsfdsaf-adsf" == util.rootdev_from_cmdline(
            "asdf root=UUID=adsfdsaf-adsf"
        )


@pytest.mark.usefixtures("fake_filesystem")
class TestMaybeGetDevicePathAsWritableBlock:
    def test_maybe_get_writable_device_path_none_on_overlayroot(self, caplog):
        """When devpath is overlayroot (on MAAS), is_dev_writable is False."""
        info = "does not matter"
        devpath = wrap_and_call(
            "cloudinit.config.cc_resizefs.util",
            {"is_container": {"return_value": False}},
            maybe_get_writable_device_path,
            "overlayroot",
            info,
        )
        assert devpath is None
        assert "Not attempting to resize devpath 'overlayroot'" in caplog.text

    def test_maybe_get_writable_device_path_warns_missing_cmdline_root(
        self, caplog
    ):
        """When root does not exist isn't in the cmdline, log warning."""
        info = "does not matter"

        def fake_mount_info(path, log):
            assert "/" == path
            assert LOG == log
            return ("/dev/root", "ext4", "/")

        exists_mock_path = "cloudinit.config.cc_resizefs.os.path.exists"
        with mock.patch(exists_mock_path) as m_exists:
            m_exists.return_value = False
            devpath = wrap_and_call(
                "cloudinit.config.cc_resizefs.util",
                {
                    "is_container": {"return_value": False},
                    "get_mount_info": {"side_effect": fake_mount_info},
                    "get_cmdline": {"return_value": "BOOT_IMAGE=/vmlinuz.efi"},
                },
                maybe_get_writable_device_path,
                "/dev/root",
                info,
            )
        assert devpath is None
        assert (
            mock.ANY,
            logging.WARNING,
            "Unable to find device '/dev/root'",
        ) in caplog.record_tuples

    def test_maybe_get_writable_device_path_does_not_exist(self, caplog):
        """When devpath does not exist, a warning is logged."""
        info = "dev=/dev/I/dont/exist mnt_point=/ path=/dev/none"
        devpath = wrap_and_call(
            "cloudinit.config.cc_resizefs.util",
            {"is_container": {"return_value": False}},
            maybe_get_writable_device_path,
            "/dev/I/dont/exist",
            info,
        )
        assert devpath is None
        assert (
            mock.ANY,
            logging.WARNING,
            "Device '/dev/I/dont/exist' did not exist. cannot resize: %s"
            % info,
        ) in caplog.record_tuples

    def test_maybe_get_writable_device_path_does_not_exist_in_container(
        self, caplog
    ):
        """When devpath does not exist in a container, log a debug message."""
        info = "dev=/dev/I/dont/exist mnt_point=/ path=/dev/none"
        devpath = wrap_and_call(
            "cloudinit.config.cc_resizefs.util",
            {"is_container": {"return_value": True}},
            maybe_get_writable_device_path,
            "/dev/I/dont/exist",
            info,
        )
        assert devpath is None
        assert (
            mock.ANY,
            logging.DEBUG,
            "Device '/dev/I/dont/exist' did not exist in container. cannot"
            " resize: %s" % info,
        ) in caplog.record_tuples

    def test_maybe_get_writable_device_path_raises_oserror(self):
        """When unexpected OSError is raises by os.stat it is reraised."""
        info = "dev=/dev/I/dont/exist mnt_point=/ path=/dev/none"
        with pytest.raises(OSError, match="Something unexpected"):
            wrap_and_call(
                "cloudinit.config.cc_resizefs",
                {
                    "util.is_container": {"return_value": True},
                    "os.stat": {
                        "side_effect": OSError("Something unexpected")
                    },
                },
                maybe_get_writable_device_path,
                "/dev/I/dont/exist",
                info,
            )

    def test_maybe_get_writable_device_path_non_block(self, caplog):
        """When device is not a block device, emit warning return False."""
        fake_devpath = "dev/readwrite"
        util.write_file(fake_devpath, "", mode=0o600)  # read-write
        info = "dev=/dev/root mnt_point=/ path={0}".format(fake_devpath)

        devpath = wrap_and_call(
            "cloudinit.config.cc_resizefs.util",
            {"is_container": {"return_value": False}},
            maybe_get_writable_device_path,
            fake_devpath,
            info,
        )
        assert devpath is None
        assert (
            mock.ANY,
            logging.WARNING,
            "device '{0}' not a block device. cannot resize: {1}".format(
                fake_devpath, info
            ),
        ) in caplog.record_tuples

    def test_maybe_get_writable_device_path_non_block_on_container(
        self, caplog
    ):
        """When device is non-block device in container, emit debug log."""
        fake_devpath = "dev/readwrite"
        util.write_file(fake_devpath, "", mode=0o600)  # read-write
        info = "dev=/dev/root mnt_point=/ path={0}".format(fake_devpath)

        devpath = wrap_and_call(
            "cloudinit.config.cc_resizefs.util",
            {"is_container": {"return_value": True}},
            maybe_get_writable_device_path,
            fake_devpath,
            info,
        )
        assert devpath is None
        assert (
            mock.ANY,
            logging.DEBUG,
            "device '{0}' not a block device in container. cannot resize:"
            " {1}".format(fake_devpath, info),
        ) in caplog.record_tuples

    def test_maybe_get_writable_device_path_returns_command_line_root(
        self, caplog
    ):
        """When root device is UUID in kernel command_line, update devpath."""
        # XXX Long-term we want to use fake_filesystem test to avoid
        # touching os.stat.
        FakeStat = namedtuple(
            "FakeStat", ["st_mode", "st_size", "st_mtime"]
        )  # minimal def.
        info = "dev=/dev/root mnt_point=/ path=/does/not/matter"
        devpath = wrap_and_call(
            "cloudinit.config.cc_resizefs",
            {
                "util.get_cmdline": {"return_value": "asdf root=UUID=my-uuid"},
                "util.is_container": False,
                "os.path.exists": False,  # /dev/root doesn't exist
                "os.stat": {
                    "return_value": FakeStat(25008, 0, 1)
                },  # char block device
            },
            maybe_get_writable_device_path,
            "/dev/root",
            info,
        )
        assert "/dev/disk/by-uuid/my-uuid" == devpath
        assert (
            mock.ANY,
            logging.DEBUG,
            "Converted /dev/root to '/dev/disk/by-uuid/my-uuid' per kernel"
            " cmdline",
        ) in caplog.record_tuples

    @mock.patch("cloudinit.util.mount_is_read_write")
    @mock.patch("cloudinit.config.cc_resizefs.os.path.isdir")
    @mock.patch("cloudinit.subp.subp")
    def test_resize_btrfs_mount_is_ro(self, m_subp, m_is_dir, m_is_rw):
        """Do not resize / directly if it is read-only. (LP: #1734787)."""
        m_is_rw.return_value = False
        m_is_dir.return_value = True
        m_subp.return_value = SubpResult("btrfs-progs v4.19 \n", "")
        assert (
            "btrfs",
            "filesystem",
            "resize",
            "max",
            "//.snapshots",
        ) == _resize_btrfs("/", "/dev/sda1")

    @mock.patch("cloudinit.util.mount_is_read_write")
    @mock.patch("cloudinit.config.cc_resizefs.os.path.isdir")
    @mock.patch("cloudinit.subp.subp")
    def test_resize_btrfs_mount_is_rw(self, m_subp, m_is_dir, m_is_rw):
        """Do not resize / directly if it is read-only. (LP: #1734787)."""
        m_is_rw.return_value = True
        m_is_dir.return_value = True
        m_subp.return_value = SubpResult("btrfs-progs v4.19 \n", "")
        assert ("btrfs", "filesystem", "resize", "max", "/") == _resize_btrfs(
            "/", "/dev/sda1"
        )

    @mock.patch("cloudinit.util.mount_is_read_write")
    @mock.patch("cloudinit.config.cc_resizefs.os.path.isdir")
    @mock.patch("cloudinit.subp.subp")
    def test_resize_btrfs_mount_is_rw_has_queue(
        self, m_subp, m_is_dir, m_is_rw
    ):
        """Queue the resize request if btrfs >= 5.10"""
        m_is_rw.return_value = True
        m_is_dir.return_value = True
        m_subp.return_value = SubpResult("btrfs-progs v5.10 \n", "")
        assert (
            "btrfs",
            "filesystem",
            "resize",
            "--enqueue",
            "max",
            "/",
        ) == _resize_btrfs("/", "/dev/sda1")

    @mock.patch("cloudinit.util.mount_is_read_write")
    @mock.patch("cloudinit.config.cc_resizefs.os.path.isdir")
    @mock.patch("cloudinit.subp.subp")
    def test_resize_btrfs_version(self, m_subp, m_is_dir, m_is_rw):
        """Queue the resize request if btrfs >= 6.10"""
        m_is_rw.return_value = True
        m_is_dir.return_value = True
        m_subp.return_value = SubpResult(
            "btrfs-progs v6.10 \n\n-EXPERIMENTAL -INJECT -STATIC +LZO +ZSTD "
            "+UDEV +FSVERITY +ZONED CRYPTO=libgcrypt",
            "",
        )
        assert (
            "btrfs",
            "filesystem",
            "resize",
            "--enqueue",
            "max",
            "/",
        ) == _resize_btrfs("/", "/dev/sda1")

    @mock.patch("cloudinit.util.is_container", return_value=True)
    @mock.patch("cloudinit.util.is_FreeBSD")
    def test_maybe_get_writable_device_path_zfs_freebsd(
        self, freebsd, m_is_container
    ):
        freebsd.return_value = True
        info = "dev=gpt/system mnt_point=/ path=/"
        devpth = maybe_get_writable_device_path("gpt/system", info)
        assert "gpt/system" == devpth


class TestResizefsSchema:
    @pytest.mark.parametrize(
        "config, error_msg",
        [
            ({"resize_rootfs": True}, None),
            (
                {"resize_rootfs": "wrong"},
                r"'wrong' is not one of \[True, False, 'noblock'\]",
            ),
        ],
    )
    @skipUnlessJsonSchema()
    def test_schema_validation(self, config, error_msg):
        if error_msg is None:
            validate_cloudconfig_schema(config, get_schema(), strict=True)
        else:
            with pytest.raises(SchemaValidationError, match=error_msg):
                validate_cloudconfig_schema(config, get_schema(), strict=True)


class TestZpool:
    @mock.patch(M_PATH + "os")
    @mock.patch("cloudinit.subp.subp")
    def test_get_device_info_from_zpool(self, zpool_output, m_os):
        # mock /dev/zfs exists
        m_os.path.exists.return_value = True
        # mock subp command from util.get_mount_info_fs_on_zpool
        zpool_output.return_value = (
            readResource("zpool_status_simple.txt"),
            "",
        )
        ret = get_device_info_from_zpool("vmzroot")
        assert "gpt/system" == ret
        m_os.path.exists.assert_called_with("/dev/zfs")

    @mock.patch(M_PATH + "os")
    @mock.patch("cloudinit.subp.subp", return_value=("", ""))
    def test_get_device_info_from_zpool_no_dev_zfs(self, m_os, m_subp):
        # mock /dev/zfs missing
        m_os.path.exists.return_value = False
        assert not get_device_info_from_zpool("vmzroot")

    @mock.patch(M_PATH + "os")
    @mock.patch("cloudinit.subp.subp")
    def test_get_device_info_from_zpool_handles_no_zpool(self, m_sub, m_os):
        """Handle case where there is no zpool command"""
        # mock /dev/zfs exists
        m_os.path.exists.return_value = True
        m_sub.side_effect = ProcessExecutionError("No zpool cmd")
        assert not get_device_info_from_zpool("vmzroot")

    @mock.patch(M_PATH + "os")
    @mock.patch("cloudinit.subp.subp")
    def test_get_device_info_from_zpool_on_error(self, m_subp, m_os):
        # mock /dev/zfs exists
        m_os.path.exists.return_value = True

        # mock subp command from get_mount_info_fs_on_zpool
        m_subp.return_value = SubpResult(
            readResource("zpool_status_simple.txt"),
            "error",
        )
        assert not get_device_info_from_zpool("vmzroot")
