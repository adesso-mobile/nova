# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright (C) 2012 Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import sys

from nova import exception
from nova import test
from nova.tests import utils as tests_utils
from nova import utils

from nova.virt.disk.vfs import localfs as vfsimpl

dirs = []
files = {}
commands = []


def fake_execute(*args, **kwargs):
    commands.append({"args": args, "kwargs": kwargs})

    if args[0] == "readlink":
        if args[1] == "-nm":
            if args[2] in ["/scratch/dir/some/file",
                           "/scratch/dir/some/dir",
                           "/scratch/dir/other/dir",
                           "/scratch/dir/other/file"]:
                return args[2], ""
        elif args[1] == "-e":
            if args[2] in files:
                return args[2], ""

        return "", "No such file"
    elif args[0] == "mkdir":
        dirs.append(args[2])
    elif args[0] == "chown":
        owner = args[1]
        path = args[2]
        if not path in files:
            raise Exception("No such file: " + path)

        sep = owner.find(':')
        if sep != -1:
            user = owner[0:sep]
            group = owner[sep + 1:]
        else:
            user = owner
            group = None

        if user:
            if user == "fred":
                uid = 105
            else:
                uid = 110
            files[path]["uid"] = uid
        if group:
            if group == "users":
                gid = 500
            else:
                gid = 600
            files[path]["gid"] = gid
    elif args[0] == "chgrp":
        group = args[1]
        path = args[2]
        if not path in files:
            raise Exception("No such file: " + path)

        if group == "users":
            gid = 500
        else:
            gid = 600
        files[path]["gid"] = gid
    elif args[0] == "chmod":
        mode = args[1]
        path = args[2]
        if not path in files:
            raise Exception("No such file: " + path)

        files[path]["mode"] = int(mode, 8)
    elif args[0] == "cat":
        path = args[1]
        if not path in files:
            files[path] = {
                "content": "Hello World",
                "gid": 100,
                "uid": 100,
                "mode": 0700
                }
        return files[path]["content"], ""
    elif args[0] == "tee":
        if args[1] == "-a":
            path = args[2]
            append = True
        else:
            path = args[1]
            append = False
        print str(files)
        if not path in files:
            files[path] = {
                "content": "Hello World",
                "gid": 100,
                "uid": 100,
                "mode": 0700,
                }
        if append:
            files[path]["content"] += kwargs["process_input"]
        else:
            files[path]["content"] = kwargs["process_input"]


class VirtDiskVFSLocalFSTestPaths(test.TestCase):
    def setUp(self):
        super(VirtDiskVFSLocalFSTestPaths, self).setUp()

        real_execute = utils.execute

        def nonroot_execute(*cmd_parts, **kwargs):
            kwargs.pop('run_as_root', None)
            return real_execute(*cmd_parts, **kwargs)

        self.stubs.Set(utils, 'execute', nonroot_execute)

    def test_check_safe_path(self):
        if tests_utils.is_osx():
            self.skipTest("Unable to test on OSX")
        vfs = vfsimpl.VFSLocalFS("dummy.img")
        vfs.imgdir = "/foo"
        ret = vfs._canonical_path('etc/something.conf')
        self.assertEquals(ret, '/foo/etc/something.conf')

    def test_check_unsafe_path(self):
        if tests_utils.is_osx():
            self.skipTest("Unable to test on OSX")
        vfs = vfsimpl.VFSLocalFS("dummy.img")
        vfs.imgdir = "/foo"
        self.assertRaises(exception.Invalid,
                          vfs._canonical_path,
                          'etc/../../../something.conf')


