.. _breaking_changes:

Breaking changes
****************

This section provides guidance on specific breaking changes to cloud-init
releases.

.. note::
    These changes may not be present in all distributions of cloud-init as
    many operating system vendors patch out breaking changes in
    cloud-init to ensure consistent behavior on their platform.

25.1.4
======

Strict datasource identity before network
-----------------------------------------
Affects detection of Ec2, OpenStack or AltCloud datasources for non-x86
architectures where DMI may not be accessible.

Datasource detection provided by ds-identify in cloud-init now requires strict
identification based on DMI platform information, kernel command line or
`datasource_list:` system configuration in /etc/cloud/cloud.cfg.d.

Prior to this change, ds-identify would allow non-x86 architectures without
strict identifying platform information to run in a discovery mode which would
attempt to reach out to well known static link-local IPs to attempt to
retrieve configuration once system networking is up.

To mitigate the potential of a bad-actor in a local network responding
to such provisioning requests from cloud-init clients, ds-identify will no
longer allow this late discovery mode for platforms unable to expose clear
identifying characteristics of a known cloud-init datasource.

The most likely affected cloud platforms are AltCloud, Ec2 and OpenStack for
non-x86 architectures where DMI data is not exposed by the kernel.

If your non-x86 architecture or images no longer detect the proper datasource,
cloud-init will remain disabled and perform no configuration operations during
boot.

Any of the following alternatives can ensure proper enablement of cloud-init
in non-x86 images without DMI-data:

- When launching VMs with the openstack command line client, provide
  ``--config-drive true``:

.. code-block:: shell-session

    $ openstack server create ... --config-drive true

- On the openstack image command line, modify specific image metadata to
  require config drive for the image:

.. code-block:: shell-session

    $ openstack image set <IMG_UUID> --property img_config_drive=mandatory


- OpenStack image creators can place a config file in the image at
  :file:`/etc/cloud/cloud.cfg.d/91_openstack.cfg` to force
  cloud-init to use OpenStack without DMI-based discovery. The file must
  contain a single datasource as follows:

.. code-block:: yaml

   datasource_list: [ OpenStack ]


- Charmed OpenStack Admins using glance-simplestreams-sync can default all
  syncronized images to use config_drive:

.. code-block:: shell-session

   $ juju config glance-simplestreams-sync custom-properties="img_config_drive=mandatory"


- OpenStack Nova admins can globally configure Nova to provide config drives
  to all images by default in :file:`/etc/nova/nova.conf`:

.. code-block:: toml

    [DEFAULT]
    force_config_drive = true

- Alternatively, providing
  :ref:`kernel command line arguments<kernel_datasource_override>` to a
  virtual machine containing ``ds=openstack`` will force ds-identify to use the
  specific datasource.


25.1
====

/usr merge
----------

Cloud-init's packaging code no longer installs anything to ``/lib``. Instead,
anything that was installed to ``/lib`` is now installed to ``/usr/lib``.
This shouldn't affect any systemd-based distributions as they have all
transitioned to the ``/usr`` merge. However, this could affect older
stable releases, non-systemd and non-Linux distributions. See
`commit 054734921 <https://github.com/canonical/cloud-init/commit/0547349214fcfb827e58c1de5e4ad7d23d08cc7f>`_
for more details.

24.4
====

Cloud-init's `cloud-final.service` order was standardized. This caused a
change to the systemd boot order on some distributions. See
`commit 245f94674 <https://github.com/canonical/cloud-init/pull/5830/commits/245f94674f8c14cbe09d9944a12b994913720450>`_
for more details.

24.3
====

Single Process Optimization
---------------------------

As a performance optimization, cloud-init no longer runs as four seperate
Python processes. Instead, it launches a single process and then
communicates with the init system over a Unix socket to allow the init system
to tell it when it should start each stage and to tell the init system when
each stage has completed. Init system ordering is preserved.

This should have no noticable affect for end users, besides a faster boot time.
This is labeled a breaking change for three reasons:

