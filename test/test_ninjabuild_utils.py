import os
import tempfile
import unittest
from ninjabuild import isCPPLikeFile, isProtoLikeFile, _copyFilesBackNForth

class TestNinjaBuildUtils(unittest.TestCase):
    def test_is_cpp_like(self):
        for name in ['foo.c', 'bar.cc', 'baz.cpp', 'inc.h', 'hdr.hpp']:
            self.assertTrue(isCPPLikeFile(name))
        self.assertFalse(isCPPLikeFile('readme.txt'))

    def test_is_proto_like(self):
        self.assertTrue(isProtoLikeFile('service.proto'))
        self.assertFalse(isProtoLikeFile('service.cc'))

    def test_copy_files(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            with open(os.path.join(src, 'a.txt'), 'w') as f:
                f.write('hello')
            os.mkdir(os.path.join(src, 'sub'))
            with open(os.path.join(src, 'sub', 'b.txt'), 'w') as f:
                f.write('world')
            _copyFilesBackNForth(src, dst)
            self.assertTrue(os.path.exists(os.path.join(dst, 'a.txt')))
            self.assertTrue(os.path.exists(os.path.join(dst, 'sub', 'b.txt')))

if __name__ == '__main__':
    unittest.main()
