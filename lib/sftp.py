import pysftp
import shutil
import os
import re

class Sftp:
    """SFTP client for getting files from OCA"""

    def __init__(self, host, user, pswd, dir):
        # Authorize SSH Host for SFTP connection
        os.system("ssh-keyscan -t dsa {host} >> ~/.ssh/known_hosts")

        self.sftp = pysftp.Connection(host=host, username=user, password=pswd)
        self.dir = dir


    def list_files(self, pattern):

        all_files = self.sftp.listdir(self.dir)

        files = [os.path.basename(x) for x in all_files if re.search(pattern, x)]

        return files


    def download_files(self, remote_files, local_dir):
        """
        Download file(s) from SFTP to local directory

        :param remote_file_paths: list of file paths on SFTP server
        :param local_dir: str path to local directory to save files
        """
        remote_files = [remote_files] if isinstance(remote_files, str) else remote_files

        # https://stackoverflow.com/a/14210233/7051239
        for f in remote_files:
            sftp_file = self.sftp.open(os.path.join(self.dir, f))
            local_file = open(os.path.join(local_dir, f), 'wb')
            shutil.copyfileobj(sftp_file, local_file)
            local_file.close()
            sftp_file.close()
