import contextlib
from textwrap import dedent
from tasks.cephfs.cephfs_test_case import run_tests, CephFSTestCase
from tasks.cephfs.filesystem import Filesystem, ObjectNotFound


class TestFlush(CephFSTestCase):
    # Environment references
    mount = None

    def setUp(self):
        self.fs.mds_restart()
        self.fs.wait_for_daemons()
        if not self.mount.is_mounted():
            self.mount.mount()
            self.mount.wait_until_mounted()

        self.mount.run_shell(["rm", "-rf", "*"])

    def tearDown(self):
        self.mount.teardown()

    def test_flush(self):
        self.mount.run_shell(["mkdir", "mydir"])
        self.mount.run_shell(["touch", "mydir/alpha"])
        dir_ino = self.mount.path_to_ino("mydir")
        file_ino = self.mount.path_to_ino("mydir/alpha")

        # Before flush, the dirfrag object does not exist
        with self.assertRaises(ObjectNotFound):
            self.fs.list_dirfrag(dir_ino)

        # Before flush, the file's backtrace has not been written
        with self.assertRaises(ObjectNotFound):
            self.fs.read_backtrace(file_ino)

        # Execute flush
        flush_data = self.fs.mds_asok(["flush", "journal"])
        self.assertEqual(flush_data['return_code'], 0)

        # After flush, the dirfrag object has been created
        dir_list = self.fs.list_dirfrag(dir_ino)
        self.assertEqual(dir_list, ["alpha_head"])

        # ...and the data object has its backtrace
        backtrace = self.fs.read_backtrace(file_ino)
        self.assertEqual(['alpha', 'mydir'], [a['dname'] for a in backtrace['ancestors']])
        self.assertEqual([dir_ino, 1], [a['dirino'] for a in backtrace['ancestors']])
        self.assertEqual(file_ino, backtrace['ino'])

        # ...and the journal is truncated to just a single subtreemap
        self.assertEqual(self.fs.journal_tool(["event", "get", "summary"]),
                         dedent(
                             """
                             Events by type:
                               SUBTREEMAP: 1
                             """
                         ).strip())


@contextlib.contextmanager
def task(ctx, config):
    fs = Filesystem(ctx, config)

    # Pick out the clients we will use from the configuration
    # =======================================================
    if len(ctx.mounts) < 1:
        raise RuntimeError("Need at least one client")
    mount = ctx.mounts.values()[0]

    # Stash references on ctx so that we can easily debug in interactive mode
    # =======================================================================
    ctx.filesystem = fs
    ctx.mount = mount

    run_tests(ctx, config, TestFlush, {
        'fs': fs,
        'mount': mount,
    })

    # Continue to any downstream tasks
    # ================================
    yield
