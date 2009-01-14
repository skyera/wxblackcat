import sys
import os
sys.path.append(os.path.join(sys.path[0], ".."))
from blackcat import *
import unittest

class CadModelTest(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testOpen(self):
        cadmodel = CadModel()
        ok = cadmodel.open("rect.stl")
        self.assert_(ok)

    def testOpen_notexistfile(self):
        cadmodel = CadModel()
        ok = cadmodel.open("xxx.stl")
        self.assert_(not ok)

    def testOpen_wrongformat(self):
        fname = 'tmp.txt'
        f = open(fname, 'w')
        print >> f, 'xxx'
        f.close()

        cadmodel = CadModel()
        ok = cadmodel.open(fname)
        self.assert_(not ok)

    def testOpen_emptyfile(self):
        fname = 'tmp.txt'
        f = open(fname, 'w')
        f.close()

        cadmodel = CadModel()
        ok = cadmodel.open(fname)
        self.assert_(not ok)

    def testOpen_normal(self):
        fname = 'tmp.txt'
        f = open(fname, 'w')
        print >> f, "solid TEST"
        print >> f, "facet norma"
        f.close()

        cadmodel = CadModel()
        ok = cadmodel.open(fname)
        self.assert_(not ok)

if __name__ == '__main__':
    unittest.main()
