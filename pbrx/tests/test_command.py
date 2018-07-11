# -*- coding: utf-8 -*-

# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import fixtures

from pbrx.cmd import main
from pbrx.tests import base


class TestCommand(base.TestCase):

    def patch_argv(self, *args):
        argv = ["pbrx"]
        argv.extend(args)
        self.useFixture(fixtures.MonkeyPatch("sys.argv", argv))

    def test_no_args(self):
        '''Test no arguments to the command'''
        self.patch_argv()
        main.main()