class VirtDiskVFSLocalFSTest(test.TestCase):

    def setUp(self):
        super(VirtDiskVFSLocalFSTest, self).setUp()

    def test_makepath(self):
        global dirs, commands
        dirs = []
        commands = []
        self.stubs.Set(utils, 'execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.imgdir = "/scratch/dir"
        vfs.make_path("/some/dir")
        vfs.make_path("/other/dir")

        self.assertEqual(dirs,
                         ["/scratch/dir/some/dir", "/scratch/dir/other/dir"]),

        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/dir'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('mkdir', '-p',
                                    '/scratch/dir/some/dir'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/other/dir'),
                            'kwargs': {'run_as_root': True}},
                          {'args': ('mkdir', '-p',
                                    '/scratch/dir/other/dir'),
                           'kwargs': {'run_as_root': True}}])

    def test_append_file(self):
        global files, commands
        files = {}
        commands = []
        self.stubs.Set(utils, 'execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.imgdir = "/scratch/dir"
        vfs.append_file("/some/file", " Goodbye")

        self.assertTrue("/scratch/dir/some/file" in files)
        self.assertEquals(files["/scratch/dir/some/file"]["content"],
                          "Hello World Goodbye")

        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('tee', '-a',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'process_input': ' Goodbye',
                                      'run_as_root': True}}])

    def test_replace_file(self):
        global files, commands
        files = {}
        commands = []
        self.stubs.Set(utils, 'execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.imgdir = "/scratch/dir"
        vfs.replace_file("/some/file", "Goodbye")

        self.assertTrue("/scratch/dir/some/file" in files)
        self.assertEquals(files["/scratch/dir/some/file"]["content"],
                          "Goodbye")

        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('tee', '/scratch/dir/some/file'),
                           'kwargs': {'process_input': 'Goodbye',
                                      'run_as_root': True}}])

    def test_read_file(self):
        global commands, files
        files = {}
        commands = []
        self.stubs.Set(utils, 'execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.imgdir = "/scratch/dir"
        self.assertEqual(vfs.read_file("/some/file"), "Hello World")

        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('cat', '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}}])

    def test_has_file(self):
        global commands, files
        files = {}
        commands = []
        self.stubs.Set(utils, 'execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.imgdir = "/scratch/dir"
        vfs.read_file("/some/file")

        self.assertTrue(vfs.has_file("/some/file"))
        self.assertFalse(vfs.has_file("/other/file"))

        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('cat', '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('readlink', '-e',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/other/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('readlink', '-e',
                                    '/scratch/dir/other/file'),
                           'kwargs': {'run_as_root': True}},
                          ])

    def test_set_permissions(self):
        global commands, files
        commands = []
        files = {}
        self.stubs.Set(utils, 'execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.imgdir = "/scratch/dir"
        vfs.read_file("/some/file")

        vfs.set_permissions("/some/file", 0777)
        self.assertEquals(files["/scratch/dir/some/file"]["mode"], 0777)

        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('cat', '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('chmod', '777',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}}])

    def test_set_ownership(self):
        global commands, files
        commands = []
        files = {}
        self.stubs.Set(utils, 'execute', fake_execute)

        vfs = vfsimpl.VFSLocalFS(imgfile="/dummy.qcow2", imgfmt="qcow2")
        vfs.imgdir = "/scratch/dir"
        vfs.read_file("/some/file")

        self.assertEquals(files["/scratch/dir/some/file"]["uid"], 100)
        self.assertEquals(files["/scratch/dir/some/file"]["gid"], 100)

        vfs.set_ownership("/some/file", "fred", None)
        self.assertEquals(files["/scratch/dir/some/file"]["uid"], 105)
        self.assertEquals(files["/scratch/dir/some/file"]["gid"], 100)

        vfs.set_ownership("/some/file", None, "users")
        self.assertEquals(files["/scratch/dir/some/file"]["uid"], 105)
        self.assertEquals(files["/scratch/dir/some/file"]["gid"], 500)

        vfs.set_ownership("/some/file", "joe", "admins")
        self.assertEquals(files["/scratch/dir/some/file"]["uid"], 110)
        self.assertEquals(files["/scratch/dir/some/file"]["gid"], 600)

        self.assertEqual(commands,
                         [{'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('cat', '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('chown', 'fred',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('chgrp', 'users',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('readlink', '-nm',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}},
                          {'args': ('chown', 'joe:admins',
                                    '/scratch/dir/some/file'),
                           'kwargs': {'run_as_root': True}}])
