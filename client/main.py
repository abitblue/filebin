import argparse
import io
import os
import pathlib
import re
import sys
from datetime import datetime, timezone
from getpass import getpass
from typing import Tuple

import paramiko

parent_path = pathlib.Path(__file__).parent.absolute()


class ConnStringStoreAction(argparse.Action):
    conn_regex = re.compile(r'(.+?)(?::(.+))?@(.+?):(\d{1,5})(/.*)')

    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("nargs not None")
        super(ConnStringStoreAction, self).__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        match = self.conn_regex.match(values)

        setattr(namespace, 'username', match.groups()[0])
        setattr(namespace, 'password', match.groups()[1])
        setattr(namespace, 'hostname', match.groups()[2])
        setattr(namespace, 'port', match.groups()[3])
        setattr(namespace, 'tofiledir', match.groups()[4])


class SFTP:
    def __init__(self, hostname, port, username, password=None, keyfile=None):
        self.ssh: paramiko.SSHClient = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connected = False

        if password and not connected:
            try:
                self.ssh.connect(hostname, port, username, password=password)
                connected = self.ssh.get_transport().authenticated
            except paramiko.ssh_exception.BadAuthenticationType:
                pass

        if keyfile and not connected:
            try:
                key = self.open_key(keyfile)
                self.ssh.connect(hostname, port, username, pkey=key)
                connected = self.ssh.get_transport().authenticated
            except paramiko.ssh_exception.BadAuthenticationType:
                pass

        if not connected:
            raise paramiko.ssh_exception.SSHException(
                f'Could not connect to {username}@{hostname}:{port} using provided auth method(s)')

        self.sftp: paramiko.SFTPClient = self.ssh.open_sftp()

    def __enter__(self) -> Tuple[paramiko.SSHClient, paramiko.SFTPClient]:
        return self.ssh, self.sftp

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.sftp.close()
        self.ssh.close()

    @classmethod
    def open_key(cls, keyfile) -> paramiko.PKey:
        opened = False
        key = None
        while not opened:
            try:
                keyfile.seek(0)
                key = paramiko.RSAKey.from_private_key(keyfile)
                opened = key.can_sign()
            except paramiko.ssh_exception.PasswordRequiredException:
                try:
                    keyfile.seek(0)
                    password = getpass('Enter passphrase for key \'' + keyfile.name + '\': ')
                    key = paramiko.RSAKey.from_private_key(keyfile, password=password)
                    opened = key.can_sign()
                except paramiko.ssh_exception.SSHException:
                    pass
        return key


if __name__ == '__main__':
    # Arg parse
    parser = argparse.ArgumentParser(
        prog='filebin',
        description='Upload to a filebin server via sftp',
        epilog='Connstring looks like this: <username>:<userpassword>@<hostname>:<port>/<absolute path>. '
               'Ex: user:pass@example.com:22/home/user/filebin/server/assets',
        fromfile_prefix_chars='+'
    )
    parser.add_argument('connstring', action=ConnStringStoreAction, help='Connect to location')
    parser.add_argument('file', nargs='?', type=argparse.FileType('rb'), default=sys.stdin, help='File to upload. Blank or \'-\' for stdin')
    parser.add_argument('-i', '--identity-file', type=argparse.FileType('r'), help='SSH Identify File')

    args = parser.parse_args()

    # Save args to file
    arg_file = parent_path / 'filebin.args'
    if not arg_file.exists():
        save_to_file = input('Would you like to save the current arguments to file? [y/N] ').lower()[0:1] == 'y'
        if save_to_file:
            print(f'Saving current arguments to {arg_file}')
            print(f'You can rerun filebin with the current args using: \'filebin +{arg_file}\'')

            with open(arg_file, 'w') as f:
                f.write('\n'.join(sys.argv[1:]))

    # SFTP Connect
    with SFTP(args.hostname, args.port, args.username, password=args.password, keyfile=args.identity_file) as (
            ssh, sftp):
        sftp.chdir(args.tofiledir)  # Go to dir

        # Request a filename and expire date
        stdin, stdout, stderr = ssh.exec_command(f'python3 {args.tofiledir}/../request_name.py')
        data = str(stdout.read(), encoding='utf-8').split()

        # stdin has unknown file typing, will default to txt
        if isinstance(args.file, io.BufferedReader):
            suffix = pathlib.Path(args.file.name).suffix
            if suffix == '':
                suffix = '.txt'

            filename = f'{args.tofiledir}/{data[0]}{suffix}'
        else:
            filename = f'{args.tofiledir}/{data[0]}.txt'

        # to_transfer is 0 in print
        file_size = os.fstat(args.file.fileno()).st_size
        def print_totals(transferred: int, to_transfer: int):
            percent = '{0:.02f}'.format(transferred / (transferred if file_size == 0 else file_size) * 100)
            print('Transferred: {} of {} bytes ({} %)'.format(transferred, file_size, percent), end='\r')

        attr = sftp.putfo(args.file, filename, callback=print_totals)
        print('\n' + str(attr))

        print(f'Link: https://bin.abitblue.com/{pathlib.Path(filename).name}')
        print('Link will expire at:',
              datetime.fromtimestamp(float(data[1]), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z'))

    # asyncio.get_event_loop().run_until_complete(upload(sftp_uri='sftp://ryang@localhost:22', ws_uri='ws://localhost:8765'))
