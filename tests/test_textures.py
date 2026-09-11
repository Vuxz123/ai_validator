from test_lifecycle import RepoCase


GUID = '12345678901234567890123456789012'


def meta(guid=GUID):
    return f'fileFormatVersion: 2\nguid: {guid}\nTextureImporter:\n  maxTextureSize: 2048\n'


class TextureTests(RepoCase):
    def test_folder_named_like_image_is_not_an_orphan_texture(self):
        self.baseline()
        self.commit('Assets/Folder.png/readme.txt', 'A folder, not an image')
        self.commit('Assets/Folder.png.meta', f'guid: {GUID}\nfolderAsset: yes\nDefaultImporter: {{}}\n')
        report = self.report()
        self.assertEqual(self.check(report, 'TEXTURE_META_001')['status'], 'NOT_APPLICABLE')
        self.assertNotEqual(report['assessment'], 'FINDINGS')

    def baseline(self):
        self.commit('Assets/Art/Icon.PNG', 'image fixture')
        self.commit('Assets/Art/Icon.PNG.meta', meta())
        self.order('a')
        self.cli('confirm', 'a')

    def report(self):
        self.order('b')
        return self.cli('analyze', 'b')['report']

    def check(self, report, check_id):
        checks = {c['check_id']: c for c in report['checks']}
        self.assertIn(check_id, checks)
        return checks[check_id]

    def test_texture_only_change_reads_unchanged_meta_and_numeric_guid(self):
        self.baseline()
        self.commit('Assets/Art/Icon.PNG', 'new image')
        report = self.report()
        self.assertIn('texture_metadata', report['selected_workflows'])
        for check_id in ('TEXTURE_META_001', 'TEXTURE_GUID_001', 'TEXTURE_IMPORT_001'):
            self.assertEqual(self.check(report, check_id)['status'], 'PASS')

    def test_missing_meta_produces_findings_without_agent(self):
        self.baseline()
        self.git('rm', 'Assets/Art/Icon.PNG.meta')
        self.git('commit', '-qm', 'Remove meta')
        report = self.report()
        self.assertEqual(self.check(report, 'TEXTURE_META_001')['status'], 'FAIL')
        self.assertEqual(report['assessment'], 'FINDINGS')

    def test_meta_only_guid_change_is_found(self):
        self.baseline()
        self.commit('Assets/Art/Icon.PNG.meta', meta('a' * 32))
        report = self.report()
        self.assertEqual(self.check(report, 'TEXTURE_GUID_001')['status'], 'FAIL')

    def test_orphan_meta_and_bad_importer(self):
        self.baseline()
        self.commit('Assets/Art/Orphan.png.meta', meta())
        self.commit('Assets/Art/Icon.PNG.meta', f'guid: {GUID}\nDefaultImporter: {{}}\n')
        report = self.report()
        self.assertEqual(self.check(report, 'TEXTURE_META_001')['status'], 'FAIL')
        self.assertEqual(self.check(report, 'TEXTURE_IMPORT_001')['status'], 'FAIL')

    def test_delete_both_is_valid(self):
        self.baseline()
        self.git('rm', 'Assets/Art/Icon.PNG', 'Assets/Art/Icon.PNG.meta')
        self.git('commit', '-qm', 'Remove pair')
        report = self.report()
        self.assertEqual(self.check(report, 'TEXTURE_META_001')['status'], 'PASS')
        self.assertEqual(self.check(report, 'TEXTURE_GUID_001')['status'], 'NOT_APPLICABLE')

    def test_invalid_guid_and_conflict_are_reported(self):
        self.baseline()
        self.commit('Assets/Art/Icon.PNG.meta', 'guid: invalid\n<<<<<<< HEAD\nTextureImporter: {}\n')
        report = self.report()
        self.assertEqual(self.check(report, 'TEXTURE_GUID_001')['status'], 'FAIL')
        self.assertEqual(self.check(report, 'TEXTURE_IMPORT_001')['status'], 'FAIL')
