# GPL License

import unittest
import sys


class TestAddon(unittest.TestCase):
    def test_syntax_check(self):
        try:
            import cats
        except SyntaxError as e:
            return self.fail('SyntaxError in plugin found!')

    def test_manifest(self):
        import tomllib
        import os
        manifest_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'blender_manifest.toml')
        with open(manifest_path, 'rb') as f:
            manifest = tomllib.load(f)
        self.assertIn('id', manifest)
        self.assertIn('version', manifest)
        self.assertEqual(manifest['id'], 'cats_blender_plugin')


suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestAddon)
runner = unittest.TextTestRunner()
ret = not runner.run(suite).wasSuccessful()
sys.exit(ret)
