"""Install/remove the optional store using the same standalone verifier as EXE.

This is an optional command-line wrapper, not a dependency of the EXE installer.
Example for an isolated developer state and source checkout:
  python install_extension.py install --root D:/test/CompanyAgent --host D:/src/AX-Workspace
"""
import argparse
import os
from pathlib import Path
import subprocess


def main():
    here = Path(__file__).resolve().parent
    local = Path(os.environ.get('LOCALAPPDATA', Path.home()))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'uninstall'])
    parser.add_argument('--root', type=Path, default=local / 'CompanyAgent', help='Common app state parent (contains local-ui/)')
    parser.add_argument('--host', type=Path, default=local / 'Programs/AX Workspace/AX-Workspace.exe')
    parser.add_argument('--package', type=Path, default=here / 'store-package.zip')
    parser.add_argument('--helper', type=Path, default=here / 'StoreInstaller.exe')
    parser.add_argument('--connection', type=Path, help='Optional downloaded server-origin file; defaults to connection.json beside this wrapper')
    args = parser.parse_args()
    if not args.helper.is_file():
        parser.error('Use the built portable ZIP, or pass --helper and --package from the build output')
    command = [str(args.helper.resolve()), args.action, str(args.root.resolve())]
    if args.action == 'install':
        command += [str(args.package.resolve()), str(args.host.resolve())]
        connection = args.connection or (here / 'connection.json')
        if args.connection is not None or connection.exists() or connection.is_symlink():
            # Native validation rejects links; preserve the supplied path so
            # resolving it here cannot hide a symlink from the verifier.
            command.append(str(connection.absolute()))
    raise SystemExit(subprocess.run(command, check=False).returncode)


if __name__ == '__main__':
    main()