1. this change included renaming a systemd service:
   ``cloud-init.service`` -> ``cloud-init-network.service``
2. new dependency on openbsd's netcat implementation
3. a precaution to avoid unintentionally breaking users on stable distributions

Any external services which are ordered after or depend on the old
``cloud-init.service`` name can safely switch to ``cloud-config.target``, which
should provide the same point in boot order before and after this change.

OpenBSD netcat is already included in many major distributions, however any
distribution that wishes to avoid this dependency might prefer to use a
`Python3 equivalent`_ one-liner. Upstream prefers OpenBSD netcat for
performance reasons.

Any systemd distribution that wants to revert this behavior wholesale for
backwards compatibility may want to use `this patch`_.

.. note::

    Support has not yet been added for non-systemd distributions, however it is
    possible to add support.

    The command line arguments used to invoke each stage retain support
    for now to allow for adoption and stabilization.


Addition of NoCloud network-config
----------------------------------

The NoCloud datasource now has support for providing network configuration
using network-config. Any installation that doesn't provide this configuration
file will experience a retry/timeout in boot. Adding an empty
``network-config`` file should provide backwards compatibility with previous
behavior.

24.1
====

Removal of ``--file`` top-level option
--------------------------------------

The ``--file`` top-level option has been removed from cloud-init. It only
applied to a handful of subcommands so it did not make sense as a top-level
option. Instead, ``--file`` may be passed to a subcommand that supports it.
For example, the following command will no longer work:

.. code-block:: bash

    cloud-init --file=userdata.yaml modules --mode config

Instead, use:

.. code-block:: bash

    cloud-init modules --file=userdata.yaml --mode config


Removed Ubuntu's ordering dependency on snapd.seeded
----------------------------------------------------

In Ubuntu releases, cloud-init will no longer wait on ``snapd`` pre-seeding to
run. If a user-provided script relies on a snap, it must now be prefixed with
``snap wait system seed.loaded`` to ensure the snaps are ready for use. For
example, a cloud config that previously included:

.. code-block:: yaml

    runcmd:
      - [ snap, install, mc-installer ]


Will now need to be:

.. code-block:: yaml

    runcmd:
      - [ snap, wait, system, seed.loaded ]
      - [ snap, install, mc-installer ]


23.2-24.1 - Datasource identification
=====================================

**23.2**
    If the detected ``datasource_list`` contains a single datasource or
    that datasource plus ``None``, automatically use that datasource without
    checking to see if it is available. This allows for using datasources that
    don't have a way to be deterministically detected.
**23.4**
    If the detected ``datasource_list`` contains a single datasource plus
    ``None``, no longer automatically use that datasource because ``None`` is
    a valid datasource that may be used if the primary datasource is
    not available.
**24.1**
    ds-identify no longer automatically appends ``None`` to a
    datasource list with a single entry provided under ``/etc/cloud``.
    If ``None`` is desired as a fallback, it must be explicitly added to the
    customized datasource list.

23.4 - added status code for recoverable error
==============================================

Cloud-init return codes have been extended with a new error code (2),
which will be returned when cloud-init experiences an error that it can
recover from. See :ref:`this page which documents the change <error_codes>`.


23.2 - kernel command line
==========================

The ``ds=`` kernel command line value is used to forcibly select a specific
datasource in cloud-init. Prior to 23.2, this only optionally selected
the ``NoCloud`` datasource.

Anyone that previously had a matching ``ds=nocloud*`` in their kernel command
line that did not want to use the ``NoCloud`` datasource may experience broken
behavior as a result of this change.

Workarounds include updating the kernel command line and optionally configuring
a ``datasource_list`` in ``/etc/cloud/cloud.cfg.d/*.cfg``.


.. _attach a ConfigDrive: https://docs.openstack.org/nova/2024.1/admin/config-drive.html
.. _this patch: https://github.com/canonical/cloud-init/blob/ubuntu/noble/debian/patches/no-single-process.patch
.. _Python3 equivalent:  https://github.com/canonical/cloud-init/pull/5489#issuecomment-2408210561
