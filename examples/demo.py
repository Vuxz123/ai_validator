"""Create a disposable Git fixture and retain two real CLI reports; no AI calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / '.validator'
    output.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='demo-', dir=output))
    repo = directory / 'game'
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()

    def cli(*args):
        result = subprocess.check_output(
            [sys.executable, '-m', 'validator', '--db', str(directory / 'state.db'), *args],
            cwd=ROOT, text=True,
        )
        return json.loads(result)

    def order(build_id):
        return cli('order', '--repo', str(repo), '--branch', 'main', '--profile', 'android',
                   '--target', 'HEAD', '--build-id', build_id, '--no-start')

    git('init', '-b', 'main')
    git('config', 'user.name', 'Local Validator Demo')
    git('config', 'user.email', 'demo@example.invalid')
    script = repo / 'Assets/Scripts/Ads/Reward.cs'
    script.parent.mkdir(parents=True)
    script.write_text('class Reward { void OnSuccess() { Grant(); } void Grant() {} }\n')
    git('add', '.')
    git('commit', '-qm', 'Initial fixture')
    order('demo-1')
    first = cli('analyze', 'demo-1')
    cli('confirm', 'demo-1')  # Simulated successful build; this demo does not run Unity.
    script.write_text('class Reward { void StartAd() { Grant(); } void Grant() {} }\n')
    git('add', '.')
    git('commit', '-qm', 'Change fixture reward flow')
    order('demo-2')
    second = cli('analyze', 'demo-2')
    for number, report in enumerate((first, second), 1):
        (directory / f'report-{number}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'directory': str(directory),
                      'first_assessment': first['report']['assessment'],
                      'second_assessment': second['report']['assessment'],
                      'note': 'No agent configured: business checks correctly remain UNKNOWN.'}, indent=2))


if __name__ == '__main__':
    main()
